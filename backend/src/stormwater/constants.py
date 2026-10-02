"""全局假设参数（对应交接文档 §3.5 Assumptions 工作表）。

标注「假设值」的参数没有出处，是原 Excel 模型自己拍的，必须在 UI 上显式暴露
并允许覆盖，不能当成常量埋进计算里。
"""

from dataclasses import dataclass
from math import ceil
from typing import Literal

from .pumps import (
    DEFAULT_AVAILABILITY,
    DEFAULT_DUTY_FACTOR,
    DEFAULT_PUMP_CAPACITY,
    DEFAULT_PUMP_TIERS,
    PumpTier,
    fleet_weighted_capacity,
    uniform_tier,
)


#: 三道防线的判定口径，见 `Assumptions.defence_basis`。
#: ⚠ 旧的 `"window"`（管网按满流 Qcap 恒排 T 小时）已**删除**，不是改默认值 ——
#: 它被一维与二维水动力成果同时证伪，证据链见 `ponding_curve.py` 模块头注释。
DefenceBasis = Literal["hydrodynamic", "peak"]


@dataclass(frozen=True)
class Assumptions:
    """一次计算所用的全局假设。默认值与原 Excel 模型一致。"""

    #: 淤积裕量系数 —— 有出处：DM 导则 Sec 5.1
    sed_factor: float = 1.05

    #: 过程线形状系数 —— 假设值：三角形过程线近似（V = ½·Q·D 里的那个 ½），
    #: 现在乘的是**事件径流总量**而不是超量流量，真值需 InfoSWMM 演算
    shape_factor: float = 0.50

    #: 三道防线的判定口径 —— **改的是问题本身，不是一个系数**。
    #:
    #: * ``"hydrodynamic"``（默认）：总量取二维演算的**全程**净入流，
    #:   R1 = max(0, 总量 − R × T)，R 是该点演算实测的**退水期平均**退水速率
    #:   （`PondingCurve.mean_drain_rate_m3h`；取最大帧降幅那版已于 2026-09-21
    #:   回退，它在 123 个有演算的点上无一例外高估 1.9–8.1 倍）——
    #:   问的是「管网这条腿在工期 T 内分担不掉多少」；排不完的交调蓄，
    #:   再排不完的交移动泵。没跑过演算的点**不出结论**，不外推。
    #: * ``"peak"``：原 Excel 口径。只看峰值时刻的超量流量，回答「峰值会不会
    #:   溢流」。保留它只为复现原 Excel（见 `backend/tests/test_rational.py`）。
    #:
    #: ⚠ 旧的 ``"window"``（R1 = max(0, V_in − Qcap × T)）已删除。它假定管网以
    #: 满流能力恒排 T 小时，而实测 `corr(Qcap, 排空速率) = −0.156` —— 管段满流
    #: 能力对排空速率无预测力，方向还是反的。完整证据见 `ponding_curve.py`。
    defence_basis: DefenceBasis = "hydrodynamic"

    #: **三道防线共用的时限 T**（小时）—— 运营设定，应替换为实际应急响应 SLA。
    #: 第一道问「T 时刻地面上还剩多少水」，第三道问「剩下的要几台泵在同一个 T
    #: 内排完」，改这一个值三道防线一起变。判定口径见 `rational.evaluate()`。
    #:
    #: ⚠ 2 h 这个默认值**与二维演算不相容**：Al Bateen RP100 下 10 个积水量
    #: ≥500 m³ 的点，等效排空时间常数落在 10.2–16.8 h（中位 12.4 h），地表退水
    #: 本身就要半天。拿 T=2 h 去要求排完 100 年一遇的水，逼出来的是没法采购的
    #: 车队规模。T 是**服务水平目标**，该由决策者显式选，不该当默认值用。
    drawdown_hours: float = 2.0

    #: 移动泵车分档表（12″ / 8″ / 6″）—— 铭牌值经两级折减，见 `pumps.py`。
    #: ⚠ **只在 `pump_capacity` 置空时才参与派车**，默认口径是下面的单档配置式。
    pump_tiers: tuple[PumpTier, ...] = DEFAULT_PUMP_TIERS

    #: 工况扬程折减 —— **推算系数**，只作用于分档表（单档模式下排量是直接给的）
    pump_duty_factor: float = DEFAULT_DUTY_FACTOR

    #: 出勤占空（加油、转场、清堵）—— **推算系数**，同上只作用于分档表
    pump_availability: float = DEFAULT_AVAILABILITY

    #: **单泵抽排能力（m³/h）—— 页面上那个旋钮，也是默认口径。**
    #:
    #: 给了值（默认 300）就忽略分档表，全部点按这一个排量算；配合
    #: `pumps_per_point` 构成「每点配 N 台 × 每台 X m³/h」的配置式车队。
    #: 300 是假设值，但不是凭空拍的 —— 见 `pumps.DEFAULT_PUMP_CAPACITY`。
    #:
    #: 置 `None` 则退回 12″/8″/6″ 分档派车（`pumps.dispatch()` 按水量解台数），
    #: 那是回答「采购该买哪几档」时唯一说得清的口径，故逻辑完整保留。
    pump_capacity: float | None = DEFAULT_PUMP_CAPACITY

    #: **每个积水点配置几台移动泵 —— 页面上那个旋钮，默认 1 台/点。**
    #:
    #: 这一个值把第三道防线的问题**掉了个方向**：原来问「这个点要几台泵」
    #: （模型按水量解台数），现在问「配了这几台够不够、要多久」。两个答案都留着：
    #: `pumps_required` 仍是「T 内排完该配几台」，而 `pumps_configured` /
    #: `chain_residual_m3` / `chain_hours_required` 说的是当前配置的实际效果。
    #: 两者的差就是缺口，那才是采购论证要的数。
    #:
    #: ⚠ 泵单独配是配不出外运能力的 —— 见 `tankers_per_point`。
    pumps_per_point: int = 1

    #: **每个积水点配置几辆罐车 —— 页面上那个旋钮，默认 1 辆/点。**
    #:
    #: ⚠ 它与 `pumps_per_point` 是**串联**的一条链，不是两个并列选项：泵把水抽
    #: 进罐车，罐车拉到受纳点倒掉再回来。所以这个点的外运能力取两侧的**较小值**
    #: （`chain_rate`），罐车不够时泵只能干等着 —— 多配泵一滴水也多排不出去。
    #:
    #: 默认 1 辆/点与 1 台/点对称，但两侧在默认参数下**差着一个量级**：一辆
    #: 15 m³、周转 60 min 的罐车持续外运只有 15 m³/h，而一台泵 300 m³/h ——
    #: 要喂饱一台泵得配 `tankers_per_pump` = 20 辆。这个比值是本模型最该被看见
    #: 的结论之一，故不把默认值设成「刚好配平」把它藏起来。
    tankers_per_point: int = 1

    #: 罐车单车储水能力（m³/车次）—— 假设值，应替换为实际车队单车载量
    tanker_capacity: float = 15.0

    #: **罐车单车往返周转时间（分钟/趟）—— 页面上那个旋钮，默认 60。**
    #:
    #: 一趟 = 现场装载 + 开到受纳点 + 卸载 + 空车返回（+ 机动）。
    #:
    #: 没有这个量就**只能算车次、算不出辆数**：泵是连续流量（m³/h），时限 T 直接
    #: 乘就是运力；罐车是离散往返，T 必须先换成「一辆车在 T 内能跑几趟」才能把
    #: 车次折成辆数。交接文档 §7 待决策第 5 条说的正是这件事 —— 不纳入周转，
    #: 「101 车次」只是体积换算，不是调度结论。
    #:
    #: ⚠ 60 min 是**假设值，本项目没有任何数据支撑它**（与单泵 300 m³/h 不同，
    #: 那个至少落在在册车队加权平均附近）。真值取决于受纳点位置与路况，应由
    #: DMT 给出实际周转记录。正因为无出处，它必须摆在页面上让人改。
    tanker_turnaround_min: float = 60.0

    def __post_init__(self) -> None:
        if self.pumps_per_point < 1:
            raise ValueError(f"每个积水点至少配 1 台泵，得到 {self.pumps_per_point}")
        if self.tankers_per_point < 1:
            raise ValueError(
                f"每个积水点至少配 1 辆罐车（泵抽出来的水得有车拉走），"
                f"得到 {self.tankers_per_point}"
            )
        if self.pump_capacity is not None and self.pump_capacity <= 0:
            raise ValueError(f"单泵抽排能力必须为正，得到 {self.pump_capacity}")
        if self.tanker_capacity <= 0:
            raise ValueError(f"罐车单车容量必须为正，得到 {self.tanker_capacity}")
        if self.tanker_turnaround_min <= 0:
            raise ValueError(
                f"罐车往返周转时间必须为正，得到 {self.tanker_turnaround_min}"
            )

    def tanker_trips_within(self, window_hours: float) -> int:
        """时限内**一辆**罐车能完成几趟往返 —— 车次折成辆数的换算系数。

        取下整：跑到一半的那趟在时限内没送到，不算数。

        返回 0 表示**周转时间比时限还长**，一辆车连一趟都跑不完 —— 此时整条
        「泵 → 罐车 → 受纳点」的链在这个时限下运不走一滴水（泵抽出来也没车拉），
        调用方必须按「不出数」处理，不能拿 0 去除。⚠ 这是**时延**约束不是运力
        约束：多配车也跑不完一趟，加车没用，只能放宽 T 或把受纳点设得更近。
        """
        return int(window_hours * 60.0 // self.tanker_turnaround_min)

    @property
    def tanker_vehicle_rate_m3hr(self) -> float:
        """**一辆**罐车的持续外运能力（m³/h）= 单车容量 ÷ 往返周转。

        默认参数下 15 m³ ÷ 1 h = 15 m³/h —— 拿它和单泵 300 m³/h 并排看，
        就知道这条链卡在哪一侧。

        ⚠ 这是**长时段的持续能力**，不计「半趟不算」的取整损失；问「时限 T 内
        运得走多少」要用 `tanker_trips_within(T) × 单车容量`，两者不等价。
        """
        return self.tanker_capacity / (self.tanker_turnaround_min / 60.0)

    @property
    def tankers_per_pump(self) -> int:
        """**喂饱一台泵要配几辆罐车** = ⌈单泵排量 / 单车持续外运能力⌉。

        默认参数下 ⌈300 / 15⌉ = 20 辆。低于这个数，泵就是在等车 ——
        这个点的实际外运能力由罐车侧定，和泵配了几台无关。
        """
        rate = self.tanker_vehicle_rate_m3hr
        return ceil(self.pump_unit_capacity / rate) if rate > 0 else 0

    @property
    def pump_configured_m3hr(self) -> float:
        """一个点上配置的泵侧抽排能力（m³/h）= 台数 × 单泵排量。"""
        return self.pumps_per_point * self.pump_unit_capacity

    @property
    def tanker_configured_m3hr(self) -> float:
        """一个点上配置的罐车侧持续外运能力（m³/h）= 辆数 × 单车外运能力。"""
        return self.tankers_per_point * self.tanker_vehicle_rate_m3hr

    @property
    def chain_configured_m3hr(self) -> float:
        """**这条链实际的外运能力（m³/h）= 两侧取小。**

        串联的两段，通过量由瓶颈段定：泵抽得再快，没车拉走也只能停机。
        """
        return min(self.pump_configured_m3hr, self.tanker_configured_m3hr)

    @property
    def chain_bottleneck(self) -> str:
        """这条链卡在哪一侧：``"pump"`` / ``"tanker"`` / ``"balanced"``。"""
        pump_rate = self.pump_configured_m3hr
        tanker_rate = self.tanker_configured_m3hr
        if abs(pump_rate - tanker_rate) < 1e-9:
            return "balanced"
        return "tanker" if tanker_rate < pump_rate else "pump"

    @property
    def effective_tiers(self) -> tuple[PumpTier, ...]:
        """实际参与派车的分档表 —— 设了 `pump_capacity` 就退化成单档。"""
        if self.pump_capacity:
            return (uniform_tier(self.pump_capacity),)
        return self.pump_tiers

    @property
    def pump_unit_capacity(self) -> float:
        """配置式口径下的**单台**泵排量（m³/h）—— 「每点 N 台」里那个「台」。

        单档模式下就是 `pump_capacity` 本身。退回分档表时取在册构成的加权平均
        （约 321 m³/h），好让「每点配 N 台」在两种口径下都说得出一个数 ——
        那种口径下「一台」本来就是混合车队里的平均一台，不是某个具体档。
        """
        if self.pump_capacity:
            return self.pump_capacity
        return fleet_weighted_capacity(
            self.pump_tiers, self.pump_duty_factor, self.pump_availability
        )


DEFAULT_ASSUMPTIONS = Assumptions()

#: 旧口径：原 Excel 模型对全车队统一假设的单泵排量，**无出处**。
#: 保留仅为回归对照 —— `Assumptions(pump_capacity=LEGACY_PUMP_CAPACITY)` 可复现旧结果。
LEGACY_PUMP_CAPACITY = 300.0

#: 推理公式法的适用上限（公顷）。超过须拆分子汇水区或改用过程线法。
#: 来源：DM 导则 —— 交接文档 §3.7
RATIONAL_METHOD_MAX_AREA_HA = 80.0
