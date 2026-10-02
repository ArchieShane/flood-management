"""逐点汇水面积 / 径流系数 / 集流时间的批算（catchment_batch.py）。

这三项原来是「501 个点共用一个 12 ha」，换成实测后最容易悄悄出错的是四件事：

1. **取值必须能追回 ADQCC 原表**：Table 3-8 的七行是法定值，写错一个数，
   全网 845 个点的 C 一起错，且错得看不出来 —— 故逐条锁死。
2. **面积不能重复计**：下垫面分项按扣减顺序去重，加起来必须等于单元面积。
3. **出处不能混**：没有地籍数据的点必须退回假设，不能拿几何代理冒充实测。
4. **tc 的两个下限不能被抹平**：入网时间 10 分钟是导则规定，不是可调参数。
"""

import math

import pytest

from stormwater.catchment_batch import (
    BARE_C,
    CELL_RADIUS_M,
    MIN_ENTRY_MIN,
    PLOT_CLASS_C,
    SURFACE_C,
    TC_MAX_CLAMP,
    _overland_velocity,
    _pipe_velocity,
    _priority,
    _weighted_c,
    summarise,
)


def row(**kw) -> dict:
    """一行单元统计，默认是个 19.5 ha 的全铺装单元。"""
    base = {
        "uid": "TEST-001",
        "share_n": 1,
        "flow_path_m": 250.0,
        "cell_m2": 195_000.0,
        "bldg_m2": 0.0,
        "parking_m2": 0.0,
        "pedestrian_m2": 0.0,
        "landscape_m2": 0.0,
        "plot_m2": 0.0,
        "road_m2": 195_000.0,
        "bare_m2": 0.0,
        "pipe_len_m": 2900.0,
        "dia_med_mm": 300.0,
        "slope_med": 0.0025,
    }
    base.update(kw)
    return base


def run(r: dict, classes=None, nearest=100.0, dem=None):
    return summarise(r, classes or {}, nearest, dem, 12.0, 0.75, 20.0)


class TestAdqccTablesAreQuotedNotInvented:
    """Table 3-8 / 3-9 的取值逐条锁死 —— 改了就得先改导则。"""

    def test_table_3_8_surface_values(self):
        assert SURFACE_C == {
            "bldg": 0.85,        # Roofs
            "road": 0.90,        # Asphaltic
            "parking": 0.90,     # Asphaltic
            "pedestrian": 0.78,  # Interlocking
            "landscape": 0.15,   # > 70% irrigated grass & plantings
        }

    def test_walled_residential_plot_uses_the_020_row(self):
        """住宅院落走「Walled plot; not connected to network」0.20，不是随手给的。"""
        assert PLOT_CLASS_C["residential"] == 0.20
        assert PLOT_CLASS_C["unspecified"] == 0.20      # Poor ground cover
        assert PLOT_CLASS_C["openspace"] == 0.15        # > 70% irrigated grass

    def test_bare_sand_is_the_table_3_9_sum(self):
        """未开发沙地 = 平缓 0.14 + 深厚砂土 0.06 + 无植被 0.16 + 一般滞蓄 0.08。"""
        assert BARE_C == pytest.approx(0.14 + 0.06 + 0.16 + 0.08)


class TestAreaIsNotDoubleCounted:
    def test_parts_sum_back_to_the_cell(self):
        r = run(row(
            cell_m2=100_000.0, bldg_m2=20_000.0, road_m2=30_000.0,
            plot_m2=40_000.0, bare_m2=10_000.0,
        ))
        total = (
            r.bldg_m2 + r.road_m2 + r.parking_m2 + r.pedestrian_m2
            + r.landscape_m2 + r.plot_m2 + r.bare_m2
        )
        assert total == pytest.approx(r.area_cell_ha * 1e4, abs=1.0)

    def test_bare_land_is_excluded_from_the_headline_area(self):
        """沙地单列，不进 A —— 要对照就看 area_incl_bare_ha。"""
        r = run(row(cell_m2=100_000.0, road_m2=60_000.0, bare_m2=40_000.0))
        assert r.area_ha == pytest.approx(6.0)
        assert r.area_bare_ha == pytest.approx(4.0)
        assert r.area_incl_bare_ha == pytest.approx(10.0)

    def test_coincident_points_split_the_cell(self):
        """两个点落在同一个 Voronoi 单元时面积对半分，不能各算一遍。"""
        one = run(row(cell_m2=100_000.0, road_m2=100_000.0))
        two = run(row(cell_m2=100_000.0, road_m2=100_000.0, share_n=2))
        assert two.area_ha == pytest.approx(one.area_ha / 2)


