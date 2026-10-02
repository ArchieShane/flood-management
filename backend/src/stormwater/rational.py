"""推理公式法计算链（交接文档 §3.2）+ 统一时限下的三道防线判定。

对每个「积水点 × 重现期」组合算出：峰值流量 → 第一道（时限内地面的水退掉
多少）→ 第二道（剩余量调蓄能不能接住）→ 第三道（还剩多少要移动泵在同一
时限内排完，需要几台）。

**三道防线共用同一个时限 T**（`Assumptions.drawdown_hours`，默认 2 小时）：

    第一道：R1 = max(0, V_全程 − R × T)    管网在工期 T 内分担不掉、往下交的量
    第二道：需调蓄 = R1 × 淤积裕量
            剩余 R2 = max(0, 需调蓄 − 可用调蓄)
    第三道：抽排速率 = R2 / T  → 按单泵抽排能力解台数（`pumps_required`）
            罐车侧：车次 = R2 / 单车容量，辆数 = 车次 / ⌊T×60 / 周转时间⌋
            并行给出「页面配了 N 台泵 + M 辆罐车够不够」（`chain_residual_m3`）

## 第三道防线是一条串联的链，不是两个可选方案

**移动泵和罐车不是「或」的关系** —— 泵把积水抽进罐车，罐车拉到受纳点倒掉再
回来。两段串在一起，通过量由**瓶颈段**定：

    链的外运能力 = min(泵侧抽排能力, 罐车侧持续外运能力)

所以 `pumps_required` 与 `tankers_required` 是**同时都要**的一对，不是二选一；
页面配置侧同理，泵配得再多，车不够就只能停机等车，一滴水也多排不出去。

默认参数下两侧差着一个量级：一台泵 300 m³/h，一辆 15 m³、周转 60 min 的罐车
持续外运只有 15 m³/h —— **喂饱一台泵要 20 辆罐车**
（`Assumptions.tankers_per_pump`）。这个比值是本模块最该被看见的数之一。

两侧的取整口径不同，不要混用：泵侧是连续流量，乘 T 就是运力；罐车侧是离散
往返，时限内只有**跑完整趟**的才算数（`tanker_trips_within()`），所以
「T 内运得走多少」用整趟数算，而「排完要几小时」用持续能力算。

## 第一道防线：**平均**退水速率 × T，Qcap 不进水量平衡

**时限 T 是「工期」不是「观测时刻」**：总积水量要在 T 内清完，重力自排（第一
道）与移动泵（第三道）是**并联的两条出路**，在同一个 T 内各排各的：

    总量   = V_全程 = curve.net_inflow_m3   演算全程 Σ 正 ΔV，**不掐在 T 上**
    第一道 = min(总量, R_avg × T)           R_avg = 峰后累计退水 ÷ 峰后退水期
    第三道 = max(0, 总量 − 第一道) × 淤积裕量

总量之所以取全程而非 V(T)：T 既然是工期，那 T 之后才到的水**照样要清**，掐在
T 上只会把它们凭空抹掉。Al Bateen 16 个有水的点里 6 个峰值落在 t=180 min，
V(T) 口径把总量记少 7%–29%（ADM-377 是 7,324 vs 9,007）。取净入流而不是峰值
`peak_m3`，是为了双峰过程不漏掉第二次上涨 —— 单峰点上两者相等。

### ⚠ R 取**平均**不取最大 —— 这条走过两遍坑

2026-09-21 之前 R 取 `drain_rate_m3h`，即时程里**最大的**那一段帧间降幅。它
答的是「峰值水头下最快能退多快」，拿来当 T 小时的恒速就是把瞬时上限外推成
持续能力，而真实退水是强衰减的（线性水库 τ 落在 61–228 min）。

实测这个高估是**系统性**的：按各点自己的 R_max 恒排，123 个有演算的点排完
全量所需时间比演算实测的退干时间短 **1.9–8.1 倍（中位 3.7 倍），无一例外**。

用户是在 **ADM-379** 上抓到的 —— 页面同时写着「一道 · 2 h 内排走 3,684 m³」
和「实测退干需 16.8 h」，两个数来自互不相干的读法。核下来两处硬伤：

* 该点 R_max = 1,842 m³/h 出现在 **t=210–225 min**，落在 T=2 h 窗口**之外**；
  0–120 min 内该点的水还在**涨**、实测退水是 0，公式却记了已排 3,684 m³。
* 按 1,842 m³/h 恒排，5,636 m³ 只要 **3.06 h** 就干，演算说 **16.75 h**。

现在 R 取**整个退水期的平均**：`mean_drain_rate_m3h` = 峰后累计退水 ÷ 峰后
退水期时长。ADM-379 = 5,632 ÷ 13.75 h = **410 m³/h**，一道 3,684 → **820 m³**，
T = 13.75 h 时恰好等于总量 —— 与实测退干时间自洽。

**分母从峰值起算**而不是 t=0：一道的窗口 T 也从峰值起算，两者必须同起点，
否则 T = 退水期时长时一道对不上总量。用绝对退干时刻 16.75 h 当分母会把涨水期
摊进来，ADM-379 得 336 而不是 410 m³/h（低 18%）。

**方向**：平均口径偏保守 —— 峰值段真实退得比平均快，所以第一道记少、第三道的
泵记多。这是有意选的（决策者 2026-09-21 定），比原先高估 3.7 倍安全。

全量（123 点 / T=2 h）：一道 142,940 → **37,433 m³**，交给二三道 118,385 →
**223,892 m³**；旧口径在 T=4 h 有 67 个点被判「一道全退完」，新口径只剩个位数。

⚠ 这个量是**地表净退水**，管网、下渗、ANUGA 的概化排水项混在一起，严格说
不止「管网排走」。一维那份 SWMM 给不出纯管网项（99.99% 时间步不收敛、连续性
误差 −58.3%、仿真只有 4 h 且退水时刻整体右删失）。

⚠ 本口径与旧口径差一个量级，MDL-078 在 T=2 h 上是 657 → 241 m³。旧口径把 T
读作观测时刻、直接取实测 V(T) 当残量（`R1 = V(T)`，水量账
`V_in = drained + V(T)` 逐帧闭合），答的是「T 那一刻地面上还剩多少」。两个
问题都成立，但不能混着用。

⚠ 还有一处未解的口径张力：总量是演算 V(t) 的净入流，而 V(t) 是「进 − 出」的
净值，**上涨期已经扣过一次管网排水**；第一道再减一次峰后退水，管网那条腿在
上涨期被记了两遍，方向是把第三道的泵记少。解掉它得从 `.sww` 的 xmomentum/ymomentum 算毛
通量 —— 靠存量外推站不住（全区口径高估 51%，见 `ponding_batch` 模块头）。

### 为什么 `Qcap × T` 不能当第一道

管段满流能力 `qcap_m3s` 答的是「这根管满流时每秒过多少水」，不是「地面的水
能以多快进到管里」。三份成果同时证伪：

* `corr(Qcap, 实测排空速率) = −0.156` —— 无预测力，方向还是反的。极端例子：
  ADM-376 的 Qcap 2.092 m³/s 是这批点最高，实测速率 0.011 m³/s；ADM-380 的
  Qcap 只有 0.430，实测速率 0.253。而
  `corr(洼地库容, 实测峰值积水) = +0.982` —— 积多少由地形定。
* 代进第一道会让 **112/123 个有演算的点（91%）泵需求归零**，第三道防线整条
  消失；而这批点演算实测要 10 多小时才退干（MDL-078 是 14.75 h）。Qcap 说
  MDL-078 的 783 m³ 靠重力 21 分钟走光，直接推翻演算。量级差最大到 28 倍
  （MDL-003：Qcap 76,569 m³/h，实测 2,693 m³/h）。
* 一维 SWMM 全城 run 在 RP100 下产流 6,336 ML、排放口出流仅 34 ML，其余从
  检查井溢出；而那份模型的管道坡度取自地形，满流能力比实测内底反算的还高
  2.4 倍（`swmm_batch.py`）。比真实管网乐观得多的模型都排不出去。
* 二维 run 的耦合是 `one_way_swmm_to_anuga`，注到地面的正是节点溢流 ——
  **积水期管网是源不是汇**。

`Qcap` 因此退出水量平衡，只留作峰值诊断（`peak_exceeds_capacity`：Q > Qcap
→ 地面会积起来）。这是它唯一站得住的用法，也正是一维成果支持的定性结论。

## 没跑过二维演算的点不出结论

`hotspot.ponding is None` 时三道防线整块**不出数**（`l1_basis` 记
`uncalibrated`，各量为 None，`defence_line` 为 None），而不是退回旧公式或
给一个外推值 —— 外推需要逐点洼地库容，全域只有 30.35 m 的 GLO-30 DEM，
分辨不出 Al Bateen 那些 0.04–6 ha 的洼地。当前 845 点里 18 个有标定。

`peak` 口径（原 Excel）不受影响，见 `Assumptions.defence_basis`。

降雨强度从可切换的 IDF 数据集取（见 `idf.py`）：迪拜 DM 查表取档，
ADQCC WA-726-1 用连续公式。两者的历时语义不同，故强度与历时一起返回。
峰值流量 Q 仍按推理公式算 —— 它算的是**流量**，那部分没有被证伪。

⚠ 本模块属**筛查与排序工具**，非最终设计（交接文档 §3.7）：
  两套导则都要求调蓄池和泵站的实际设计必须用 InfoSWMM 等软件建模报批。
"""

