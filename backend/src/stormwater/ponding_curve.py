"""逐点积水量时程曲线 —— 第一道防线的**唯一**数据来源。

读 `ponding_batch.py` 产出的两个文件，把「这个点在 t 时刻地面上有多少水」
做成可查的曲线，供 `rational.evaluate()` 直接取用。本模块一个数都不推算，
只做插值与逐帧累加。

## 为什么第一道防线不再用 Qcap × T

原先第一道防线按「管网以满流能力 Qcap 恒排 T 小时」算水量，被三份成果同时
证伪。用 Al Bateen RP100 这一个 run 里 10 个积水量 ≥500 m³ 的点实测：

| 要预测的量 | 原先用的自变量 | 实测表现 |
|---|---|---|
| 这个点会积多少水 | 汇水面积 A（Voronoi 代理） | 实测/预测比值 0.00–8.29，跨三个量级 |
| 积了多久排得完 | Qcap（管段满流能力） | 与实际排空速率 corr = **−0.156** |

同一批点上，换成地形量就立刻对上了：

* `corr(洼地库容, 实测峰值积水) = +0.982`（n = 18）—— 积多少由地形洼地定；
* 等效排空时间常数落在 10.2–16.8 h，中位 **12.4 h**，10 个点全在一个窄带里，
  与各点 Qcap（0.397–2.092 m³/s，差 5 倍）无关 —— 多久排完也不由管网定。

极端例子：ADM-376 的 Qcap 2.092 m³/s 是这批点里最高的，实测排空速率
0.011 m³/s；ADM-380 的 Qcap 只有 0.430，实测速率 0.253。**方向是反的**。

一维成果给出同向的旁证：那份 SWMM 全城 run 在 RP100 下产流 6,336 ML，
排放口出流仅 34 ML，其余从检查井溢出 —— 而它的管道内底是「DEM 地面高程减
固定埋深 1.10 m」、坡度即地形坡度，满流能力比实测内底反算的还高 2.4 倍
（见 `swmm_batch.py`）。**比真实管网乐观得多的模型，都排不出去。**

结论：`Qcap` 退出第一道防线的水量平衡，只保留为峰值诊断量
（`peak_exceeds_capacity`，Q > Qcap → 地面会积起来）—— 这是它唯一站得住的
用法，也正是一维成果支持的那个定性结论。

⚠ 「三道防线同时工作，第三道不该接手全部存水」这个顾虑是对的，**减法现在
做了** —— 第一道 = `min(全程净入流, mean_drain_rate_m3h × T)`，T 读作工期，
R 取**整个退水期的平均退水速率**。走过两个错版本：`Qcap × T` 会让 91% 的点泵
需求归零（已回退）；`drain_rate_m3h × T` 拿**最陡一帧**的瞬时降幅当恒速，在
123 个点上系统性高估 1.9–8.1 倍（2026-09-21 回退）。完整复盘见
`rational.evaluate()` 水动力分支的注释与 `mean_drain_rate_m3h` 的属性注释。

## 覆盖不到的点不出结论

第一道防线现在只对**跑过二维演算**的点成立。当前只有 Al Bateen RP100 一个
run，845 点里 18 个（2.1%）。其余点 `curve_for()` 返回 None，
`rational.evaluate()` 据此把三道防线整块标成「无水动力标定」而**不出数**。

这是刻意的：外推需要逐点洼地库容，而全域只有 30.35 m 的 Copernicus GLO-30
DEM（`data/DEM_UAE_UTM40`），Al Bateen 的洼地面积在 0.04–6 ha、最小的只有
1–2 个 20 m 格，30 m 栅格分辨不出来。给个算不准的数，比不给更坏。

## 三个量怎么取

时限 T 上给出三个量，**水量账严格闭合**（`inflow = drained + residual`）：

* `inflow_m3`   —— Σ 正 ΔV 到 T 为止，「T 内一共积进来多少水」；
* `drained_m3`  —— Σ 负 ΔV 到 T 为止，「T 内已经退走多少」；
* `residual_m3` —— V(T)，「T 时刻地面上还剩多少」。

⚠ 总量走 `net_inflow_m3`（全程），第一道走 `mean_drain_rate_m3h × T`；后者的
分子是 `recession_total_m3`，而那是拿 `state_at()` 在峰值与退水期末各取一次
算出来的 —— 所以 `state_at()` **现在又回到了水量平衡的主链上**，改它会
动防线结论。`inflow_m3` / `residual_m3` 仍只服务于诊断文案（那句「时限一到
地面上只有 X m³」）。

⚠ 用 Σ 正 ΔV 而不是取峰值：Al Bateen 这场雨下 16 个有水的点里 15 个是单峰
过程，两者相等，但 ADM-398 在 t=180 min 有一次 +0.53 m³ 的回涨。量很小，
可换一场双峰的雨，取峰值就会整段漏掉第二次上涨。口径同 `ponding_batch.py`。

⚠ `drained_m3` 是**净退水**，不含上涨期的过路水。`ponding_batch.py` 试过把
那部分回算加上（线性水库 τ 落在 61–154 min，退水段拟合相关系数 −0.95~−1.00），
外推到上涨期站不住 —— 全区口径下算出的通过量比实际入流高 51%，因为上涨期水
摊在两倍面积上，大部分是过路水而非滞蓄。故这里也不回算。

## 三条跟着数字一起走的限制

* **`坡面直排` 的点只报本格水量**（Al Bateen 18 个里有 4 个）。它们没挂上任何
  洼地，积水量是**下限**，不是该点的实际积水量。`attribution_basis` 原样带出，
  页面必须显示。
* **20 m 网格把洼地并粗**。源数据是 5 m DTM，聚合后路缘、分隔带被抹平，相邻但
  实际隔开的积水坑会并成一个（洼地 5 含 5 个台账点）。逐点值只可用于筛查排序，
  不可作单点设计依据。
* **绝对量受上游耦合缺口拖累**。该 run 的 SWMM 注入实际只进了 123,263 m³，比
  预设的 288,838 m³ 少 165,575 m³（峰值蓄水量的 32%）。修好之前这批数只能用于
  相对排序与过程分析。

另：快照只存 ≥0.01 m 的格子，薄于 1 cm 的水被截掉 —— 这批量是「≥1 cm 的地表
滞蓄量」，与 run 自己的 `final_surface_volume_m3` 同口径，不是额外误差。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BACKEND_DIR / "data" / "processed"
HOTSPOT_PONDING_CSV = PROCESSED_DIR / "hotspot_ponding.csv"
HOTSPOT_PONDING_SERIES_CSV = PROCESSED_DIR / "hotspot_ponding_series.csv"

#: 模型识别片区那一套（`model_cluster_batch.py` 产出）。与台账那两份**同构**，
#: 故这里只是多读一对文件 —— 曲线的装配、插值、水量账一个字都不用改。
#:
#: 两套点的 uid 互不相交（片区是 `MDL-`），故可以并进同一张表：`curve_for()`
#: 不必知道调用方问的是哪一套。覆盖率差别很大，这正是要让人看见的：
#: 台账 845 点里只有 18 个跑过演算（2.1%），片区 107 个**全部**跑过（100%）——
#: 片区本来就是从这次演算里识别出来的。
MODEL_PONDING_CSV = PROCESSED_DIR / "model_cluster_ponding.csv"
MODEL_PONDING_SERIES_CSV = PROCESSED_DIR / "model_cluster_ponding_series.csv"

#: 归属口径里**只报本格水量**的那一档，见模块头注释。这批点的积水量是下限。
OVERLAND_BASIS = "坡面直排"


@dataclass(frozen=True)
class PondingState:
    """时限 T 上的三个量。恒满足 `inflow_m3 = drained_m3 + residual_m3`。"""

    inflow_m3: float        #: Σ 正 ΔV 到 T 为止 —— T 内一共积进来多少水
    drained_m3: float       #: Σ 负 ΔV 到 T 为止 —— T 内已经退走多少（诊断量）
    residual_m3: float      #: V(T) —— T 时刻地面上还剩多少（诊断量，不进水量平衡）


@dataclass(frozen=True)
class PondingCurve:
    """一个台账点在一场演算里的积水量时程。

    `samples` 是 (分钟, m³) 升序序列，**不含 t=0** —— 起点恒为 (0, 0)，由
    `state_at()` 隐式补上。全程无水的点 `samples` 为空元组，此时任何时刻的
    三个量都是 0：这是「演算说这里不积水」的正常结论，不是缺数据。
    """

    uid: str
    run_id: str
    return_period_yr: int | None
    attribution_basis: str | None    #: 点内 / 汇流 / 坡面直排，见模块头注释
    samples: tuple[tuple[float, float], ...]
    peak_m3: float                   #: 全程瞬时峰值，含过路水，系统性偏大
    peak_time_min: float | None
    net_inflow_m3: float             #: 全程 Σ 正 ΔV —— 这个点一共积了多少水
    settled_m3: float | None         #: t≥285 min 之后的峰值，可归属口径
    drain_min: float | None          #: 退到 <0.01 m 的时刻；None = 演算结束仍未退干
    depression_capacity_m3: float | None   #: 宿主洼地的静态库容，页面用来解释积水量

    @property
    def is_overland(self) -> bool:
        """积水量是否只是本格水量 —— 是的话这个数是**下限**。"""
        return self.attribution_basis == OVERLAND_BASIS

    @property
    def drain_rate_m3h(self) -> float:
        """峰值水头下的**瞬时**退水速率（m³/h）—— 诊断量，**不进水量平衡**。

        取全程相邻两帧之间**最大的**那一段降幅，即整条曲线退得最快的那一刻。

        ⚠ **2026-09-21 起不再用它算第一道防线**（换成 `mean_drain_rate_m3h`）。
        它是瞬时上限，乘以 T 当成恒速会系统性高估：按这个速率恒排，123 个有
        演算的点排完全量所需时间比演算实测的退干时间短 **1.9–8.1 倍**（中位
        3.7 倍），**无一例外**。ADM-379 是用户发现它的那个点 —— R_max =
        1,842 m³/h 出现在 t=210–225 min，按它恒排 3.06 h 就该干，演算实测
        16.75 h；更糟的是那一帧落在 T=2h 窗口**之外**，而 0–120 min 内该点
        的水还在涨、实测退水是 0，公式却记了管网已排 3,684 m³。

        真实退水是衰减的（线性水库拟合 τ 落在 61–228 min），所以任何「恒速
        × T」都得用**整个退水期的平均**，见 `mean_drain_rate_m3h`。

        ⚠ **不要换成 `qcap_batch.py` 的 `qcap_m3s`。** 那是管段满流能力，
        答的是「这根管满流时每秒能过多少水」，不是「地面的水能以多快进到管里」。
        两者在 123 个有演算的点上实测差到 28 倍（MDL-003：Qcap 76,569 m³/h，
        实测 2,693 m³/h），代进第一道会让 **112/123 个点（91%）泵需求归零** ——
        而这批点演算实测要 10 多小时才退干。corr(Qcap, 实测排空速率) = −0.156，
        方向还是反的。详见模块头注释。

        全程没有任何退水段（单调上涨到演算结束）时返回 0.0 —— 那是「重力自排
        无出路」的正常结论，第一道防线在这个点上颗粒无收。
        """
        best = 0.0
        for (t0, v0), (t1, v1) in zip(self.samples, self.samples[1:]):
            span_h = (t1 - t0) / 60.0
            if span_h <= 0:
                continue
            best = max(best, (v0 - v1) / span_h)
        return best

    @property
    def recession_total_m3(self) -> float:
        """峰值之后**一共要退掉多少水**（m³）—— `mean_drain_rate_m3h` 的分子。

            峰值时地面上的水 + 峰后又进来的水 − 退水期结束时还剩的水

        「峰后又进来的水」是为双峰过程留的（ADM-398 在 t=180 min 有一次回涨）；
        单峰点上这一项为 0。「还剩的水」只在**演算结束仍未退干**时才非零 ——
        退干了就是一滴不剩，`drain_min` 就是曲线自己报的那个时刻。

        ⚠ **不要改回「样本里看得见的退水」（Σ 负 ΔV）。** 时程只存 ≥1 cm 的水
        （口径限制见模块头），退得快的点整个退水段一帧都留不下：ADM-381 只有
        `((75 min, 6.82 m³),)` 这**一帧**，`drain_min = 90` —— 15 分钟内就退干
        了。按样本差分算，它的退水量是 0、速率是 0，于是被判成「重力自排无出路、
        6.82 m³ 全额上泵」，而事实恰恰相反：这是全批退得最快的点之一。这个错
        2026-09-21 由用户在 ADM-381 上发现（页面写「无排水管网」「一道 0 m³」，
        而管网库实测该点 11.9 m 外有管、Qcap = 0.397 m³/s）。

        同一个 bug 的轻症版覆盖 120/123 个点：末帧总还剩一点水才跌破 1 cm 阈值，
        那截尾巴合计 555 m³（占总量 0.2%），按样本差分同样漏掉。
        """
        if not self.samples:
            return 0.0
        peak_t = self.peak_time_min or 0.0
        at_peak = self.state_at(peak_t)
        end_t = self.drain_min if self.drain_min is not None else self.samples[-1][0]
        at_end = self.state_at(max(end_t, peak_t))
        later_inflow = max(0.0, at_end.inflow_m3 - at_peak.inflow_m3)
        # 退干了就一滴不剩；没退干，末帧那点残量本来就得靠泵收尾，不算进自排战果
        left = 0.0 if self.drain_min is not None else at_end.residual_m3
        return max(0.0, at_peak.residual_m3 + later_inflow - left)

    @property
    def recession_hours(self) -> float | None:
        """**峰值之后**退水期有多长（h）：到退干为止，没退干就到演算结束。

        与 `drain_min`（自演算 t=0 起算的绝对退干时刻）差一个峰值时刻。页面上
        要和第一道防线并排比的是这个数 —— 一道的窗口也是从峰值起算的。
        ADM-379：绝对 16.75 h，峰后 13.75 h。
        """
        if not self.samples:
            return None
        start = self.peak_time_min or 0.0
        end = self.drain_min if self.drain_min is not None else self.samples[-1][0]
        span = (end - start) / 60.0
        return span if span > 0.0 else None

    @property
    def mean_drain_rate_m3h(self) -> float:
        """**第一道防线的排水速率**：整个退水期的**平均**退水速率（m³/h）。

            R_avg = recession_total_m3 ÷ recession_hours

        分子是「峰后一共要退掉多少水」，分母是「峰后退水期有多长」——
        到退干为止，没退干的点到演算结束。ADM-379：5,636 ÷ 13.75 h = **410 m³/h**。

        ⚠ 分子**不能**取「样本里看得见的退水」：时程只存 ≥1 cm 的水，退得快的点
        整个退水段一帧都留不下，会被算成速率 0 → 全额上泵。详见
        `recession_total_m3` 的注释（ADM-381 就是这么被判错的）。

        ⚠ **不要换回 `drain_rate_m3h`**（2026-09-21 回退的那一版）。那是曲线上
        **最陡一帧**的瞬时降幅，拿来当 T 小时的恒速会系统性高估：按各点自己的
        R_max 恒排，123 个有演算的点排完全量所需时间比演算实测的退干时间短
        **1.9–8.1 倍（中位 3.7 倍），无一例外**。ADM-379 上 R_max = 1,842 m³/h
        出现在 t=210–225 min，还落在 T=2 h 窗口**之外**。

        ⚠ 也不要换成 `qcap_m3s`（更早回退的那一版）：那是管段满流能力，答的是
        「这根管满流时每秒能过多少水」，不是「地面的水能以多快进到管里」，代进来
        会让 112/123 个点（91%）泵需求归零。详见模块头注释。

        分母从**峰值**起算而不是 t=0：一道的窗口 T 也是从峰值起算的，两者必须
        同起点，否则 T = 退水期时长时一道对不上总量。用绝对退干时刻当分母会把
        涨水期摊进来，ADM-379 会得 336 而不是 410 m³/h（低 18%）。

        全程没有任何退水段（单调上涨到演算结束）时返回 0.0 —— 那是「重力自排
        无出路」的正常结论，第一道防线在这个点上颗粒无收。
        """
        hours = self.recession_hours
        if not hours:
            return 0.0
        return self.recession_total_m3 / hours

    def volume_at(self, minutes: float) -> float:
        """V(t)，样本之间线性插值。早于首帧按 0 算，晚于末帧按末帧值。"""
        if not self.samples:
            return 0.0
        if minutes <= 0.0:
            return 0.0
        first_t, first_v = self.samples[0]
        if minutes <= first_t:
            # 首帧之前：从 (0, 0) 线性升到首帧，与 state_at 的累加口径一致
            return first_v * minutes / first_t
        if minutes >= self.samples[-1][0]:
            return self.samples[-1][1]
        for (t0, v0), (t1, v1) in zip(self.samples, self.samples[1:]):
            if t0 <= minutes <= t1:
                return v0 + (v1 - v0) * (minutes - t0) / (t1 - t0)
        return self.samples[-1][1]

    def state_at(self, minutes: float) -> PondingState:
        """逐帧累加 ΔV 到 T 为止，跨越 T 的那一帧按时间比例切分。

        切分是必要的：时限默认 2 h 正落在 120 min 这一帧上，而帧距 15 min，
        不切的话最多会把一整帧的水量算进或漏掉。
        """
        if not self.samples or minutes <= 0.0:
            return PondingState(0.0, 0.0, 0.0)
        inflow = drained = 0.0
        prev_t, prev_v = 0.0, 0.0
        for t, v in self.samples:
            if t <= minutes:
                span_t, span_v = t, v
            else:
                # 这一帧跨过 T：按时间比例取 ΔV 的前一段
                frac = (minutes - prev_t) / (t - prev_t)
                span_t, span_v = minutes, prev_v + (v - prev_v) * frac
            delta = span_v - prev_v
            if delta >= 0:
                inflow += delta
            else:
                drained -= delta
            prev_t, prev_v = span_t, span_v
            if t > minutes:
                break
        return PondingState(inflow, drained, prev_v)


def _number(value: str | None) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _text(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def load_curves(
    points_path: Path = HOTSPOT_PONDING_CSV,
    series_path: Path = HOTSPOT_PONDING_SERIES_CSV,
) -> dict[str, PondingCurve]:
    """读两个 CSV 装配逐点曲线。文件缺失返回空表 —— 届时全部点都算「无标定」。

    ⚠ 覆盖判据是**出现在 `hotspot_ponding.csv` 里**，不是「有时序」：演算说
    某点全程不积水时，它在汇总表里有行、在时序表里没有行，那是「第一道成立」
    的正常结论，不能和「没跑过演算」混为一谈。
    """
    if not points_path.exists():
        return {}

    series: dict[str, list[tuple[float, float]]] = {}
    if series_path.exists():
        with series_path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                t, v = _number(row.get("time_min")), _number(row.get("volume_m3"))
                if t is None or v is None:
                    continue
                series.setdefault(row["uid"], []).append((t, v))
    for samples in series.values():
        samples.sort()

    curves: dict[str, PondingCurve] = {}
    with points_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            uid = row["uid"]
            rp = _number(row.get("return_period_years"))
            curves[uid] = PondingCurve(
                uid=uid,
                run_id=row.get("run_id", ""),
                return_period_yr=int(rp) if rp is not None else None,
                attribution_basis=_text(row.get("attribution_basis")),
                samples=tuple(series.get(uid, ())),
                peak_m3=_number(row.get("peak_volume_m3")) or 0.0,
                peak_time_min=_number(row.get("peak_time_min")),
                net_inflow_m3=_number(row.get("net_inflow_m3")) or 0.0,
                settled_m3=_number(row.get("settled_volume_m3")),
                drain_min=_number(row.get("drain_time_min")),
                depression_capacity_m3=_number(row.get("depression_capacity_m3")),
            )
    return curves


_CACHE: dict[str, PondingCurve] | None = None


def load_all_curves() -> dict[str, PondingCurve]:
    """两套点的曲线并成一张表。uid 互不相交，故直接合并不会串。

    片区那一套缺文件时静默跳过 —— 没跑过 `model_cluster_batch.py` 的机器上
    台账那一路照常工作，只是片区全部算「无水动力标定」。
    """
    curves = load_curves()
    curves.update(load_curves(MODEL_PONDING_CSV, MODEL_PONDING_SERIES_CSV))
    return curves


def curve_for(uid: str) -> PondingCurve | None:
    """取某点的积水曲线；没跑过二维演算的点返回 None。"""
    global _CACHE
    if _CACHE is None:
        _CACHE = load_all_curves()
    return _CACHE.get(uid)


def reset_cache() -> None:
    """清缓存 —— 重跑 `ponding_batch.py` 后或测试里换数据时用。"""
    global _CACHE
    _CACHE = None
