"""§3.6 示例点 H1 的回归测试基准。

原始 Excel 已用 LibreOffice 逐格重算比对确认一致，本测试锁死这些数字。
任何改动导致这里失败 = 计算链被改坏了，或者是有意变更范式（需同步更新基准）。

⚠ 本文件的基准全部是**迪拜 DM 数据集 + 峰值口径**的。计算器的默认已改为
  ADQCC Zone B + 水动力口径（`defence_basis="hydrodynamic"`），所以这里每处都
  显式传 ``dataset=DUBAI`` 与 ``defence_basis="peak"`` —— 基准锁的是「复现原
  Excel」这件事，不是「默认行为」。ADQCC 的行为见 tests/test_idf_datasets.py，
  水动力口径的行为见本文件末尾的 TestDefenceHydrodynamic。
"""

import pytest

from stormwater.constants import LEGACY_PUMP_CAPACITY, Assumptions
from stormwater.idf import snap_duration
from stormwater.ponding_curve import PondingCurve
from stormwater.rational import Hotspot, evaluate, evaluate_all, fleet_summary

DUBAI = "dubai_dm"

#: 原 Excel 的两处口径：全车队统一单泵 300 m³/h，且三道防线按**峰值**判
#: （管网只在降雨历时内起作用）。两者都已不是默认，但「复现原 Excel」
#: 这件事仍要锁死，故基准测试显式退回。
LEGACY = Assumptions(pump_capacity=LEGACY_PUMP_CAPACITY, defence_basis="peak")
#: 只退回峰值口径，其余走默认（单档配置式，每点 1 台 × 300 m³/h）。
PEAK = Assumptions(defence_basis="peak")
#: 峰值口径 + **显式退回 12″/8″/6″ 分档派车**（`pump_capacity=None`）。
#: 分档不再是默认口径（默认是页面那个单泵抽排能力），但逻辑一行没删，
#: 它仍是回答「采购该买哪几档」时唯一说得清的口径，故这里继续锁死。
TIERED = Assumptions(defence_basis="peak", pump_capacity=None)

H1 = Hotspot(
    hotspot_id="H1",
    area_ha=12.0,
    runoff_c=0.75,
    tc_min=20.0,
    qcap_m3s=1.8,
    pond_available_m3=0.0,
)

# 交接文档 §3.6 表格：重现期, I, C_adj, Q, 超量, 所需调蓄, 缺口, 泵, 罐车
H1_BASELINE = [
    (5,   53.54, 0.7500, 1.339, 0.000,    0.0,    0.0, 0,   0),
    (10,  68.58, 0.7500, 1.715, 0.000,    0.0,    0.0, 0,   0),
    (25,  85.92, 0.8250, 2.363, 0.563,  354.6,  354.6, 1,  24),
    (50, 108.78, 0.9000, 3.263, 1.463,  921.9,  921.9, 2,  62),
    (100,134.49, 0.9375, 4.203, 2.403, 1513.8, 1513.8, 3, 101),
]


@pytest.mark.parametrize(
    "rp,intensity,c_adj,q,excess,storage,shortfall,pumps,tankers", H1_BASELINE
)
def test_h1_matches_excel_baseline(rp, intensity, c_adj, q, excess, storage, shortfall, pumps, tankers):
    r = evaluate(H1, rp, LEGACY, dataset=DUBAI)
    assert r.duration_min == 20
    assert r.intensity_mm_hr == pytest.approx(intensity)
    assert r.c_adjusted == pytest.approx(c_adj, abs=1e-4)
    assert r.peak_flow_m3s == pytest.approx(q, abs=5e-4)
    assert r.excess_flow_m3s == pytest.approx(excess, abs=5e-4)
    assert r.required_storage_m3 == pytest.approx(storage, abs=0.05)
    assert r.shortfall_m3 == pytest.approx(shortfall, abs=0.05)
    assert r.pumps_required == pumps
    assert r.tanker_loads == tankers


def test_h1_fleet_summary_totals():
    summary = fleet_summary(evaluate_all(H1, assumptions=LEGACY, dataset=DUBAI))
    assert summary[100]["pumps_required"] == 3
    assert summary[100]["tanker_loads"] == 101
    assert summary[5]["shortfall_m3"] == pytest.approx(0.0)


def test_available_pond_reduces_shortfall_but_not_required_storage():
    """已有调蓄只抵扣缺口，不改变所需总容量。"""
    with_pond = Hotspot(**{**H1.__dict__, "pond_available_m3": 400.0})
    base = evaluate(H1, 50, PEAK, dataset=DUBAI)
    pooled = evaluate(with_pond, 50, PEAK, dataset=DUBAI)
    assert pooled.required_storage_m3 == pytest.approx(base.required_storage_m3)
    assert pooled.shortfall_m3 == pytest.approx(base.shortfall_m3 - 400.0)
    assert pooled.tanker_loads < base.tanker_loads


