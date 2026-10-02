"""845 个积水点的只读台账，供指挥中心页面落图与批量场景计算。

数据来自 `hotspots.py` 生成的 `backend/data/processed/hotspots_845.csv`（WGS84 经纬度）。
本模块只做三件事：

1. 读台账 → `HotspotRecord`（字段是台账里**真有**的东西）；
2. 用 DEM 采样每个点的高程 → 判 ADQCC Zone A / Zone B（§3.2.4 的 200 m 分界）；
3. 合并三份批算：`qcap_batch.py` 的逐点 Qcap、`storage_batch.py` 的逐点可用调蓄、
   `catchment_batch.py` 的逐点汇水面积 A / 径流系数 C / 集流时间 tc；
4. 把台账行 + 批算结果（批不到的才用**剖面假设**兜底）装配成 `rational.Hotspot`。

⚠ 第 4 步是整个页面最需要警惕的地方 —— 每一项都要说得清是实测还是假设。

  A / C / tc 已由 `catchment_batch.py` 从地籍与地物图层逐点反算（845 个点全部有值，
  `udm_plot` 覆盖三个市政区，不像管网只覆盖 ADM）。出处记在 `catchment_basis`。
  ⚠ 但它**不是汇水区划分成果**：边界用的是「相邻积水点 Voronoi 等分 + 250 m 截断」
  这一几何代理，可用于筛查排序，不可作为单点设计依据。清单 §09 仍然缺。

  Qcap 已经不是假设了：845 个点里 434 个由管网拓扑逐点反算（见 `qcap_batch.py`），
  50 个实测确认周边无管网，其余 361 个仍走假设。每个点的出处记在 `qcap_basis`。

  已有可用调蓄容量同样走了批算（见 `storage_batch.py`）。2026-09-19 补数后不再是
  全库 0：250 m 内 137 条设施记录分布在 **43 个点**周边，其中 1 个点的容量来自
  台账 `pond.volume`（**实测**，36.5 万 m³），另 42 个点靠 `storage_dims.py` 的
  **深度/尺寸缺省值目录**补（出处是 ADQCC WA-726-1/-2 等标准，不是拍脑袋）。
  出处记在 `storage_basis`：`measured` / `assumed_dimensions` / 「实测没有设施」
  / 「这一片没有设施数据」四者必须分得开。

⚠ **不要再用台账的 `network_available` 判有无管网。** 与管网几何逐点核对后发现：
  ADM 写「无管网」的 171 个点里有 135 个、250 m 内实际有雨水管；写「有管网」的
  335 个里有 28 个附近没有管。这个字段现在只在**完全没有管网数据的区域**
  （艾因 AAM、西部区 DRM，共 339 个点）作为唯一线索保留，并标成低置信度。
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Literal

from .idf import CatchmentPriority
from .ponding_curve import curve_for
from .rational import Hotspot

BACKEND_DIR = Path(__file__).resolve().parents[2]
HOTSPOTS_CSV = BACKEND_DIR / "data" / "processed" / "hotspots_845.csv"
HOTSPOT_QCAP_CSV = BACKEND_DIR / "data" / "processed" / "hotspot_qcap.csv"
HOTSPOT_QCAP_SWMM_CSV = BACKEND_DIR / "data" / "processed" / "hotspot_qcap_swmm.csv"
HOTSPOT_STORAGE_CSV = BACKEND_DIR / "data" / "processed" / "hotspot_storage.csv"
HOTSPOT_CATCHMENT_CSV = BACKEND_DIR / "data" / "processed" / "hotspot_catchment.csv"
HOTSPOT_DISTRICT_CSV = BACKEND_DIR / "data" / "processed" / "hotspot_district.csv"
HOTSPOT_PONDING_CSV = BACKEND_DIR / "data" / "processed" / "hotspot_ponding.csv"
DEM_TIF = BACKEND_DIR / "data" / "DEM_UAE_UTM40" / "DEM_UAE_UTM40.tif"

#: Qcap 取哪一套反算结果。`manning` 是唯一进主口径的；`swmm` 只做敏感性对照，
#: 代价写在 `resolve_qcap()` 与 `swmm_batch.py` 的注释里。
QcapSource = Literal["manning", "swmm"]

#: ADQCC §3.2.4：Zone A / Zone B 以海拔 200 m 等高线分界（精确边界见 Figure 3-2）。
ZONE_A_MIN_ELEVATION_M = 200.0

#: DEM 取不到值时的兜底分区 —— 845 个点绝大多数在平原区。
FALLBACK_ZONE_KEY = "adqcc_zone_b"


@dataclass(frozen=True)
class HotspotRecord:
    """台账里的一个积水点。字段全部来自 CSV，没有推导出来的业务量。"""

    uid: str
    source: str                 #: ADM / AAM / DRM
    municipality: str
    area: str
    location: str
    lat: float
    lon: float
    criticality: str | None     #: Very High / High / Medium / Low
    network_available: bool | None
    root_cause: str | None
    intervention_type: str | None
    intervention_status: str | None
    pumps_qty: float | None     #: 台账**已配**的泵数，用于和模型需求对照
    #: 台账逐点的分档泵数。⚠ 与 `pumps_qty` 对不上（全网 107/86/579 = 772，
    #: 而 `pumps_qty` 合计 918），也与 `pumps.DEFAULT_PUMP_TIERS` 的在册
    #: 144/121/579 对不上 —— 三个口径来自台账的不同列，孰为准须 DMT 确认。
    #: 它的用处是**跟着筛选口径一起缩放**：只算一部分点时，拿全网在册数比需求会失真。
    pump_12in_qty: float | None
    pump_8in_qty: float | None
    pump_6in_qty: float | None
    tankers_qty: float | None
    budget_required_aed: float | None
    coord_precision_m: float | None
    qc_flags: tuple[str, ...]
    elevation_m: float | None = None   #: DEM 采样，取不到为 None
    idf_zone: str | None = None        #: 由高程判定的 IDF 数据集 key
    #: 以下三项来自 `qcap_batch.py`，没跑过批算时全为 None / "unknown"
    nearest_pipe_m: float | None = None      #: 到最近雨水管的距离（米），无上限
    qcap_measured_m3s: float | None = None   #: 反算出的管网能力；None 表示算不出
    qcap_basis: str = "unknown"              #: measured / measured_no_network /
    #:                                          no_coverage / uncomputable / unknown
    #: 以下两项来自 `swmm_batch.py`，**默认不参与计算**，只有
    #: `resolve_qcap(qcap_source="swmm")` 才会用 —— 那份模型的管道坡度是地形坡度，
    #: 满流能力中位高估 2.4 倍，理由见 `swmm_batch.py` 模块头注释。
    qcap_swmm_m3s: float | None = None       #: SWMM 演算成果反推的满流能力
    qcap_swmm_basis: str = "unknown"         #: swmm / out_of_model / no_local_class /
    #:                                          no_pipes / unknown
    #: 以下三项来自 `storage_batch.py`（第二道防线），没跑过批算时为 None / "unknown"
    nearest_storage_m: float | None = None       #: 到最近调蓄设施的距离（米），无上限
    storage_measured_m3: float | None = None     #: 反算出的可用调蓄容量（实测口径）
    #: 实测 + `storage_dims.py` 缺省值目录补出来的合计；没有实测时用它，出处标 assumed_dimensions
    storage_assumed_m3: float | None = None
    storage_basis: str = "unknown"               #: measured / measured_none /
    #:                                              no_asset / no_coverage / unknown
    #: 以下五项来自 `catchment_batch.py`，没跑过批算时为 None / "unknown"
    area_measured_ha: float | None = None        #: 反算出的汇水面积（已开发部分）
    runoff_c_measured: float | None = None        #: 下垫面面积加权的 C
    tc_measured_min: float | None = None          #: 入网时间 + 管内流行时间
    impervious_share: float | None = None         #: 不透水率，页面用来解释 C 的来历
    catchment_basis: str = "unknown"              #: measured / measured_undeveloped /
    #:                                               assumed_no_landuse / unknown
    #: 以下四项来自 `district_batch.py`（官方行政片区），没跑过批算时为 None / "unknown"
    #: ⚠ 片区按 `udm_community` 面几何判，不是台账的 `area` 自由文本列
    district: str | None = None                  #: `districtnameeng`，全大写，如 AL BATEEN
    district_ar: str | None = None
    #: 面自带的市政区代码（ADM / AAM / WRM）。台账 `municipality` 是人填的，不一致时以此为准
    district_municipality: str | None = None
    district_basis: str = "unknown"              #: measured / outside / unknown
    #: 以下九项来自 `ponding_batch.py` —— ANUGA 二维演算反算出来的**逐点积水量**，
    #: 是项目里唯一一个不靠流量差估、而是从水动力成果上读出来的水量。
    #: ⚠ 只覆盖跑过 ANUGA 的片区（当前仅 Al Bateen RP100 一个 run，845 点里 18 个），
    #: 其余点全为 None / "unknown"，页面据此整块不显示，而不是显示 0。
    ponding_run_id: str | None = None
    ponding_rp_yr: int | None = None             #: 该 run 的重现期；它**不随页面选的级别变**
    ponding_peak_m3: float | None = None         #: 全程瞬时峰值，含过路水，系统性偏大
    ponding_settled_m3: float | None = None      #: 落定后的峰值，可归属口径
    ponding_net_inflow_m3: float | None = None   #: Σ 正 ΔV —— 「这个点一共积了多少水」
    ponding_volume_hours_m3h: float | None = None  #: ∫V dt，m³·h，排泵车看它
    ponding_peak_time_min: float | None = None
    ponding_drain_min: float | None = None       #: 退到 <0.01 m 的时刻（分钟），即该点的积水时长
    ponding_basis: str = "unknown"               #: in_depression / routed / overland / unknown
    #: 汇水区**边界**是怎么来的。与 `catchment_basis`（下垫面数据的出处）是两件事：
    #: 一个说「这块地的范围怎么圈的」，一个说「圈出来之后 C 是实测还是假设」。
    #: `voronoi_250m` —— 相邻点 Voronoi 等分 ∩ 250 m 圆（台账 845 点全部走这个，纯几何代理）
    #: `d8_depression` —— 20 m DTM 上 D8 汇流实算（模型片区走这个，见 `model_cluster_batch.py`）
    #: `cluster_only`  —— 该片区无宿主洼地，只算它自身范围
    catchment_boundary: str | None = None
    #: 对照口径的汇水面积：D8 那一路并列摆出同点的 Voronoi 代理值，看代理偏到哪去。
    #: 台账点没有第二口径可比，恒为 None。
    area_voronoi_ha: float | None = None
    #: 以下两项只有模型识别片区有（`model_cluster_batch.py`），台账点恒为 None。
    #: 它们不参与任何计算，只用来把一条记录认回到地图上那个片区。
    cluster_rank: int | None = None              #: 片区 rank，与页面上的 `#1` 对得上
    mechanism_key: str | None = None             #: 四类成因的 key，见 `model_ponding.py`

    @property
    def in_coverage(self) -> bool:
        """这个点落在**有管网数据的区域**内吗 —— 决定它该不该参与计算。

        判据是 `qcap_batch.py` 逐点算出的到最近雨水管距离（`COVERAGE_RADIUS_M`
        = 5 km），不是地图上那张覆盖面 —— 面经过简化，边界上和批算对不上号，
        只能用来看，见 `coverage_batch.py` 头注释。

        ⚠ 不要用行政区代替：845 个点里有 5 个台账记为阿布扎比市，却在数据区之外。
        """
        return self.qcap_basis not in ("no_coverage", "unknown")

    @property
    def district_key(self) -> str | None:
        """片区的**唯一**标识：`市政区代码 / 片区名`，如 `ADM / AL BATEEN`。

        ⚠ 不要拿片区名单独当 key —— 全库 121 个片区名里恰好有一个重名：
        `AL BATEEN` 在 ADM（阿布扎比岛，18 个点，全部有实测管网数据）和
        AAM（艾因 Ghafat Al Shwaihi，3 个点，无管网数据）下各有一个，
        两者隔着 130 km。筛选、落图、导出一律用本 key。
        """
        if not self.district:
            return None
        return f"{self.district_municipality or '—'} / {self.district}"

    def as_json(self) -> dict:
        d = asdict(self)
        d["qc_flags"] = list(self.qc_flags)
        d["in_coverage"] = self.in_coverage
        d["district_key"] = self.district_key
        return d


@dataclass(frozen=True)
class CatchmentProfile:
    """一组汇水参数假设。**五个字段全部是假设值**，没有逐点出处。"""

    area_ha: float = 12.0
    runoff_c: float = 0.75
    tc_min: float = 20.0
    qcap_m3s: float = 0.60
    pond_available_m3: float = 0.0


#: 兜底剖面的 key（台账成因为空的点走它）
DEFAULT_PROFILE_KEY = "_default"

#: 按积水成因分组的默认剖面。数字是筛查用的占位假设，**改这里不改计算口径**。
DEFAULT_PROFILES: dict[str, CatchmentProfile] = {
    "Inadequate Design Capacity": CatchmentProfile(
        area_ha=12.0, runoff_c=0.75, tc_min=20.0, qcap_m3s=0.60
    ),
    "Absence of Drainage Network": CatchmentProfile(
        area_ha=12.0, runoff_c=0.70, tc_min=30.0, qcap_m3s=0.00
    ),
    "Topography & Road Engineering": CatchmentProfile(
        area_ha=8.0, runoff_c=0.80, tc_min=15.0, qcap_m3s=0.30
    ),
    DEFAULT_PROFILE_KEY: CatchmentProfile(),
}

#: 页面上逐项显示的出处说明 —— 有出处的和拍脑袋的必须看得出区别。
PROFILE_FIELD_BASIS: dict[str, str] = {
    "area_ha": (
        "**仅当该点没有地籍数据时才用本假设**。已由 catchment_batch.py 从 Voronoi "
        "汇水单元里的已开发面积逐点反算的点会覆盖它，出处见每个点的 catchment_basis"
    ),
    "runoff_c": (
        "**仅当该点没有地籍数据时才用本假设**。已逐点反算的点按 ADQCC Table 3-8 "
        "分项面积加权，出处见每个点的 catchment_basis"
    ),
    "tc_min": (
        "**仅当该点没有地籍数据时才用本假设**。已逐点反算的点按 ADQCC §3.2.3 "
        "「入网时间 + 管内流行时间」计算，出处见每个点的 catchment_basis"
    ),
    "qcap_m3s": (
        "**仅当该点没有管网数据时才用本假设**。已由 qcap_batch.py 从管网拓扑逐点"
        "反算的点会覆盖它，出处见每个点的 qcap_basis"
    ),
    "pond_available_m3": (
        "**仅当该点没有设施数据时才用本假设**。已由 storage_batch.py 从管网库"
        "逐点反算的点会覆盖它，出处见每个点的 storage_basis"
    ),
}

#: `storage_basis` 的取值 → 给人看的说明（第二道防线）。
STORAGE_BASIS_LABEL: dict[str, str] = {
    "measured": "实测 —— 250 m 内调蓄设施反算的可用容量",
    "measured_none": "实测 —— 周边有调蓄设施，但尺寸或深度数据不可用，按 0 计",
    "measured_no_asset": "实测 —— 该片有设施数据，此点 250 m 内没有调蓄设施",
    "assumed_dimensions": (
        "假设尺寸 —— 周边设施位置实测，但深度/尺寸库里没有，"
        "按 storage_dims.py 的标准缺省值目录估算"
    ),
    "assumed_no_coverage": "假设 —— 此点 5 km 内无任何调蓄设施记录（设施图层未覆盖该片）",
    "assumed": "假设 —— 尚未跑过 storage_batch.py 批算",
}

#: `catchment_basis` 的取值 → 给人看的说明（汇水面积 A / 径流系数 C / 集流时间 tc）。
CATCHMENT_BASIS_LABEL: dict[str, str] = {
    "measured": "实测 —— Voronoi 汇水单元（∩ 250 m）内的已开发面积，C 按 ADQCC Table 3-8 分项加权",
    "measured_undeveloped": "实测 —— 单元内几乎没有城市下垫面，按整单元的沙地口径计（Table 3-9）",
    "assumed_no_landuse": "假设 —— 此点 5 km 内无任何地块记录（地籍图层未覆盖该片）",
    "assumed": "假设 —— 尚未跑过 catchment_batch.py 批算",
}

#: `qcap_basis` 的取值 → 给人看的说明。页面必须把实测和假设区分开。
QCAP_BASIS_LABEL: dict[str, str] = {
    "measured": "实测 —— 250 m 内 LATERAL/SECONDARY 管道反算的最大满流能力",
    "measured_no_network": "实测 —— 该片有管网数据，但此点 250 m 内确实没有雨水管，Qcap 取 0",
    "ledger_no_network": "台账声明无管网（该区域无管网数据可核实，低置信度）",
    "assumed_no_coverage": "假设 —— 此点 5 km 内无任何雨水管记录（该片管网尚未导出）",
    "assumed_uncomputable": "假设 —— 算不出 Qcap：附近有管但缺管底高程/平坡，或无收集级管道",
    "assumed": "假设 —— 尚未跑过 qcap_batch.py 批算",
    "swmm": "SWMM 演算反推 —— ⚠ 该模型坡度取自地形，满流能力中位高估 2.4 倍，仅供敏感性对照",
}


#: `hotspot_ponding.csv` 的 `attribution_basis` 列写的是中文（`ponding_batch.py`
#: 的产出口径），但 API 上的 basis 一律是稳定的 ascii key —— 前端拿它查标签色与文案，
#: 不能随语言变。认不出的值原样透传，不吞成 unknown。
PONDING_BASIS_KEY: dict[str, str] = {
    "点内": "in_depression",
    "汇流": "routed",
    "坡面直排": "overland",
}

#: `ponding_basis` 的取值 → 给人看的说明（逐点积水量的归属口径）。
PONDING_BASIS_LABEL: dict[str, str] = {
    "in_depression": "演算 —— 点落在洼地格上，水量取该洼地（多点共用时按最近点切分）",
    "routed": "演算 —— 点所在格按 D8 汇入某个洼地，水量取该洼地里划给本点的部分",
    "overland": "演算 —— 点既不在洼地内也不汇入洼地，只报本格水量，不挂洼地",
    "unknown": "无 —— 该片尚未跑过 ANUGA 二维演算",
}


def _text(value: str) -> str | None:
    v = (value or "").strip()
    return v or None


def _number(value: str) -> float | None:
    v = (value or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _bool(value: str) -> bool | None:
    v = (value or "").strip()
    if v == "True":
        return True
    if v == "False":
        return False
    return None


def _read_csv(path: Path = HOTSPOTS_CSV) -> list[HotspotRecord]:
    if not path.exists():
        raise FileNotFoundError(
            f"未找到积水点标准表 {path}；先跑 `python -m stormwater.hotspots` 生成。"
        )
    out: list[HotspotRecord] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            lat, lon = _number(row["lat"]), _number(row["lon"])
            if lat is None or lon is None:
                continue  # 无坐标的点落不了图；当前 845 行全部有坐标
            out.append(
                HotspotRecord(
                    uid=row["uid"],
                    source=row["source"],
                    municipality=row["municipality"],
                    area=_text(row["area"]) or "—",
                    location=_text(row["location"]) or row["uid"],
                    lat=lat,
                    lon=lon,
                    criticality=_text(row["criticality"]),
                    network_available=_bool(row["network_available"]),
                    root_cause=_text(row["root_cause"]),
                    intervention_type=_text(row["intervention_type"]),
                    intervention_status=_text(row["intervention_status"]),
                    pumps_qty=_number(row["pumps_qty"]),
                    pump_12in_qty=_number(row["pump_12in_qty"]),
                    pump_8in_qty=_number(row["pump_8in_qty"]),
                    pump_6in_qty=_number(row["pump_6in_qty"]),
                    tankers_qty=_number(row["tankers_qty"]),
                    budget_required_aed=_number(row["budget_required_aed"]),
                    coord_precision_m=_number(row["coord_precision_m"]),
                    qc_flags=tuple(f for f in (row["qc_flags"] or "").split("|") if f),
                )
            )
    return out


def _read_qcap(path: Path = HOTSPOT_QCAP_CSV) -> dict[str, dict]:
    """读 `qcap_batch.py` 的批算结果。没跑过批算时返回空字典，逐点 Qcap 退回假设。"""
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["uid"]] = {
                "nearest_pipe_m": _number(row["nearest_any_m"]),
                "qcap_measured_m3s": _number(row["qcap_m3s"]),
                "qcap_basis": _text(row["basis"]) or "unknown",
            }
    return out


def _read_qcap_swmm(path: Path = HOTSPOT_QCAP_SWMM_CSV) -> dict[str, dict]:
    """读 `swmm_batch.py` 的批算结果。**只在显式切到 swmm 口径时才被取用**。"""
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["uid"]] = {
                "qcap_swmm_m3s": _number(row["qcap_m3s"]),
                "qcap_swmm_basis": _text(row["basis"]) or "unknown",
            }
    return out


def _read_storage(path: Path = HOTSPOT_STORAGE_CSV) -> dict[str, dict]:
    """读 `storage_batch.py` 的批算结果。没跑过批算时返回空字典，逐点调蓄退回假设。"""
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["uid"]] = {
                "nearest_storage_m": _number(row["nearest_any_m"]),
                "storage_measured_m3": _number(row["available_m3"]),
                # 旧版 CSV 没有这一列 —— 缺列时退回实测口径，行为与改动前一致
                "storage_assumed_m3": _number(row.get("available_with_assumed_m3", "")),
                "storage_basis": _text(row["basis"]) or "unknown",
            }
    return out


def _read_catchment(path: Path = HOTSPOT_CATCHMENT_CSV) -> dict[str, dict]:
    """读 `catchment_batch.py` 的批算结果。没跑过批算时返回空字典，A/C/tc 退回假设。"""
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["uid"]] = {
                "area_measured_ha": _number(row["area_ha"]),
                "runoff_c_measured": _number(row["runoff_c"]),
                "tc_measured_min": _number(row["tc_min"]),
                "impervious_share": _number(row["impervious_share"]),
                "catchment_basis": _text(row["basis"]) or "unknown",
            }
    return out


def _read_district(path: Path = HOTSPOT_DISTRICT_CSV) -> dict[str, dict]:
    """读 `district_batch.py` 的批算结果。没跑过批算时返回空字典，片区筛选自动消失。"""
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["uid"]] = {
                "district": _text(row["district"]),
                "district_ar": _text(row["district_ar"]),
                "district_municipality": _text(row["district_municipality"]),
                "district_basis": _text(row["basis"]) or "unknown",
            }
    return out


def _read_ponding(path: Path = HOTSPOT_PONDING_CSV) -> dict[str, dict]:
    """读 `ponding_batch.py` 的批算结果。没跑过批算时返回空字典，页面整块不显示积水量。

    ⚠ 这份 CSV 是**单个 ANUGA run 的成果**，重现期写在 `return_period_years` 列里，
    与页面上选的那一级无关 —— 引用数字时必须把它一起说出来。
    """
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rp = _number(row["return_period_years"])
            basis = _text(row["attribution_basis"]) or "unknown"
            out[row["uid"]] = {
                "ponding_run_id": _text(row["run_id"]),
                "ponding_rp_yr": int(rp) if rp is not None else None,
                "ponding_peak_m3": _number(row["peak_volume_m3"]),
                "ponding_settled_m3": _number(row["settled_volume_m3"]),
                "ponding_net_inflow_m3": _number(row["net_inflow_m3"]),
                "ponding_volume_hours_m3h": _number(row["volume_hours_m3h"]),
                "ponding_peak_time_min": _number(row["peak_time_min"]),
                "ponding_drain_min": _number(row["drain_time_min"]),
                "ponding_basis": PONDING_BASIS_KEY.get(basis, basis),
            }
    return out


def sample_elevations(records: list[HotspotRecord]) -> list[float | None]:
    """用 DEM 采样每个点的高程（米）。DEM 缺失或 rasterio 不可用时全部返回 None。"""
    if not DEM_TIF.exists():
        return [None] * len(records)
    try:
        import rasterio
        from rasterio.warp import transform as warp_transform
    except ImportError:
        return [None] * len(records)

    try:
        with rasterio.open(DEM_TIF) as dem:
            xs, ys = warp_transform(
                "EPSG:4326", dem.crs,
                [r.lon for r in records], [r.lat for r in records],
            )
            nodata = dem.nodata
            values: list[float | None] = []
            for v in dem.sample(zip(xs, ys)):
                val = float(v[0])
                # DEM 的 nodata 是 3.4e38；海面是真实的 0
                if (nodata is not None and val == nodata) or val > 1e6:
                    values.append(None)
                else:
                    values.append(val)
            return values
    except Exception:  # noqa: BLE001 — DEM 只是锦上添花，读不了就退化为默认分区
        return [None] * len(records)


def zone_for_elevation(elevation_m: float | None) -> str | None:
    if elevation_m is None:
        return None
    return "adqcc_zone_a" if elevation_m > ZONE_A_MIN_ELEVATION_M else "adqcc_zone_b"


@lru_cache(maxsize=1)
def load_registry() -> tuple[HotspotRecord, ...]:
    """读台账 + DEM 判分区 + 合并各路批算。

    结果缓存，进程内只算一次（DEM 采样约 0.2 秒）。各份输入互相独立：缺 DEM 退化为默认分区，
    缺 Qcap / 调蓄批算结果各自退化为剖面假设，缺积水量批算只是页面不显示那一段，
    都不影响其余字段。
    """
    records = _read_csv()
    elevations = sample_elevations(records)
    qcap = _read_qcap()
    qcap_swmm = _read_qcap_swmm()
    storage = _read_storage()
    catchment = _read_catchment()
    district = _read_district()
    ponding = _read_ponding()
    return tuple(
        replace(
            r,
            elevation_m=e,
            idf_zone=zone_for_elevation(e),
            # 台账点没有地形可依，汇水区边界一律是 Voronoi 代理 —— 自述出来，
            # 免得和模型片区那一路的 D8 实算边界混为一谈
            catchment_boundary="voronoi_250m" if r.uid in catchment else None,
            **qcap.get(r.uid, {}),
            **qcap_swmm.get(r.uid, {}),
            **storage.get(r.uid, {}),
            **catchment.get(r.uid, {}),
            **district.get(r.uid, {}),
            **ponding.get(r.uid, {}),
        )
        for r, e in zip(records, elevations)
    )


def profile_key_for(record: HotspotRecord) -> str:
    """该点按哪套剖面取参数 —— 目前按积水成因分组。"""
    if record.root_cause and record.root_cause in DEFAULT_PROFILES:
        return record.root_cause
    return DEFAULT_PROFILE_KEY


def resolve_qcap(
    record: HotspotRecord,
    profile: CatchmentProfile,
    *,
    zero_qcap_without_network: bool = True,
    qcap_source: QcapSource = "manning",
) -> tuple[float, str]:
    """定一个点的 Qcap 取值与出处。返回 (Qcap, basis)。

    优先级：**实测 > 实测确认无管网 > 台账声明 > 假设**。

    只有在该区域**完全没有管网数据**时才回退到台账的 `network_available` ——
    在有管网几何可核对的 ADM，这个字段被证实错了 135 处（见模块头注释）。

    Args:
        qcap_source: `"manning"`（默认，`qcap_batch.py` 从 `sw_edge` 实测内底
            反算）或 `"swmm"`（`swmm_batch.py` 从 SWMM 演算成果反推）。
            ⚠ **切到 swmm 只为做敏感性对照**：那份模型的管道内底 = DEM 地面
            减固定 1.10 m，坡度即地形坡度（与 DEM 坡度相关系数 1.000），
            满流能力同管对照中位高估 2.4 倍，结论会全面偏乐观。
            取不到 SWMM 值的点自动退回 manning，两套数会并存于同一张表，
            逐点出处看 `qcap_basis`。详见 `swmm_batch.py` 模块头注释。
    """
    if qcap_source == "swmm" and record.qcap_swmm_m3s is not None:
        return record.qcap_swmm_m3s, "swmm"

    if record.qcap_measured_m3s is not None:
        return record.qcap_measured_m3s, "measured"

    if record.qcap_basis == "measured_no_network":
        # 该片有管网数据，此点周边确实没有管 —— 这是实测结论，不是台账声明
        if zero_qcap_without_network:
            return 0.0, "measured_no_network"
        return profile.qcap_m3s, "assumed"

    if record.qcap_basis == "no_coverage":
        # 艾因 / 西部区：管网未导出。台账声明是唯一线索，但置信度低
        if zero_qcap_without_network and record.network_available is False:
            return 0.0, "ledger_no_network"
        return profile.qcap_m3s, "assumed_no_coverage"

    if record.qcap_basis == "uncomputable":
        return profile.qcap_m3s, "assumed_uncomputable"

    return profile.qcap_m3s, "assumed"


def resolve_pond(
    record: HotspotRecord,
    profile: CatchmentProfile,
) -> tuple[float, str]:
    """定一个点的已有可用调蓄容量与出处。返回 (容量, basis)。

    优先级与 Qcap 同构：**实测 > 实测确认无设施 > 假设**。

    优先级：**实测（台账容量/实测尺寸）> 假设尺寸（位置实测，深度尺寸查目录）>
    实测确认无设施 > 无设施数据**。后两者都是 0，但**出处不同** ——
    实测确认没有设施，和这一片根本没有设施数据，不是一回事。
    """
    if record.storage_measured_m3 is not None:
        return record.storage_measured_m3, "measured"
    if (record.storage_basis == "assumed_dimensions"
            and record.storage_assumed_m3 is not None):
        # 设施位置是实测的，缺的只是深度与尺寸 —— 用带出处的缺省值目录补，
        # 出处标签自己会说这是假设。想切回纯实测口径：把这一段去掉即可。
        return record.storage_assumed_m3, "assumed_dimensions"
    if record.storage_basis == "measured_none":
        # 周边有设施，但尺寸/深度数据不可用 —— 不能当成有容量
        return 0.0, "measured_none"
    if record.storage_basis == "no_asset":
        # 该片有设施数据，此点 250 m 内确实没有 —— 这是实测结论
        return 0.0, "measured_no_asset"
    if record.storage_basis == "no_coverage":
        return profile.pond_available_m3, "assumed_no_coverage"
    return profile.pond_available_m3, "assumed"


def resolve_catchment(
    record: HotspotRecord,
    profile: CatchmentProfile,
) -> tuple[float, float, float, str]:
    """定一个点的汇水面积 A、径流系数 C、集流时间 tc 与出处。

    优先级与 Qcap 同构：**实测 > 假设**。三项同进同退 —— 面积、C、tc 是同一次
    下垫面统计算出来的，混用一部分实测一部分假设会让 Q = C·i·A 失去内部一致性。
    """
    if (
        record.area_measured_ha is not None
        and record.runoff_c_measured is not None
        and record.tc_measured_min is not None
        and record.catchment_basis in ("measured", "measured_undeveloped")
    ):
        return (
            record.area_measured_ha,
            record.runoff_c_measured,
            record.tc_measured_min,
            record.catchment_basis,
        )
    basis = (
        "assumed_no_landuse"
        if record.catchment_basis == "assumed_no_landuse"
        else "assumed"
    )
    return profile.area_ha, profile.runoff_c, profile.tc_min, basis


def catchment_basis_for(
    record: HotspotRecord,
    profiles: dict[str, CatchmentProfile],
) -> str:
    """该点 A / C / tc 的出处标签 —— 页面用它区分实测与假设。"""
    profile = profiles.get(profile_key_for(record)) or profiles.get(
        DEFAULT_PROFILE_KEY
    ) or CatchmentProfile()
    return resolve_catchment(record, profile)[3]


def storage_basis_for(
    record: HotspotRecord,
    profiles: dict[str, CatchmentProfile],
) -> str:
    """该点最终调蓄容量的出处标签 —— 页面用它区分实测与假设。"""
    profile = profiles.get(profile_key_for(record)) or profiles.get(
        DEFAULT_PROFILE_KEY
    ) or CatchmentProfile()
    return resolve_pond(record, profile)[1]


def qcap_basis_for(
    record: HotspotRecord,
    profiles: dict[str, CatchmentProfile],
    *,
    zero_qcap_without_network: bool = True,
    qcap_source: QcapSource = "manning",
) -> str:
    """该点最终 Qcap 的出处标签 —— 页面用它区分实测与假设，别再猜。"""
    profile = profiles.get(profile_key_for(record)) or profiles.get(
        DEFAULT_PROFILE_KEY
    ) or CatchmentProfile()
    return resolve_qcap(
        record,
        profile,
        zero_qcap_without_network=zero_qcap_without_network,
        qcap_source=qcap_source,
    )[1]


def build_hotspot(
    record: HotspotRecord,
    profiles: dict[str, CatchmentProfile],
    *,
    priority: CatchmentPriority | None = None,
    zero_qcap_without_network: bool = True,
    qcap_source: QcapSource = "manning",
) -> Hotspot:
    """台账行 + 剖面假设 → 可以进 `rational.evaluate()` 的输入。

    Args:
        zero_qcap_without_network: 确认无排水管网的点，Qcap 强制为 0。
            默认开启；关掉只为做敏感性对照（此时这些点改用剖面假设值）。
            判定依据见 `resolve_qcap()` —— 以管网几何为准，不再直接采信台账。
        qcap_source: Qcap 取哪一套，见 `resolve_qcap()`。默认 `"manning"`。
    """
    key = profile_key_for(record)
    profile = profiles.get(key) or profiles.get(DEFAULT_PROFILE_KEY) or CatchmentProfile()
    qcap, _ = resolve_qcap(
        record,
        profile,
        zero_qcap_without_network=zero_qcap_without_network,
        qcap_source=qcap_source,
    )
    pond, _ = resolve_pond(record, profile)
    area_ha, runoff_c, tc_min, _ = resolve_catchment(record, profile)
    return Hotspot(
        hotspot_id=record.uid,
        area_ha=area_ha,
        runoff_c=runoff_c,
        tc_min=tc_min,
        qcap_m3s=qcap,
        pond_available_m3=pond,
        priority=priority,
        # 第一道防线的唯一数据源。取不到（没跑过二维演算）就是 None，
        # `rational.evaluate()` 据此把三道防线整块标成「无标定」而不出数。
        ponding=curve_for(record.uid),
    )


def dataset_key_for(record: HotspotRecord, selection: str) -> str:
    """选哪套 IDF：`auto` 按 DEM 分区逐点判，其余按选择固定。"""
    if selection != "auto":
        return selection
    return record.idf_zone or FALLBACK_ZONE_KEY


def facets(records: tuple[HotspotRecord, ...]) -> dict[str, list[dict]]:
    """页面筛选器用的取值清单（按出现次数排序）。"""

    def count(attr: str) -> list[dict]:
        tally: dict[str, int] = {}
        for r in records:
            v = getattr(r, attr)
            label = "未填写" if v is None else str(v)
            tally[label] = tally.get(label, 0) + 1
        return [
            {"value": k, "count": v}
            for k, v in sorted(tally.items(), key=lambda kv: -kv[1])
        ]

    return {
        "source": count("source"),
        "municipality": count("municipality"),
        "criticality": count("criticality"),
        "root_cause": count("root_cause"),
        "intervention_status": count("intervention_status"),
        "district": district_facet(records),
    }


def district_facet(records: tuple[HotspotRecord, ...]) -> list[dict]:
    """片区取值清单。value 是 `district_key`（市政区限定），label 才是给人看的名字。

    没跑过 `district_batch.py` 时返回空列表 —— 页面据此把片区筛选整块藏掉，
    而不是显示一个空的下拉框。
    """
    tally: dict[str, dict] = {}
    for r in records:
        key = r.district_key
        if key is None:
            continue
        row = tally.setdefault(
            key,
            {
                "value": key,
                "label": r.district,
                "municipality": r.district_municipality,
                "count": 0,
                "in_coverage": 0,
            },
        )
        row["count"] += 1
        row["in_coverage"] += 1 if r.in_coverage else 0
    for key, row in tally.items():
        pond = district_ponding([r for r in records if r.district_key == key])
        if pond:
            row["ponding"] = pond
    return sorted(tally.values(), key=lambda x: (-x["count"], x["value"]))


def district_ponding(records: list[HotspotRecord]) -> dict | None:
    """一个片区的积水量总账 —— 跑过 ANUGA 的片区才有，其余返回 None。

    `window_min` 取该片区**退水最慢的那个点**的积水时长：三道防线共用的时限 T 要
    覆盖全片，取最大值而不是平均值；`drain_min` 同时给出区间两端，页面写成
    「15 – 1185 min（19.75 h）」，一眼看得出这个 T 是被谁定住的。

    ⚠ `return_period_yr` 是这个 ANUGA run 自己的重现期，**不随页面上选的级别变**。
    同一片区混了多个 run 时不合并 —— 取点数最多的那个 run，其余忽略。
    """
    runs: dict[str, list[HotspotRecord]] = {}
    for r in records:
        if r.ponding_run_id:
            runs.setdefault(r.ponding_run_id, []).append(r)
    if not runs:
        return None
    run_id, rows = max(runs.items(), key=lambda kv: len(kv[1]))
    drains = [r.ponding_drain_min for r in rows if r.ponding_drain_min is not None]
    if not drains:
        return None
    rps = {r.ponding_rp_yr for r in rows if r.ponding_rp_yr is not None}
    window_min = max(drains)
    return {
        "run_id": run_id,
        "return_period_yr": rps.pop() if len(rps) == 1 else None,
        "points": len(rows),
        "wet_points": sum(1 for r in rows if (r.ponding_net_inflow_m3 or 0) > 0),
        "drain_min": [min(drains), window_min],
        "window_min": window_min,
        "window_h": round(window_min / 60.0, 2),
        "net_inflow_m3": round(sum(r.ponding_net_inflow_m3 or 0.0 for r in rows), 2),
        "peak_m3": round(sum(r.ponding_peak_m3 or 0.0 for r in rows), 2),
    }
