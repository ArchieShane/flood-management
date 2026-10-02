"""ANUGA 成果反算逐点积水量的批算（ponding_batch.py）。

这个量项目里此前完全没有，最容易悄悄出错的是四件事：

1. **填洼必须真的封住**：priority-flood 出错会让洼地漏成一片，或者反过来把整个
   区判成一个大坑。填洼后的 DEM 处处不低于原 DEM，且出口种子高程不变。
2. **切分必须不重不漏**：一个洼地里有几个台账点时，各点拿到的格子互不相交，
   并起来覆盖整个洼地。少一格就少算水，多一格就重复计。
3. **共用洼地的成员不能被切成 0**：`汇流` 成员不在洼地内，只按洼地格切会让
   靠外的那个一格都分不到（ADM-380 踩过）。每个成员至少拿到自己那一格。
4. **落定时刻的语义不能反**：`settled_volume_m3` 取的是 `SETTLE_MINUTES` 之后的
   峰值，必须不大于全程峰值，否则两个口径就混了。
5. **净累计进水不能退化成峰值**：Al Bateen 这场雨恰好逐点单峰，两者相等，很容易把
   实现写成直接取峰值而不自知 —— 换一场双峰的雨就会少算第二次上涨的水。
"""

import numpy as np
import pytest

from stormwater.ponding_batch import (
    DEPRESSION_MIN_DEPTH_M,
    _fill_depressions,
    _flow_terminals,
    _label_depressions,
    _series_metrics,
    _split_shared,
    find_settle_time,
)


@pytest.fixture
def bowl():
    """5×5 自西向东升高的斜面（10→14 m），在 (2,3) 挖一个闭合坑。

    坑底 11 m，西邻 12 m、东邻 14 m —— 四周都比它高，水进得去出不来，
    溢流高程是最低邻格的 12 m，故填洼深度应为 1 m。
    """
    dem = np.tile(10.0 + np.arange(5, dtype=float), (5, 1))
    dem[2, 3] = 11.0
    land = np.ones((5, 5), bool)
    return dem, land


def test_fill_never_lowers_terrain(bowl):
    dem, land = bowl
    filled = _fill_depressions(dem, land)
    assert np.all(filled >= dem - 1e-9), "填洼只能抬高地面"


def test_fill_seals_the_pit(bowl):
    """坑被填到溢流高程，坑外一格不动。"""
    dem, land = bowl
    filled = _fill_depressions(dem, land)
    assert filled[2, 3] == pytest.approx(12.0)
    outside = np.ones((5, 5), bool)
    outside[2, 3] = False
    assert filled[outside] == pytest.approx(dem[outside])


def test_single_depression_labelled(bowl):
    dem, land = bowl
    depth = _fill_depressions(dem, land) - dem
    label = _label_depressions(depth)
    assert label.max() == 0, "只有一个坑"
    assert label[2, 3] == 0
    assert (label == 0).sum() == 1


def test_flat_terrain_has_no_depression():
    """没有坑就不该凭空标出洼地 —— 噪声阈值是 DEPRESSION_MIN_DEPTH_M。"""
    dem = np.tile(10.0 + np.arange(5, dtype=float), (5, 1))
    land = np.ones((5, 5), bool)
    depth = _fill_depressions(dem, land) - dem
    assert depth.max() <= DEPRESSION_MIN_DEPTH_M
    assert _label_depressions(depth).max() == -1


def test_slope_cells_route_into_the_pit(bowl):
    """坑正东那一格地势更高，D8 应把它送进坑里，而不是判成直排。"""
    dem, land = bowl
    filled = _fill_depressions(dem, land)
    label = _label_depressions(filled - dem)
    term = _flow_terminals(filled, land, label)
    assert term[2, 3] == 0, "坑自身"
    assert term[2, 4] == 0, "东侧高地应汇入坑"
    assert term[2, 0] == -1, "西边界格直排出区"
    assert term[2, 2] == -1, "坑西侧地势更低的一路，顺坡直排，不进坑"


