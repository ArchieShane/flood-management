"""把场景计算器的计算结果导出成中文文档与中文表头明细表（可重跑）。

    cd backend && PYTHONPATH=src .venv/bin/python -m stormwater.report

产出两份：

* ``backend/data/processed/scenario_points_zh.csv`` —— 主口径逐点明细，845 行，中文表头；
* ``docs/SCENARIO_RESULTS.md`` —— 中文报告，五档重现期汇总 + 分区分级 + 车队对照
  + 数据可信度 + 局限声明。

⚠ 本模块**不做任何计算**，只调用 `scenario.run_batch()` 并把结果翻成中文。
  想改数字请改计算侧，不要改这里 —— 这里改了会和页面对不上。

⚠ 报告里的逐点汇水面积 A、径流系数 C、集流时间 tc 已由 `catchment_batch.py` 从地籍与
  地物图层逐点反算，但用的是「相邻积水点 Voronoi 等分 + 250 m 截断」的几何代理边界，
  **不是汇水区划分成果**（清单 §09 仍然缺）。所有结论只能当筛查与排序用。
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .constants import (
    DEFAULT_ASSUMPTIONS,
    LEGACY_PUMP_CAPACITY,
    RATIONAL_METHOD_MAX_AREA_HA,
)
from .idf import FLEET_RETURN_PERIODS
from .pumps import DEFAULT_PUMP_TIERS, fleet_weighted_capacity
from .registry import HotspotRecord, load_registry
from .scenario import BatchOptions, fleet_gap, run_batch

BACKEND_DIR = Path(__file__).resolve().parents[2]
POINTS_CSV = BACKEND_DIR / "data" / "processed" / "scenario_points_zh.csv"
#: 报告写到仓库的 docs/ 下，不在后端包里 —— 本脚本只在开发机上重跑
REPORT_MD = BACKEND_DIR.parent / "docs" / "SCENARIO_RESULTS.md"

#: 主口径 —— 与页面默认值、DMT 数据需求清单保持一致，改这里等于改对外口径。
#: 主口径重现期。⚠ **必须与二维演算 run 的重现期一致**：第一道防线读的是那一场
#: 演算的积水时程，选别的档所有点都会落到「无标定」，整份报告没有防线结论。
#: 当前唯一的 run 是 100 年一遇（Al Bateen）。见 `ponding_curve.py`。
MAIN_RETURN_PERIOD = 100
MAIN_DATASET = "auto"

MUNI_CN = {"Abu Dhabi": "阿布扎比市", "Al Ain": "艾因", "Al Dhafra": "扎夫拉"}
#: `udm_community.municipality` 用的是代码，与台账那一列不是同一套写法
MUNI_CODE_CN = {"ADM": "阿布扎比市", "AAM": "艾因", "WRM": "扎夫拉"}
CRIT_CN = {"Very High": "极高", "High": "高", "Medium": "中", "Low": "低"}
CRIT_ORDER = ("Very High", "High", "Medium", "Low", "未填写")
CAUSE_CN = {
    "Inadequate Design Capacity": "管网能力不足",
    "Absence of Drainage Network": "无排水管网",
    "Topography & Road Engineering": "地形与道路工程",
}
DATASET_CN = {
    "adqcc_zone_a": "ADQCC Zone A（山区）",
    "adqcc_zone_b": "ADQCC Zone B（平原区）",
    "dubai_dm": "迪拜 DM（仅供回归对照，不可报送）",
    "custom_storm": "自定义降雨（非标准口径）",
}
LINE_CN = {
    1: "第一道防线 · 时限内地面的水退完",
    2: "第二道防线 · 加上调蓄排完",
    3: "第三道防线 · 需出动移动排水设备",
    #: ⚠ 与 1/2/3 **并列**，不是「第四道」：这个点没跑过二维演算，不出结论。
    None: "无水动力标定 · 不出结论",
}
#: 第一道防线这一行的数是哪来的。三个值与 `rational.ScenarioResult.l1_basis` 对齐。
L1_BASIS_CN = {
    "hydrodynamic": "二维水动力演算时程 —— T 时刻地面实测残留水量",
    "peak": "原 Excel 峰值口径 —— 仅供回归对照，不可报送",
    "uncalibrated": "无标定 —— 本点未跑过二维演算，或演算的重现期与所选不符",
}


def _blank(value):
    """无标定点的各量是 None，导出成**空白**而不是 0。

    0 的意思是「算过，结果是零」，空白的意思是「没算」。这两件事差着一个
    调度决定，在交给甲方的表里尤其不能混。
    """
    return "" if value is None else value


def _yes_no_blank(value):
    """是 / 否 / 空白。**不要**和下面的 `_yes_no`（有 / 无 / —）混用。"""
    return "" if value is None else ("是" if value else "否")
#: 出处措辞与 `web/command_centre.html` 的 QCAP_BASIS / STORAGE_BASIS 逐字一致，
#: 页面导出与本模块导出的同一列内容必须对得上，改一边要改两边。
QCAP_BASIS_CN = {
    "measured": "实测 —— 250 m 内 LATERAL/SECONDARY 管道反算的最大满流能力",
    "measured_no_network": "实测：无管网 —— 该片有管网数据，此点 250 m 内确实没有雨水管",
    "ledger_no_network": "台账：无管网 —— 该区域无管网数据可核实，低置信度",
    "assumed_no_coverage": "假设：无管网数据 —— 此点 5 km 内没有雨水管记录，该片管网尚未导出",
    "assumed_uncomputable": "假设：算不出 —— 附近有管但缺管底高程/平坡，或无收集级管道",
    "assumed": "假设 —— 尚未跑过 qcap_batch.py 批算",
}
CATCHMENT_BASIS_CN = {
    "measured": "实测 —— Voronoi 汇水单元（∩ 250 m）内的已开发面积，C 按 ADQCC Table 3-8 分项加权",
    "measured_undeveloped": "实测：无城市下垫面 —— 单元内几乎全是沙地，按 Table 3-9 的整单元口径计",
    "assumed_no_landuse": "假设：无地籍数据 —— 此点 5 km 内没有地块记录，地籍图层未覆盖",
    "assumed": "假设 —— 尚未跑过 catchment_batch.py 批算",
}
STORAGE_BASIS_CN = {
    "measured": "实测 —— 250 m 内调蓄设施反算的可用容量",
    "measured_none": "实测：数据不可用 —— 周边有设施，但尺寸或深度数据不可用，按 0 计",
    "measured_no_asset": "实测：无设施 —— 该片有设施数据，此点 250 m 内没有调蓄设施",
    "assumed_dimensions": "假设尺寸 —— 设施位置实测，深度/尺寸按标准缺省值目录估算",
    "assumed_no_coverage": "假设：无设施数据 —— 此点 5 km 内没有调蓄设施记录，设施图层未覆盖",
    "assumed": "假设 —— 尚未跑过 storage_batch.py 批算",
}

CSV_COLUMNS: tuple[tuple[str, str], ...] = (
    ("编号", "uid"), ("来源台账", "source"), ("行政区", "municipality"),
    # 两列片区各说各话，不能合并：`台账片区` 是各市政区自填的自由文本，
    # `官方片区` 是 district_batch.py 按 udm_community 社区面几何判出来的。
    # 以巴廷区为例，岛上 18 个点的台账片区全写着 Island。
    ("台账片区", "area"), ("官方片区", "district_cn"),
    ("位置", "location"), ("纬度", "lat"), ("经度", "lon"),
    ("严重度", "criticality_cn"), ("积水成因", "root_cause_cn"),
    ("台账-有无管网", "network_available_cn"),
    ("在管网数据区内", "in_coverage_cn"), ("DEM高程_m", "elevation_m"),
    ("IDF数据集", "dataset_cn"), ("降雨口径", "storm_cn"),
    ("设计历时_min", "duration_min"), ("降雨强度_mm_per_hr", "intensity_mm_hr"),
    ("径流系数C_调整后", "c_adjusted"), ("汇水面积_ha", "area_ha"),
    ("集流时间tc_min", "tc_min"), ("汇水面积出处", "catchment_basis_cn"),
    ("不透水率", "impervious_share"),
    ("管网能力Qcap_m3_per_s", "qcap_m3s"), ("Qcap出处", "qcap_basis_cn"),
    ("最近雨水管距离_m", "nearest_pipe_m"),
    ("峰值流量_m3_per_s", "peak_flow_m3s"), ("超量流量_m3_per_s", "excess_flow_m3s"),
    ("峰值是否超管网能力", "peak_exceeds_cn"),
    ("时限_h", "window_hours"), ("第一道数据源", "l1_basis_cn"),
    ("全程积水量_m3", "runoff_volume_m3"),
    # —— 第一道防线（读二维演算时程，不由 Qcap 推算）——
    ("一道_时限内已退走_m3", "network_drained_m3"),
    ("一道_能否时限内退完", "cleared_by_network_cn"),
    ("一道_实测退干需_h", "drain_hours"),
    ("一道_峰后退干需_h", "recession_hours"),
    ("一道后剩余_m3", "residual_after_network_m3"),
    ("演算峰值积水_m3", "ponding_peak_m3"),
    ("演算峰值时刻_min", "ponding_peak_time_min"),
    ("积水量归属口径", "ponding_attribution"),
    # —— 第二道防线 ——
    ("二道_需调蓄_m3", "required_storage_m3"), ("二道_可用调蓄_m3", "pond_available_m3"),
    ("调蓄出处", "storage_basis_cn"), ("二道_调蓄实吸收_m3", "storage_used_m3"),
    ("二道_能否接住剩余", "cleared_by_storage_cn"),
    # —— 第三道防线 ——
    ("三道_待排水量_m3", "shortfall_m3"),
    ("三道_所需抽排速率_m3_per_hr", "pumping_rate_m3hr"),
    ("派出运力_m3_per_hr", "pump_deployed_m3hr"),
    ("所需移动泵_台", "pumps_required"), ("所需罐车_车次", "tanker_loads"),
    ("单车时限内趟数", "tanker_trips_per_vehicle"), ("所需罐车_辆", "tankers_required"),
    ("喂饱所需泵需罐车_辆", "tankers_to_feed_pumps"),
    # —— 页面配置的车队：配了几台泵几辆车、够不够。与上面「所需」列**并列** ——
    ("配置移动泵_台", "pumps_configured"),
    ("配置罐车_辆", "tankers_configured"),
    ("配置泵侧能力_m3_per_hr", "pump_configured_m3hr"),
    ("配置罐车侧能力_m3_per_hr", "tanker_configured_m3hr"),
    ("链外运能力_m3_per_hr", "chain_configured_m3hr"),
    ("瓶颈在哪侧", "chain_bottleneck_cn"),
    ("配置是否够用", "configured_suffice_cn"),
    ("配置清不完_m3", "chain_residual_m3"),
    ("按配置清完需_hr", "chain_hours_required"),
    ("台账已配泵_台", "pumps_qty"), ("台账已配罐车_台", "tankers_qty"),
    ("防线归类", "line_cn"), ("模型输入版本", "inputs_version"),
)

#: 串联链的瓶颈落在哪一侧 —— 空串 = 这个点没出结论。
BOTTLENECK_CN = {"pump": "泵侧", "tanker": "罐车侧", "balanced": "两侧配平"}

MODEL_VERSION = "0.2.0"

#: 与页面「模型输入」抽屉的初始版本号对应 —— 本模块只跑未改动的默认假设。
DEFAULT_INPUTS_VERSION = "v1.0"


def _n(v: float | int | None, digits: int = 0) -> str:
    """千分位数字；None 显示为 —。"""
    if v is None:
        return "—"
    return f"{v:,.{digits}f}"


def _storage_assets_found() -> int:
    """250 m 内找到的调蓄设施总条数，取自 storage_batch 的产出。缺文件返回 0。"""
    from .registry import HOTSPOT_STORAGE_CSV

    if not HOTSPOT_STORAGE_CSV.exists():
        return 0
    with HOTSPOT_STORAGE_CSV.open(encoding="utf-8-sig", newline="") as fh:
        return sum(int(r["assets_in_radius"] or 0) for r in csv.DictReader(fh))


def _yes_no(v: bool | None) -> str:
    return "—" if v is None else ("有" if v else "无")


def run(
    records: tuple[HotspotRecord, ...] | None = None,
    return_period: int = MAIN_RETURN_PERIOD,
    dataset: str = MAIN_DATASET,
    coverage_only: bool = True,
) -> dict:
    """跑主口径 + 五档重现期，返回导出所需的全部素材。

    `coverage_only` 与页面、`/api/scenario` 同一默认：**只算有管网数据的区域**
    （501 / 845 个点，全部在阿布扎比市）。落在覆盖外的 344 个点没有管网数据，Qcap 只能套假设剖面，
    把它们算进来得到的车队数字不具备对外报送条件（见 `DMT_DATA_REQUEST.md` §01）。
    """
    recs = tuple(records if records is not None else load_registry())
    if coverage_only:
        recs = tuple(r for r in recs if r.in_coverage)
    by_uid = {r.uid: r for r in recs}
    opts = lambda rp: BatchOptions(dataset=dataset, return_period_yr=rp)  # noqa: E731
    main = run_batch(recs, opts(return_period))
    sweep = {rp: run_batch(recs, opts(rp)) for rp in FLEET_RETURN_PERIODS}
    if return_period not in sweep:
        sweep[return_period] = main
    return {
        "records": recs, "by_uid": by_uid, "main": main, "sweep": sweep,
        "return_period": return_period, "dataset": dataset,
        "coverage_only": coverage_only,
    }


# --------------------------------------------------------------------------
# 逐点明细（中文表头）
# --------------------------------------------------------------------------

def _row(point: dict, rec: HotspotRecord, return_period: int) -> dict:
    return {
        "uid": rec.uid, "source": rec.source,
        "municipality": MUNI_CN.get(rec.municipality, rec.municipality),
        "area": rec.area,
        "district_cn": (
            f"{rec.district}（{MUNI_CODE_CN.get(rec.district_municipality, rec.district_municipality)}）"
            if rec.district else "未判定"
        ),
        "location": rec.location,
        "lat": rec.lat, "lon": rec.lon,
        "criticality_cn": CRIT_CN.get(rec.criticality or "", rec.criticality or "未填写"),
        "root_cause_cn": CAUSE_CN.get(rec.root_cause or "", rec.root_cause or "未填写"),
        "network_available_cn": _yes_no(rec.network_available),
        "in_coverage_cn": "是" if rec.in_coverage else "否",
        "elevation_m": rec.elevation_m,
        "dataset_cn": DATASET_CN.get(point["dataset_key"], point["dataset_key"]),
        "storm_cn": f"{return_period} 年一遇",
        "duration_min": point["duration_min"],
        "intensity_mm_hr": point["intensity_mm_hr"],
        "c_adjusted": point["c_adjusted"], "area_ha": point["area_ha"],
        "tc_min": point["tc_min"],
        "catchment_basis_cn": CATCHMENT_BASIS_CN.get(
            point["catchment_basis"], point["catchment_basis"]
        ),
        "impervious_share": rec.impervious_share,
        "qcap_m3s": point["qcap_m3s"],
        "qcap_basis_cn": QCAP_BASIS_CN.get(point["qcap_basis"], point["qcap_basis"]),
        "nearest_pipe_m": rec.nearest_pipe_m,
        "peak_flow_m3s": point["peak_flow_m3s"],
        "excess_flow_m3s": point["excess_flow_m3s"],
        "peak_exceeds_cn": "是" if point["peak_exceeds_capacity"] else "否",
        "window_hours": point["window_hours"],
        "l1_basis_cn": L1_BASIS_CN.get(point["l1_basis"], point["l1_basis"]),
        #: ⚠ 以下各列在无标定点上一律留空，**不是 0** —— 空白 = 这个点没跑过
        #: 二维演算，三道防线不出结论。填 0 会让汇总看起来比实际乐观。
        "runoff_volume_m3": _blank(point["runoff_volume_m3"]),
        "network_drained_m3": _blank(point["network_drained_m3"]),
        "cleared_by_network_cn": _yes_no_blank(point["cleared_by_network"]),
        #: 空白 = 无标定，或演算到结束仍未退干（重力自排无出路）
        #: `drain_hours` 自演算 t=0 起算；`recession_hours` 自峰值起算，与第一道
        #: 的时限 T 同起点，要拿一道的数去对照退干时间用的是后者。
        "drain_hours": _blank(point["drain_hours"]),
        "recession_hours": _blank(point["recession_hours"]),
        "residual_after_network_m3": _blank(point["residual_after_network_m3"]),
        "ponding_peak_m3": _blank(point["ponding_peak_m3"]),
        "ponding_peak_time_min": _blank(point["ponding_peak_time_min"]),
        "ponding_attribution": point["ponding_attribution"] or "",
        "required_storage_m3": _blank(point["required_storage_m3"]),
        "pond_available_m3": point["pond_available_m3"],
        "storage_basis_cn": STORAGE_BASIS_CN.get(point["storage_basis"], point["storage_basis"]),
        "storage_used_m3": _blank(point["storage_used_m3"]),
        "cleared_by_storage_cn": (
            "" if point["cleared_by_storage"] is None
            else "不需要" if point["cleared_by_network"]
            else ("是" if point["cleared_by_storage"] else "否")
        ),
        "shortfall_m3": _blank(point["shortfall_m3"]),
        "pumping_rate_m3hr": _blank(point["pumping_rate_m3hr"]),
        "pump_deployed_m3hr": _blank(point["pump_deployed_m3hr"]),
        "pumps_required": _blank(point["pumps_required"]),
        "tanker_loads": point["tanker_loads"],
        "tanker_trips_per_vehicle": _blank(point["tanker_trips_per_vehicle"]),
        #: 空白 = 周转长于时限，一辆车跑不满一趟，辆数不出数（与 0 辆不是一回事）
        "tankers_required": _blank(point["tankers_required"]),
        "tankers_to_feed_pumps": _blank(point["tankers_to_feed_pumps"]),
        "pumps_configured": _blank(point["pumps_configured"]),
        "tankers_configured": _blank(point["tankers_configured"]),
        "pump_configured_m3hr": _blank(point["pump_configured_m3hr"]),
        "tanker_configured_m3hr": _blank(point["tanker_configured_m3hr"]),
        "chain_configured_m3hr": _blank(point["chain_configured_m3hr"]),
        "chain_bottleneck_cn": BOTTLENECK_CN.get(point["chain_bottleneck"], ""),
        "configured_suffice_cn": _yes_no_blank(point["configured_fleet_suffice"]),
        "chain_residual_m3": _blank(point["chain_residual_m3"]),
        "chain_hours_required": _blank(point["chain_hours_required"]),
        "pumps_qty": rec.pumps_qty, "tankers_qty": rec.tankers_qty,
        "line_cn": LINE_CN[point["line"]],
        #: 页面「模型输入」抽屉没动过就是 v1.0，本模块跑的正是那套默认值。
        "inputs_version": DEFAULT_INPUTS_VERSION,
    }


def write_points_csv(material: dict, path: Path = POINTS_CSV) -> Path:
    """逐点明细写成 CSV。用 utf-8-sig，Excel 直接双击不乱码。"""
    rows = [
        _row(p, material["by_uid"][p["uid"]], material["return_period"])
        for p in material["main"]["points"]
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([cn for cn, _ in CSV_COLUMNS])
        for r in rows:
            w.writerow([r[key] for _, key in CSV_COLUMNS])
    return path


# --------------------------------------------------------------------------
# 中文报告
# --------------------------------------------------------------------------

def _tally_table(tally: dict, name_cn: str, label: dict[str, str], order=None) -> list[str]:
    keys = [k for k in (order or []) if k in tally] or sorted(tally)
    out = [
        f"| {name_cn} | 积水点 | 一道排完 | 二道排完 | 需车队 | 需调蓄 m³ | 待排水量 m³ | 移动泵 台 | 罐车 车次 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for k in keys:
        t = tally[k]
        c = t["line_counts"]
        out.append(
            f"| {label.get(k, k)} | {_n(t['hotspots'])} | {_n(c['1'])} | {_n(c['2'])} | "
            f"{_n(c['3'])} | {_n(t['required_storage_m3'])} | {_n(t['shortfall_m3'])} | "
            f"{_n(t['pumps_required'])} | {_n(t['tanker_loads'])} |"
        )
    return out


def _basis_tally(points: list[dict], key: str, label: dict[str, str]) -> list[str]:
    """按**实际生效**的出处计数 —— 用逐点结果里的 basis，不是台账原始字段。"""
    tally: dict[str, int] = {}
    for p in points:
        k = p[key]
        tally[k] = tally.get(k, 0) + 1
    out = ["| 出处 | 点数 | 含义 |", "|---|---:|---|"]
    for k, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        text = label.get(k, k)
        head, _, tail = text.partition(" —— ")
        out.append(f"| {head} | {_n(n)} | {tail or '—'} |")
    return out


def build_markdown(material: dict) -> str:
    main, sweep = material["main"], material["sweep"]
    recs = material["records"]
    rp, s = material["return_period"], main["summary"]
    a = DEFAULT_ASSUMPTIONS
    gap = fleet_gap(s, a.effective_tiers)
    s_tiers = s["pump_tiers"]
    usage = main["dataset_usage"]
    assets = _storage_assets_found()
    L: list[str] = []
    w = L.append

    w("# 雨水调蓄场景计算结果（中文版）")
    w("")
    scoped = material.get("coverage_only", False)
    done = s["calibrated_hotspots"]
    blank = s["line_counts"]["uncalibrated"]
    w(f"阿布扎比三份 Hotspot Analysis 台账合并清洗后的 {_n(len(recs))} 个积水点，逐点跑一场雨，")
    w(f"结果归入三道防线并汇总为移动泵与罐车需求。主口径为 **{rp} 年重现期**，")
    w("IDF 数据集按每个点的 DEM 高程自动判 ADQCC Zone A / Zone B。")
    w("")
    w(f"⚠ **三道防线只对跑过二维水动力演算的点出结论** —— 本次 {_n(done)} 个点有结论，")
    w(f"{_n(blank)} 个点标为「无标定」。第一道防线读的是演算出来的积水量时程，")
    w("不再由管网能力 Q_cap 推算：实测 `corr(Q_cap, 排空速率) = −0.156`，管段满流能力")
    w("对排空速率没有预测力，方向还是反的（证据链见 `ponding_curve.py` 模块头注释）。")
    w("无标定的点**不外推、不出数**，下文所有水量与车队数字都只是那 "
      f"{_n(done)} 个点的合计。")
    w("")
    w("| | |")
    w("|---|---|")
    w(f"| 生成日期 | {date.today():%Y-%m-%d} |")
    w(f"| 覆盖积水点 | {_n(len(recs))} |")
    w(f"| 主口径重现期 | {rp} 年 |")
    w(f"| IDF 数据集 | 自动分区 —— {' · '.join(f'{DATASET_CN.get(k, k)} {v} 个点' for k, v in sorted(usage.items()))} |")
    w("| 依据标准 | ADQCC WA-726-1，第三版 2022-04 |")
    w(f"| 计算范围 | {'仅有管网数据的区域（全表 845 点中的 ' + _n(len(recs)) + ' 个）' if scoped else '全部 845 个点（含无管网数据区，Qcap 走假设）'} |")
    w(f"| 模型版本 | v{MODEL_VERSION} |")
    w("")
    if scoped:
        w("> **范围说明**：艾因 184 + 西部区 155 + 市区 5 = 344 个点落在管网数据覆盖之外，")
        w("> 其管网能力无法反算，本文不含这些点。补齐所需数据见 `DMT_DATA_REQUEST.md` §01。")
        w("")
    w(f"> 逐点明细见 `backend/data/processed/scenario_points_zh.csv`（{_n(len(recs))} 行，中文表头，UTF-8 BOM，")
    w("> Excel 可直接打开）。本文与明细表均由 `python -m stormwater.report` 生成，改数字请改计算侧。")
    w("")
    w(f"**三道防线共用一个时限 T = {a.drawdown_hours:g} 小时**：第一道问「T 时刻地面上还剩多少水」，")
    w("第二道问「这些水现有调蓄接不接得住」，第三道问「还剩的要几台移动泵在同一个 T 内排完」。")
    w("")
    w("四个关键数字：")
    w("")
    _d = done or 1
    w(f"- **{_n(s['line_counts']['1'])}** 个点（有结论的 {s['line_counts']['1'] / _d:.0%}）在 {a.drawdown_hours:g} h 内地面的水退完 —— 第一道成立")
    w(f"- **{_n(s['line_counts']['3'])}** 个点（有结论的 {s['line_counts']['3'] / _d:.0%}）在 {rp} 年一遇下要靠第三道防线，即出动移动泵与罐车")
    w(f"- **{_n(s['shortfall_m3'])} m³** 要在 {a.drawdown_hours:g} h 内抽走，其中无一立方被现有调蓄吸收 —— 第二道防线当前恒为 0")
    w(f"- **{_n(gap['pumps_required'])}** 台移动泵的需求 vs 这 {_n(done)} 个点台账已配 "
      f"**{_n(gap['pumps_on_ledger'])}** 台，缺口 {_n(gap['pumps_gap'])} 台")
    w("")
    w(f"> 在册台数只数有结论的那 {_n(done)} 个点 —— 与需求侧同口径，缺口才算得准。"
      f"筛选范围内全部 {_n(len(recs))} 个点的在册数是 "
      f"{_n(s['ledger_all_pumps_qty'])} 台，那是另一个口径，不能拿来比这里的需求。")
    w("")
    w(f"⚠ 另有 **{_n(s['peak_exceeds_capacity'])}** 个点峰值流量超过管网能力 —— 这些点**地面会积起来**。")
    w(f"「会不会淹」和「{a.drawdown_hours:g} h 内退不退得完」是两个问题，明细表的")
    w("「峰值是否超管网能力」与「一道_能否时限内退完」两列分别回答。前者由推理公式的")
    w("峰值流量与 Q_cap 比得出，对每个点都有；后者只有跑过二维演算的点才有。")
    w("")
    w("---")
    w("")

    w("## 1 · 五档重现期总览")
    w("")
    w("同一套输入、同一套假设，只换重现期。")
    w("")
    w("⚠ **除主口径外的各档「有结论」都是 0** —— 二维演算只跑过 100 年一遇这一场，")
    w("其余各档没有任何点出得了防线结论。这几行的 0 是「**没算**」，不是「没事」，")
    w("不可据此说低重现期下不需要车队。要填满这张表，须逐档重跑 ANUGA。")
    w("")
    w(f"| 重现期 | 有结论 | 一道退完 | 二道排完 | 需车队 | 需调蓄 m³ | {a.drawdown_hours:g}h 待排 m³ | 移动泵 台 | 罐车 车次 |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for k in sorted(sweep):
        t = sweep[k]["summary"]
        c = t["line_counts"]
        star = " ★" if k == rp else ""
        if not t["calibrated_hotspots"]:
            # 一个点都没结论：整行画横线，绝不写 0
            w(f"| **{k} 年**{star} | 0 | — | — | — | — | — | — | — |")
            continue
        w(
            f"| **{k} 年**{star} | {_n(t['calibrated_hotspots'])} | "
            f"{_n(c['1'])} | {_n(c['2'])} | {_n(c['3'])} | "
            f"{_n(t['required_storage_m3'])} | {_n(t['shortfall_m3'])} | "
            f"{_n(t['pumps_required'])} | {_n(t['tanker_loads'])} |"
        )
    w("")
    w(f"★ = 主口径。「二道排完」一列为 0 不是没算，是**算出来就是 0**：{_n(len(recs))} 个点 250 m 内")
    w(f"共找到 {_n(assets)} 条调蓄设施记录，无一条的深度数据可用（见 §5）。")
    w("")
    # 台数是派车组合的结果，**不保证**随重现期单调。真出现回落时才提醒，
    # 并指出是哪两档 —— 输入一变（如逐点 A / C / tc 换成实测）回落就可能消失。
    rps = sorted(sweep)
    dips = [
        (lo, hi) for lo, hi in zip(rps, rps[1:])
        if sweep[hi]["summary"]["pumps_required"] < sweep[lo]["summary"]["pumps_required"]
    ]
    if dips:
        lo, hi = dips[0]
        w(f"⚠ **移动泵的「台数」一列不随重现期单调上升**（{lo} 年 "
          f"{_n(sweep[lo]['summary']['pumps_required'])} 台 > {hi} 年 "
          f"{_n(sweep[hi]['summary']['pumps_required'])} 台）。这不是算错：派车规则按"
          "「总排量 + 台数 × 最小档排量」最小选组合，需求越过某档门槛后，")
        w("**一台大泵替掉两台小泵**，台数反而降。单调上升的是待排水量与派出运力，"
          "台数只是组合结果 —— 采购论证看 §6.1 的分档表，不要只看总台数。")
    else:
        w("⚠ 本次五档台数恰好单调上升，但**台数本身不保证单调**：派车规则按"
          "「总排量 + 台数 × 最小档排量」最小选组合，需求越过某档门槛时"
          "一台大泵可替掉两台小泵，台数会回落。单调的是待排水量与派出运力 ——"
          "采购论证看 §6.1 的分档表，不要只看总台数。")
    w("")

    w(f"## 2 · 主口径（{rp} 年一遇）三道防线")
    w("")
    T = a.drawdown_hours
    w("判定口径：总量取二维演算的**全程**净入流（不掐在时限上 —— T 是工期不是观测")
    w(f"时刻）；第一道 R1 = max(0, 总量 − R × T)，R 是该点演算实测的**退水期平均**速率，")
    w(f"即「管网这条腿在 T = {T:g} h 内分担不掉、要往下交的量」；这部分交给现有调蓄；")
    w("再接不住的，由移动泵在**同一个** T 内抽走。Q_cap 不参与这条水量链，只用来判")
    w("「峰值会不会溢流」。")
    w("")
    w("| 归类 | 积水点 | 占有结论的 | 判定条件 |")
    w("|---|---:|---:|---|")
    meanings = {
        1: f"总量 ≤ R × T —— 管网这条腿 {T:g} h 内自己就排完了，不需要额外动作",
        2: "还有积水，但余量 ≤ 周边可用调蓄容量",
        3: f"调蓄也不够，余量要靠移动泵在 {T:g} h 内抽排 + 罐车外运",
        None: "本点未跑过二维演算（或演算的重现期与本表不符），不出结论",
    }
    for line in (1, 2, 3):
        n = s["line_counts"][str(line)]
        w(f"| {LINE_CN[line]} | {_n(n)} | {n / _d:.1%} | {meanings[line]} |")
    w(f"| {LINE_CN[None]} | {_n(blank)} | — | {meanings[None]} |")
    w("")
    w(f"**这些水在 {T:g} 小时的工期里由谁清走**（m³，全网合计）：")
    w("")
    w("| 防线 | 水量 m³ | 占比 |")
    w("|---|---:|---:|")
    _tot = (s["line1_m3"] + s["line2_m3"] + s["line3_m3"]) or 1.0
    for name, key in (("第一道 · 管网时限内排走", "line1_m3"),
                      ("第二道 · 现有调蓄吸收", "line2_m3"),
                      ("第三道 · 移动泵抽排", "line3_m3")):
        w(f"| {name} | {_n(s[key])} | {s[key] / _tot:.1%} |")
    w(f"| **合计** | **{_n(_tot)}** | 100% |")
    w("")
    w(f"全程积水总量 **{_n(s['runoff_volume_m3'])} m³**（演算全程净入流，与时限无关；"
      f"合计略小于上表，差额是第二、三道计入的 "
      f"{a.sed_factor:g} 倍淤积裕量）。所需调蓄合计 **{_n(s['required_storage_m3'])} m³**，"
      f"已有可用调蓄 **{_n(s['available_pond_m3'])} m³**。")
    w("")
    w("峰值口径对照（m³/s，全网合计）：管网吃下 "
      f"**{s['line1_m3s']:,.1f}**，峰值溢流 **{s['excess_flow_m3s']:,.1f}**，"
      f"总峰值 **{s['peak_flow_m3s']:,.1f}**。")
    w("")
    w("⚠ 上表的水量来自 **ANUGA 二维演算的逐帧积水量**，随成果一起带三条限制：")
    w("")
    w("1. 只覆盖 Al Bateen 一个 run，且该 run 的 SWMM 注入实际只进了 123,263 m³，")
    w("   比预设的 288,838 m³ 少 32% —— 绝对量偏小，目前只宜用于相对排序与过程分析。")
    w("2. 20 m 计算网格由 5 m DTM 聚合，路缘、分隔带被抹平，相邻积水坑会并粗；")
    w("   逐点值只可用于筛查排序，**不可作单点设计依据**。")
    w("3. 归属口径为「坡面直排」的点只报本格水量，是**下限**而非该点实际积水量；")
    w("   明细表的「积水量归属口径」一列逐点标出。")
    w("")
    w(f"⚠ 时限 T = {T:g} h 与演算结果不相容：这批点的等效排空时间常数落在 10.2–16.8 h")
    w("（中位 12.4 h），地表退水本身就要半天。车队规模对 T 是**先升后降**的非单调")
    w("曲线，在 T ≈ 2 h 见顶 —— 那时水已经积起来、却还没时间退，而时限又短到抽排")
    w("速率压不下来。T 是服务水平目标，应由决策者显式选定，不该沿用默认值。")
    w("")

    w(f"### 2.1 需出动车队的点里最吃紧的 15 个（按 {a.drawdown_hours:g} h 待排水量排序）")
    w("")
    w("| # | 编号 | 位置 | 片区 | 时限内积水 m³ | 管网排走 m³ | 待排 m³ | 大型 12″ | 中型 8″ | 小型 6″ | 台账已配 |")
    w("|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    worst = sorted(
        (q for q in main["points"] if q["line"] == 3),
        key=lambda q: -q["shortfall_m3"],
    )[:15]
    for i, q in enumerate(worst, 1):
        r_ = material["by_uid"][q["uid"]]
        t_ = q["pumps_by_tier"]
        w(f"| {i} | {q['uid']} | {(r_.location or '—')[:28]} | {r_.area or '—'} | "
          f"{_n(q['runoff_volume_m3'])} | {_n(q['network_drained_m3'])} | "
          f"{_n(q['shortfall_m3'])} | {t_.get('12in', 0)} | {t_.get('8in', 0)} | "
          f"{t_.get('6in', 0)} | {_n(r_.pumps_qty)} |")
    w("")
    w("⚠ 前几名里 Q_cap 实测为 0 的点（250 m 内确实没有雨水管）之间，差距只剩汇水面积")
    w("与下垫面构成 —— 而汇水边界用的是 Voronoi 几何代理，不是实测汇水区，")
    w("**这一段内的先后次序仍然不够硬**，要定先后得先有逐点汇水区划分（清单 §09）。")
    w("")
    w(f"完整的 {_n(len(recs))} 个点逐点结论见 `backend/data/processed/scenario_points_zh.csv` ——")
    w("每行给出该点三道防线各自的答案：管网在时限内能排多少、还剩多少、调蓄接不接得住、")
    w("最后要几台什么口径的泵。")
    w("")

    w("## 3 · 分行政区")
    w("")
    L.extend(_tally_table(main["by_municipality"], "行政区", MUNI_CN))
    w("")

    w("## 4 · 分严重度（台账口径）")
    w("")
    L.extend(_tally_table(main["by_criticality"], "严重度", CRIT_CN, CRIT_ORDER))
    w("")
    w("⚠ 严重度是台账已有的官方分级，**不是**本模型算出来的，两者可能不一致；")
    w("模型的排序依据是时限内的待排水量，见明细表的「三道_待排水量_m3」列。")
    w("")

    w("## 5 · 数据可信度")
    w("")
    w("### 5.1 管网能力 Qcap 的出处")
    w("")
    L.extend(_basis_tally(main["points"], "qcap_basis", QCAP_BASIS_CN))
    w("")
    w("⚠ 台账的「有无排水管网」字段不可单独作准：与管网几何逐点核对后，ADM 写「无管网」的")
    w("171 个点里有 135 个、250 m 内实际有雨水管；写「有管网」的 335 个里有 28 个附近没有管。")
    _ledger_n = sum(1 for p in main["points"] if p["qcap_basis"] == "ledger_no_network")
    w("只有在完全没有管网数据的区域（艾因、西部区）才回退到这个字段，并标为低置信度"
      + ("。" if _ledger_n else "；本文范围内没有这样的点。"))
    w("")
    w("### 5.2 可用调蓄容量的出处")
    w("")
    L.extend(_basis_tally(main["points"], "storage_basis", STORAGE_BASIS_CN))
    w("")
    w(f"250 m 内共找到 {_n(assets)} 条设施记录，**无一条通过深度校验**：调蓄池 23 条里 19 条池底与盖板同高；")
    w("蓄水构筑物 20 条全部「最高水位 ≤ 池底高程」；渗井 977 条里 923 条三个尺寸字段全为 0。")
    w("因此第二道防线全网为 0 —— 这是数据问题，不是现场真的一处调蓄都没有。")
    _nocov = sum(1 for p in main["points"] if p["storage_basis"] == "assumed_no_coverage")
    if _nocov:
        w("")
        w(f"另有 **{_n(_nocov)}** 个点 5 km 内没有任何调蓄设施记录 —— 设施图层在计算范围内部"
          "也不连续，这类点的 0 是「没数据」，与上面「实测没有」不是一回事（见 §03）。")
    w("")

    w("## 6 · 车队需求 vs 台账已配")
    w("")
    w("| | 模型需求 | 台账已配 | 差额 |")
    w("|---|---:|---:|---:|")
    w(f"| 移动泵（台） | {_n(gap['pumps_required'])} | {_n(gap['pumps_on_ledger'])} | {_n(gap['pumps_gap'])} |")
    w(f"| 罐车（辆） | {_n(gap['tankers_required'])} | {_n(gap['tankers_on_ledger'])} | {_n(gap['tankers_gap'])} |")
    _lpt = gap["loads_per_tanker"]
    w(f"| 罐车（车次） | {_n(gap['tanker_loads_required'])} 车次 | — | "
      + (f"台账每辆约跑 {_n(_lpt)} 趟" if _lpt else "台账这批点没有罐车")
      + " |")
    w("")
    w("⚠ **两个数不同口径，相减只能当量级参考，不能当采购依据。** 模型给的是「同时出动的泵台数」，")
    w("台账给的是「各点已列装的泵台数」。")
    w("")
    w(f"⚠ 罐车的**车次**只是体积换算（待排水量 ÷ 单车 {a.tanker_capacity:g} m³），与时限无关；"
      f"**辆数**才是调度结论 —— 按单车往返周转 {a.tanker_turnaround_min:g} min，"
      f"一辆车在 {a.drawdown_hours:g} h 内跑 "
      f"{a.tanker_trips_within(a.drawdown_hours)} 趟折算而来。周转时间**本项目无数据支撑**，"
      "是待 DMT 补的实测量（交接文档 §7 待决策第 5 条）。")
    if gap["points_tanker_infeasible"]:
        w("")
        w(f"⚠ 其中 **{_n(gap['points_tanker_infeasible'])}** 个点的周转时间长于时限 —— "
          "一辆车连一趟都跑不完。泵抽出来的水没车拉走，这些点第三道防线**整条不成立**，"
          "上面的辆数合计是下限。加车没用（卡的是时延不是运力），只能放宽时限或把受纳点设近。")
    w("")
    w("### 5.x 泵和罐车是一条串联的链，不是两个可选方案")
    w("")
    w("移动泵把积水抽进罐车，罐车拉到受纳点倒掉再回来 —— **两段串在一起，缺一段就是零**。")
    w("所以上表的泵台数与罐车辆数是**同时都要**的一对，不能二选一；")
    w("这个点每小时真正走得掉多少水，由**瓶颈段**定：")
    w("")
    w("```")
    w("链的外运能力 = min(泵侧抽排能力, 罐车侧持续外运能力)")
    w("```")
    w("")
    w(f"两侧在当前参数下差着一个量级 —— 一台泵 {_n(a.pump_unit_capacity)} m³/h，"
      f"而一辆 {a.tanker_capacity:g} m³、周转 {a.tanker_turnaround_min:g} min 的罐车"
      f"持续外运只有 **{_n(a.tanker_vehicle_rate_m3hr, 1)} m³/h**：")
    w("")
    w(f"> **喂饱一台泵要配 {a.tankers_per_pump} 辆罐车。**")
    w("")
    w(f"按这个比值，全域所需的 **{_n(gap['pumps_required'])}** 台泵要 "
      f"**{_n(gap['tankers_to_feed_pumps'])}** 辆车才喂得饱；按水量算需 "
      f"**{_n(gap['tankers_required'])}** 辆。两个约束都得满足，故真正要配的是"
      f"取大的那个：**{_n(gap['tankers_required_binding'])}** 辆"
      f"（台账在册 {_n(gap['tankers_on_ledger'])} 辆，缺 **{_n(gap['tankers_gap'])}** 辆）。")
    w("")
    w("⚠ 罐车侧是这条链的**结构性瓶颈**，不是参数没调好：单车容量和周转时间"
      "决定了一辆车每小时只搬得动十几立方米的水。要么大幅增加车辆，要么把水"
      "就近排进受纳水体/管网（那样才轮不到罐车），二者必居其一。")
    w("")
    w("### 6.0 按页面当前配置")
    w("")
    w(f"页面上配的是**每个积水点 {a.pumps_per_point} 台泵（每台 "
      f"{_n(a.pump_unit_capacity)} m³/h）+ {a.tankers_per_point} 辆罐车"
      f"（每辆 {a.tanker_capacity:g} m³ / {a.tanker_turnaround_min:g} min）**。")
    w(f"两侧能力 {_n(a.pump_configured_m3hr)} vs {_n(a.tanker_configured_m3hr, 1)} m³/h，"
      f"取小 —— 这条链实际的外运能力是 **{_n(a.chain_configured_m3hr, 1)} m³/h**，"
      f"瓶颈在**{BOTTLENECK_CN[a.chain_bottleneck]}**。按这个配置跑下来：")
    w("")
    w(f"- 有结论的点共配 **{_n(gap['pumps_configured'])}** 台泵、"
      f"**{_n(gap['tankers_configured'])}** 辆罐车；"
      f"要在 {a.drawdown_hours:g} h 内清完则需 **{_n(gap['pumps_required'])}** 台泵"
      f"（还差 **{_n(gap['pumps_configured_gap'])}** 台）+ "
      f"**{_n(gap['tankers_required_binding'])}** 辆罐车")
    w(f"- **{_n(gap['points_under_served'])}** 个点按这个配置在 {a.drawdown_hours:g} h 内清不完，"
      f"合计还剩 **{_n(gap['chain_residual_m3'])} m³** 留在地面")
    if gap["points_tanker_bound"]:
        w(f"- 其中 **{_n(gap['points_tanker_bound'])}** 个点**卡在罐车侧** —— "
          f"这些点再加泵一滴水也多排不出去，要加的是车")
    w("")
    w("⚠ 这三个数**分开读**：「配置」是页面上设的假设，「需求」是模型按水量算的，")
    w("「台账已配」是实际列装记录。两两相减各有各的含义，不可混为一谈。")
    w("")

    single_tier = [t["key"] for t in s_tiers] == ["uniform"]
    w("### 6.1 移动泵分口径")
    w("")
    if single_tier:
        w("本次按**页面设定的单一排量**算，故这里只有一行合计 —— 在册台数是")
        w("12″/8″/6″ 三档之和，单档口径下拆不开，也不该假装拆得开。")
    else:
        w("总台数够不代表大口径够 —— 采购论证看的是这张表。")
    w("")
    w("| 口径 | 额定排量 m³/h | 模型需求（台） | 阿布扎比市在册（台） | 缺口 |")
    w("|---|---:|---:|---:|---:|")
    rated = {t["key"]: t for t in s_tiers}
    for row in gap["by_tier"]:
        cap = rated.get(row["key"], {}).get("rated_m3hr")
        w(f"| {row['label']} | {_n(cap)} | {_n(row['required'])} | "
          f"{_n(row['on_fleet'])} | {_n(row['gap'])} |")
    w(f"| **合计** | | **{_n(gap['pumps_required'])}** | "
      f"**{_n(gap['fleet_total'])}** | |")
    w("")
    if single_tier:
        w("要按 12″/8″/6″ 分档出需求构成（采购论证的形式），把页面上的「单泵抽排能力」")
        w("清空即可 —— 分档派车的逻辑完整保留在 `pumps.dispatch()`，只是不再是默认口径。")
    else:
        w("派车规则：在总排量不小于需求的组合里，取「总排量 + 台数 × 最小档排量」最小的那个 ——")
        w("即**车不是免费的，每多派一台按一台 6″ 泵的运力计价**。只求最少台数会把 300 m³/h 的")
        w("小活也派一台 12″（在册仅 144 台、约 4.5 t 需拖车）；只求最小过配会给一个点摆二十多台 6″。")
    w("")
    w("⚠ 在册台数是**阿布扎比市**口径（三份台账），艾因与扎夫拉未单列；")
    w("且模型不受在册台数约束 —— 某档需求超出在册台数正是要报出来的结论。")
    w("")

    w("## 7 · 计算口径与假设参数")
    w("")
    w("| 参数 | 取值 | 性质 |")
    w("|---|---:|---|")
    w(f"| 淤积裕量系数 | {a.sed_factor} | 有出处（DM 导则 Sec 5.1） |")
    w(f"| 过程线形状系数 | {a.shape_factor} | **假设值** —— 三角形近似，真值需 InfoSWMM 演算 |")
    w(f"| **三道防线共用时限 T** | {a.drawdown_hours} hr | 运营设定，应替换为实际应急响应 SLA |")
    w(f"| **每个积水点配置泵数** | {a.pumps_per_point} 台/点 | 页面设定 —— 运营配置，不是模型算出来的 |")
    w(f"| **单泵抽排能力** | {_n(a.pump_unit_capacity)} m³/hr | "
      f"页面设定 —— **假设值**，落在在册车队加权平均 321 附近 |")
    w(f"| **每个积水点配置罐车数** | {a.tankers_per_point} 辆/点 | "
      f"页面设定 —— 与泵**串联**，两侧取小才是实际外运能力 |")
    w(f"| 罐车单车储水能力 | {a.tanker_capacity} m³/车次 | 页面设定 —— **假设值**，应替换为实际单车载量 |")
    w(f"| **罐车单车往返周转时间** | {a.tanker_turnaround_min:g} min/趟 | "
      f"页面设定 —— **假设值，本项目无任何数据支撑**；车次折辆数、单车外运能力全靠它 |")
    w(f"| 单车持续外运能力 | {_n(a.tanker_vehicle_rate_m3hr, 1)} m³/hr | "
      f"= 单车容量 / 周转，不单独设定 |")
    w(f"| **喂饱一台泵需配罐车** | {a.tankers_per_pump} 辆/台 | "
      f"= ⌈单泵排量 / 单车外运能力⌉，不单独设定 —— 这条链的核心比值 |")
    w(f"| 泵车工况扬程折减 | {a.pump_duty_factor} | **推算系数** —— TDH 10–20 m 下的经验区间中值（只作用于分档表） |")
    w(f"| 泵车出勤占空 | {a.pump_availability} | **推算系数** —— 加油、转场、清堵占用（只作用于分档表） |")
    w("")
    if single_tier:
        w("### 7.1 移动泵分档排量（参照，本次未参与计算）")
        w("")
        w(f"上面那个 {_n(a.pump_unit_capacity)} m³/h 是页面上设的一个数。它该设多少，"
          "对照在册车队的实际构成：")
    else:
        w("### 7.1 移动泵分档排量")
    w("")
    w("| 档位 | 铭牌最大 m³/h | 额定排量 m³/h | 在册台数 | 性质 | 出处 |")
    w("|---|---:|---:|---:|---|---|")
    #: 单档口径下 `s_tiers` 只有「移动泵」一行，摆出来没有参照价值 ——
    #: 这里改摆三档参照表，正是操作员选那个数时要看的东西。
    ref_tiers = (
        [
            {
                "label": t.label, "nameplate_m3hr": t.nameplate_m3hr,
                "rated_m3hr": t.rated_m3hr(a.pump_duty_factor, a.pump_availability),
                "fleet_qty": t.fleet_qty, "basis": t.basis, "reference": t.reference,
            }
            for t in DEFAULT_PUMP_TIERS
        ]
        if single_tier else s_tiers
    )
    for t in ref_tiers:
        w(f"| {t['label']} | {_n(t['nameplate_m3hr'])} | {_n(t['rated_m3hr'])} | "
          f"{_n(t['fleet_qty'])} | {t['basis']} | {t['reference']} |")
    w("")
    w("额定排量 = 铭牌最大流量 × 工况折减 × 出勤占空。铭牌值是**近零扬程下的最大流量**，")
    w("不能直接用；城市积水抽排的实际 TDH 在 10–20 m，离心泵在该点约为最大流量的 55–75%。")
    w("")
    w("⚠ **三档都还是铭牌折减值，没有一档是 DMT 实测。** 这是数据需求清单 §02 要补的东西 ——")
    w("拿到现场工作扬程下的实测排量后填进对应档，该档即绕过上面两级折减。")
    weighted = fleet_weighted_capacity(
        a.pump_tiers, a.pump_duty_factor, a.pump_availability
    )
    w(f"按在册构成加权平均为 {_n(weighted)} m³/h，与原 Excel 全车队统一假设的 "
      f"{_n(LEGACY_PUMP_CAPACITY)} m³/h 相差 "
      f"{abs(weighted - LEGACY_PUMP_CAPACITY) / LEGACY_PUMP_CAPACITY:.0%} —— "
      "即**总台数量级站得住，分档改变的是需求构成**。")
    w("")
    w("逐点的汇水面积 A、径流系数 C、集流时间 tc 已由 `catchment_batch.py` 逐点反算 ——")
    w("**剖面假设只剩兜底作用**，只有地籍图层未覆盖的点才会用到：")
    w("")
    w("| 成因分组 | 兜底汇水面积 ha | 兜底径流系数 C | 兜底集流时间 min | 组内点数 | 真正用到兜底的点数 |")
    w("|---|---:|---:|---:|---:|---:|")
    from .registry import DEFAULT_PROFILES, profile_key_for
    group_n: dict[str, int] = {}
    fallback_n: dict[str, int] = {}
    for r in recs:
        k = profile_key_for(r)
        group_n[k] = group_n.get(k, 0) + 1
        if r.catchment_basis not in ("measured", "measured_undeveloped"):
            fallback_n[k] = fallback_n.get(k, 0) + 1
    for k, p in DEFAULT_PROFILES.items():
        if not group_n.get(k):
            continue    # 没有点落进来的分组不列（例如成因未填写时的兜底剖面）
        w(f"| {CAUSE_CN.get(k, '其他 / 未分组')} | {p.area_ha} | {p.runoff_c} | {p.tc_min} | "
          f"{_n(group_n[k])} | {_n(fallback_n.get(k, 0))} |")
    w("")
    w("实测出处的分布：")
    w("")
    L.extend(_basis_tally(main["points"], "catchment_basis", CATCHMENT_BASIS_CN))

    w("## 8 · 局限声明")
    w("")
    w("1. 使用推理公式法 + 简化三角形过程线，属**筛查与排序工具，不是最终设计**。")
    w("2. 导则要求调蓄池与泵站的实际设计必须采用 InfoSWMM（或认可的等效软件）建模报批。")
    w(f"3. 推理公式法仅适用于汇水面积 < {RATIONAL_METHOD_MAX_AREA_HA:g} 公顷的汇水区；"
      f"本次 {_n(s['oversized_catchments'])} 个点超限。")
    w("4. 汇水面积 A、径流系数 C、集流时间 tc 虽已逐点反算，但汇水**边界**用的是")
    w("   「相邻积水点 Voronoi 等分 + 250 m 截断」的几何代理，不是汇水区划分成果")
    w("   （清单 §09）。逐点数字可用于横向比较排序，不能单点当设计依据。")
    if scoped:
        w("5. 本文只含有管网数据的区域；落在覆盖外的 344 个点（艾因 184 + 西部区 155 +")
        w("   市区外围 5）不在范围内，补齐所需数据见 `DMT_DATA_REQUEST.md` §01。")
    else:
        w("5. 艾因与西部区的雨水管网尚未导出，339 个点的 Qcap 仍是假设值。")
    w(f"6. Qcap 取的是「250 m 内收集系统级管道的最大满流能力」，属**筛查代理量**，不是下游瓶颈分析。")
    w(f"7. 第一道防线按「演算实测的**退水期平均**速率 R × {a.drawdown_hours:g} 小时」估算：")
    w("   R = 峰后累计退水量 ÷ 峰后退水期时长，分母与实测退干时间同一条曲线，两者自洽。")
    w("   口径**偏保守**：峰值水头下真实退得比平均快，故第一道成立的点数是下限、需出动")
    w("   车队的点数是上限。（2026-09-21 前 R 取的是最大帧降幅，在 123 个有演算的点上无一")
    w("   例外地高估 1.9–8.1 倍，已回退。）Qcap 不参与这条水量链。")
    w(f"8. 移动泵假定**零响应时间**，与管网同在第 0 小时起算；把到场时间计入后，")
    w(f"   泵在 {a.drawdown_hours:g} h 内的有效工作时长变短，所需台数上升。实际 SLA 应替换 T。")
    w("")
    w("以上 1–6 项与 `docs/DMT_DATA_REQUEST.md` 列的数据缺口对应；")
    w("其中标为阻塞的 §03（调蓄设施深度）与 §09（汇水区 / 地形）不补齐，")
    w("本文结论不具备对外报送条件。")
    w("")
    return "\n".join(L)


def write_report_md(material: dict, path: Path = REPORT_MD) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_markdown(material), encoding="utf-8")
    return path


def main() -> None:
    material = run()
    csv_path = write_points_csv(material)
    md_path = write_report_md(material)
    n = len(material["main"]["points"])
    print(f"逐点明细：{csv_path}（{n} 行 × {len(CSV_COLUMNS)} 列）")
    print(f"中文报告：{md_path}")


if __name__ == "__main__":
    main()
