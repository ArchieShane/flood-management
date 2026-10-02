"""移动泵车分档表与派车逻辑（DMT 数据需求清单 §02）。

这里锁的是**派车范式**：排量怎么从铭牌值折算出来，以及在「过配」和「出车数」
之间怎么取舍。范式变了这些测试就该失败 —— 那是要连同报告口径一起改的事。
"""

import pytest

from stormwater.pumps import (
    DEFAULT_AVAILABILITY,
    DEFAULT_DUTY_FACTOR,
    DEFAULT_PUMP_TIERS,
    PumpTier,
    dispatch,
    fleet_weighted_capacity,
    uniform_tier,
)

RATED = {t.key: t.rated_m3hr(DEFAULT_DUTY_FACTOR, DEFAULT_AVAILABILITY)
         for t in DEFAULT_PUMP_TIERS}


class TestRatedCapacity:
    def test_two_stage_derating_from_nameplate(self):
        """额定排量 = 铭牌 × 工况折减 × 出勤占空。"""
        assert RATED["12in"] == pytest.approx(1360 * 0.65 * 0.85)
        assert RATED["8in"] == pytest.approx(520 * 0.65 * 0.85)
        assert RATED["6in"] == pytest.approx(400 * 0.65 * 0.85)

    def test_tiers_are_ordered_and_all_derived(self):
        assert [t.key for t in DEFAULT_PUMP_TIERS] == ["12in", "8in", "6in"]
        assert RATED["12in"] > RATED["8in"] > RATED["6in"]
        # 一台都还没拿到实测值 —— 报告里必须逐档标成「铭牌折减」
        assert all(t.basis == "铭牌折减" for t in DEFAULT_PUMP_TIERS)

    def test_measured_value_bypasses_derating(self):
        """DMT 给了实测排量，该档就不再打折。"""
        measured = PumpTier(key="12in", label="12″", nameplate_m3hr=1360.0,
                            fleet_qty=144, reference="DMT 实测", measured_m3hr=900.0)
        assert measured.rated_m3hr(0.65, 0.85) == 900.0
        assert measured.basis == "实测"

    def test_weighted_average_is_close_to_the_old_assumption(self):
        """按在册构成加权约 321 m³/h —— 原假设 300 的量级站得住，构成才是问题。"""
        assert fleet_weighted_capacity() == pytest.approx(321.0, abs=1.0)


class TestDispatch:
    def test_no_demand_sends_nothing(self):
        d = dispatch(0.0)
        assert d.total_units == 0 and d.counts == ()

    def test_small_job_gets_the_smallest_pump(self):
        assert dict(dispatch(50.0).counts) == {"6in": 1}

    def test_small_job_never_gets_a_scarce_12in(self):
        """300 m³/h 单台 8″/6″ 都不够，但也不该派 12″ —— 两台 6″ 才对。

        12″ 在册仅 144 台、约 4.5 t 需拖车，被小活吃掉会凭空造出大口径需求。
        """
        assert dict(dispatch(300.0).counts) == {"6in": 2}

    def test_large_job_is_not_split_into_a_swarm(self):
        """纯最小过配会给 5,000 m³/h 派 23 台 6″ —— 出车数必须计价。"""
        d = dispatch(5000.0)
        assert d.total_units <= 10
        assert d.qty("12in") >= 5

    @pytest.mark.parametrize("required", [1, 50, 221, 300, 600, 751.4, 1000,
                                          2000, 5000, 20000, 50000])
    def test_deployed_capacity_always_covers_demand(self, required):
        d = dispatch(required)
        assert d.deployed_m3hr >= required
        assert d.total_units == sum(n for _, n in d.counts)
        assert d.spare_m3hr >= 0 and 0 < d.utilisation <= 1.0

    def test_counts_are_ordered_largest_first(self):
        keys = [k for k, _ in dispatch(5000.0).counts]
        assert keys == [k for k in ("12in", "8in", "6in") if k in keys]

    def test_single_tier_table_degrades_to_plain_ceiling(self):
        d = dispatch(756.9, (uniform_tier(300.0),))
        assert dict(d.counts) == {"uniform": 3}     # ⌈756.9 / 300⌉

    def test_measured_values_flow_through_to_dispatch(self):
        """DMT 给实测值后派车立刻跟着变 —— 这正是 §02 补齐后要发生的事。

        默认折减是 0.65 × 0.85 = 0.5525；实测若比这更高，同样的活就该少派车。
        """
        def measured(fraction):
            return tuple(
                PumpTier(key=t.key, label=t.label, nameplate_m3hr=t.nameplate_m3hr,
                         fleet_qty=t.fleet_qty, reference="DMT 实测",
                         measured_m3hr=t.nameplate_m3hr * fraction)
                for t in DEFAULT_PUMP_TIERS
            )
        derated = dispatch(3000.0)
        better = dispatch(3000.0, measured(0.75))
        worse = dispatch(3000.0, measured(0.40))
        assert better.deployed_m3hr >= 3000.0 and worse.deployed_m3hr >= 3000.0
        assert better.total_units < derated.total_units < worse.total_units

    def test_empty_tier_table_is_rejected(self):
        with pytest.raises(ValueError, match="不能为空"):
            dispatch(100.0, ())