from dataclasses import dataclass, field, replace
from math import ceil

from .constants import DEFAULT_ASSUMPTIONS, RATIONAL_METHOD_MAX_AREA_HA, Assumptions
from .idf import (
    DEFAULT_DATASET_KEY,
    FLEET_RETURN_PERIODS,
    CatchmentPriority,
    IdfDataset,
    get_dataset,
)
from .ponding_curve import PondingCurve
from .pumps import PumpDispatch, add_dispatch, dispatch as dispatch_pumps


@dataclass(frozen=True)
class Hotspot:
    """一个积水点的输入参数（对应 Excel 的 Hotspots 工作表一行）。"""

    hotspot_id: str
    area_ha: float          #: 汇水面积（公顷）
    runoff_c: float         #: 径流系数 C（未经 Cf 调整）
    tc_min: float           #: 集流时间（分钟）
    #: 管网承载能力（m³/s）。⚠ **不参与三道防线的水量平衡** —— 只用来算峰值
    #: 诊断量 `excess_flow_m3s`。退出水量平衡的理由见模块头注释。
    qcap_m3s: float
    pond_available_m3: float = 0.0   #: 已有可用调蓄容量（m³）
    #: ADQCC Table 3-3 汇水区优先级 → 设计历时乘数 M。
    #: 迪拜数据集没有这个概念，选了也会被忽略（结果里会注明）。
    priority: CatchmentPriority | None = None
    #: 二维演算的积水量时程 —— **第一道防线的唯一数据源**。None = 这个点没跑过
    #: 二维演算，三道防线整块不出结论。见 `ponding_curve.py`。
    ponding: PondingCurve | None = None

    def __post_init__(self) -> None:
        if self.area_ha <= 0:
            raise ValueError(f"{self.hotspot_id}: 汇水面积必须为正，得到 {self.area_ha}")
        if not 0 < self.runoff_c <= 1:
            raise ValueError(f"{self.hotspot_id}: 径流系数 C 应在 (0, 1]，得到 {self.runoff_c}")
        if self.qcap_m3s < 0 or self.pond_available_m3 < 0:
            raise ValueError(f"{self.hotspot_id}: Qcap 与可用调蓄容量不能为负")
        if self.tc_min <= 0:
            raise ValueError(f"{self.hotspot_id}: 集流时间必须为正，得到 {self.tc_min}")

    @property
    def exceeds_rational_method_limit(self) -> bool:
        """汇水面积是否超出推理公式法的适用范围（§3.7 / ADQCC §3.4）。"""
        return self.area_ha > RATIONAL_METHOD_MAX_AREA_HA