class TestRunoffCoefficient:
    def test_all_asphalt_is_090(self):
        assert run(row()).runoff_c == pytest.approx(0.90)

    def test_composite_is_area_weighted(self):
        parts = {"bldg": 4000.0, "landscape": 6000.0}
        c_dev, _ = _weighted_c(parts, plot_c=0.20)
        assert c_dev == pytest.approx((4000 * 0.85 + 6000 * 0.15) / 10000)

    def test_plot_remainder_follows_land_use(self):
        """同样的几何，住宅地块和商业地块不能算出同一个 C。"""
        r = row(cell_m2=100_000.0, road_m2=0.0, plot_m2=100_000.0)
        residential = run(r, classes={"residential": 100_000.0})
        commercial = run(r, classes={"commercial": 100_000.0})
        assert residential.runoff_c == pytest.approx(PLOT_CLASS_C["residential"])
        assert commercial.runoff_c == pytest.approx(PLOT_CLASS_C["commercial"])
        assert commercial.runoff_c > residential.runoff_c

    def test_bare_only_moves_the_alternate_column(self):
        r = run(row(cell_m2=100_000.0, road_m2=50_000.0, bare_m2=50_000.0))
        assert r.runoff_c == pytest.approx(0.90)                       # 只算已开发部分
        assert r.runoff_c_incl_bare == pytest.approx((0.90 + BARE_C) / 2)


class TestTimeOfConcentration:
    def test_entry_time_floor_is_the_adqcc_ten_minutes(self):
        """不透水汇水区入网时间下限 10 分钟（ADQCC §3.2.3），密网也不能更短。"""
        r = run(row(pipe_len_m=50_000.0))      # 管网极密 → 坡面流长趋近 0
        assert r.tc_entry_min == pytest.approx(MIN_ENTRY_MIN)

    def test_tc_is_entry_plus_pipe_travel(self):
        r = run(row())
        assert r.tc_min == pytest.approx(r.tc_entry_min + r.tc_pipe_min, abs=0.15)
        assert r.tc_pipe_min > 0

    def test_no_pipes_means_all_overland(self):
        """单元内没有管的点全程按坡面流走，流程长等于最长流径。"""
        r = run(row(pipe_len_m=None, dia_med_mm=None, slope_med=None), dem=0.003)
        assert r.overland_m == pytest.approx(r.flow_path_m)
        assert r.tc_pipe_min == 0.0
        assert r.pipe_velocity_ms is None

    def test_tc_is_clamped_and_flagged_past_the_rational_limit(self):
        """推理公式法 tc < 30 min 的适用上限要标出来，不能悄悄超。"""
        r = run(row(pipe_len_m=None, dia_med_mm=None, slope_med=None,
                    bldg_m2=0.0, road_m2=0.0, plot_m2=195_000.0), dem=0.0)
        assert r.tc_min <= TC_MAX_CLAMP
        assert r.tc_exceeds_rational is (r.tc_min > 30.0)

    def test_pipe_velocity_follows_manning_with_n_0015(self):
        v = _pipe_velocity(300.0, 0.0025)
        expected = (1 / 0.015) * (0.3 / 4) ** (2 / 3) * math.sqrt(0.0025)
        assert v == pytest.approx(expected)

    def test_paved_surfaces_shed_faster_than_unpaved(self):
        assert _overland_velocity(1.0, 0.005) > _overland_velocity(0.0, 0.005)


class TestBasisIsNotFudged:
    def test_no_land_use_data_falls_back_to_the_profile(self):
        r = run(row(), nearest=9_000.0)
        assert r.basis == "assumed_no_landuse"
        assert (r.area_ha, r.runoff_c, r.tc_min) == (12.0, 0.75, 20.0)

    def test_missing_nearest_plot_is_treated_as_no_data(self):
        assert run(row(), nearest=None).basis == "assumed_no_landuse"

    def test_empty_desert_cell_is_a_measurement_not_an_assumption(self):
        """周边确实没有城市下垫面 —— 这是实测结论，按整单元的沙地口径算。"""
        r = run(row(road_m2=0.0, bare_m2=195_000.0))
        assert r.basis == "measured_undeveloped"
        assert r.area_ha == pytest.approx(19.5)
        assert r.runoff_c == pytest.approx(BARE_C)

    def test_slope_prefers_measured_pipe_gradient_over_dem(self):
        assert run(row(), dem=0.02).slope_basis == "pipe"
        assert run(row(slope_med=None), dem=0.02).slope_basis == "dem"
        assert run(row(slope_med=None), dem=None).slope_basis == "fallback"


class TestPrioritySuggestion:
    def test_split_is_the_table_3_3_fifty_percent_line(self):
        assert _priority(0.50, "residential") == "HIGH_DENSITY"
        assert _priority(0.49, "residential") == "LOW_DENSITY"

    def test_land_use_overrides_the_density_split(self):
        assert _priority(0.95, "industrial") == "INDUSTRIAL"
        assert _priority(0.95, "openspace") == "OPEN_AREA"


class TestCellGeometry:
    def test_flow_path_never_exceeds_the_cut_radius(self):
        assert run(row()).flow_path_m <= CELL_RADIUS_M