def test_pond_larger_than_requirement_clamps_to_zero():
    covered = Hotspot(**{**H1.__dict__, "pond_available_m3": 5000.0})
    r = evaluate(covered, 100, PEAK, dataset=DUBAI)
    assert r.shortfall_m3 == 0.0
    assert r.pumps_required == 0 and r.tanker_loads == 0


def test_cf_missing_falls_back_to_one():
    """IDF 有 20 年一遇但 Cf 表没有 —— 原 Excel 的 IFERROR 回退 1.0。"""
    assert evaluate(H1, 20, dataset=DUBAI).c_adjusted == pytest.approx(0.75)


def test_c_adjusted_clamped_at_one():
    high_c = Hotspot(**{**H1.__dict__, "runoff_c": 0.95})
    assert evaluate(high_c, 100, dataset=DUBAI).c_adjusted == pytest.approx(1.0)  # 0.95 × 1.25 = 1.19 → 1.0


class TestDurationSnapping:
    """§3.2 步骤 1 的已知缺陷：MATCH type=1 向下取档。"""

    @pytest.mark.parametrize("tc,expected", [(5, 5), (20, 20), (25, 20), (44, 30), (1441, 1440)])
    def test_snaps_down(self, tc, expected):
        assert snap_duration(tc) == expected

    def test_below_minimum_raises(self):
        with pytest.raises(ValueError, match="#N/A"):
            snap_duration(4.9)


def test_assumptions_are_overridable():
    """§3.5 标注为「假设值」的参数必须可覆盖，不能写死。"""
    realistic = Assumptions(pump_capacity=600.0, tanker_capacity=25.0, defence_basis="peak")
    r = evaluate(H1, 100, realistic, dataset=DUBAI)
    assert r.pumps_required == 2           # 756.9 / 600 → 2（单档 300 时为 3）
    assert r.tanker_loads == 61            # 1513.8 / 25 → 61（默认 15 时为 101）


def test_rational_method_area_limit_flagged():
    """§3.7：推理公式法只适用于 < 80 ha。"""
    assert not H1.exceeds_rational_method_limit
    assert Hotspot(**{**H1.__dict__, "area_ha": 120.0}).exceeds_rational_method_limit


@pytest.mark.parametrize("bad", [
    {"area_ha": 0}, {"area_ha": -1}, {"runoff_c": 0}, {"runoff_c": 1.5}, {"qcap_m3s": -1},
])
def test_invalid_inputs_rejected(bad):
    with pytest.raises(ValueError):
        Hotspot(**{**H1.__dict__, **bad})


# --------------------------------------------------------------------------
# 分档派车（DMT 数据需求清单 §02）
# --------------------------------------------------------------------------

def test_default_is_the_page_configured_single_pump():
    """默认口径是页面那两个旋钮：每点 1 台 × 300 m³/h，不是分档表。"""
    a = Assumptions()
    assert a.pumps_per_point == 1
    assert a.pump_capacity == 300.0
    assert a.pump_unit_capacity == 300.0
    assert [t.key for t in a.effective_tiers] == ["uniform"]


def test_tier_table_still_available_when_capacity_is_cleared():
    """`pump_capacity=None` 退回分档表 —— 采购论证的口径没被删掉。"""
    a = Assumptions(pump_capacity=None)
    assert [t.key for t in a.effective_tiers] == ["12in", "8in", "6in"]
    # 「每点 N 台」里那个「台」退化成在册构成的加权平均
    assert a.pump_unit_capacity == pytest.approx(321.0, abs=1.0)


def test_tiered_dispatch_breaks_pumps_down_by_bore():
    """H1 百年一遇需 756.9 m³/h —— 分档后要能说清是哪几台。"""
    r = evaluate(H1, 100, TIERED, dataset=DUBAI)
    d = r.pump_dispatch
    assert d.total_units == r.pumps_required == sum(n for _, n in d.counts)
    assert d.deployed_m3hr >= r.pumping_rate_m3hr        # 派出的运力必须够
    assert dict(d.counts) == {"12in": 1, "6in": 1}


def test_single_tier_override_collapses_the_table():
    """给了 pump_capacity 就退回单档 —— 敏感性分析与旧口径回归都靠它。"""
    r = evaluate(H1, 100, LEGACY, dataset=DUBAI)
    assert dict(r.pump_dispatch.counts) == {"uniform": 3}


def test_fleet_summary_tallies_each_tier():
    summary = fleet_summary(evaluate_all(H1, assumptions=TIERED, dataset=DUBAI))
    by_tier = summary[100]["pumps_by_tier"]
    assert sum(by_tier.values()) == summary[100]["pumps_required"]
    assert set(by_tier) <= {"12in", "8in", "6in"}


# --------------------------------------------------------------------------
# 页面配置式车队：「每点配 N 台 × X m³/h，够不够」
# --------------------------------------------------------------------------