def test_split_partitions_without_overlap():
    """两点共用一个 4 格洼地：各自拿到的格子不相交，并起来正好是洼地。"""
    label = np.full((3, 6), -1, np.int32)
    label[1, 1:5] = 0
    points = [
        {"uid": "A", "depression_id": 0, "row": 1, "col": 1, "cell_id": 1 * 6 + 1},
        {"uid": "B", "depression_id": 0, "row": 1, "col": 4, "cell_id": 1 * 6 + 4},
    ]
    owned = _split_shared(points, label, width=6)
    a, b = owned["A"], owned["B"]
    assert not set(a.tolist()) & set(b.tolist()), "不能重复计"
    assert set(a.tolist()) | set(b.tolist()) == set(np.where(label.ravel() == 0)[0].tolist())


def test_split_never_starves_a_member():
    """B 在洼地外、紧挨着 A —— 只切洼地格会让它拿到 0 格（ADM-380 的坑）。"""
    label = np.full((3, 6), -1, np.int32)
    label[1, 1:3] = 0
    points = [
        {"uid": "A", "depression_id": 0, "row": 1, "col": 1, "cell_id": 1 * 6 + 1},
        {"uid": "B", "depression_id": 0, "row": 1, "col": 3, "cell_id": 1 * 6 + 3},
    ]
    owned = _split_shared(points, label, width=6)
    assert len(owned["B"]) >= 1
    assert 1 * 6 + 3 in owned["B"].tolist(), "至少要拿到自己那一格"
    assert not set(owned["A"].tolist()) & set(owned["B"].tolist())


def test_settled_peak_never_exceeds_overall_peak():
    times = np.array([0.0, 100.0, 200.0, 300.0, 400.0])
    series = np.array([0.0, 500.0, 900.0, 300.0, 50.0])
    m = _series_metrics(series, times, settle=285.0)
    assert m["peak_volume_m3"] == pytest.approx(900.0)
    assert m["peak_time_min"] == 200.0
    assert m["settled_volume_m3"] == pytest.approx(300.0)
    assert m["settled_volume_m3"] <= m["peak_volume_m3"]


def test_drain_time_is_first_zero_after_peak():
    times = np.array([0.0, 15.0, 30.0, 45.0, 60.0])
    series = np.array([0.0, 10.0, 40.0, 0.0, 0.0])
    m = _series_metrics(series, times, settle=0.0)
    assert m["drain_time_min"] == 45.0


def test_volume_hours_is_trapezoid_in_hours():
    """∫V dt 用小时，不是分钟 —— 差 60 倍，排泵车时会一路错下去。"""
    times = np.array([0.0, 60.0, 120.0])
    series = np.array([0.0, 120.0, 0.0])  # 三角形，底 2 h、高 120 m³
    m = _series_metrics(series, times, settle=0.0)
    assert m["volume_hours_m3h"] == pytest.approx(120.0)


def test_settle_time_is_when_ponds_stop_overtopping():
    """洼地内蓄水回落到静态容积以下的那一帧。"""
    label = np.full((1, 3), -1, np.int32)
    label[0, 1] = 0
    times = np.array([0.0, 15.0, 30.0, 45.0])
    depth = np.array([[0.0, 1.0, 0.0], [0.0, 5.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.5, 0.0]])
    settle = find_settle_time(depth, times, label, capacity_total=2.0 * 400, cell_area=400.0)
    assert settle == 45.0, "30 min 那帧还有 1200 m³ > 800 m³ 容积，要等到 45 min"


def test_net_inflow_equals_peak_for_single_peak():
    """单峰过程：净累计进水量就是峰值。多峰才会大于峰值。"""
    times = np.array([0.0, 15.0, 30.0, 45.0, 60.0])
    single = np.array([0.0, 40.0, 100.0, 30.0, 0.0])
    assert _series_metrics(single, times, settle=0.0)["net_inflow_m3"] == pytest.approx(100.0)


def test_net_inflow_sums_every_rise_when_multi_peak():
    """双峰：两次上涨都要计入，否则第二场雨的水凭空消失。"""
    times = np.array([0.0, 15.0, 30.0, 45.0, 60.0])
    twin = np.array([0.0, 100.0, 20.0, 70.0, 0.0])
    m = _series_metrics(twin, times, settle=0.0)
    assert m["peak_volume_m3"] == pytest.approx(100.0)
    assert m["net_inflow_m3"] == pytest.approx(150.0), "100 涨 + 50 再涨"
    assert m["net_inflow_m3"] > m["peak_volume_m3"]