@dataclass(frozen=True)
class ScenarioResult:
    """一个「积水点 × 重现期」组合的计算结果（对应 Scenario_Calc 一行）。"""

    hotspot_id: str
    return_period_yr: int
    dataset_key: str           #: 用的哪套 IDF —— 结果自描述，避免两套数字混淆
    duration_min: float        #: 实际采用的降雨历时
    tc_multiplier: float       #: 实际生效的 Table 3-3 乘数（迪拜恒为 1.0）
    intensity_mm_hr: float     #: I
    c_adjusted: float          #: C × Cf，上限截断 1.0（ADQCC 的 Cf 恒为 1.0）
    peak_flow_m3s: float       #: Q

    #: 三道防线共用的时限（小时），即 `Assumptions.drawdown_hours`。
    #: 结果自带这个值，导出的表才说得清「几小时内」。
    window_hours: float
    #: 判定口径，`hydrodynamic`（读二维演算时程）或 `peak`（原 Excel 峰值口径）。
    #: 结果自描述 —— 两套数字差一个量级，混在一起没法看。
    defence_basis: str
    #: 第一道防线这一点实际走了哪条路，**三个值**：
    #: `hydrodynamic` 读到了二维时程 / `peak` 原 Excel 口径 /
    #: `uncalibrated` 没跑过二维演算，三道防线不出结论（以下各量为 None）。
    l1_basis: str
    #: 要处理的**总**水量。`hydrodynamic` 口径下 = 演算**全程**净入流量
    #: （Σ 正 ΔV，不掐在 T 上 —— T 是工期不是观测窗口）；
    #: `peak` 口径下 = V_in = Q × 历时 × 形状系数。无标定时为 None。
    #: 三道防线分担的就是这个量：总量 = 第一道 + 第二道 + 第三道。
    runoff_volume_m3: float | None

    # —— 第一道：管网这条腿在时限 T 内能分担掉多少 ——
    #: 第一道的战果 = min(总量, `mean_drain_rate_m3h` × T)。
    #: ⚠ 速率是**地表净退水**实测值，管网 + 下渗 + 概化排水项混在一起，严格说
    #: 不止「管网排走」；但它与第三道的泵是并联的两条出路，故按能力计入。
    #: ⚠ 取的是**整个退水期的平均**，不是最大帧降幅 —— 后者高估 1.9–8.1 倍，
    #: 已于 2026-09-21 回退，见 evaluate() 里的注释。
    network_drained_m3: float | None
    #: R1 = max(0, 总量 − 第一道)，T 内管网清不掉、要往下交的量。
    #: ⚠ 这是**算出来的残量**，不是演算实测的 V(T)（那是旧口径，两者不等）。
    residual_after_network_m3: float | None
    #: 退到 <0.01 m 的实测时刻（小时），**自演算 t=0 起算**。
    #: None = 演算到结束仍未退干，或无标定。
    #: ⚠ 这是**实测退水时刻**，不是 Qcap 推出来的排空时间。
    #: ⚠ 要和第一道并排比的是 `recession_hours` 而不是它 —— 一道的窗口从峰值
    #: 起算，这一列还含着涨水期（ADM-379：绝对 16.75 h / 峰后 13.75 h）。页面
    #: 上把两个口径并排放，正是用户 2026-09-21 提出「一道算错了」的直接诱因。
    drain_hours: float | None
    #: **峰值之后**还要多久退干（小时）—— 与第一道同起点，可直接比。
    recession_hours: float | None
    cleared_by_network: bool | None         #: 第一道成立 —— R1 = 0

    # —— 第二道：现有调蓄 ——
    required_storage_m3: float | None       #: R1 × 淤积裕量，需要调蓄承接的量
    storage_used_m3: float | None           #: 可用调蓄实际吃下的量
    cleared_by_storage: bool | None         #: 第二道成立 —— 前两道合起来清零

    # —— 第三道：移动排水设备（泵 → 罐车 串联的一条链）——
    #: R2，还要靠「泵 + 罐车」这条链在同一时限内清掉的量
    shortfall_m3: float | None
    pumping_rate_m3hr: float | None         #: R2 / T，两侧**各自**都要达到的速率
    pumps_required: int | None              #: 派车总台数 = 各档之和
    #: 分档派车结果（12″ / 8″ / 6″ 各几台）—— 采购论证要的是这个，不是总数
    pump_dispatch: PumpDispatch | None
    tanker_loads: int | None                #: 车次 = ⌈R2 / 单车容量⌉，**不含时限**
    #: 时限 T 内**一辆**罐车能跑几趟 = ⌊T×60 / 周转时间⌋。0 = 周转比时限还长。
    tanker_trips_per_vehicle: int | None
    #: 需要多少**辆**罐车 = ⌈车次 / 每辆趟数⌉。
    #: ⚠ 与 `pumps_required` 是**同时都要**的一对，不是二选一 —— 泵抽出来的水
    #: 得有车拉走。**None = 每辆跑不满一趟，整条链在这个时限下不成立**，不是 0。
    tankers_required: int | None
    #: 喂饱 `pumps_required` 台泵需要几辆罐车 = 台数 × `tankers_per_pump`。
    #: 与 `tankers_required`（按水量算）取大的那个才是真正要配的车数。
    tankers_to_feed_pumps: int | None

    # —— 第三道：页面配置的车队「够不够」——
    # 上面几个量回答「T 内清完**该配**多少泵、多少车」；下面几个回答「**已配**
    # 的这套够不够、要多久、卡在哪一侧」。两个问题的答案并列摆着，差额就是缺口。
    pumps_configured: int | None            #: 这个点配了几台泵（`pumps_per_point`）
    tankers_configured: int | None          #: 这个点配了几辆车（`tankers_per_point`）
    pump_configured_m3hr: float | None      #: 泵侧 = 台数 × 单泵抽排能力
    tanker_configured_m3hr: float | None    #: 罐车侧 = 辆数 × 单车持续外运能力
    #: **这条链实际的外运能力 = 两侧取小。** 这才是这个点每小时真能走掉的水量。
    chain_configured_m3hr: float | None
    #: 链卡在哪一侧：``"pump"`` / ``"tanker"`` / ``"balanced"``。
    #: 卡在 `tanker` 时加泵无用 —— 那是本模型默认参数下的常态。
    chain_bottleneck: str | None
    #: 按链的外运能力把 R2 清完实际要多久（小时）。R2 = 0 时为 0。
    #: ⚠ 用罐车的**持续**外运能力算，不含「半趟不算」的取整损失。
    chain_hours_required: float | None
    #: 时限 T 内这条链**运不走**、留在地面的量（m³）。0 = 这个配置够用。
    #: ⚠ 罐车侧按**整趟**计：跑不满一趟的车在 T 内一滴水也运不走。
    chain_residual_m3: float | None

    # —— 峰值口径的诊断量（不参与防线归类）——
    #: Q_excess = max(0, Q − Qcap)，峰值时刻的超量流量。**这是 Qcap 仅存的用途**：
    #: 回答「地面会不会积起来」，不回答「多久排得完」。
    excess_flow_m3s: float
    flood_volume_m3: float     #: 峰值口径积水体积 = Q_excess × 历时 × 形状系数

    # —— 二维演算的原始量（只有 `hydrodynamic` 口径有，供页面解释 R1 的来历）——
    ponding_peak_m3: float | None = None        #: 全程瞬时峰值，含过路水，偏大
    ponding_peak_time_min: float | None = None  #: 峰值时刻；晚于 T 时 notes 会说明
    ponding_net_inflow_m3: float | None = None  #: 全程 Σ 正 ΔV，一共积了多少水
    #: 归属口径：点内 / 汇流 / 坡面直排。**`坡面直排` 的量是下限**，页面必须显示。
    ponding_attribution: str | None = None
    ponding_run_id: str | None = None           #: 哪一场演算算出来的
    #: 那一场演算的重现期。⚠ 与本结果的 `return_period_yr` **不一定相同** ——
    #: 不同就说明「这个点有演算，但不是这场雨」，此时 `l1_basis` 是
    #: `uncalibrated`，而这两个字段仍然带出来，页面据此把「没跑过演算」和
    #: 「跑的是另一场雨」说成两件事。
    ponding_run_rp_yr: int | None = None

    notes: tuple[str, ...] = field(default=())

    @property
    def peak_exceeds_capacity(self) -> bool:
        """峰值流量是否超过管网能力 —— 超了地面就会积起来，哪怕 T 内能排完。"""
        return self.excess_flow_m3s > 0

    @property
    def is_calibrated(self) -> bool:
        """三道防线出不出得了结论 —— 没跑过二维演算的点出不了。"""
        return self.l1_basis != "uncalibrated"

    @property
    def configured_fleet_suffice(self) -> bool | None:
        """页面上配的那套「N 台泵 + M 辆罐车」，够不够在时限 T 内把 R2 清完。

        看的是整条链，不是单看泵 —— 车不够时泵在等车，照样清不完。

        **None = 这个点没跑过二维演算，不出结论** —— 与 `defence_line` 同一口径。
        """
        return None if self.chain_residual_m3 is None else self.chain_residual_m3 <= 0

    @property
    def defence_line(self) -> int | None:
        """1 = T 内地面的水退完；2 = 加上调蓄排完；3 = 还要出动移动泵。

        **None = 这个点没跑过二维演算，不出结论** —— 调用方必须显式处理这一档，
        不能当 0 或 3 用。理由见模块头注释「没跑过二维演算的点不出结论」。
        """
        if not self.is_calibrated:
            return None
        if self.cleared_by_network:
            return 1
        return 2 if self.cleared_by_storage else 3