class TestConfiguredFleet:
    """`pumps_required` 答「该配几台」，这一组答「已配的那套够不够」。

    两个问题并列 —— 锁死它们**不会被合并成一个数**，那是那次改动的全部要点。
    """

    def test_configured_capacity_is_units_times_unit_rate(self):
        a = Assumptions(defence_basis="peak", pumps_per_point=2, pump_capacity=250.0)
        r = evaluate(H1, 100, a, dataset=DUBAI)
        assert r.pumps_configured == 2
        assert r.pump_configured_m3hr == pytest.approx(500.0)

    def test_one_pump_per_point_falls_short_and_says_by_how_much(self):
        """H1 百年一遇：R2 = 1,513.8 m³，2 h 内 1 台 300 m³/h 只排得掉 600。

        但泵侧排得掉多少不是结论 —— 默认配 1 辆罐车，2 h 只跑 2 趟 × 15 m³
        = 30 m³，链卡在罐车侧。泵侧的 600 在这里是**用不上的能力**。
        """
        r = evaluate(H1, 100, PEAK, dataset=DUBAI)
        assert r.pumps_configured == 1
        assert r.pump_configured_m3hr == pytest.approx(300.0)
        assert r.configured_fleet_suffice is False
        # 瓶颈在罐车侧：1 辆 × 15 m³ / 1 h = 15 m³/h，远低于泵侧 300
        assert r.chain_bottleneck == "tanker"
        assert r.chain_configured_m3hr == pytest.approx(15.0)
        # 时限内运得走的是 1 辆 × 2 趟 × 15 m³ = 30 m³，不是泵侧的 600
        assert r.chain_residual_m3 == pytest.approx(1513.8 - 30.0, abs=0.5)
        assert r.chain_hours_required == pytest.approx(1513.8 / 15.0, abs=0.1)
        # 「该配几台」没有被这个配置盖掉 —— 它仍然是 3
        assert r.pumps_required == 3
        assert any("清不完" in n for n in r.notes)
        assert any("卡在罐车侧" in n for n in r.notes)

    def test_pumps_alone_cannot_clear_it_without_tankers(self):
        """**这次改动的要点**：泵和罐车串联，加泵加不出外运能力。

        配 3 台泵（正是 `pumps_required`）但只配 1 辆车 —— 链还是 15 m³/h，
        残量和配 1 台泵时**一模一样**。泵在等车。
        """
        one = evaluate(H1, 100, Assumptions(
            defence_basis="peak", pumps_per_point=1, tankers_per_point=1),
            dataset=DUBAI)
        three = evaluate(H1, 100, Assumptions(
            defence_basis="peak", pumps_per_point=3, tankers_per_point=1),
            dataset=DUBAI)
        assert three.pump_configured_m3hr == 3 * one.pump_configured_m3hr
        assert three.chain_configured_m3hr == one.chain_configured_m3hr
        assert three.chain_residual_m3 == one.chain_residual_m3
        assert three.chain_bottleneck == "tanker"

    def test_enough_pumps_and_tankers_leave_no_residual_and_no_note(self):
        """两侧都配够才清得完 —— 3 台泵 + 76 辆车（2 h 跑 2 趟 × 15 m³）。"""
        a = Assumptions(defence_basis="peak", pumps_per_point=3,
                        pump_capacity=300.0, tankers_per_point=76)
        r = evaluate(H1, 100, a, dataset=DUBAI)
        assert r.configured_fleet_suffice is True
        assert r.chain_residual_m3 == 0.0
        assert not any("清不完" in n for n in r.notes)

    def test_adding_tankers_beyond_the_pump_flips_the_bottleneck(self):
        """车加过头，瓶颈换到泵侧 —— 那时该加的是泵。"""
        a = Assumptions(defence_basis="peak", pumps_per_point=1,
                        pump_capacity=300.0, tankers_per_point=40)
        r = evaluate(H1, 100, a, dataset=DUBAI)
        # 40 辆 × 15 m³/h = 600 m³/h > 泵侧 300
        assert r.tanker_configured_m3hr == pytest.approx(600.0)
        assert r.chain_configured_m3hr == pytest.approx(300.0)
        assert r.chain_bottleneck == "pump"

    def test_tankers_per_pump_is_the_ratio_that_keeps_a_pump_fed(self):
        """默认参数下喂饱一台 300 m³/h 的泵要 20 辆 15 m³/h 的车。"""
        a = Assumptions(pump_capacity=300.0, tanker_capacity=15.0,
                        tanker_turnaround_min=60.0)
        assert a.tanker_vehicle_rate_m3hr == pytest.approx(15.0)
        assert a.tankers_per_pump == 20
        r = evaluate(H1, 100, Assumptions(defence_basis="peak"), dataset=DUBAI)
        assert r.tankers_to_feed_pumps == r.pumps_required * 20

    def test_nothing_to_pump_needs_no_time(self):
        """5 年一遇下 R2 = 0 —— 配了车也不用出车，别报出一个非零时长。"""
        r = evaluate(H1, 5, PEAK, dataset=DUBAI)
        assert r.shortfall_m3 == 0.0
        assert r.chain_hours_required == 0.0 and r.chain_residual_m3 == 0.0
        assert r.configured_fleet_suffice is True

    def test_tanker_capacity_is_per_truck(self):
        """罐车容量是**单车**载量：翻倍则车次减半。"""
        base = evaluate(H1, 100, PEAK, dataset=DUBAI)
        big = evaluate(
            H1, 100, Assumptions(defence_basis="peak", tanker_capacity=30.0),
            dataset=DUBAI,
        )
        assert base.tanker_loads == 101 and big.tanker_loads == 51


