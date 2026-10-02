"""移动泵车的分档额定排量与派车逻辑（对应 DMT 数据需求清单 §02）。

原模型对全部 845 个点统一假设单泵 300 m³/h，**该值无出处**。本模块把它换成
按口径分档的排量表，并按「最少台数、同台数下最小冗余」派车，使结论落在
「12″ / 8″ / 6″ 各需多少台」上 —— 这才是能和在册构成 144 / 121 / 579 对照、
支撑采购论证的形式。

⚠ 表里的排量仍**不是 DMT 实测值**，是厂商铭牌值经两级折减得到的暂定值：

  额定排量 = 铭牌最大流量 × 工况折减 × 出勤占空

  * 铭牌最大流量取 Xylem Godwin CD 系列（市政移动柴油自吸泵的事实基准），
    是近零扬程下的最大流量，**不能直接用**；
  * 工况折减 0.65 —— 城市积水抽排的实际工况：吸程 2–4 m + 100–300 m 层流
    软管沿程损失，TDH 落在 10–20 m，离心泵在该点约为最大流量的 55–75%；
  * 出勤占空 0.85 —— 加油、转场、清堵、滤网堵塞占用的时间。

  DMT 给出现场工作扬程下的实测排量后，填进对应档的 ``measured_m3hr``，
  该档即绕过上面两级折减（见 ``PumpTier.rated_m3hr``）。

一个旁证：按在册构成加权平均得约 320 m³/h，与原假设的 300 只差 7%。
即**总台数量级站得住**，分档真正改变的是需求的构成，不是总量。

## 分档表现在是参考，不是默认口径

页面上要能自定义「每个积水点配几台泵、单泵抽多少」，故默认走
``uniform_tier(Assumptions.pump_capacity)`` 的**单档配置式**：全部点按同一个
操作员设定的排量算，每点配 ``Assumptions.pumps_per_point`` 台（默认 1 台）。
本模块的三档表退为**选那个值时的参照物**（在册 144 / 121 / 579 台，折减后
751 / 287 / 221 m³/h），并在 ``Assumptions.pump_capacity`` 置空时重新接管派车 ——
分档派车的逻辑一行没删，它仍是回答「采购该买哪几档」时唯一说得清的口径。
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

#: 浮点容差 —— 排量以 m³/h 计，1e-9 远小于任何有意义的差异。
_EPS = 1e-9


@dataclass(frozen=True)
class PumpTier:
    """一个口径档的泵车参数。"""

    key: str                    #: 程序内标识，如 ``12in``
    #: 展示名。**写给不懂管径的调度与客户看**：通俗分级在前、口径在后，
    #: 如 ``大型泵(12吋)``。前端拼成「1 台大型泵(12吋)」，并跟上合计排量。
    label: str
    nameplate_m3hr: float       #: 厂商铭牌最大流量（近零扬程）
    fleet_qty: int              #: 阿布扎比市在册台数（三份台账口径）
    reference: str              #: 铭牌值出处
    #: DMT 提供的现场工作扬程下实测排量。填了就直接用，不再走两级折减。
    measured_m3hr: float | None = None
    #: 覆盖 `basis` 的人读说明。单档模式下排量是**操作员在页面上设的**，
    #: 既不是实测也不是铭牌折减，不写清楚会在报告里被当成实测值引用。
    basis_override: str | None = None

    def rated_m3hr(self, duty_factor: float, availability: float) -> float:
        """该档单台的额定排量（m³/h）。"""
        if self.measured_m3hr is not None:
            return self.measured_m3hr
        return self.nameplate_m3hr * duty_factor * availability

    @property
    def basis(self) -> str:
        """这一档的排量是实测、折减推算还是页面设定 —— 报告里要逐档标明。"""
        if self.basis_override:
            return self.basis_override
        return "实测" if self.measured_m3hr is not None else "铭牌折减"


#: 阿布扎比市在册移动泵车的三个口径档。在册台数取自三份 Hotspot Analysis 台账。
#: 铭牌值出处：Xylem Godwin CD 系列产品规格页（见 `reference`）。
DEFAULT_PUMP_TIERS: tuple[PumpTier, ...] = (
    PumpTier(
        key="12in", label="大型泵(12吋)", nameplate_m3hr=1360.0, fleet_qty=144,
        reference="Xylem Godwin CD300M，5,990 USgpm = 1,360 m³/h",
    ),
    PumpTier(
        key="8in", label="中型泵(8吋)", nameplate_m3hr=520.0, fleet_qty=121,
        reference="Xylem Godwin CD200M，2,290 USgpm = 520 m³/h",
    ),
    PumpTier(
        key="6in", label="小型泵(6吋)", nameplate_m3hr=400.0, fleet_qty=579,
        reference="Xylem Godwin CD150M，1,770 USgpm = 403 m³/h（取整 400）",
    ),
)

#: 工况折减与出勤占空的默认值 —— 见模块文档，二者都是**推算系数，不是实测**。
DEFAULT_DUTY_FACTOR = 0.65
DEFAULT_AVAILABILITY = 0.85

#: 每多派一台车的代价，按「一台最小档泵的额定排量」折算（见 `dispatch`）。
#: 1.0 表示多出一台车 ≈ 浪费一台小泵的运力；调大则更倾向少派车、容忍更大过配。
DISPATCH_UNIT_PENALTY = 1.0


#: 页面上「单泵抽排能力」的默认值（m³/h）。数值上等于 `LEGACY_PUMP_CAPACITY`
#: —— 原 Excel 对全车队统一假设的 300，而按在册构成加权平均是 321，两者只差 7%。
#: 即这个默认值**不是凭空拍的**：它落在在册车队的实际均值上。但它仍是**假设值**，
#: 正因如此才要摆在页面上让人改，而不是埋进计算里。
DEFAULT_PUMP_CAPACITY = 300.0


def uniform_tier(capacity_m3hr: float) -> PumpTier:
    """把「全车队一个排量」退化成单档表。

    这是**页面配置式的口径**：操作员在页面上给一个单泵抽排能力，全部积水点
    按这一个值算，不再按 12″/8″/6″ 分档派车。分档表退为参考（见
    `DEFAULT_PUMP_TIERS`），供选这个值时对照在册车队构成。

    `fleet_qty` 取三档在册合计 —— 单档口径下「在册有多少台移动泵」就是这一个数，
    拆不开，也不该假装拆得开。
    """
    return PumpTier(
        key="uniform", label="移动泵", nameplate_m3hr=capacity_m3hr,
        fleet_qty=sum(t.fleet_qty for t in DEFAULT_PUMP_TIERS),
        reference="页面设定的单泵抽排能力；在册台数取 12″/8″/6″ 三档合计",
        measured_m3hr=capacity_m3hr,
        basis_override="页面设定",
    )


@dataclass(frozen=True)
class PumpDispatch:
    """一个积水点的派车结果。"""

    #: (档 key, 台数)，按额定排量从大到小；台数为 0 的档不列。
    counts: tuple[tuple[str, int], ...]
    total_units: int            #: 总台数
    deployed_m3hr: float        #: 派出去的合计排量
    required_m3hr: float        #: 需要的排水速率

    def qty(self, tier_key: str) -> int:
        """某一档派了几台。"""
        return dict(self.counts).get(tier_key, 0)

    @property
    def spare_m3hr(self) -> float:
        """冗余排量 —— 取整到台带来的过配。"""
        return self.deployed_m3hr - self.required_m3hr

    @property
    def utilisation(self) -> float:
        """派出运力的利用率，1.0 为刚好配平。"""
        return self.required_m3hr / self.deployed_m3hr if self.deployed_m3hr else 0.0


def _min_total_with_units(required: float, caps: tuple[float, ...], units: int):
    """恰好派 `units` 台时，总排量 ≥ required 的**最小**总排量与各档台数。

    `caps` 必须按从大到小排好。无可行解返回 None。
    末两档用闭式解，故三档时整体是 O(units)，不是 O(units²)。
    """
    if units < 0:
        return None
    if len(caps) == 1:
        total = units * caps[0]
        return (total, (units,)) if total >= required - _EPS else None

    if len(caps) == 2:
        hi, lo = caps
        if hi - lo < _EPS:              # 两档排量相同，退化成单档
            total = units * hi
            return (total, (units, 0)) if total >= required - _EPS else None
        # n·hi + (units−n)·lo ≥ required  ⟹  n ≥ (required − units·lo) / (hi − lo)
        need = required - units * lo
        n = 0 if need <= _EPS else ceil(need / (hi - lo))
        if n > units:
            return None
        return (n * hi + (units - n) * lo, (n, units - n))

    best = None
    head, rest = caps[0], caps[1:]
    for n in range(units + 1):
        sub = _min_total_with_units(required - n * head, rest, units - n)
        if sub is None:
            continue
        total = n * head + sub[0]
        if best is None or total < best[0]:
            best = (total, (n,) + sub[1])
    return best


def dispatch(
    required_m3hr: float,
    tiers: tuple[PumpTier, ...] = DEFAULT_PUMP_TIERS,
    duty_factor: float = DEFAULT_DUTY_FACTOR,
    availability: float = DEFAULT_AVAILABILITY,
    unit_penalty: float = DISPATCH_UNIT_PENALTY,
) -> PumpDispatch:
    """给一个积水点派泵车：**在过配与出车数之间取折中的最优组合**。

    两个目标互相拉扯，单取一个都会出怪结果：

    * 只求最少台数 —— 300 m³/h 的小活会派一台 12″（751 m³/h，过配 150%），
      因为单台 8″ / 6″ 都不够。全网 845 个点这么派，会凭空造出大量 12″ 需求，
      而 12″ 恰恰是在册最少（144 台）、最重（约 4.5 t，需拖车）的稀缺资产。
    * 只求最小过配 —— 5,000 m³/h 的大活会派 23 台 6″，一个点摆二十多台车；
      1,000 m³/h 会为省 2% 运力多派两台车。

    故把两者折进同一个量纲：**车不是免费的，每多一台按一台最小档泵的运力计价**。
    在总排量不小于需求的组合里，取 ``总排量 + 台数 × 最小档排量`` 最小的那个：

    ==========  ====================  =========
    需求 m³/h   派车                  合计 m³/h
    ==========  ====================  =========
    50          1×6″                  221
    300         2×6″                  442
    600         1×12″                 751
    1,000       1×12″ + 1×8″          1,039
    5,000       6×12″ + 1×8″ + 1×6″   5,017
    ==========  ====================  =========

    ⚠ **不受在册台数约束** —— 本模型算的是需求侧，够不够由 `fleet_gap()` 对照。
      多点同时出动时全网某一档需求超过在册台数，正是要报出来的结论。

    ⚠ 总台数**不随排量单调变化**。排量整体下调时各档的相对位置会变，最优组合
      跟着重排：例如 400 m³/h 在默认表下是 2×6″（442），三档同比降到 2/3 后
      反而变成 1×12″（501）—— 一台车送 501 比三台车送 442 更划算，结论没错，
      但别拿总台数当排量的单调指标。看分档构成，不看总数。
    """
    if not tiers:
        raise ValueError("泵车分档表不能为空")
    if required_m3hr <= _EPS:
        return PumpDispatch(counts=(), total_units=0, deployed_m3hr=0.0,
                            required_m3hr=max(0.0, required_m3hr))

    ranked = sorted(tiers, key=lambda t: t.rated_m3hr(duty_factor, availability),
                    reverse=True)
    caps = tuple(t.rated_m3hr(duty_factor, availability) for t in ranked)
    if caps[0] <= _EPS:
        raise ValueError("泵车分档表里最大档的额定排量必须为正")

    penalty = max(_EPS, caps[-1] * unit_penalty)
    min_units = ceil(required_m3hr / caps[0])
    # 台数上界：再多派车，光罚项就已经超过 min_units 台方案的总代价了。
    max_units = min_units + ceil(caps[0] / penalty)

    best = None                         # (代价, 总排量, 各档台数)
    for units in range(min_units, max_units + 1):
        candidate = _min_total_with_units(required_m3hr, caps, units)
        if candidate is None:
            continue
        total, quantities = candidate
        cost = total + units * penalty
        if best is None or cost < best[0] - _EPS:
            best = (cost, total, quantities)
    if best is None:                    # 理论上不会发生：min_units 台最大档必然够
        best = (0.0, min_units * caps[0],
                (min_units,) + (0,) * (len(caps) - 1))

    _, total, quantities = best
    return PumpDispatch(
        counts=tuple((t.key, n) for t, n in zip(ranked, quantities) if n > 0),
        total_units=sum(quantities),
        deployed_m3hr=total,
        required_m3hr=required_m3hr,
    )


def fleet_weighted_capacity(
    tiers: tuple[PumpTier, ...] = DEFAULT_PUMP_TIERS,
    duty_factor: float = DEFAULT_DUTY_FACTOR,
    availability: float = DEFAULT_AVAILABILITY,
) -> float:
    """按在册台数加权的平均单泵排量 —— 只用于和旧的单一假设值对照，不参与派车。"""
    qty = sum(t.fleet_qty for t in tiers)
    if not qty:
        return 0.0
    return sum(
        t.fleet_qty * t.rated_m3hr(duty_factor, availability) for t in tiers
    ) / qty


def add_dispatch(tally: dict[str, int], result: PumpDispatch) -> dict[str, int]:
    """把一次派车结果累加进分档台数字典（原地改，并返回它）。"""
    for key, qty in result.counts:
        tally[key] = tally.get(key, 0) + qty
    return tally