def evaluate(
    hotspot: Hotspot,
    return_period_yr: int,
    assumptions: Assumptions = DEFAULT_ASSUMPTIONS,
    dataset: IdfDataset | str | None = None,
) -> ScenarioResult:
    """跑完一个点的计算链，返回三道防线各自的结论。

    时限 T 取 `assumptions.drawdown_hours`，**三道防线共用，且是「工期」不是
    「观测时刻」**：总积水量要在 T 内清完，管网（第一道）与移动泵（第三道）是
    并联的两条出路，在同一个 T 内各排各的，故第三道 = 总量 − 第一道 × T。

    ⚠ `hydrodynamic` 口径下没有 `hotspot.ponding` 的点**不出结论**：
    `l1_basis` 记 `uncalibrated`，三道防线各量为 None，`defence_line` 为 None。
    峰值诊断量（`peak_flow_m3s` / `excess_flow_m3s`）照常给 —— 那部分不依赖
    二维演算。调用方必须显式处理无结论这一档，见模块头注释。

    Args:
        dataset: IDF 数据集，可传实例或 key。None 取默认（ADQCC Zone B）。
    """
    idf = dataset if isinstance(dataset, IdfDataset) else get_dataset(dataset)
    notes: list[str] = []

    # 步骤 1–2：历时与降雨强度。
    # 两件事由数据集一起决定：迪拜向下取档后档位即历时；ADQCC 的历时是 tc × M。
    if hotspot.priority is None:
        multiplier = 1.0
    elif idf.supports_tc_multiplier:
        multiplier = hotspot.priority.tc_multiplier
    else:
        multiplier = 1.0
        notes.append(
            f"{idf.label} 没有设计历时乘数这一概念，已忽略优先级"
            f"「{hotspot.priority.label}」。"
        )

    lookup = idf.intensity(return_period_yr, hotspot.tc_min, multiplier)

    # 步骤 3：峰值流量。推理公式 Q = C·i·A/360（ADQCC 写作 2.77e-3·C·i·A，等价）
    c_adj = min(hotspot.runoff_c * idf.runoff_adjustment_factor(return_period_yr), 1.0)
    peak_flow = c_adj * lookup.intensity_mm_hr * hotspot.area_ha / 360.0

    duration_s = lookup.duration_min * 60.0
    window_h = assumptions.drawdown_hours

    # 峰值口径的诊断量：地面会不会积起来 —— 与「T 内排不排得完」是两回事。
    # ⚠ 这是 Qcap 仅存的用途，它不再进下面任何一道防线的水量平衡。
    excess_flow = max(0.0, peak_flow - hotspot.qcap_m3s)
    flood_volume = excess_flow * duration_s * assumptions.shape_factor

    #: 原始曲线的出处，**重现期对不上时也要带出来** —— 页面要区分「没跑过演算」
    #: 与「跑的是另一场雨」，两者的补救动作不一样。
    run_id = hotspot.ponding.run_id if hotspot.ponding else None
    run_rp = hotspot.ponding.return_period_yr if hotspot.ponding else None

    curve = hotspot.ponding
    # ⚠ 演算是按某一场雨跑的，**重现期对不上就不能采信**。当前只有 RP100 一个
    # run，页面选 25 年时把 RP100 的积水量拿来当 RP25 的用，就是一种外推 ——
    # 和「没跑过演算的点不外推」是同一条规矩，这里一并挡住。
    storm_mismatch = (
        curve is not None
        and curve.return_period_yr is not None
        and curve.return_period_yr != return_period_yr
    )
    if storm_mismatch:
        notes.append(
            f"本点的二维演算是 {curve.return_period_yr} 年一遇那一场（run "
            f"{curve.run_id}），与所选的 {return_period_yr} 年一遇不是同一场雨，"
            "第一道防线不出结论。"
        )
        curve = None

    # 第一道防线。两个口径回答的是两个问题，见 `Assumptions.defence_basis`。
    if assumptions.defence_basis == "peak":
        # 原 Excel 口径：只看峰值时刻的超量流量，不给管网在降雨结束后继续排水
        # 的时间。保留它是为了复现原 Excel（见 tests/test_rational.py）。
        runoff_volume = peak_flow * duration_s * assumptions.shape_factor
        residual = flood_volume
        network_drained = runoff_volume - residual
        drain_hours = None
        recession_hours = None
        l1_basis = "peak"
    elif curve is None:
        # 没跑过二维演算 —— 三道防线整块不出结论。不回退到旧公式，也不外推。
        return ScenarioResult(
            hotspot_id=hotspot.hotspot_id,
            return_period_yr=return_period_yr,
            dataset_key=idf.key,
            duration_min=lookup.duration_min,
            tc_multiplier=multiplier,
            intensity_mm_hr=lookup.intensity_mm_hr,
            c_adjusted=c_adj,
            peak_flow_m3s=peak_flow,
            window_hours=window_h,
            defence_basis=assumptions.defence_basis,
            l1_basis="uncalibrated",
            runoff_volume_m3=None,
            network_drained_m3=None,
            residual_after_network_m3=None,
            drain_hours=None,
            recession_hours=None,
            cleared_by_network=None,
            required_storage_m3=None,
            storage_used_m3=None,
            cleared_by_storage=None,
            shortfall_m3=None,
            pumping_rate_m3hr=None,
            pumps_required=None,
            pump_dispatch=None,
            tanker_loads=None,
            tanker_trips_per_vehicle=None,
            tankers_required=None,
            tankers_to_feed_pumps=None,
            pumps_configured=None,
            tankers_configured=None,
            pump_configured_m3hr=None,
            tanker_configured_m3hr=None,
            chain_configured_m3hr=None,
            chain_bottleneck=None,
            chain_hours_required=None,
            chain_residual_m3=None,
            excess_flow_m3s=excess_flow,
            flood_volume_m3=flood_volume,
            ponding_run_id=run_id,
            ponding_run_rp_yr=run_rp,
            notes=tuple(
                notes
                + ([] if storm_mismatch else [
                    "本点没有二维水动力演算覆盖，三道防线不出结论 —— "
                    "积水量无从得知，光有管网能力 Qcap 算不出第三道要排多少。"
                ])
            ),
        )
    else:
        #
        # 水动力口径。总量取**全程**净入流 `curve.net_inflow_m3`（Σ 正 ΔV），
        # 不是 V(T) —— T 是工期，不是观测窗口，水在 T 之后照样接着涨。
        # ADM-377 峰值落在 t=180 min，掐在 T=2 h 会漏掉 1,683 m³（19%）。
        # 取净入流而非峰值 `peak_m3`，是为了双峰过程不漏掉第二次上涨，
        # 两者在单峰点上相等，见 `ponding_batch.py` 模块头。
        #
        # ⚠ **Qcap 不进这里，`Qcap × T` 更不进** —— 换成「T = 工期」的读法
        #   之后这条依然成立，而且更明显了。曾经被改成
        #   `min(V_in, max(Qcap×T, drained))`，被这些实测挡回来：
        #   ① corr(Qcap, 实测排空速率) = **−0.156**，方向是反的。极端例子
        #      ADM-376 的 Qcap 2.092 m³/s 是这批点最高，实测速率 0.011 m³/s；
        #      ADM-380 的 Qcap 只有 0.430，实测速率 0.253。
        #   ② 代进第一道会让 **112/123 个有演算的点（91%）泵需求归零** ——
        #      而这批点演算实测要 10 多小时才退干（MDL-078 是 14.75 h）。
        #      Qcap 说 MDL-078 的 783 m³ 靠重力 21 分钟走光，直接推翻演算。
        #   ③ 该 run 的耦合是 one_way_swmm_to_anuga，注到地面的正是节点溢流
        #      —— 积水期管网是**源不是汇**。
        #   Qcap 只保留为峰值诊断量（`excess_flow_m3s`，Q > Qcap → 地面会积
        #   起来），那是它唯一站得住的用法。
        #
        runoff_volume = curve.net_inflow_m3
        #
        # 第一道 = **平均**退水速率 × T。**T 是「工期」不是「观测时刻」。**
        #
        # 问的是「这些水要在 T 内清完，重力自排这条腿在 T 内能分担多少」，自排
        # 与第三道的泵是**并联的两条出路**、同一个 T 内各排各的，故这里做减法。
        # 旧口径把 T 读作观测时刻、直接取 V(T) 当残量，问的是另一个问题。
        #
        # ⚠ 速率取 `curve.mean_drain_rate_m3h` = 峰后累计退水 ÷ 峰后退水期时长。
        #   **不要换回另外两个** —— 这一行走过两遍坑：
        #   ① `qcap_m3s`：会让 112/123 个点泵需求归零（详见下面 Qcap 那段）。
        #   ② `drain_rate_m3h`（2026-09-21 回退）：那是曲线上**最陡的那一帧**的
        #      瞬时降幅。真实退水是衰减的，按它恒排，123 个点排完全量所需时间比
        #      演算实测退干时间短 **1.9–8.1 倍（中位 3.7），无一例外**。用户是在
        #      ADM-379 上抓到的：页面同时写着「一道 2 h 排走 3,684 m³」和「实测
        #      退干需 16.8 h」，两个数来自互不相干的读法。更糟的是那个 R_max 出现
        #      在 t=210–225 min，落在 T=2h 窗口**之外**，而 0–120 min 内该点的水
        #      还在涨、实测退水是 0。换平均后该点是 410 m³/h → 一道 820 m³。
        #   平均口径偏保守（峰值段真实退得比平均快），方向是第一道记少、泵记多，
        #   用的时候要知道这个方向。口径细节见
        #   `ponding_curve.PondingCurve.mean_drain_rate_m3h` 的注释。
        #
        # ⚠ 仍有一处口径张力，改之前先读懂：`runoff_volume` 是演算 V(t) 的净
        #   入流，而 V(t) 本身是「进 − 出」的净值，**上涨期已经扣过一次管网
        #   排水**；这里再减一次 R×T，管网那条腿被记了两遍，方向是把第三道的
        #   泵记少。要解掉它得从 `.sww` 的 xmomentum/ymomentum 算毛通量，存量
        #   外推站不住（全区口径高估 51%），复盘见 `ponding_batch` 模块头。
        drain_rate = curve.mean_drain_rate_m3h
        network_drained = min(runoff_volume, drain_rate * window_h)
        residual = max(0.0, runoff_volume - network_drained)
        drain_hours = curve.drain_min / 60.0 if curve.drain_min is not None else None
        # 与第一道**可比**的那个退干时间：一道的窗口从峰值起算，所以并排要看
        # 峰后还要多久（ADM-379 绝对 16.75 h / 峰后 13.75 h）。`drain_hours`
        # 保持绝对时刻不动 —— 报表里那一列是曲线事实，换语义会静默改数。
        recession_hours = curve.recession_hours
        l1_basis = "hydrodynamic"
        if drain_rate <= 0.0 and runoff_volume > 0.0:
            notes.append(
                "演算全程没有退水段 —— 重力自排无出路，第一道防线排水量为 0，"
                "积水全额交给第三道。"
            )
        if curve.peak_time_min is not None and curve.peak_time_min > window_h * 60.0:
            # 总量已按全程取，故这里**不再**是「结论偏低」的警告，而是作业
            # 时序的提醒：T 一到水还在涨，那时地面上并没有这么多水，剩下的是
            # T 之后才到的 —— 设备要按全程量配，但排水作业必然跨出时限。
            notes.append(
                f"峰值积水出现在 t={curve.peak_time_min:g} min，晚于时限 "
                f"{window_h:g} h —— 总量按全程 {runoff_volume:,.0f} m³ 计，"
                f"但时限一到地面上只有 {curve.state_at(window_h * 60.0).residual_m3:,.0f} m³，"
                f"其余是 T 之后才到的水：设备按全程量配，作业跨出时限。"
            )
        if curve.drain_min is None:
            notes.append("演算到结束仍未退干 —— 重力自排无出路，须泵排收尾。")
        if curve.is_overland:
            notes.append(
                "归属口径为「坡面直排」：本点未挂上任何地形洼地，积水量只是"
                "所在格的水量，是下限而非该点实际积水量。"
            )

    # 第二道防线：第一道之后还留在地面的水交给现有调蓄（淤积裕量在此计入）。
    required_storage = residual * assumptions.sed_factor
    storage_used = min(hotspot.pond_available_m3, required_storage)

    # 第三道防线：剩下的要「移动泵 → 罐车」这条链在**同一个** T 小时内清完。
    # ⚠ 泵与罐车**串联**，不是二选一：泵把水抽进罐车，罐车拉走再回来。两侧都
    #   得达到 R2/T 才算清得完，所以下面两组数是**同时都要**的一对。
    shortfall = max(0.0, required_storage - hotspot.pond_available_m3)
    pumping_rate = shortfall / window_h
    pumps = dispatch_pumps(
        pumping_rate,
        assumptions.effective_tiers,
        assumptions.pump_duty_factor,
        assumptions.pump_availability,
    )
    tankers = ceil(shortfall / assumptions.tanker_capacity)

    # 车次 → 辆数：泵是连续流量，T 乘一下就是运力；罐车是离散往返，得先知道
    # 一辆车在 T 内跑得完几趟。跑不满一趟就**不出辆数**（None），不是 0 辆 ——
    # 0 会被读成「不需要罐车」，而实际含义是「这个时限下水根本运不走」。
    trips_per_vehicle = assumptions.tanker_trips_within(window_h)
    if not tankers:                     # R2 = 0，不用出车
        tankers_needed = 0
    elif trips_per_vehicle >= 1:
        tankers_needed = ceil(tankers / trips_per_vehicle)
    else:
        tankers_needed = None
        notes.append(
            f"罐车往返周转 {assumptions.tanker_turnaround_min:g} min 长于时限 "
            f"{window_h:g} h —— 一辆车在时限内连一趟都跑不完。泵抽出来的水没车"
            f"拉走，第三道防线在这个时限下整条不成立（加车也没用，卡的是时延"
            f"不是运力）。要么放宽时限，要么把受纳点设得更近。"
        )

    # 按水量算出来的车数不一定喂得饱按水量算出来的泵数 —— 两个数都要，取大的。
    tankers_to_feed = pumps.total_units * assumptions.tankers_per_pump
    if tankers_needed is not None and tankers_to_feed > tankers_needed and shortfall > 0:
        notes.append(
            f"按水量算需 {tankers_needed} 辆罐车，但要喂饱 {pumps.total_units} 台泵"
            f"（每台配 {assumptions.tankers_per_pump} 辆）需 {tankers_to_feed} 辆 —— "
            f"取大的那个：少于 {tankers_to_feed} 辆时泵在等车，抽排能力用不满。"
        )

    # 同一个第三道，换一个问法：页面上给这个点配了 N 台泵 + M 辆罐车，
    # 这套配置在时限 T 内清得完吗、清不完还差多少、真要清完得几小时、卡在哪侧。
    # ⚠ 与上面那组「该配多少」**并列**，不是它的替代；两组的差才是缺口。
    configured_units = assumptions.pumps_per_point
    configured_tankers = assumptions.tankers_per_point
    pump_rate = assumptions.pump_configured_m3hr
    tanker_rate = assumptions.tanker_configured_m3hr
    chain_rate = assumptions.chain_configured_m3hr      # 串联取小
    bottleneck = assumptions.chain_bottleneck
    chain_hours = shortfall / chain_rate if chain_rate > 0 else None

    # 时限内实际清得掉多少：泵侧按连续流量（速率 × T），罐车侧按**整趟**计
    # （半趟在 T 内没送到，不算数），再取小。两侧取整口径不同是故意的。
    pump_volume_in_window = pump_rate * window_h
    tanker_volume_in_window = (
        configured_tankers * trips_per_vehicle * assumptions.tanker_capacity
    )
    chain_volume_in_window = min(pump_volume_in_window, tanker_volume_in_window)
    chain_residual = max(0.0, shortfall - chain_volume_in_window)
    if chain_residual > 0:
        _side = {
            "tanker": f"卡在罐车侧（{configured_tankers} 辆 × "
                      f"{assumptions.tanker_vehicle_rate_m3hr:,.0f} m³/h/辆）—— 加泵无用，"
                      f"要喂饱 {configured_units} 台泵得配 "
                      f"{configured_units * assumptions.tankers_per_pump} 辆",
            "pump": f"卡在泵侧（{configured_units} 台 × "
                    f"{assumptions.pump_unit_capacity:,.0f} m³/h）",
            "balanced": "两侧刚好配平",
        }[bottleneck]
        notes.append(
            f"按当前配置（每点 {configured_units} 台泵 + {configured_tankers} 辆罐车，"
            f"链的外运能力 {chain_rate:,.0f} m³/h，{_side}），{window_h:g} h 内清不完："
            f"还差 {chain_residual:,.0f} m³，清完要 {chain_hours:,.1f} h。"
            f"要在 {window_h:g} h 内清完须配 {pumps.total_units} 台泵 + "
            + (f"{max(tankers_needed, tankers_to_feed)} 辆罐车。"
               if tankers_needed is not None else "足够的罐车（当前时限下辆数不出数）。")
        )

    return ScenarioResult(
        hotspot_id=hotspot.hotspot_id,
        return_period_yr=return_period_yr,
        dataset_key=idf.key,
        duration_min=lookup.duration_min,
        tc_multiplier=multiplier,
        intensity_mm_hr=lookup.intensity_mm_hr,
        c_adjusted=c_adj,
        peak_flow_m3s=peak_flow,
        window_hours=window_h,
        defence_basis=assumptions.defence_basis,
        l1_basis=l1_basis,
        runoff_volume_m3=runoff_volume,
        network_drained_m3=network_drained,
        residual_after_network_m3=residual,
        drain_hours=drain_hours,
        recession_hours=recession_hours,
        cleared_by_network=residual <= 0,
        required_storage_m3=required_storage,
        storage_used_m3=storage_used,
        cleared_by_storage=shortfall <= 0,
        shortfall_m3=shortfall,
        pumping_rate_m3hr=pumping_rate,
        pumps_required=pumps.total_units,
        pump_dispatch=pumps,
        tanker_loads=tankers,
        tanker_trips_per_vehicle=trips_per_vehicle,
        tankers_required=tankers_needed,
        tankers_to_feed_pumps=tankers_to_feed,
        pumps_configured=configured_units,
        tankers_configured=configured_tankers,
        pump_configured_m3hr=pump_rate,
        tanker_configured_m3hr=tanker_rate,
        chain_configured_m3hr=chain_rate,
        chain_bottleneck=bottleneck,
        chain_hours_required=chain_hours,
        chain_residual_m3=chain_residual,
        excess_flow_m3s=excess_flow,
        flood_volume_m3=flood_volume,
        ponding_peak_m3=curve.peak_m3 if curve else None,
        ponding_peak_time_min=curve.peak_time_min if curve else None,
        ponding_net_inflow_m3=curve.net_inflow_m3 if curve else None,
        ponding_attribution=curve.attribution_basis if curve else None,
        ponding_run_id=run_id,
        ponding_run_rp_yr=run_rp,
        notes=tuple(notes),
    )