class TestTankerFleet:
    """车次 → 辆数。**两个量，不可互相替代** —— 车次是体积换算，辆数才是调度结论
    （交接文档 §7 待决策第 5 条）。折算全靠往返周转时间，时限 T 单独给不出辆数。
    """

    def test_loads_ignore_the_window_but_vehicles_do_not(self):
        """车次只由单车容量定，时限改了不动；辆数跟着时限走。"""
        def at(hours):
            return evaluate(
                H1, 100,
                Assumptions(defence_basis="peak", drawdown_hours=hours),
                dataset=DUBAI,
            )

        two, six = at(2.0), at(6.0)
        assert two.tanker_loads == six.tanker_loads == 101   # 车次与 T 无关
        # 60 min/趟：2 h 跑 2 趟 → 51 辆；6 h 跑 6 趟 → 17 辆
        assert two.tanker_trips_per_vehicle == 2 and two.tankers_required == 51
        assert six.tanker_trips_per_vehicle == 6 and six.tankers_required == 17

    def test_faster_turnaround_needs_fewer_vehicles_same_loads(self):
        def at(turnaround):
            return evaluate(
                H1, 100,
                Assumptions(defence_basis="peak", tanker_turnaround_min=turnaround),
                dataset=DUBAI,
            )

        slow, fast = at(60.0), at(20.0)
        assert slow.tanker_loads == fast.tanker_loads == 101
        assert fast.tankers_required < slow.tankers_required
        assert fast.tanker_trips_per_vehicle == 6      # ⌊120 / 20⌋

    def test_turnaround_longer_than_window_yields_no_vehicle_count(self):
        """一辆车跑不满一趟 —— 辆数是 **None，不是 0**。

        0 会被读成「不需要罐车」，实际含义是「这个时限下罐车根本来不及」。
        """
        r = evaluate(
            H1, 100,
            Assumptions(defence_basis="peak", drawdown_hours=1.0,
                        tanker_turnaround_min=90.0),
            dataset=DUBAI,
        )
        assert r.tanker_loads > 0            # 水还是那么多水
        assert r.tanker_trips_per_vehicle == 0
        assert r.tankers_required is None
        assert any("连一趟都跑不完" in n for n in r.notes)

    def test_nothing_to_haul_needs_no_vehicles(self):
        """R2 = 0 时辆数是实打实的 0，与上面那个 None 不是一回事。"""
        r = evaluate(H1, 5, PEAK, dataset=DUBAI)
        assert r.tanker_loads == 0 and r.tankers_required == 0

    def test_non_positive_turnaround_rejected(self):
        with pytest.raises(ValueError, match="周转时间"):
            Assumptions(tanker_turnaround_min=0)

    @pytest.mark.parametrize("bad", [
        {"pumps_per_point": 0}, {"pump_capacity": 0}, {"tanker_capacity": 0},
    ])
    def test_invalid_fleet_knobs_rejected(self, bad):
        with pytest.raises(ValueError):
            Assumptions(**bad)


# --------------------------------------------------------------------------
# 水动力口径：第一道防线读二维演算的积水量时程（默认口径）
# --------------------------------------------------------------------------

def _curve(samples, *, peak_time=None, drain=None, basis="点内", uid="H1"):
    """合成一条积水时程。峰值与净入流由样本自洽推出，免得基准里两处对不上。"""
    peak = max((v for _, v in samples), default=0.0)
    inflow = 0.0
    prev = 0.0
    for _, v in samples:
        if v > prev:
            inflow += v - prev
        prev = v
    return PondingCurve(
        uid=uid, run_id="test-run", return_period_yr=100, attribution_basis=basis,
        samples=tuple(samples), peak_m3=peak,
        peak_time_min=peak_time if peak_time is not None else next(
            (t for t, v in samples if v == peak), None),
        net_inflow_m3=inflow, settled_m3=None, drain_min=drain,
        depression_capacity_m3=None,
    )


