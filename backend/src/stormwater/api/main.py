"""HTTP API：指挥中心（845 点落图批算）、单点快算、Qcap 反算。

前后端分离：本进程**只出 JSON**，页面由 `frontend/` 那个 Vue 3 + Vite 工程单独部署。
跨源访问靠下面的 CORS 白名单放行，见 .env 的 `CORS_ORIGINS`。

IDF 数据集可切换（迪拜 DM / ADQCC Zone A / ADQCC Zone B），
切换的不只是数字还有方法，故每次计算的结果都带上 `dataset_key` 自描述。

⚠ 批量场景（`/api/scenario`）用的逐点 A / C / tc / Qcap 是**按成因分组的假设剖面**
  （见 `registry.py`），不是实测值；返回体里的 caveats 与 limitations 必须原样展示。
"""

import json
import os
from contextlib import asynccontextmanager
from dataclasses import asdict, replace

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..constants import DEFAULT_ASSUMPTIONS, Assumptions, DefenceBasis
from ..i18n import caveats as caveats_for, resolve_lang, tr, tr_all, tr_values
from ..idf import (
    ADQCC_TABLE_DURATIONS_MIN,
    ADQCC_ZONE_B_DDF_DEPTH_MM,
    DEFAULT_DATASET_KEY,
    DESIGN_RETURN_PERIOD_BY_FACILITY,
    DUBAI_DURATIONS_MIN,
    FLEET_RETURN_PERIODS,
    IDF_DATASETS,
    IDF_DUBAI,
    CatchmentPriority,
    get_dataset,
)
from .. import hyetograph, sim_mock
from .rda import router as rda_router
from .simulations import router as simulations_router
from ..model_registry import load_model_registry
from ..manning import (
    DiameterUnit, GradientConvention, circular_pipe_qcap, manning_n,
    normalize_diameter, normalize_gradient,
)
from ..rational import Hotspot, ScenarioResult, compare_datasets, evaluate_all, fleet_summary
from ..registry import (
    DEFAULT_PROFILES,
    PONDING_BASIS_LABEL,
    PROFILE_FIELD_BASIS,
    ZONE_A_MIN_ELEVATION_M,
    CatchmentProfile,
    build_hotspot,
    catchment_basis_for,
    dataset_key_for,
    district_ponding,
    facets,
    load_registry,
    qcap_basis_for,
    storage_basis_for,
)
from ..scenario import (
    CUSTOM_RETURN_PERIOD,
    BatchOptions,
    CustomStormIdf,
    fleet_gap,
    run_batch,
)

#: 与所选 IDF 数据集无关的通用局限（交接文档 §3.7）
LIMITATIONS = [
    "使用推理公式法 + 简化三角形过程线，属筛查与排序工具，非最终设计。",
    "导则要求调蓄池与泵站的实际设计必须采用 InfoSWMM（或认可的等效软件）建模报批。",
    "推理公式法仅适用于汇水面积 < 80 公顷的汇水区，超过须拆分子汇水区或改用 SCS 过程线法。",
    "过程线形状系数 0.50，以及页面上那几个旋钮的默认值（每点 1 台泵、单泵 300 m³/hr、"
    "每点 1 辆罐车、单车 15 m³ / 周转 60 min）均为假设值，须替换为实测值 —— "
    "正因如此才摆在页面上让人改。",
    "第一道防线只对跑过二维水动力演算的点出结论；其余点标为「无标定」，不外推、不出数。"
    "当前 845 个台账点里 18 个有标定（仅 Al Bateen 100 年一遇一场），所有水量与车队数字都只是这批点的合计。",
    "移动泵与罐车是**串联**的一条链，不是两个可选方案：泵把积水抽进罐车、罐车运走，"
    "所以外运能力取两侧较小值，泵数与车数同时都要。默认参数下单泵 300 m³/hr、"
    "单车持续外运仅 15 m³/hr —— 喂饱一台泵要 20 辆车，瓶颈几乎总在罐车侧。",
    "移动泵按零响应时间、与地表退水同在第 0 小时起算；把到场时间计入后所需台数上升。",
    "时限 T 默认 2 小时，与二维演算不相容 —— 实测等效排空时间常数中位 12.4 小时。"
    "车队规模对 T 是先升后降的非单调曲线，T 应作为服务水平目标显式选定。",
]

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 算力侧未接入前，后台模拟仿真任务的进度（见 `sim_mock.py`；SIM_MOCK_PROGRESS=0 关闭）
    stop = sim_mock.start()
    yield
    if stop is not None:
        stop.set()


app = FastAPI(title="雨水调蓄计算器 API", version="0.3.0", lifespan=lifespan)

#: 允许跨源访问本 API 的前端地址。前后端分离后浏览器会拦跨源请求，得逐个放行。
#: 默认放行 Vite 开发服务器的两种写法（localhost / 127.0.0.1）；
#: 部署到别的域名时在 .env 里用逗号分隔覆盖，例如
#: `CORS_ORIGINS=https://flood.example.com,https://staging.example.com`。
#: 本地开发若走 Vite 代理（前端默认做法），请求是同源的，压根不经过这里。
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
CORS_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if o.strip()
]