def evaluate_all(
    hotspot: Hotspot,
    return_periods: tuple[int, ...] = FLEET_RETURN_PERIODS,
    assumptions: Assumptions = DEFAULT_ASSUMPTIONS,
    dataset: IdfDataset | str | None = None,
) -> list[ScenarioResult]:
    """对一个积水点跑全部重现期。

    数据集不支持的重现期会被跳过（例如 ADQCC 没有 20 年一遇）。
    """
    idf = dataset if isinstance(dataset, IdfDataset) else get_dataset(dataset)
    return [
        evaluate(hotspot, rp, assumptions, idf)
        for rp in return_periods
        if rp in idf.return_periods
    ]


def compare_datasets(
    hotspot: Hotspot,
    return_periods: tuple[int, ...] = FLEET_RETURN_PERIODS,
    assumptions: Assumptions = DEFAULT_ASSUMPTIONS,
    dataset_keys: tuple[str, ...] = (DEFAULT_DATASET_KEY, "dubai_dm"),
) -> dict[str, list[ScenarioResult]]:
    """同一个点跑多套 IDF，供页面并排对照。"""
    return {
        key: evaluate_all(hotspot, return_periods, assumptions, key)
        for key in dataset_keys
    }


def fleet_summary(results: list[ScenarioResult]) -> dict[int, dict]:
    """按重现期汇总全网车队需求（对应 Fleet_Summary 工作表）。

    `pumps_by_tier` 是各口径档的台数合计，`pumps_required` 是它们的和 ——
    这一组连同 `tankers_required` 是「该配多少泵、多少车」（两者**同时都要**，
    泵抽进车、车拉走）。另一组 `pumps_configured` / `tankers_configured` /
    `chain_residual_m3` / `points_under_served` 是「页面已配的那套够不够」，
    两组并列不可相加。

    ⚠ **无标定的结果整条跳过**，不是补 0。某个重现期一条都没有时，汇总里
    干脆没有那个 key —— 调用方据此显示「该档没出结论」，而不是「该档不需要泵」。
    """
    summary: dict[int, dict] = {}
    for r in results:
        # 无标定的结果没有车队数字，跳过 —— 它们在这里补 0 会让车队总数
        # 看起来比实际小（少算的正是没算的那部分）。
        if not r.is_calibrated:
            continue
        bucket = summary.setdefault(
            r.return_period_yr,
            {"hotspots": 0, "required_storage_m3": 0.0, "shortfall_m3": 0.0,
             "pumps_required": 0, "pumps_by_tier": {}, "tanker_loads": 0,
             "tankers_required": 0, "points_tanker_infeasible": 0,
             "tankers_to_feed_pumps": 0,
             "pumps_configured": 0, "tankers_configured": 0,
             "chain_residual_m3": 0.0, "points_under_served": 0,
             "points_tanker_bound": 0},
        )
        bucket["hotspots"] += 1
        bucket["required_storage_m3"] += r.required_storage_m3
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
        # 清不完且卡在罐车侧的点 —— 这些点加泵一滴水也多排不出去。
        if not r.configured_fleet_suffice and r.chain_bottleneck == "tanker":
            bucket["points_tanker_bound"] += 1
    return summary


def with_qcap(hotspot: Hotspot, qcap_m3s: float) -> Hotspot:
    """替换 Qcap 生成新的积水点 —— 用于批量回填数据库算出的逐点 Qcap。"""
    return replace(hotspot, qcap_m3s=qcap_m3s)
