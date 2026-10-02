"""按一场雨把整份台账跑一遍，产出指挥中心页面要的本场总账与逐点结论。

单点算法完全复用 `rational.evaluate()`（已有回归测试锁死），本模块只负责：

* 逐点选数据集（`auto` 时按 DEM 分区，Zone A 的点走 Zone A 公式）；
* 把结果归到「三道防线」：时限内地面的水退完 / 加上调蓄排完 / 还要出动车队；
* 汇总成车队规模，并和台账**已配**的泵与罐车对照。

三道防线共用一个时限 T（`Assumptions.drawdown_hours`，默认 2 h），
判定口径见 `rational.evaluate()` 的模块头注释 —— 本模块不自带算法。

⚠ **第一道防线只对跑过二维水动力演算的点出结论**，其余点 `line` 为 None、
各量为 None，汇总里单列在 `line_counts["uncalibrated"]`。所有水量与车队数字
都只是 `calibrated_hotspots` 那批点的合计 —— 两个数必须一起读，否则会把
「没算」当成「没事」。理由见 `ponding_curve.py` 模块头注释。

自定义降雨（`CustomStormIdf`）是页面上的敏感性工具，**不属任何导则**，
结果里的 `dataset_key` 会自报家门，导出的 CSV 同样带着它。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from .constants import DEFAULT_ASSUMPTIONS, Assumptions
from .idf import (
    DEFAULT_DATASET_KEY,
    CatchmentPriority,
    IdfDataset,
    IdfLookup,
    get_dataset,
)
from .pumps import DEFAULT_PUMP_TIERS, add_dispatch
from .rational import ScenarioResult, evaluate
from .registry import (
    DEFAULT_PROFILES,
    CatchmentProfile,
    HotspotRecord,
    build_hotspot,
    catchment_basis_for,
    qcap_basis_for,
    storage_basis_for,
    dataset_key_for,
    profile_key_for,
)

#: 自定义降雨没有重现期，用 0 占位，UI 上显示为「自定义」。
CUSTOM_RETURN_PERIOD = 0


class CustomStormIdf(IdfDataset):
    """操作员直接给定「P mm 落在 D 分钟内」的一场雨。

    设计历时取 max(tc × M, D)：集流时间短于给定历时时按给定历时算，
    强度 I = P / 历时 × 60。**没有任何导则背书**，只用于压力测试。
    """

    key = "custom_storm"
    label = "自定义降雨（非标准口径）"
    source = "操作员输入 —— 不属 ADQCC 或迪拜 DM 任何一套导则"
    return_periods = (CUSTOM_RETURN_PERIOD,)
    supports_tc_multiplier = True
    supports_cf = False

    def __init__(self, depth_mm: float, duration_min: float) -> None:
        if depth_mm <= 0 or duration_min <= 0:
            raise ValueError("自定义降雨的雨量与历时都必须为正")
        self.depth_mm = depth_mm
        self.duration_min = duration_min
        self.notes = (
            f"自定义：{depth_mm:g} mm / {duration_min:g} min，"
            "结果不可对外报送，仅用于压力测试。",
            "无 Cf 频率调整；设计历时取 max(tc × M, 给定历时)。",
        )

    def intensity(
        self, return_period_yr: int, tc_min: float, tc_multiplier: float = 1.0
    ) -> IdfLookup:
        self._check_return_period(return_period_yr)
        self._check_multiplier(tc_multiplier)
        duration = max(tc_min * tc_multiplier, self.duration_min)
        return IdfLookup(self.depth_mm / duration * 60.0, duration)


@dataclass(frozen=True)
class BatchOptions:
    """一次批量场景计算的全部可调项。"""

    dataset: str = DEFAULT_DATASET_KEY      #: 数据集 key，或 `auto` 按 DEM 分区逐点判
    return_period_yr: int = 25
    assumptions: Assumptions = DEFAULT_ASSUMPTIONS
    profiles: dict[str, CatchmentProfile] = field(
        default_factory=lambda: dict(DEFAULT_PROFILES)
    )
    priority: CatchmentPriority | None = None
    zero_qcap_without_network: bool = True
    custom_storm: CustomStormIdf | None = None


def defence_line(result: ScenarioResult) -> int | None:
    """1 = 时限内地面的水退完；2 = 加上调蓄排完；3 = 需要出动移动泵与罐车。

    **None = 该点没跑过二维水动力演算，不出结论**（`l1_basis == "uncalibrated"`）。
    判定挂在 `ScenarioResult` 上，这里只是给批算和页面用的薄封装。
    """
    return result.defence_line


def _round(value: float | None, digits: int) -> float | None:
    """无标定点的各量是 None，直接 round() 会炸 —— 这里统一兜住。"""
    return None if value is None else round(value, digits)


def _empty_totals() -> dict[str, float]:
    return {
        "hotspots": 0,
        "peak_flow_m3s": 0.0,
        "excess_flow_m3s": 0.0,
        "runoff_volume_m3": 0.0,        # 时限内要处理的总水量
        "required_storage_m3": 0.0,
        "available_pond_m3": 0.0,
        "shortfall_m3": 0.0,
        "pumps_required": 0,
        "pumps_by_tier": {},    # {档 key: 台数} —— 采购论证看的是这个
        "tanker_loads": 0,
        #: 需要的罐车**辆数**（把车次按「一辆车在 T 内跑几趟」折算）。
        #: ⚠ 与 `pumps_required` 是**同时都要**的一对，不是二选一 —— 泵把水抽
        #: 进罐车、罐车拉走，两段串联，通过量由瓶颈段定。
        #: ⚠ `points_tanker_infeasible` 与它**并列**：那批点的周转时间长于时限，
        #: 一辆车跑不满一趟，辆数不出数。补 0 会把「来不及」读成「不用车」。
        "tankers_required": 0,
        "points_tanker_infeasible": 0,
        #: 喂饱 `pumps_required` 台泵所需的车数（Σ 每点 台数 × tankers_per_pump）。
        #: 与 `tankers_required`（按水量算）取大的那个才是真正要配的车数。
        "tankers_to_feed_pumps": 0,
        # —— 页面配置的车队。⚠ 与上面那组（该配多少）**并列** ——
        "pumps_configured": 0,          # Σ 每点配的台数 = 有结论的点数 × 每点台数
        "tankers_configured": 0,        # Σ 每点配的辆数
        "chain_residual_m3": 0.0,       # Σ 时限内这条链运不走的量
        "points_under_served": 0,       # 配置不够用的点数
        "points_tanker_bound": 0,       # 其中卡在罐车侧的点数（加泵无用）
        # 三道防线的水量分配（m³）——「时限内谁排走了多少」，三者之和 ≈ 总径流量。
        # ⚠ 第二、三道带淤积裕量，故合计可略大于 runoff_volume_m3。
        "line1_m3": 0.0,        # Σ 管网在时限 T 内排走的量（退水期平均速率 × T）
        "line2_m3": 0.0,        # Σ 调蓄吃下的量
        "line3_m3": 0.0,        # Σ 留给移动泵的量
        "line1_m3s": 0.0,       # Σ min(Q, Qcap) —— 峰值口径，仅供对照
        #: ⚠ `uncalibrated` 与 1/2/3 **并列**，不是它们的子集：没跑过二维演算的
        #: 点不出防线结论。四个数之和 = hotspots。前端画占比必须带上它，
        #: 否则会把「没算」显示成「没事」。
        "line_counts": {"1": 0, "2": 0, "3": 0, "uncalibrated": 0},
        #: 出得了结论的点数 —— 以上所有水量与泵数**只是这批点的合计**。
        "calibrated_hotspots": 0,
        "peak_exceeds_capacity": 0,     # 峰值超管网能力的点数（地面会积水）
    }


def _accumulate(bucket: dict, r: ScenarioResult, qcap: float, pond: float) -> None:
    """把一个点并进汇总。

    ⚠ 无标定的点**只计入 `hotspots`、`line_counts["uncalibrated"]` 与峰值诊断**，
    水量、泵数、罐车一律不并 —— 那些量在这个点上不存在，补 0 会让总账看起来
    比实际乐观（少算的正是没算的那部分）。看总账必须同时看 `calibrated_hotspots`。
    """
    bucket["hotspots"] += 1
    bucket["peak_flow_m3s"] += r.peak_flow_m3s
    bucket["excess_flow_m3s"] += r.excess_flow_m3s
    bucket["peak_exceeds_capacity"] += 1 if r.peak_exceeds_capacity else 0
    bucket["line1_m3s"] += min(r.peak_flow_m3s, qcap)

    line = defence_line(r)
    if line is None:
        bucket["line_counts"]["uncalibrated"] += 1
        return

    bucket["calibrated_hotspots"] += 1
    bucket["line_counts"][str(line)] += 1
    bucket["runoff_volume_m3"] += r.runoff_volume_m3
    bucket["required_storage_m3"] += r.required_storage_m3
    bucket["available_pond_m3"] += pond
    bucket["shortfall_m3"] += r.shortfall_m3
    bucket["pumps_required"] += r.pumps_required
    add_dispatch(bucket["pumps_by_tier"], r.pump_dispatch)
    bucket["tanker_loads"] += r.tanker_loads
    if r.tankers_required is None:
        bucket["points_tanker_infeasible"] += 1
    else:
        bucket["tankers_required"] += r.tankers_required
    bucket["tankers_to_feed_pumps"] += r.tankers_to_feed_pumps
    bucket["pumps_configured"] += r.pumps_configured
    bucket["tankers_configured"] += r.tankers_configured
    bucket["chain_residual_m3"] += r.chain_residual_m3
    bucket["points_under_served"] += 0 if r.configured_fleet_suffice else 1
    if not r.configured_fleet_suffice and r.chain_bottleneck == "tanker":
        bucket["points_tanker_bound"] += 1
    bucket["line1_m3"] += r.network_drained_m3
    bucket["line2_m3"] += r.storage_used_m3
    bucket["line3_m3"] += r.shortfall_m3


def run_batch(
    records: tuple[HotspotRecord, ...] | list[HotspotRecord],
    options: BatchOptions = BatchOptions(),
) -> dict:
    """对给定的积水点集合跑一场雨，返回逐点结果 + 汇总。"""
    points: list[dict] = []
    skipped: list[dict] = []
    totals = _empty_totals()
    by_municipality: dict[str, dict] = {}
    by_criticality: dict[str, dict] = {}
    #: 按官方行政片区汇总（`district_batch.py` 打的标签）。key 是市政区限定的
    #: `district_key` —— `AL BATEEN` 在 ADM 与 AAM 下各有一个，只按名字并会串台。
    by_district: dict[str, dict] = {}
    dataset_usage: dict[str, int] = {}
    oversized = 0
    #: 在册泵与罐车，**只累加出得了结论的那批点**。需求侧同样只算这批点
    #: （见 `_accumulate`），拿全量在册数去比一小撮点的需求，缺口会被系统性
    #: 抹平成 0 —— 当前 501 个点在册 768 台，而有结论的只有 18 个点。
    #: 全量口径另记在 `ledger_all_*`，供说明范围用，不参与缺口计算。
    ledger_pumps = 0.0
    ledger_tankers = 0.0
    ledger_by_tier = {"12in": 0.0, "8in": 0.0, "6in": 0.0}
    ledger_all_pumps = 0.0
    ledger_all_tankers = 0.0

    rp = CUSTOM_RETURN_PERIOD if options.custom_storm else options.return_period_yr

    for record in records:
        ledger_all_pumps += record.pumps_qty or 0.0
        ledger_all_tankers += record.tankers_qty or 0.0

        idf: IdfDataset = options.custom_storm or get_dataset(
            dataset_key_for(record, options.dataset)
        )
        if rp not in idf.return_periods:
            skipped.append(
                {"uid": record.uid, "reason": f"{idf.label} 无 {rp} 年重现期"}
            )
            continue

        hotspot = build_hotspot(
            record,
            options.profiles,
            priority=options.priority,
            zero_qcap_without_network=options.zero_qcap_without_network,
        )
        result = evaluate(hotspot, rp, options.assumptions, idf)
        line = defence_line(result)
        if line is not None:
            ledger_pumps += record.pumps_qty or 0.0
            ledger_tankers += record.tankers_qty or 0.0
            ledger_by_tier["12in"] += record.pump_12in_qty or 0.0
            ledger_by_tier["8in"] += record.pump_8in_qty or 0.0
            ledger_by_tier["6in"] += record.pump_6in_qty or 0.0
        if hotspot.exceeds_rational_method_limit:
            oversized += 1

        dataset_usage[idf.key] = dataset_usage.get(idf.key, 0) + 1
        _accumulate(totals, result, hotspot.qcap_m3s, hotspot.pond_available_m3)
        for tally, key in (
            (by_municipality, record.municipality),
            (by_criticality, record.criticality or "未填写"),
            (by_district, record.district_key or "未判定片区"),
        ):
            _accumulate(
                tally.setdefault(key, _empty_totals()),
                result, hotspot.qcap_m3s, hotspot.pond_available_m3,
            )

        points.append(
            {
                "uid": record.uid,
                "line": line,
                "dataset_key": idf.key,
                "profile_key": profile_key_for(record),
                "duration_min": round(result.duration_min, 2),
                "intensity_mm_hr": round(result.intensity_mm_hr, 2),
                "c_adjusted": round(result.c_adjusted, 3),
                "area_ha": hotspot.area_ha,
                "tc_min": hotspot.tc_min,
                "catchment_basis": catchment_basis_for(record, options.profiles),
                "qcap_m3s": round(hotspot.qcap_m3s, 3),
                "qcap_basis": qcap_basis_for(
                    record, options.profiles,
                    zero_qcap_without_network=options.zero_qcap_without_network,
                ),
                "pond_available_m3": hotspot.pond_available_m3,
                "storage_basis": storage_basis_for(record, options.profiles),
                "peak_flow_m3s": round(result.peak_flow_m3s, 3),
                "excess_flow_m3s": round(result.excess_flow_m3s, 3),
                "peak_exceeds_capacity": result.peak_exceeds_capacity,
                # —— 三道防线（共用时限 window_hours）——
                # ⚠ `l1_basis == "uncalibrated"` 时以下各量**全部为 None**：
                # 这个点没跑过二维演算，不出结论。前端必须按 None 显示「无标定」，
                # 不能当 0 画进任何图里。见 `rational.evaluate()`。
                "window_hours": result.window_hours,
                "l1_basis": result.l1_basis,
                "is_calibrated": result.is_calibrated,
                "runoff_volume_m3": _round(result.runoff_volume_m3, 1),
                "network_drained_m3": _round(result.network_drained_m3, 1),
                "residual_after_network_m3": _round(result.residual_after_network_m3, 1),
                # 两个退干时间口径不同，页面上别混：`drain_hours` 自演算 t=0
                # 起算，`recession_hours` 自峰值起算。与第一道并排可比的是后者
                # —— 窗口 T 也是从峰值起算的（ADM-379：16.75 / 13.75 h）。
                "drain_hours": _round(result.drain_hours, 2),
                "recession_hours": _round(result.recession_hours, 2),
                "cleared_by_network": result.cleared_by_network,
                "required_storage_m3": _round(result.required_storage_m3, 1),
                "storage_used_m3": _round(result.storage_used_m3, 1),
                "cleared_by_storage": result.cleared_by_storage,
                "shortfall_m3": _round(result.shortfall_m3, 1),
                "pumping_rate_m3hr": _round(result.pumping_rate_m3hr, 1),
                "pumps_required": result.pumps_required,
                "pumps_by_tier": (
                    dict(result.pump_dispatch.counts) if result.pump_dispatch else None
                ),
                "pump_deployed_m3hr": (
                    round(result.pump_dispatch.deployed_m3hr, 1)
                    if result.pump_dispatch else None
                ),
                "tanker_loads": result.tanker_loads,
                #: 车次 → 辆数。`tankers_required` 为 null 且本点有结论 =
                #: 周转时间长于时限，一辆车跑不满一趟，**不是 0 辆**。
                "tanker_trips_per_vehicle": result.tanker_trips_per_vehicle,
                #: ⚠ 与 `pumps_required` **同时都要**，不是二选一 ——
                #: 泵把水抽进罐车，罐车运走，两段串联。
                "tankers_required": result.tankers_required,
                #: 喂饱 `pumps_required` 台泵要几辆车；与上一个取大的才是要配的数
                "tankers_to_feed_pumps": result.tankers_to_feed_pumps,
                # —— 页面配置的车队：配了 N 台泵 + M 辆车够不够、卡在哪一侧 ——
                # ⚠ 与上面那组（该配多少）**并列**，不可混用。
                "pumps_configured": result.pumps_configured,
                "tankers_configured": result.tankers_configured,
                "pump_configured_m3hr": _round(result.pump_configured_m3hr, 1),
                "tanker_configured_m3hr": _round(result.tanker_configured_m3hr, 1),
                #: 这条链真正的外运能力 = 两侧取小
                "chain_configured_m3hr": _round(result.chain_configured_m3hr, 1),
                "chain_bottleneck": result.chain_bottleneck,
                "chain_hours_required": _round(result.chain_hours_required, 2),
                "chain_residual_m3": _round(result.chain_residual_m3, 1),
                "configured_fleet_suffice": result.configured_fleet_suffice,
                # —— 二维演算的原始量，供页面解释 R1 是怎么来的 ——
                "ponding_peak_m3": _round(result.ponding_peak_m3, 1),
                "ponding_peak_time_min": _round(result.ponding_peak_time_min, 1),
                "ponding_net_inflow_m3": _round(result.ponding_net_inflow_m3, 1),
                "ponding_attribution": result.ponding_attribution,
                "ponding_run_id": result.ponding_run_id,
                #: ⚠ 与本行的 `return_period_yr` 不同就说明「有演算但不是这场雨」
                "ponding_run_rp_yr": result.ponding_run_rp_yr,
                "notes": list(result.notes),
            }
        )

    a = options.assumptions
    return {
        "return_period_yr": rp,
        "dataset_selection": "custom_storm" if options.custom_storm else options.dataset,
        "dataset_usage": dataset_usage,
        "points": points,
        "skipped": skipped,
        "summary": {
            **totals,
            "oversized_catchments": oversized,
            #: ⚠ 以下三项只统计**出得了结论的点**，与需求侧同口径，缺口才算得准。
            "ledger_pumps_qty": ledger_pumps,
            "ledger_pumps_by_tier": {k: int(v) for k, v in ledger_by_tier.items()},
            "ledger_tankers_qty": ledger_tankers,
            #: 筛选范围内**全部**点的在册数，只用来说明范围，不参与缺口计算。
            "ledger_all_pumps_qty": ledger_all_pumps,
            "ledger_all_tankers_qty": ledger_all_tankers,
            "points_computed": len(points),
            "drawdown_hours": a.drawdown_hours,
            "pump_tiers": [
                {
                    "key": t.key,
                    "label": t.label,
                    "rated_m3hr": round(
                        t.rated_m3hr(a.pump_duty_factor, a.pump_availability), 1
                    ),
                    "nameplate_m3hr": t.nameplate_m3hr,
                    "fleet_qty": t.fleet_qty,
                    "basis": t.basis,
                    "reference": t.reference,
                }
                for t in a.effective_tiers
            ],
            #: 12″/8″/6″ 三档**参照表**，恒给，与本次是否按它派车无关 ——
            #: 页面上要选「单泵抽排能力」时，对照的就是这张表。
            "pump_reference_tiers": [
                {
                    "key": t.key,
                    "label": t.label,
                    "rated_m3hr": round(
                        t.rated_m3hr(a.pump_duty_factor, a.pump_availability), 1
                    ),
                    "nameplate_m3hr": t.nameplate_m3hr,
                    "fleet_qty": t.fleet_qty,
                    "basis": t.basis,
                    "reference": t.reference,
                }
                for t in DEFAULT_PUMP_TIERS
            ],
            "pump_duty_factor": a.pump_duty_factor,
            "pump_availability": a.pump_availability,
            "pump_capacity_m3hr": a.pump_capacity,   # 非空即单档模式，见 Assumptions
            #: 页面上那两个旋钮。`pump_unit_capacity_m3hr` 与 `pump_capacity_m3hr`
            #: 在单档模式下相同；回退到分档表时前者是在册加权平均，后者为 null。
            "pumps_per_point": a.pumps_per_point,
            "pump_unit_capacity_m3hr": round(a.pump_unit_capacity, 1),
            "tankers_per_point": a.tankers_per_point,
            "tanker_capacity_m3": a.tanker_capacity,
            "tanker_turnaround_min": a.tanker_turnaround_min,
            #: 时限内一辆罐车能跑几趟 —— 车次折辆数的换算系数。0 = 跑不满一趟。
            "tanker_trips_per_vehicle": a.tanker_trips_within(a.drawdown_hours),
            #: —— 泵 → 罐车 这条**串联**链的两侧能力，页面并排摆这两个数 ——
            #: 一辆罐车的持续外运能力 = 单车容量 / 往返周转（默认 15 m³/h）
            "tanker_vehicle_rate_m3hr": round(a.tanker_vehicle_rate_m3hr, 1),
            #: **喂饱一台泵要几辆罐车**（默认 ⌈300/15⌉ = 20）—— 少于这个数，
            #: 这个点的外运能力由罐车侧定，加泵无用。
            "tankers_per_pump": a.tankers_per_pump,
            #: 每点两侧的配置能力与链的实际能力（m³/h），三个数一起看瓶颈
            "pump_configured_m3hr": round(a.pump_configured_m3hr, 1),
            "tanker_configured_m3hr": round(a.tanker_configured_m3hr, 1),
            "chain_configured_m3hr": round(a.chain_configured_m3hr, 1),
            "chain_bottleneck": a.chain_bottleneck,
        },
        "by_municipality": by_municipality,
        "by_criticality": by_criticality,
        "by_district": by_district,
    }


def fleet_gap(summary: dict, tiers: tuple | None = None) -> dict:
    """模型需求 vs 台账已配 —— 页面顶部那张对照卡。

    ⚠ 两个数不同口径：模型给的是「同时出动的泵台数」，台账给的是
    「各点已列装的泵台数」，相减只能当量级参考，不能当采购依据。

    第三个数是**页面配置**（`pumps_configured` = 有结论的点数 × 每点台数），
    那是操作员设的假设，既不是模型算出来的需求也不是台账的实际列装 ——
    三个数分开读。`pumps_configured_gap` 只回答一件事：按页面这个配置，
    要在时限 T 内排完还差几台。

    ⚠ **泵与罐车不是二选一。** 泵把水抽进罐车、罐车拉到受纳点倒掉再回来，
    两段串联，所以 `pumps_required` 和 `tankers_required` 是同时都要的一对，
    看缺口必须两边一起看。链的通过量由瓶颈段定，默认参数下瓶颈几乎总在罐车侧
    （单泵 300 m³/h vs 单车 15 m³/h，`tankers_per_pump` = 20）——
    `points_tanker_bound` 数的就是那些「加泵一滴水也多排不出去」的点。

    `by_tier` 是逐档对照：模型需求 vs 在册台数。在册给两个口径，**不要混用**：

    * `on_fleet` —— 全网在册（12″ 144 / 8″ 121 / 6″ 579，`pumps.DEFAULT_PUMP_TIERS`）。
      口径固定，不随筛选变。
    * `on_fleet_in_scope` —— 只数**本次参与计算的那些点**台账里列的分档泵数。
      只算一部分点（如只算有管网数据的区域）时，该看这一个 —— 拿全网在册数
      去比一部分点的需求，缺口会被系统性低估。

    ⚠ 两个口径本来就对不上（全网 107/86/579 vs 在册 144/121/579），
      因为它们取自台账不同的列。孰为准是 DMT 清单 §02 要确认的事。
    """
    pumps_need = int(summary["pumps_required"])
    pumps_have = int(summary["ledger_pumps_qty"])
    tankers_have = int(summary["ledger_tankers_qty"])
    loads = int(summary["tanker_loads"])
    tankers_need = int(summary.get("tankers_required", 0))
    tankers_to_feed = int(summary.get("tankers_to_feed_pumps", 0))
    tanker_blocked = int(summary.get("points_tanker_infeasible", 0))
    need_by_tier = summary.get("pumps_by_tier", {})
    in_scope = summary.get("ledger_pumps_by_tier") or {}

    if tiers is None:
        tiers = tuple(DEFAULT_ASSUMPTIONS.effective_tiers)

    def _in_scope(key: str) -> int | None:
        """这一档在参与计算的那些点的台账里列了多少台。

        单档口径下台账拆不出档 —— 三列相加就是「这些点一共列了多少台移动泵」，
        正对应单档那一行的语义。空 dict 时返回 None（台账没有分档列）。
        """
        if key != "uniform":
            return in_scope.get(key)
        return sum(in_scope.values()) if in_scope else None

    by_tier = [
        {
            "key": t.key,
            "label": t.label,
            "required": need_by_tier.get(t.key, 0),
            "on_fleet": t.fleet_qty,
            "on_fleet_in_scope": _in_scope(t.key),
            "gap": max(0, need_by_tier.get(t.key, 0) - t.fleet_qty),
            "gap_in_scope": (
                None if _in_scope(t.key) is None
                else max(0, need_by_tier.get(t.key, 0) - _in_scope(t.key))
            ),
        }
        for t in tiers
    ]

    # 页面配置的车队 vs 模型算出来「该配几台」。⚠ 这一组和上面的
    # `pumps_on_ledger`（台账已列装）**不是一回事**：配置是操作员在页面上设的
    # 假设，台账是实际列装记录。三个数要分开读，不能两两相减当结论。
    configured = int(summary.get("pumps_configured", 0))
    tankers_configured = int(summary.get("tankers_configured", 0))
    # 真正要配的车数：按水量算的和喂饱泵要的，取大 —— 两个约束都得满足。
    tankers_need_binding = max(tankers_need, tankers_to_feed)
    return {
        "pumps_required": pumps_need,
        "pumps_on_ledger": pumps_have,
        "pumps_gap": max(0, pumps_need - pumps_have),
        "by_tier": by_tier,
        #: 三档在册合计（阿布扎比市口径），和逐点台账的 `pumps_on_ledger` 不是一回事
        "fleet_total": sum(t.fleet_qty for t in tiers),
        #: —— 页面配置式的对照：配了多少、够不够 ——
        "pumps_configured": configured,
        #: 按当前配置**还差几台**才能在时限 T 内排完（全域口径）
        "pumps_configured_gap": max(0, pumps_need - configured),
        #: 配置的车队在时限内运不走、留在地面的总量（m³）与涉及的点数。
        #: ⚠ 这是**整条链**的残量（泵侧与罐车侧取小），不是单看泵。
        "chain_residual_m3": round(float(summary.get("chain_residual_m3", 0.0)), 1),
        "points_under_served": int(summary.get("points_under_served", 0)),
        #: 其中**卡在罐车侧**的点数 —— 这些点再加泵也排不出去，要加的是车。
        "points_tanker_bound": int(summary.get("points_tanker_bound", 0)),
        "tankers_configured": tankers_configured,
        "tanker_loads_required": loads,
        #: 需要的罐车**辆数** —— 车次按「一辆车在时限内跑几趟」折算而来。
        #: 与 `tanker_loads_required`（车次）是两个量，别混着报。
        #: ⚠ 与 `pumps_required` **同时都要**，不是它的替代方案。
        "tankers_required": tankers_need,
        #: 喂饱 `pumps_required` 台泵所需的车数（台数 × `tankers_per_pump`）
        "tankers_to_feed_pumps": tankers_to_feed,
        #: **真正要配的车数 = 上面两个取大** —— 水量和喂泵两个约束都得满足
        "tankers_required_binding": tankers_need_binding,
        "tankers_on_ledger": tankers_have,
        "tankers_gap": max(0, tankers_need_binding - tankers_have),
        #: 周转时间长于时限、辆数不出数的点数。>0 时上面那个辆数**是下限**；
        #: 那些点第三道防线整条不成立（泵抽出来的水没车拉走）。
        "points_tanker_infeasible": tanker_blocked,
        #: 台账现有的车每辆得跑几趟 —— 拿在册辆数去除车次，与需求侧的
        #: `tankers_required` 不是一回事（那个是按时限反推该有几辆）。
        "loads_per_tanker": ceil(loads / tankers_have) if tankers_have else None,
    }