app.include_router(simulations_router)
app.include_router(rda_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    # 本 API 不认 Cookie 也不发 Session，故不开 credentials —— 开了就不能用通配源，
    # 且会把「谁都能带着用户 Cookie 打这个接口」的风险引进来。
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


# ---------------------------------------------------------------------------
# 语言 —— 只作用于**展示文案**，一个数字、一个 key 都不动。见 `i18n.py` 的模块文档。
# ---------------------------------------------------------------------------


def lang_of(
    lang: str | None = None,
    accept_language: str | None = Header(default=None, alias="Accept-Language"),
) -> str:
    """`?lang=zh|en` 优先，其次 `Accept-Language`，都没有就中文。"""
    return resolve_lang(lang, accept_language)


Lang = Depends(lang_of)


def _fail(status: int, detail: str, lang: str):
    """报错也要跟着语言走 —— 页面把 detail 直接印在提示条上。"""
    return HTTPException(status_code=status, detail=tr(detail, lang))


def _loc_dataset(d: dict, lang: str) -> dict:
    """数据集自述：只翻 label / source / notes，`key` 是协议值不动。"""
    if not d:
        return d
    return {**d, "label": tr(d.get("label"), lang), "source": tr(d.get("source"), lang),
            "notes": tr_all(d.get("notes"), lang)}


def _loc_tiers(tiers, lang: str) -> list:
    """泵分档表：`key` 不动，展示名与出处跟着语言走。"""
    return [
        {**t, "label": tr(t.get("label"), lang), "basis": tr(t.get("basis"), lang),
         "reference": tr(t.get("reference"), lang)}
        for t in (tiers or [])
    ]


def _loc_skipped(rows, lang: str) -> list:
    return [{**r, "reason": tr(r.get("reason"), lang)} for r in (rows or [])]


def _loc_batch(batch: dict, lang: str) -> dict:
    """一次批算的产出里带文案的三处：summary.pump_tiers、skipped、逐点 notes。

    ⚠ 逐点 `notes` 必须翻 —— 水动力口径下它承载的是「本点为什么没结论」
    「峰值在时限之后，结论是下限」这类**判读前提**，不是补充说明。英文界面上
    漏翻，等于把这些前提藏起来。
    """
    summary = batch.get("summary") or {}
    return {
        **batch,
        "summary": {
            **summary,
            "pump_tiers": _loc_tiers(summary.get("pump_tiers"), lang),
            "pump_reference_tiers": _loc_tiers(
                summary.get("pump_reference_tiers"), lang
            ),
        },
        "skipped": _loc_skipped(batch.get("skipped"), lang),
        "points": [_loc_point(p, lang) for p in (batch.get("points") or [])],
    }


# ---------------------------------------------------------------------------
# 两套积水点，同一条计算链
# ---------------------------------------------------------------------------

#: 地图与计算器能对着算的两套点。**同一个 `HotspotRecord` 类型**，故
#: `/api/scenario` 与 `/api/point-curve` 对两者走的是同一段代码、同一套判据：
#:   `ledger` —— 845 个历史上报台账点（`registry.py`）
#:   `model`  —— 107 个二维演算识别片区（`model_registry.py`，只有 Al Bateen 一个 run）
#: 两者**不合并**：它们不是同一批地物，合在一起排序等于把行政记录和演算结论混为一谈。
POINT_SOURCES = ("ledger", "model")

DEFAULT_SOURCE = "ledger"


def ponding_check(records, points: list[dict], assumptions, lang: str) -> dict | None:
    """推理公式法估的来水量 × 二维演算实测的积水量，**并列对照**。

    只有身上带 `ponding_*` 的点才进这张表（跑过 ANUGA 的那一片）：107 个模型片区
    全部有，845 个台账点里只有 Al Bateen 的 18 个有。

    ⚠ **推理那一侧必须自己算，不能读 `runoff_volume_m3`。** 水动力口径
      （`defence_basis="hydrodynamic"`，现默认）下那一列就是演算的全程净入流，
      与本表右侧 `anuga_net_inflow_m3` **逐点相等** —— 拿它当左侧等于同一个数
      跟自己比，比值恒为 1。故这里按推理公式法本来的定义重算：

          V_rational = shape_factor × Q_peak × D

      Q_peak 与设计历时 D 仍随重现期走，且**与第一道防线的口径无关** ——
      它们现在只作峰值诊断（`peak_exceeds_capacity`），正是本对照要拿来校核的量。

    ⚠ **比值不是「误差」，两个数历时口径不同。** 推理公式法给的是 tc 历时
      （本批中位 13 min）内那一段设计峰值过程线的体积，是筛查排序用的量；
      演算给的是整场 180 min 雨下来实际滞留的水，还含管网溢流注入与汇流范围
      之外流进来的水。这个差距正是第一道防线改读演算时程的原因之一
      （完整证据链见 `ponding_curve.py` 模块头）。

    只有页面选的重现期与该 run 的重现期相同时才 `comparable` —— 不同级别的两个数
    摆在一起会让人误以为是同一场雨。
    """
    by_uid = {r.uid: r for r in records}
    rows = [
        (p, by_uid[p["uid"]])
        for p in points
        if by_uid.get(p["uid"]) is not None
        and by_uid[p["uid"]].ponding_net_inflow_m3 is not None
        and p.get("peak_flow_m3s") is not None
        and p.get("duration_min") is not None
    ]
    if not rows:
        return None
    shape = assumptions.shape_factor
    rational = sum(shape * p["peak_flow_m3s"] * p["duration_min"] * 60.0 for p, _ in rows)
    anuga = sum(r.ponding_net_inflow_m3 or 0.0 for _, r in rows)
    rps = {r.ponding_rp_yr for _, r in rows if r.ponding_rp_yr is not None}
    run_rp = rps.pop() if len(rps) == 1 else None
    selected_rp = {p.get("return_period_yr") for p, _ in rows}
    selected = selected_rp.pop() if len(selected_rp) == 1 else None
    return {
        "points": len(rows),
        "rational_runoff_m3": round(rational, 1),
        "anuga_net_inflow_m3": round(anuga, 1),
        "anuga_peak_m3": round(sum(r.ponding_peak_m3 or 0.0 for _, r in rows), 1),
        "ratio": round(anuga / rational, 2) if rational > 0 else None,
        "shape_factor": shape,
        "run_id": next((r.ponding_run_id for _, r in rows if r.ponding_run_id), None),
        "run_return_period_yr": run_rp,
        # 页面选的级别与 run 的级别不一致时，两个数不是同一场雨，不能并排下结论
        "comparable": run_rp is not None and selected is not None and run_rp == selected,
        "note": tr(
            "推理公式法的来水量按 shape × Q_peak × D 重算（tc 历时内设计峰值过程线的"
            "体积，筛查口径），ANUGA 的积水量是整场雨演算下来实际滞留的水（含管网"
            "溢流注入与汇流范围外来水）—— 历时口径不同，比值不是误差。第一道防线"
            "现已改读演算时程，不再由推理公式法与 Qcap 推算。",
            lang,
        ),
    }


def records_for(source: str, lang: str = "zh") -> tuple:
    """按数据源取记录。认不出的 source 直接报错，不悄悄退回台账。"""
    if source == "ledger":
        return load_registry()
    if source == "model":
        return load_model_registry()
    raise _fail(422, f"未知数据源 {source!r}，可取：{'、'.join(POINT_SOURCES)}", lang)


def find_record(uid: str):
    """按 uid 找一条记录，两套都找。uid 前缀本身就区分得开（`MDL-` 是片区）。"""
    for source in POINT_SOURCES:
        hit = next((r for r in records_for(source) if r.uid == uid), None)
        if hit is not None:
            return hit
    return None


class HotspotInput(BaseModel):
    hotspot_id: str = "H1"
    area_ha: float = Field(gt=0, description="汇水面积（公顷）")
    runoff_c: float = Field(gt=0, le=1, description="径流系数 C")
    tc_min: float = Field(gt=0, description="集流时间（分钟）")
    qcap_m3s: float = Field(ge=0, description="管网承载能力（m³/s）")
    pond_available_m3: float = Field(default=0.0, ge=0)
    priority: CatchmentPriority | None = Field(
        default=None, description="ADQCC Table 3-3 汇水区优先级；迪拜数据集会忽略"
    )


class AssumptionsInput(BaseModel):
    sed_factor: float = DEFAULT_ASSUMPTIONS.sed_factor
    shape_factor: float = DEFAULT_ASSUMPTIONS.shape_factor
    defence_basis: DefenceBasis = Field(
        default=DEFAULT_ASSUMPTIONS.defence_basis,
        description=(
            "三道防线的判定口径。hydrodynamic = 第一道读二维演算的积水量时程"
            "（默认，回答「T 时刻地面上还剩多少水」，没跑过演算的点不出结论）；"
            "peak = 原 Excel 的峰值口径（回答「峰值会不会溢流」，仅供回归对照）。"
            "⚠ 旧的 window 口径（Qcap × T）已删除 —— 实测 corr(Qcap, 排空速率)"
            " = −0.156，管段满流能力对排空速率没有预测力"
        ),
    )
    drawdown_hours: float = Field(
        default=DEFAULT_ASSUMPTIONS.drawdown_hours, gt=0,
        description="三道防线共用的时限 T（小时）—— 第一道与第三道都按它算",
    )
    pump_duty_factor: float = Field(
        default=DEFAULT_ASSUMPTIONS.pump_duty_factor, gt=0, le=1,
        description="工况扬程折减 —— 推算系数，不是实测",
    )
    pump_availability: float = Field(
        default=DEFAULT_ASSUMPTIONS.pump_availability, gt=0, le=1,
        description="出勤占空（加油、转场、清堵）—— 推算系数",
    )
    pump_capacity: float | None = Field(
        default=DEFAULT_ASSUMPTIONS.pump_capacity, gt=0,
        description=(
            "单泵抽排能力（m³/h）—— **页面可改的主口径**，默认 300。"
            "全部积水点按这一个排量算，配合 pumps_per_point 构成"
            "「每点 N 台 × 每台 X m³/h」的配置式车队。"
            "置 null 则退回 12″/8″/6″ 分档派车（按水量解台数），"
            "那是回答「采购该买哪几档」时唯一说得清的口径"
        ),
    )
    pumps_per_point: int = Field(
        default=DEFAULT_ASSUMPTIONS.pumps_per_point, ge=1, le=50,
        description=(
            "每个积水点配置几台移动泵 —— **页面可改**，默认 1 台/点。"
            "结果里 pumps_required 仍是「T 内清完该配几台」，"
            "pumps_configured / chain_residual_m3 / chain_hours_required "
            "是「已配的这套够不够、清不完还差多少、要几小时」。"
            "⚠ 泵单独配配不出外运能力 —— 见 tankers_per_point"
        ),
    )
    tankers_per_point: int = Field(
        default=DEFAULT_ASSUMPTIONS.tankers_per_point, ge=1, le=500,
        description=(
            "每个积水点配置几辆罐车 —— **页面可改**，默认 1 辆/点。"
            "⚠ 与 pumps_per_point **串联**不是并列：泵把水抽进罐车、罐车运走，"
            "这个点的外运能力取两侧较小值（chain_configured_m3hr）。"
            "默认参数下单泵 300 m³/h、单车持续外运只有 15 m³/h，"
            "喂饱一台泵要 20 辆车（summary.tankers_per_pump）"
        ),
    )
    tanker_capacity: float = Field(
        default=DEFAULT_ASSUMPTIONS.tanker_capacity, gt=0,
        description="罐车单车储水能力（m³/车次）—— **页面可改**，默认 15",
    )
    tanker_turnaround_min: float = Field(
        default=DEFAULT_ASSUMPTIONS.tanker_turnaround_min, gt=0,
        description=(
            "罐车单车往返周转时间（分钟/趟：装载 + 运输 + 卸载 + 返回）"
            "—— **页面可改**，默认 60。它同时定两件事："
            "① 车次折辆数——一辆车在时限 T 内跑 ⌊T×60 / 周转⌋ 趟；"
            "② 单车持续外运能力 = 单车容量 / 周转，即这条链罐车侧的通过量。"
            "⚠ 本项目没有数据支撑这个默认值，须由 DMT 给实际周转记录"
        ),
    )


class CalcRequest(BaseModel):
    hotspot: HotspotInput
    assumptions: AssumptionsInput = AssumptionsInput()
    dataset: str = Field(default=DEFAULT_DATASET_KEY, description="IDF 数据集 key")


class CompareRequest(BaseModel):
    hotspot: HotspotInput
    assumptions: AssumptionsInput = AssumptionsInput()
    datasets: list[str] = Field(default_factory=lambda: [DEFAULT_DATASET_KEY, "dubai_dm"])


class QcapRequest(BaseModel):
    diameter: float = Field(gt=0)
    diameter_unit: DiameterUnit = DiameterUnit.MM
    gradient: float = Field(gt=0)
    gradient_convention: GradientConvention = GradientConvention.DECIMAL
    pipe_material: str | None = None


class ProfileInput(BaseModel):
    """一组汇水参数假设。**全部是假设值**，页面上必须标注来源存疑。"""

    area_ha: float = Field(gt=0)
    runoff_c: float = Field(gt=0, le=1)
    tc_min: float = Field(gt=0)
    qcap_m3s: float = Field(ge=0)
    pond_available_m3: float = Field(default=0.0, ge=0)


class ScenarioRequest(BaseModel):
    """批量场景计算的入参。筛选条件为空表示不筛。"""

    dataset: str = Field(
        default="auto",
        description="IDF 数据集 key，或 `auto`（按 DEM 分区逐点判）/ `custom_storm`",
    )
    return_period_yr: int = 25
    custom_depth_mm: float = Field(default=50.0, gt=0)
    custom_duration_min: float = Field(default=120.0, gt=0)
    assumptions: AssumptionsInput = AssumptionsInput()
    profiles: dict[str, ProfileInput] = Field(default_factory=dict)
    priority: int | None = Field(default=None, description="ADQCC Table 3-3 汇水区优先级")
    source: str = Field(
        default=DEFAULT_SOURCE,
        description=(
            "算哪一套点：`ledger` 历史上报台账（845 个）/ `model` 二维演算识别片区"
            "（107 个，只有 Al Bateen）。两套走同一条计算链，但**不是同一批地物**，"
            "不可合并统计"
        ),
    )
    zero_qcap_without_network: bool = True
    coverage_only: bool = Field(
        default=True,
        description=(
            "只算落在有管网数据区域内的点（501 个）。置 false 会把艾因与西部区的 "
            "339 个点按假设剖面一并算进来 —— 那批数字站不住，只在做敏感性对照时用"
        ),
    )
    municipality: list[str] = Field(default_factory=list)
    criticality: list[str] = Field(default_factory=list)
    root_cause: list[str] = Field(default_factory=list)
    district: list[str] = Field(
        default_factory=list,
        description=(
            "官方行政片区，取值是**市政区限定**的 key（`ADM / AL BATEEN`），"
            "不是片区名 —— `AL BATEEN` 在阿布扎比岛（ADM，18 个点）与艾因"
            "（AAM，3 个点）下各有一个，只按名字筛会把两地混在一起"
        ),
    )

    def matches(self, record) -> bool:
        if self.coverage_only and not record.in_coverage:
            return False
        if self.district and record.district_key not in self.district:
            return False
        if self.municipality and record.municipality not in self.municipality:
            return False
        if self.criticality and (record.criticality or "未填写") not in self.criticality:
            return False
        if self.root_cause and (record.root_cause or "未填写") not in self.root_cause:
            return False
        return True


@app.get("/")
def root(lang: str = Lang) -> dict:
    """探活。页面在前端工程里，这里只答「API 活着、有哪些端点」。"""
    return {
        "service": app.title,
        "version": app.version,
        "docs": "/docs",
        "frontend": tr("前后端已分离，页面由 frontend/（Vue 3 + Vite）单独部署", lang),
    }


@app.get("/api/coverage")
def coverage() -> dict:
    """有管网数据区域的落图面（`coverage_batch.py` 产出）。

    缺文件时返回空 FeatureCollection —— 页面照常出图，只是不画覆盖面，
    跟批算无关（逐点参不参与计算看 `in_coverage`，不看这张面）。
    """
    from ..coverage_batch import OUTPUT_GEOJSON

    if not OUTPUT_GEOJSON.exists():
        return {"type": "FeatureCollection", "features": [], "available": False}
    return {**json.loads(OUTPUT_GEOJSON.read_text(encoding="utf-8")), "available": True}


@app.get("/api/network/{layer}")
def network(layer: str) -> dict:
    """雨水管网本身的落图线（`network_batch.py` 产出）。

    两层分开取：`mains` 三级干管 1.6 MB，按下按钮就要；`laterals` 支管 3.2 MB，
    前端放大到街区尺度才来取（见 `network_batch` 模块头）。

    缺文件时返回空 FeatureCollection —— 页面照常出图，只是画不出管网。
    """
    from ..network_batch import OUTPUT_LATERALS, OUTPUT_MAINS

    paths = {"mains": OUTPUT_MAINS, "laterals": OUTPUT_LATERALS}
    if layer not in paths:
        raise HTTPException(404, f"没有 {layer} 这一层管网，可取：{'、'.join(paths)}")
    path = paths[layer]
    if not path.exists():
        return {"type": "FeatureCollection", "features": [], "available": False}
    return {**json.loads(path.read_text(encoding="utf-8")), "available": True}


@app.get("/api/districts")
def districts() -> dict:
    """官方行政片区的轮廓（`district_batch.py` 产出），只含有积水点的片区。

    缺文件时返回空 FeatureCollection —— 页面据此把片区筛选整块藏掉，
    不影响其余功能（片区归属本身在 `/api/hotspots` 的逐点字段里）。
    """
    from ..district_batch import OUTPUT_GEOJSON

    if not OUTPUT_GEOJSON.exists():
        return {"type": "FeatureCollection", "features": [], "available": False}
    fc = json.loads(OUTPUT_GEOJSON.read_text(encoding="utf-8"))
    # 落图与筛选共用同一个 key，前端不用自己拼
    for f in fc.get("features", []):
        props = f.get("properties", {})
        props["key"] = f"{props.get('municipality') or '—'} / {props.get('district')}"
    return {**fc, "available": True}


@app.get("/api/model-ponding")
def model_ponding(lang: str = Lang) -> dict:
    """二维水动力模型识别出的易积水片区（`model_ponding.py` 读离线成果）。

    与 `/api/hotspots` 是**并列的两套数据，不是同一批地物**：那边是历史上报的
    845 个台账点（参与三道防线批算），这边是 ANUGA 演算出的 107 个片区
    （只有 Al Bateen 一个 run，不参与计算）。页面上用数据源开关切着看，
    两者的差集本身就是要给人看的东西 —— 故此处不做任何与台账的合并或匹配。

    缺文件时返回空 FeatureCollection + `available: false`，页面据此把数据源
    开关整块藏掉，台账那一路照常。
    """
    from ..model_ponding import (
        CAVEATS as PONDING_CAVEATS,
        MECHANISM_ORDER,
        RUN_META,
        load_features,
        summarise,
    )

    features = load_features()
    if not features:
        return {"type": "FeatureCollection", "features": [], "available": False}
    # 展示文案过 tr()，`mechanism_key` / `run_id` / `status` 等协议值一律不动
    run = {**RUN_META, **{k: tr(RUN_META[k], lang) for k in ("area_label", "storm", "coupling", "criterion")}}
    for f in features:
        props = f["properties"]
        props["mechanism"] = tr(props.get("mechanism"), lang)
    return {
        "type": "FeatureCollection",
        "features": features,
        "available": True,
        "run": run,
        "mechanism_order": MECHANISM_ORDER,
        "summary": summarise(features),
        "caveats": tr_all(PONDING_CAVEATS, lang),
    }


@app.get("/api/hotspots")
def hotspots(source: str = DEFAULT_SOURCE, lang: str = Lang) -> dict:
    """积水点的落图数据 + 页面筛选器取值 + 默认汇水剖面假设。

    `source=ledger`（默认）出 845 个历史上报台账点；`source=model` 出 107 个
    二维演算识别片区 —— **返回体结构完全相同**，故页面两路共用同一段载入逻辑。
    两套不是同一批地物，`/api/scenario` 也按 `source` 分开算，不合并统计。
    """
    records = records_for(source, lang)
    with_zone = sum(1 for r in records if r.idf_zone)
    basis_tally: dict[str, int] = {}
    storage_tally: dict[str, int] = {}
    catchment_tally: dict[str, int] = {}
    for r in records:
        basis_tally[r.qcap_basis] = basis_tally.get(r.qcap_basis, 0) + 1
        storage_tally[r.storage_basis] = storage_tally.get(r.storage_basis, 0) + 1
        catchment_tally[r.catchment_basis] = catchment_tally.get(r.catchment_basis, 0) + 1
    measured_areas = [r.area_measured_ha for r in records if r.area_measured_ha is not None]
    storage_assets = _storage_assets_found()
    inside = [r for r in records if r.in_coverage]
    outside_by_muni: dict[str, int] = {}
    for r in records:
        if not r.in_coverage:
            outside_by_muni[r.municipality] = outside_by_muni.get(r.municipality, 0) + 1
    return {
        "source": source,
        "count": len(records),
        "points": [r.as_json() for r in records],
        "facets": facets(records),
        "coverage": {
            "inside": len(inside),
            "outside": len(records) - len(inside),
            "outside_by_municipality": outside_by_muni,
            "measured": basis_tally.get("measured", 0),
            "measured_no_network": basis_tally.get("measured_no_network", 0),
            "uncomputable": basis_tally.get("uncomputable", 0),
            "rule": tr(
                "落在有管网数据区域内 = 该点 5 km 内有雨水管段（qcap_batch.py 逐点实算）。"
                "不用行政区判 —— 台账记为阿布扎比市的点里有 5 个在数据区之外。",
                lang,
            ),
            "source": tr(
                "coverage_batch.py：sw_edge 缓冲成面，落图用；逐点判定以 in_coverage 为准", lang
            ),
        },
        "district": {
            "stamped": sum(1 for r in records if r.district_basis == "measured"),
            "count": len({r.district_key for r in records if r.district_key}),
            "ambiguous_names": sorted(
                name
                for name, munis in _district_names(records).items()
                if len(munis) > 1
            ),
            "source": tr(
                "district_batch.py：积水点落在 geoserver_ref.udm_community 的哪个社区面里，"
                "按 districtnameeng 聚合成片区。⚠ 不是台账的 area 自由文本列",
                lang,
            ),
        },
        "profiles": {k: asdict(v) for k, v in DEFAULT_PROFILES.items()},
        "profile_field_basis": tr_values(PROFILE_FIELD_BASIS, lang),
        "zone": {
            "threshold_m": ZONE_A_MIN_ELEVATION_M,
            "sampled": with_zone,
            "zone_a": sum(1 for r in records if r.idf_zone == "adqcc_zone_a"),
            "zone_b": sum(1 for r in records if r.idf_zone == "adqcc_zone_b"),
            "source": tr("DEM_UAE_UTM40.tif 逐点采样高程，> 200 m 判为 Zone A", lang),
        },
        "catchment": {
            "measured": catchment_tally.get("measured", 0),
            "measured_undeveloped": catchment_tally.get("measured_undeveloped", 0),
            "assumed_no_landuse": catchment_tally.get("assumed_no_landuse", 0),
            "area_ha_median": (
                round(sorted(measured_areas)[len(measured_areas) // 2], 2)
                if measured_areas else None
            ),
            "source": tr(
                "catchment_batch.py：积水点 Voronoi 单元 ∩ 250 m 圆，按 udm_plot / "
                "udm_building / udm_roadedge / udm_landscape / udm_parking / "
                "udm_pedestrianarea 统计下垫面，C 取 ADQCC Table 3-8 分项加权",
                lang,
            ),
        },
        "storage": {
            "assets_found": storage_assets["found"],
            "assets_usable": storage_assets["usable"],
            "assets_assumed": storage_assets["assumed"],
            "measured_m3": storage_assets["measured_m3"],
            "assumed_m3": storage_assets["assumed_m3"],
            "measured": storage_tally.get("measured", 0),
            "assumed_dimensions": storage_tally.get("assumed_dimensions", 0),
            "measured_none": storage_tally.get("measured_none", 0),
            "no_asset": storage_tally.get("no_asset", 0),
            "no_coverage": storage_tally.get("no_coverage", 0),
            "source": tr(
                "storage_batch.py：250 m 内的 pond / soakaway / sw_reservoirstructure；"
                "深度与尺寸缺的按 storage_dims.py 的标准缺省值目录补，"
                "出处见 docs/STORAGE_DIMENSION_BASIS.md",
                lang,
            ),
        },
        "ponding": _ponding_block(records, lang),
        "caveats": caveats_for(
            lang,
            catch_measured=catchment_tally.get("measured", 0),
            catch_undeveloped=catchment_tally.get("measured_undeveloped", 0),
            catch_no_landuse=catchment_tally.get("assumed_no_landuse", 0),
            qcap_measured=basis_tally.get("measured", 0),
            qcap_no_network=basis_tally.get("measured_no_network", 0),
            qcap_assumed=(
                len(records)
                - basis_tally.get("measured", 0)
                - basis_tally.get("measured_no_network", 0)
            ),
            assets_found=storage_assets["found"],
            assets_usable=storage_assets["usable"],
            assets_assumed=storage_assets["assumed"],
            store_measured=storage_tally.get("measured", 0),
            store_assumed_dims=storage_tally.get("assumed_dimensions", 0),
            store_no_asset=storage_tally.get("no_asset", 0),
            store_no_coverage=storage_tally.get("no_coverage", 0),
        ),
    }


def _ponding_block(records, lang: str) -> dict:
    """逐点积水量的总账 —— 这是项目里唯一不靠流量差估、而从二维演算读出来的水量。

    ⚠ 覆盖面极窄：只有跑过 ANUGA 的片区有值。没有任何片区有值时 `available` 为 false，
    页面据此整块不显示，而不是摆一排 0。
    """
    rows = [r for r in records if r.ponding_run_id]
    by_district = {
        key: pond
        for key in sorted({r.district_key for r in rows if r.district_key})
        if (pond := district_ponding([r for r in records if r.district_key == key]))
    }
    return {
        "available": bool(rows),
        "points": len(rows),
        "wet_points": sum(1 for r in rows if (r.ponding_net_inflow_m3 or 0) > 0),
        "by_district": by_district,
        "basis": tr_values(PONDING_BASIS_LABEL, lang),
        "source": tr(
            "ponding_batch.py：ANUGA 二维演算成果（15 min 一帧）按地形洼地 + D8 汇流"
            "逐点切分，积水总量取 Σ 正 ΔV（净累计进水量），积水时长取水深退到 "
            "0.01 m 以下的时刻",
            lang,
        ),
        "limits": tr_all(
            [
                "只覆盖跑过 ANUGA 的片区，845 个点里只挂得上 18 个（2.1%）。",
                "重现期由该 run 自己定（Al Bateen 是 100 年一遇），"
                "与页面上选的那一级无关 —— 两者不是一回事。",
                "81% 的积水量落在台账里没有点的洼地上，逐点数字只可用于筛查与排序。",
                "20 m 计算网格会把相邻的积水坑并粗，不可作为单点设计依据。",
                "该 run 的 SWMM 注入比预定值少 16.6 万 m³，绝对量偏小，"
                "修好之前只能看相对排序。",
            ],
            lang,
        ),
    }


@app.post("/api/scenario")
def scenario(req: ScenarioRequest, lang: str = Lang) -> dict:
    """按一场雨把筛选后的积水点全部跑一遍，返回逐点结论 + 本场总账。"""
    records = [r for r in records_for(req.source, lang) if req.matches(r)]
    if not records:
        # 三段各自翻译再拼 —— 拼好了再翻，精确匹配就对不上了
        parts = [tr("筛选条件没有匹配到任何积水点", lang)]
        if req.coverage_only:
            parts.append(tr(
                "当前只算有管网数据的区域（艾因与西部区全部在区域外），"
                "要把它们按假设剖面算进来，请在「模型输入」里关掉该项",
                lang,
            ))
        if req.district:
            parts.append(
                tr("当前片区筛选：", lang) + " / ".join(req.district)
            )
        raise HTTPException(status_code=422, detail="；".join(parts) if lang == "zh"
                            else ". ".join(parts))

    try:
        custom = (
            CustomStormIdf(req.custom_depth_mm, req.custom_duration_min)
            if req.dataset == "custom_storm"
            else None
        )
        if req.dataset not in IDF_DATASETS and req.dataset not in ("auto", "custom_storm"):
            raise ValueError(f"未知 IDF 数据集 {req.dataset!r}")
        options = BatchOptions(
            dataset=req.dataset,
            return_period_yr=req.return_period_yr,
            assumptions=Assumptions(**req.assumptions.model_dump()),
            profiles={
                k: CatchmentProfile(**v.model_dump()) for k, v in req.profiles.items()
            } or dict(DEFAULT_PROFILES),
            priority=CatchmentPriority(req.priority) if req.priority else None,
            zero_qcap_without_network=req.zero_qcap_without_network,
            custom_storm=custom,
        )
        batch = run_batch(records, options)
    except ValueError as exc:
        raise _fail(422, str(exc), lang) from exc

    datasets_used = [
        _loc_dataset(
            get_dataset(k).describe() if k != "custom_storm" else _describe_custom(custom), lang
        )
        for k in batch["dataset_usage"]
    ]
    gap = fleet_gap(batch["summary"], options.assumptions.effective_tiers)
    gap["by_tier"] = _loc_tiers(gap.get("by_tier"), lang)
    rp_stamped = [
        {**p, "return_period_yr": req.return_period_yr} for p in batch["points"]
    ]
    return {
        **_loc_batch(batch, lang),
        "source": req.source,
        "datasets_used": datasets_used,
        "fleet_gap": gap,
        # 与二维演算实测积水量的并列对照 —— 跑过 ANUGA 的点才有
        "ponding_check": ponding_check(records, rp_stamped, options.assumptions, lang),
        "limitations": tr_all(LIMITATIONS, lang),
    }


class PointCurveRequest(BaseModel):
    """单点多重现期：一个积水点，把 5 / 10 / 25 / 50 / 100 年一遇各跑一遍。

    除 `uid` 与 `return_periods` 外，字段与 `ScenarioRequest` 同名同义 ——
    页面上两种模式共用同一套模型输入，换算口径不会因为模式不同而漂移。
    """

    uid: str
    dataset: str = Field(
        default="auto",
        description="IDF 数据集 key，或 `auto`（按 DEM 分区判）/ `custom_storm`",
    )
    return_periods: list[int] = Field(
        default_factory=lambda: list(FLEET_RETURN_PERIODS),
        description="要算的重现期；数据集不含某个重现期时该行进 skipped",
    )
    custom_depth_mm: float = Field(default=50.0, gt=0)
    custom_duration_min: float = Field(default=120.0, gt=0)
    assumptions: AssumptionsInput = AssumptionsInput()
    profiles: dict[str, ProfileInput] = Field(default_factory=dict)
    priority: int | None = None
    zero_qcap_without_network: bool = True


@app.post("/api/point-curve")
def point_curve(req: PointCurveRequest, lang: str = Lang) -> dict:
    """一个点 × 一串重现期 —— 页面「点一个点看它在各级暴雨下的表现」用这个。

    每一行都走 `run_batch()` 同一条计算链（单点批算），所以和全域批算的
    对应行**逐字段相等**，不会出现「单点页和汇总页对不上」的情况。
    """
    record = find_record(req.uid)
    if record is None:
        raise _fail(404, f"台账里没有编号 {req.uid}", lang)

    custom = (
        CustomStormIdf(req.custom_depth_mm, req.custom_duration_min)
        if req.dataset == "custom_storm"
        else None
    )
    if req.dataset not in IDF_DATASETS and req.dataset not in ("auto", "custom_storm"):
        raise _fail(422, f"未知 IDF 数据集 {req.dataset!r}", lang)

    profiles = {
        k: CatchmentProfile(**v.model_dump()) for k, v in req.profiles.items()
    } or dict(DEFAULT_PROFILES)
    rps = [0] if custom else list(dict.fromkeys(req.return_periods))

    rows: list[dict] = []
    skipped: list[dict] = []
    dataset_keys: list[str] = []
    try:
        for rp in rps:
            options = BatchOptions(
                dataset=req.dataset,
                return_period_yr=rp,
                assumptions=Assumptions(**req.assumptions.model_dump()),
                profiles=profiles,
                priority=CatchmentPriority(req.priority) if req.priority else None,
                zero_qcap_without_network=req.zero_qcap_without_network,
                custom_storm=custom,
            )
            batch = run_batch([record], options)
            if batch["skipped"]:
                skipped.append(batch["skipped"][0])
                continue
            point = batch["points"][0]
            dataset_keys.append(point["dataset_key"])
            rows.append({**point, "return_period_yr": rp,
                         "pump_tiers": _loc_tiers(batch["summary"]["pump_tiers"], lang),
                         "pump_reference_tiers": _loc_tiers(
                             batch["summary"]["pump_reference_tiers"], lang)})
    except ValueError as exc:
        raise _fail(422, str(exc), lang) from exc

    if not rows:
        raise _fail(422, f"{req.uid} 在所选数据集下没有任何可算的重现期", lang)

    key = dataset_keys[0]
    return {
        "point": record.as_json(),
        "in_scope": record.in_coverage,
        "dataset": _loc_dataset(
            _describe_custom(custom) if custom else get_dataset(key).describe(), lang
        ),
        "scenarios": rows,
        "skipped": _loc_skipped(skipped, lang),
        # 第三道防线第一次被触发的重现期 —— 单点页最该被一眼看到的数。
        # 自定义雨只有一行、没有级差可言，故恒为 null，由页面另写结论。
        "first_line3_rp": None if custom else next(
            (r["return_period_yr"] for r in rows if r["line"] == 3), None
        ),
        "ledger": {
            "pumps_qty": record.pumps_qty,
            "tankers_qty": record.tankers_qty,
            "pump_12in_qty": record.pump_12in_qty,
            "pump_8in_qty": record.pump_8in_qty,
            "pump_6in_qty": record.pump_6in_qty,
        },
        "limitations": tr_all(LIMITATIONS, lang),
    }


def _describe_custom(ds: CustomStormIdf | None) -> dict:
    return ds.describe() if ds else {}


class StormPresetRequest(BaseModel):
    """一个点 × 一个重现期的**默认降雨参数**（还没算，只是把口径摆出来）。

    页面的交互是「先选点 → 再选重现期 → 看清这一级默认落多少雨、落多久
    → 再点计算」。这个接口只负责中间那一步：把 `rational.evaluate()` 第 1–2 步
    要用的历时与强度、以及该点解算后的逐点输入原样报出来，**不跑防线计算**。

    字段与 `PointCurveRequest` 同名同义，故同一套页面状态可以直接发过来。
    """

    uid: str
    dataset: str = Field(
        default="auto",
        description="IDF 数据集 key，或 `auto`（按 DEM 分区判）/ `custom_storm`",
    )
    return_period_yr: int = 25
    custom_depth_mm: float = Field(default=50.0, gt=0)
    custom_duration_min: float = Field(default=120.0, gt=0)
    profiles: dict[str, ProfileInput] = Field(default_factory=dict)
    priority: int | None = None
    zero_qcap_without_network: bool = True


@app.post("/api/storm-preset")
def storm_preset(req: StormPresetRequest, lang: str = Lang) -> dict:
    """选中重现期后、按下「计算」之前显示的那一屏 —— 降雨参数不可改。

    历时与强度都由导则与该点的 tc 定死（ADQCC：历时 = tc × M，强度按
    Table 3-5/3-7 的 α/β 公式；迪拜 DM：向下取档），操作员无从选择，
    故页面上这两个数只读。要换一场雨只能换重现期，或切到自定义降雨。
    """
    record = find_record(req.uid)
    if record is None:
        raise _fail(404, f"台账里没有编号 {req.uid}", lang)

    custom = (
        CustomStormIdf(req.custom_depth_mm, req.custom_duration_min)
        if req.dataset == "custom_storm"
        else None
    )
    if req.dataset not in IDF_DATASETS and req.dataset not in ("auto", "custom_storm"):
        raise _fail(422, f"未知 IDF 数据集 {req.dataset!r}", lang)

    profiles = {
        k: CatchmentProfile(**v.model_dump()) for k, v in req.profiles.items()
    } or dict(DEFAULT_PROFILES)
    priority = CatchmentPriority(req.priority) if req.priority else None
    idf = custom or get_dataset(dataset_key_for(record, req.dataset))
    rp = CUSTOM_RETURN_PERIOD if custom else req.return_period_yr
    if rp not in idf.return_periods:
        raise _fail(
            422,
            f"{idf.label} 无 {req.return_period_yr} 年重现期，"
            f"可选：{list(idf.return_periods)}",
            lang,
        )

    hotspot = build_hotspot(
        record,
        profiles,
        priority=priority,
        zero_qcap_without_network=req.zero_qcap_without_network,
    )
    # 与 `rational.evaluate()` 步骤 1–2 同一段逻辑：乘数只在支持的数据集上生效。
    multiplier = (
        priority.tc_multiplier
        if priority is not None and idf.supports_tc_multiplier
        else 1.0
    )
    try:
        lookup = idf.intensity(rp, hotspot.tc_min, multiplier)
    except ValueError as exc:
        raise _fail(422, str(exc), lang) from exc

    cf = idf.runoff_adjustment_factor(rp)
    return {
        "uid": record.uid,
        "in_scope": record.in_coverage,
        "return_period_yr": None if custom else rp,
        "dataset": _loc_dataset(_describe_custom(custom) if custom else idf.describe(), lang),
        # —— 这一级默认的那场雨：只读，页面不给输入框 ——
        "duration_min": round(lookup.duration_min, 2),
        "intensity_mm_hr": round(lookup.intensity_mm_hr, 2),
        "depth_mm": round(lookup.intensity_mm_hr * lookup.duration_min / 60.0, 2),
        "tc_multiplier": multiplier,
        "priority_label": tr(priority.label, lang) if priority else None,
        # —— 该点解算后的逐点输入，字段名与 `/api/scenario` 的逐点行一致 ——
        "area_ha": hotspot.area_ha,
        "runoff_c": hotspot.runoff_c,
        "c_adjusted": round(min(hotspot.runoff_c * cf, 1.0), 3),
        "tc_min": hotspot.tc_min,
        "qcap_m3s": round(hotspot.qcap_m3s, 3),
        "pond_available_m3": hotspot.pond_available_m3,
        "catchment_basis": catchment_basis_for(record, profiles),
        "qcap_basis": qcap_basis_for(
            record, profiles,
            zero_qcap_without_network=req.zero_qcap_without_network,
        ),
        "storage_basis": storage_basis_for(record, profiles),
    }


@app.get("/api/idf-datasets")
def list_idf_datasets(lang: str = Lang) -> dict:
    """供页面渲染切换按钮：每套数据集的口径、可用重现期与警示。"""
    return {
        "default": DEFAULT_DATASET_KEY,
        "datasets": [_loc_dataset(ds.describe(), lang) for ds in IDF_DATASETS.values()],
        "priorities": [
            {"value": int(p), "label": tr(p.label, lang), "multiplier": p.tc_multiplier}
            for p in CatchmentPriority
        ],
        "design_return_periods": [
            {"return_period_yr": rp, "applies_to": tr(desc, lang)}
            for rp, desc in DESIGN_RETURN_PERIOD_BY_FACILITY
        ],
    }


@app.get("/api/idf-datasets/{key}/table")
def idf_table(key: str, lang: str = Lang) -> dict:
    """某套数据集的强度表，供页面展示与人工核对。"""
    try:
        ds = get_dataset(key)
    except ValueError as exc:
        raise _fail(404, str(exc), lang) from exc

    if hasattr(ds, "published_table"):
        durations = list(ADQCC_TABLE_DURATIONS_MIN)
        rows = {rp: list(vals) for rp, vals in sorted(ds.published_table.items(), reverse=True)}
        depth_24h = ds.depth_24h_mm
    else:
        durations = list(DUBAI_DURATIONS_MIN)
        rows = {rp: list(vals) for rp, vals in sorted(IDF_DUBAI.items(), reverse=True)}
        depth_24h = {rp: vals[-1] * 24.0 for rp, vals in IDF_DUBAI.items()}

    return {
        **_loc_dataset(ds.describe(), lang),
        "durations_min": durations,
        "intensity_mm_hr": rows,
        "depth_24h_mm": depth_24h,
    }


@app.get("/api/hyetograph/presets")
def hyetograph_presets(lang: str = Lang) -> dict:
    """雨型图页签的底板：官方 DDF 累计雨量表、9 个预设（带等效重现期）与证据边界。

    只供看图 —— 这组接口的输出不进任何计算链，见 `hyetograph.py` 模块头。
    """
    return {
        "source": tr(hyetograph.SOURCE, lang),
        "method": tr(hyetograph.METHOD, lang),
        "boundary": tr(hyetograph.BOUNDARY, lang),
        "durations_min": list(hyetograph.DURATIONS_MIN),
        "return_periods": list(hyetograph.RETURN_PERIODS),
        "ddf_depth_mm": {
            rp: list(vals) for rp, vals in sorted(ADQCC_ZONE_B_DDF_DEPTH_MM.items(), reverse=True)
        },
        "preset_depths_mm": list(hyetograph.PRESET_DEPTHS_MM),
        "preset_durations_min": list(hyetograph.PRESET_DURATIONS_MIN),
        "default": {
            "depth_mm": hyetograph.DEFAULT_PRESET[0],
            "duration_min": hyetograph.DEFAULT_PRESET[1],
        },
        "step_choices_min": list(hyetograph.STEP_CHOICES_MIN),
        "default_peak_pct": hyetograph.DEFAULT_PEAK_PCT,
        "presets": hyetograph.presets(),
    }


@app.get("/api/hyetograph")
def hyetograph_series(
    depth_mm: float,
    duration_min: float,
    step_min: int | None = None,
    peak_pct: float = hyetograph.DEFAULT_PEAK_PCT,
    lang: str = Lang,
) -> dict:
    """一条派生雨型：每步起点、雨深、雨强，以及 Zone B 等效重现期。

    `step_min` 省略时按历时取默认（3 h 以内 5 min，更长 15 min）。参数不合法回 422。
    """
    step = step_min if step_min is not None else hyetograph.default_step(duration_min)
    try:
        return hyetograph.build(depth_mm, duration_min, step, peak_pct).to_dict()
    except ValueError as exc:
        raise _fail(422, str(exc), lang) from exc


#: 单点快算页恒用的判定口径。**不是默认口径**，理由见 `calc()` 的 docstring。
CALC_DEFENCE_BASIS = "peak"


@app.post("/api/calc")
def calc(req: CalcRequest, lang: str = Lang) -> dict:
    """跑 §3.2 的 6 步计算链，返回全部重现期结果 + 各重现期的泵与罐车需求。

    ⚠ **本接口恒用峰值口径**（原 Excel 那一套），调用方传什么 `defence_basis`
    都会被覆盖，结果里的 `l1_basis` 会如实写 `peak`。

    原因：这里的输入是**手填的假想点**（A / C / tc / Qcap 四个数），不对应
    台账里任何一个位置，因此不可能有二维水动力演算覆盖它。而默认的
    `hydrodynamic` 口径下积水量只认演算出来的时程 —— 手填点在那个
    口径下永远是「无标定」，三道防线一个数都出不来，整个页面就没用了。

    峰值口径回答的是这个页面真正能回答的那个问题：「按推理公式法，这场雨的
    峰值流量会不会超过给定的管网能力，超出的部分要多少调蓄与泵」。它**不是**
    「T 小时内排不排得完」的答案 —— 那个问题要有演算才答得了。页面必须把这条
    口径差别原样标出来，不能让两套数字混着看。
    """
    try:
        ds = get_dataset(req.dataset)
        hotspot = Hotspot(**req.hotspot.model_dump())
        assumptions = replace(
            Assumptions(**req.assumptions.model_dump()),
            defence_basis=CALC_DEFENCE_BASIS,
        )
        results = evaluate_all(hotspot, FLEET_RETURN_PERIODS, assumptions, ds)
    except ValueError as exc:
        raise _fail(422, str(exc), lang) from exc

    warnings: list[str] = []
    if hotspot.exceeds_rational_method_limit:
        warnings.append(
            f"汇水面积 {hotspot.area_ha} ha 超出推理公式法适用上限 80 ha，应改用 SCS 法。"
        )
    for r in results:
        warnings.extend(n for n in r.notes if n not in warnings)

    return {
        "dataset": _loc_dataset(ds.describe(), lang),
        "scenarios": [_loc_notes(_as_dict(r), lang) for r in results],
        "fleet_summary": fleet_summary(results),
        #: 本接口用的判定口径 —— 页面据此标注，不许把它和批算的数字混着看
        "defence_basis": CALC_DEFENCE_BASIS,
        "warnings": tr_all(warnings, lang),
        "limitations": tr_all(LIMITATIONS, lang),
    }


@app.post("/api/compare")
def compare(req: CompareRequest, lang: str = Lang) -> dict:
    """同一个点并排跑多套 IDF，看口径差多少。"""
    try:
        hotspot = Hotspot(**req.hotspot.model_dump())
        by_key = compare_datasets(
            hotspot,
            FLEET_RETURN_PERIODS,
            Assumptions(**req.assumptions.model_dump()),
            tuple(req.datasets),
        )
    except ValueError as exc:
        raise _fail(422, str(exc), lang) from exc

    return {
        "datasets": [_loc_dataset(get_dataset(k).describe(), lang) for k in req.datasets],
        "results": {
            k: [_loc_notes(_as_dict(r), lang) for r in rs] for k, rs in by_key.items()
        },
        "limitations": tr_all(LIMITATIONS, lang),
    }


@app.post("/api/qcap")
def qcap(req: QcapRequest, lang: str = Lang) -> dict:
    """由管径 + 坡度 + 管材反算满流圆管 Qcap。"""
    try:
        d = normalize_diameter(req.diameter, req.diameter_unit)
        s = normalize_gradient(req.gradient, req.gradient_convention)
        n = manning_n(req.pipe_material)
        return {"qcap_m3s": circular_pipe_qcap(d, s, n), "diameter_m": d, "slope": s, "manning_n": n}
    except ValueError as exc:
        raise _fail(422, str(exc), lang) from exc


def _district_names(records) -> dict[str, set[str]]:
    """片区名 → 出现过的市政区集合。用来找出重名片区（当前只有 AL BATEEN）。"""
    out: dict[str, set[str]] = {}
    for r in records:
        if r.district:
            out.setdefault(r.district, set()).add(r.district_municipality or "—")
    return out


def _storage_assets_found() -> dict[str, int | float]:
    """250 m 内的调蓄设施条数与容量，取自 storage_batch 的产出。缺文件返回全 0。

    分三项：`found` 总条数、`usable` 深度/尺寸实测或可反推的条数、
    `assumed` 靠 `storage_dims.py` 缺省值目录补的条数。页面要把实测与假设分开说。
    """
    import csv as _csv

    from ..registry import HOTSPOT_STORAGE_CSV

    tally = {"found": 0, "usable": 0, "assumed": 0, "measured_m3": 0.0, "assumed_m3": 0.0}
    if not HOTSPOT_STORAGE_CSV.exists():
        return tally
    with HOTSPOT_STORAGE_CSV.open(encoding="utf-8-sig", newline="") as fh:
        for row in _csv.DictReader(fh):
            tally["found"] += int(row.get("assets_in_radius") or 0)
            tally["usable"] += int(row.get("assets_usable") or 0)
            tally["assumed"] += int(row.get("assets_assumed") or 0)
            tally["measured_m3"] += float(row.get("available_m3") or 0.0)
            tally["assumed_m3"] += float(row.get("assumed_m3") or 0.0)
    tally["measured_m3"] = round(tally["measured_m3"], 1)
    tally["assumed_m3"] = round(tally["assumed_m3"], 1)
    return tally


def _as_dict(r: ScenarioResult) -> dict:
    return {k: v for k, v in r.__dict__.items()}


def _loc_point(row: dict, lang: str) -> dict:
    """逐点结果里要翻的两处：`notes` 与积水量归属口径。

    归属口径是 `ponding_batch.py` 写死的中文短语（点内 / 汇流 / 坡面直排），
    页面直接显示，故在这里翻。判断分支一律走 `l1_basis`，不碰这个串。
    """
    row = _loc_notes(row, lang)
    if row.get("ponding_attribution"):
        row = {**row, "ponding_attribution": tr(row["ponding_attribution"], lang)}
    return row


def _loc_notes(row: dict, lang: str) -> dict:
    """逐行的 `notes`（「历时长于时限」「该数据集忽略优先级」那两条）。"""
    return {**row, "notes": tr_all(row.get("notes"), lang)} if "notes" in row else row