#: 涨到 1,000 m³ @ 60 min，此后**恒速退水 250 m³/h**，5 h 退干。
#: 恒速是有意的：第一道是 `R_avg × T`，恒速曲线上「平均降幅」与「最大降幅」
#: 相等，T 一变第一道就线性跟着变，边界测得干净。
#: ⚠ 正因为相等，这条曲线**区分不出**平均口径与最大口径 —— 那个区分由下面的
#: DECAY 夹具钉住（`test_first_line_uses_the_mean_recession_not_the_steepest_frame`）。
CURVE = _curve(
    [(30, 400.0), (60, 1000.0), (120, 750.0), (180, 500.0), (240, 250.0), (300, 0.0)],
    drain=300.0,
)
PONDED = Hotspot(**{**H1.__dict__, "ponding": CURVE})

#: **衰减**退水曲线 —— 峰值 1,000 m³ @ 60 min，此后越退越慢，14 h 退干。
#: 形状照着 ADM-379（用户 2026-09-21 抓到旧口径的那个点）：最陡的一帧在紧挨
#: 峰值之后，尾巴上却拖了十几个小时。两个 R 在这里差 11.2 倍：
#:     R_max = (1000−800)/0.25 h = 800 m³/h      最陡一帧
#:     R_avg = 1000 m³ ÷ 14 h    = 71.43 m³/h    整个退水期的平均
DECAY = _curve(
    [(30, 500.0), (60, 1000.0), (75, 800.0), (120, 650.0), (180, 500.0),
     (300, 300.0), (600, 100.0), (900, 0.0)],
    drain=900.0,
)
DECAYED = Hotspot(**{**H1.__dict__, "ponding": DECAY})

#: **退得太快，退水段一帧都没留下** —— 照抄 ADM-381 的形状：时程只有 `(75, 6.82)`
#: 这一帧，`drain_min = 90` 说下一帧就跌破 1 cm 存储阈值了。曲线只存 ≥1 cm 的水，
#: 所以「样本里看得见的退水」是 0，而真实退水速率是 6.82 ÷ 0.25 h = 27.3 m³/h。
FLASH = _curve([(75, 6.82)], drain=90.0)
FLASHED = Hotspot(**{**H1.__dict__, "ponding": FLASH})
#: 同一条时程，但管网能力小到咬得住：Qcap × 2 h = 600 m³ < T 内积进来的 1,000 m³。
#: H1 的 1.8 m³/s 折合 12,960 m³，会把水一次排光，测不出第一道的边界。


class TestDefenceHydrodynamic:
    """第一道防线只认演算出来的积水量时程 —— 与上面的峰值基准是两个问题。"""

    def test_first_line_reads_the_curve_not_the_pipe(self):
        """第一道 = 实测退水速率 × T，速率来自时程而不是管子。水量账闭合。"""
        r = evaluate(PONDED, 100, dataset=DUBAI)
        assert r.l1_basis == "hydrodynamic"
        assert r.runoff_volume_m3 == pytest.approx(1000.0)   # T 内净入流（总量）
        # 250 m³/h × 2 h —— 管网这条腿在工期 T 内分担掉的量
        assert r.network_drained_m3 == pytest.approx(500.0)
        assert r.residual_after_network_m3 == pytest.approx(500.0)  # 交给二、三道
        assert r.runoff_volume_m3 == pytest.approx(
            r.network_drained_m3 + r.residual_after_network_m3
        )

    def test_qcap_no_longer_moves_any_defence_line(self):
        """**这一条是口径的总闸**：管段满流能力换成任何值，三道防线一个数都不变。

        实测 `corr(Qcap, 排空速率) = −0.156` —— 它对排空速率没有预测力，
        方向还是反的，所以它不该出现在水量平衡里。见 `ponding_curve.py`。

        ⚠ 「泵在排的时候管网没停」这个顾虑是成立的，第一道现在正是按
        `R_avg × T` 把管网这条腿并联进来 —— 但 R 取**演算实测的平均退水
        速率**，不是 Qcap。把 Qcap 代进 R 会让 112/123 个有演算的点（91%）
        泵需求归零，而这批点实测要 10 多小时才退干。别再改回去。
        """
        lots = evaluate(Hotspot(**{**PONDED.__dict__, "qcap_m3s": 99.0}), 100, dataset=DUBAI)
        none = evaluate(Hotspot(**{**PONDED.__dict__, "qcap_m3s": 0.0}), 100, dataset=DUBAI)
        for field in ("runoff_volume_m3", "network_drained_m3",
                      "residual_after_network_m3", "required_storage_m3",
                      "shortfall_m3", "pumps_required", "tanker_loads",
                      "tankers_required", "chain_residual_m3"):
            assert getattr(lots, field) == getattr(none, field), field
        assert lots.defence_line == none.defence_line
        # Qcap 仅存的用途：峰值诊断，它照常跟着变
        assert lots.peak_exceeds_capacity is False
        assert none.peak_exceeds_capacity is True

    def test_first_line_uses_the_mean_recession_not_the_steepest_frame(self):
        """**这一条钉住 2026-09-21 的口径修正**：R 取整个退水期的平均，不取最大帧。

        旧口径 `R_max × T` 拿曲线上最陡的一帧当 T 小时的恒速，把瞬时上限外推
        成持续能力。实测在 123 个有演算的点上**无一例外**地高估：按各点自己的
        R_max 恒排，排完全量所需时间比演算实测的退干时间短 1.9–8.1 倍（中位
        3.7 倍）。用户是在 ADM-379 上抓到的 —— 页面同时写着「一道 2 h 排走
        3,684 m³」和「实测退干需 16.8 h」，而那个 R_max = 1,842 m³/h 出现在
        t=210–225 min，落在 T=2 h 窗口**之外**，窗口内该点的水还在涨。

        DECAY 上两个 R 差 11.2 倍，取错一个这条就红。别再改回 `drain_rate_m3h`。
        """
        assert DECAY.drain_rate_m3h == pytest.approx(800.0)        # 最陡一帧
        assert DECAY.mean_drain_rate_m3h == pytest.approx(1000.0 / 14.0)
        r = evaluate(DECAYED, 100, dataset=DUBAI)
        assert r.runoff_volume_m3 == pytest.approx(1000.0)
        # 平均口径：142.9 m³。取最大帧会是 1,000（R_max × 2 h 已封顶到总量）
        assert r.network_drained_m3 == pytest.approx(1000.0 / 7.0)
        assert r.network_drained_m3 < 0.2 * r.runoff_volume_m3
        assert r.residual_after_network_m3 == pytest.approx(1000.0 - 1000.0 / 7.0)

    def test_the_mean_rate_closes_against_the_measured_drain_time(self):
        """自洽性：T 取到「峰后退水期」那么长时，第一道恰好等于总量。

        这正是平均口径相对最大帧口径的好处 —— 分母就是实测退干时间，两个数
        再不会像 ADM-379 那样自相矛盾（旧口径 3.06 h vs 实测 16.75 h）。
        分母**从峰值起算**，与窗口 T 同起点；换成绝对退干时刻会把涨水期摊进来。
        """
        assert DECAY.recession_hours == pytest.approx(14.0)        # (900−60)/60
        assert DECAY.drain_min / 60.0 == pytest.approx(15.0)       # 绝对时刻，另一个数
        closed = evaluate(DECAYED, 100, Assumptions(drawdown_hours=14.0), dataset=DUBAI)
        assert closed.network_drained_m3 == pytest.approx(closed.runoff_volume_m3)
        assert closed.residual_after_network_m3 == 0.0
        # 差一点点的窗口就不该退完
        short = evaluate(DECAYED, 100, Assumptions(drawdown_hours=13.0), dataset=DUBAI)
        assert short.residual_after_network_m3 > 0.0

    def test_first_line_is_rate_times_window_not_the_measured_residual(self):
        """第一道 = R × T，随 T 线性走；R 是实测退水速率，不是 Qcap。

        T 在这里是**工期**不是观测时刻：总量要在 T 内清完，管网与第三道的泵
        是并联的两条出路，各排各的。所以第一道随 T 线性增长，而**不是**沿
        时程去取 V(T)（那是旧口径，答的是另一个问题）。
        """
        rates = [
            evaluate(PONDED, 100, Assumptions(drawdown_hours=h), dataset=DUBAI)
            for h in (1.0, 2.0, 3.0)
        ]
        assert [r.network_drained_m3 for r in rates] == pytest.approx([250.0, 500.0, 750.0])
        # 实测 V(T) 是另一组数（750 / 500 / 250）—— 明确不等，防止口径回退
        assert rates[0].residual_after_network_m3 == pytest.approx(750.0)
        assert PONDED.ponding.volume_at(60.0) == pytest.approx(1000.0)
        # 封顶：管网分担不会超过总量，残量不会变负
        far = evaluate(PONDED, 100, Assumptions(drawdown_hours=99.0), dataset=DUBAI)
        assert far.network_drained_m3 == pytest.approx(far.runoff_volume_m3)
        assert far.residual_after_network_m3 == 0.0

    def test_a_point_that_drains_between_frames_is_not_read_as_never_draining(self):
        """**退得太快的点不许被判成排不掉。**

        时程只存 ≥1 cm 的水，所以退水快到一帧之内的点，退水段在样本里一行都没有
        —— 但 `drain_min` 明明白白写着它退干了。速率的分子若取「样本里看得见的
        退水」，这种点会得 0，然后被判成「重力自排无出路、全额上泵」，而事实上
        它们是全批退得最快的。

        2026-09-21 用户在 **ADM-381** 上发现：页面写着「成因：无排水管网」「一道
        0 m³」「需 1 台移动泵」，而管网库实测该点 11.9 m 外有管、Qcap = 0.397 m³/s，
        演算说它 15 分钟内就退干了。同批的 ADM-163 一样。
        """
        assert FLASH.recession_hours == pytest.approx(0.25)        # (90−75)/60
        assert FLASH.recession_total_m3 == pytest.approx(6.82)     # 退干 = 一滴不剩
        assert FLASH.mean_drain_rate_m3h == pytest.approx(6.82 / 0.25)
        r = evaluate(FLASHED, 100, dataset=DUBAI)
        assert r.network_drained_m3 == pytest.approx(r.runoff_volume_m3)
        assert r.residual_after_network_m3 == 0.0
        assert r.pumps_required == 0
        assert r.defence_line == 1
        assert not any("没有退水段" in n for n in r.notes)

    def test_the_tail_below_the_storage_threshold_still_counts_as_drained(self):
        """轻症版的同一个 bug：末帧总还剩一点水才跌破 1 cm，那截尾巴也得算退走。

        实测覆盖 120/123 个点，合计 555 m³（占总量 0.2%）—— 单点无感，但按样本
        差分会让每个点的速率都偏低一点，方向和 ADM-381 那个重症一致。
        """
        # 末帧还剩 40 m³ 就跌破阈值了，drain_min 说 t=240 退干
        tail = _curve([(60, 1000.0), (120, 500.0), (180, 40.0)], drain=240.0)
        assert tail.recession_total_m3 == pytest.approx(1000.0)    # 不是 960
        assert tail.recession_hours == pytest.approx(3.0)          # (240−60)/60
        # 对照：演算结束仍未退干时，末帧残量确实不算自排战果，得留给泵
        wet = _curve([(60, 1000.0), (120, 500.0), (180, 40.0)], drain=None)
        assert wet.recession_total_m3 == pytest.approx(960.0)
        assert wet.recession_hours == pytest.approx(2.0)           # (180−60)/60

    def test_a_curve_that_never_recedes_gives_the_first_line_nothing(self):
        """演算全程只涨不退 —— 重力自排无出路，第一道颗粒无收，全额交第三道。"""
        rising = _curve([(30, 300.0), (60, 700.0), (120, 900.0)], drain=None)
        r = evaluate(Hotspot(**{**PONDED.__dict__, "ponding": rising}), 100, dataset=DUBAI)
        assert rising.mean_drain_rate_m3h == 0.0
        assert rising.recession_hours is None      # 峰值就在末帧，没有退水期
        assert r.network_drained_m3 == 0.0
        assert r.residual_after_network_m3 == pytest.approx(r.runoff_volume_m3)
        assert r.defence_line == 3
        assert any("没有退水段" in n for n in r.notes)

    def test_without_a_run_no_conclusion_is_produced(self):
        """没跑过二维演算的点不出结论 —— 不回退旧公式，也不外推。"""
        r = evaluate(H1, 100, dataset=DUBAI)      # H1 本身没有 ponding
        assert r.l1_basis == "uncalibrated"
        assert r.is_calibrated is False
        assert r.defence_line is None
        for field in ("runoff_volume_m3", "network_drained_m3",
                      "residual_after_network_m3", "cleared_by_network",
                      "required_storage_m3", "shortfall_m3", "pumps_required",
                      "pump_dispatch", "tanker_loads", "drain_hours"):
            assert getattr(r, field) is None, field
        # 峰值诊断量不依赖演算，照常给
        assert r.peak_flow_m3s == pytest.approx(4.203, abs=5e-4)
        assert r.peak_exceeds_capacity is True
        assert any("不出结论" in n for n in r.notes)

    def test_the_window_walks_along_the_curve(self):
        """时限是三道防线共用的 —— 改 T，第一道沿时程取另一个点。"""
        early = evaluate(PONDED, 100, Assumptions(drawdown_hours=1.0), dataset=DUBAI)
        late = evaluate(PONDED, 100, Assumptions(drawdown_hours=4.0), dataset=DUBAI)
        # 总量同为 T 内净入流（1 h 就已经全部积进来了），变的是第一道分担多少
        assert early.runoff_volume_m3 == pytest.approx(1000.0)
        # T=1 h：管网只来得及分担 250 m³/h × 1 h
        assert early.network_drained_m3 == pytest.approx(250.0)
        assert early.residual_after_network_m3 == pytest.approx(750.0)
        # T=4 h：250 × 4 = 1,000 ≥ 总量，管网自己就扛完了，第一道成立
        assert late.network_drained_m3 == pytest.approx(1000.0)
        assert late.residual_after_network_m3 == pytest.approx(0.0)
        assert early.defence_line == 3 and late.defence_line == 1
        # 第三道的抽排速率用的必须是同一个 T
        assert early.pumping_rate_m3hr == pytest.approx(early.shortfall_m3 / 1.0)

    def test_storage_is_the_second_line_and_only_the_second(self):
        """调蓄只接第一道之后还留在地面的水，接住了就停在第二道。"""
        pooled = Hotspot(**{**PONDED.__dict__, "pond_available_m3": 5000.0})
        r = evaluate(pooled, 100, dataset=DUBAI)
        assert r.defence_line == 2
        assert r.shortfall_m3 == 0.0 and r.pumps_required == 0
        assert r.storage_used_m3 == pytest.approx(r.required_storage_m3)
        # T=2 h 时地面还剩 500，调蓄接的是这 500（带淤积裕量）
        assert r.required_storage_m3 == pytest.approx(500.0 * 1.05)

    def test_drain_hours_is_measured_not_derived_from_qcap(self):
        """退水时间是演算读出来的时刻，不是 V/Qcap 算出来的。"""
        r = evaluate(PONDED, 100, dataset=DUBAI)
        assert r.drain_hours == pytest.approx(5.0)            # 300 min
        slow = evaluate(Hotspot(**{**PONDED.__dict__, "qcap_m3s": 0.01}), 100, dataset=DUBAI)
        assert slow.drain_hours == pytest.approx(5.0)         # Qcap 改了也不动

    def test_a_peak_after_the_window_is_flagged(self):
        """T 一到水还在涨 —— 总量照全程算，但作业必然跨出时限，要说出来。

        ⚠ 这条**不再**是「结论偏低」的警告：总量已从 V(T) 改成全程净入流，
        T 之后才到的水一样进账（见 `rational` 模块头「第一道防线」）。这里锁
        的是时序提醒 —— 全程 2,000 m³ 里只有 1,250 在 T 到时已经落地。
        """
        rising = Hotspot(**{**H1.__dict__, "ponding": _curve(
            [(60, 500.0), (180, 2000.0), (600, 0.0)], drain=600.0)})
        r = evaluate(rising, 100, dataset=DUBAI)
        assert r.ponding_peak_time_min == 180 > r.window_hours * 60
        # 总量按全程取，不掐在 T=120 min 那一刀上
        assert r.runoff_volume_m3 == pytest.approx(2000.0)
        assert any("作业跨出时限" in n for n in r.notes)

    def test_the_total_is_the_whole_run_not_the_slice_at_t(self):
        """总量与 T 无关 —— T 是工期，改工期不改这个点一共积了多少水。"""
        rising = Hotspot(**{**H1.__dict__, "ponding": _curve(
            [(60, 500.0), (180, 2000.0), (600, 0.0)], drain=600.0)})
        totals = {
            h: evaluate(rising, 100, dataset=DUBAI,
                        assumptions=Assumptions(drawdown_hours=h)).runoff_volume_m3
            for h in (0.5, 1.0, 2.0, 6.0)
        }
        assert list(totals.values()) == pytest.approx([2000.0] * 4)

    def test_a_second_rise_is_counted_in_the_total(self):
        """双峰：总量取 Σ 正 ΔV，不取峰值 —— 图省事取峰值会整段漏掉第二次上涨。"""
        twin = Hotspot(**{**H1.__dict__, "ponding": _curve(
            [(60, 800.0), (180, 200.0), (300, 700.0), (600, 0.0)], drain=600.0)})
        r = evaluate(twin, 100, dataset=DUBAI)
        assert r.ponding_peak_m3 == pytest.approx(800.0)          # 峰值
        assert r.runoff_volume_m3 == pytest.approx(1300.0)        # 800 + 500

    def test_overland_attribution_is_flagged_as_a_lower_bound(self):
        """「坡面直排」的点只报本格水量 —— 这个数是下限，页面必须知道。"""
        r = evaluate(Hotspot(**{**H1.__dict__, "ponding": _curve(
            [(60, 30.0), (120, 10.0)], basis="坡面直排", drain=180.0)}), 100, dataset=DUBAI)
        assert r.ponding_attribution == "坡面直排"
        assert any("坡面直排" in n for n in r.notes)

    def test_never_drained_is_flagged(self):
        """演算到结束仍未退干 —— 重力自排无出路，必须点名。"""
        r = evaluate(Hotspot(**{**H1.__dict__, "ponding": _curve(
            [(60, 300.0), (120, 280.0)], drain=None)}), 100, dataset=DUBAI)
        assert r.drain_hours is None
        assert any("未退干" in n for n in r.notes)

    def test_result_declares_which_basis_it_used(self):
        assert evaluate(PONDED, 25, dataset=DUBAI).defence_basis == "hydrodynamic"
        assert evaluate(PONDED, 25, PEAK, dataset=DUBAI).defence_basis == "peak"
        assert evaluate(PONDED, 25, PEAK, dataset=DUBAI).l1_basis == "peak"

    def test_a_dry_point_clears_the_first_line(self):
        """演算说这里不积水 = 第一道成立，不是「缺数据」。"""
        dry = Hotspot(**{**H1.__dict__, "ponding": _curve([], drain=0.0)})
        r = evaluate(dry, 100, dataset=DUBAI)
        assert r.is_calibrated is True and r.defence_line == 1
        assert r.residual_after_network_m3 == 0.0 and r.pumps_required == 0
