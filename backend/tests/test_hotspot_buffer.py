"""热点 200 m 圆内的地表峰值积水量与圆重叠（hotspot_buffer.py）：用合成网格对账，不依赖成果目录。"""
import math

import numpy as np
import pytest

from stormwater import hotspot_buffer as hb


def _grid(n=100, edge=10.0):
    """n×n 个 edge m 见方的单元，形心从 (5,5) 起；3 帧：水深 0 → 0.10 / 0.30 的两块 → 0.05 / 0.40。"""
    g = (np.arange(n) + 0.5) * edge
    xy = np.array([(x, y) for y in g for x in g])
    area = np.full(len(xy), edge * edge)
    F = np.zeros((3, len(xy)), np.float32)
    F[1] = np.where(xy[:, 0] < 500, 0.30, 0.10)
    F[2] = np.where(xy[:, 0] < 500, 0.05, 0.40)
    return xy, area, F, np.array([0.0, 1.0, 2.0])


def _ref(xy, area, F, c, depth, r=200.0, skip=None):
    m = np.hypot(xy[:, 0] - c[0], xy[:, 1] - c[1]) <= r
    if skip is not None:
        m &= ~skip
    Fc = F[:, m].astype(float)
    return int(round((np.where(Fc >= depth, Fc, 0) * area[m]).sum(1).max()))


def test_single_hotspot_matches_bruteforce_and_threshold():
    xy, area, F, t = _grid()
    h = np.array([[250.0, 250.0]])
    for d in (0.05, 0.15, 0.35):
        r = hb.buffer_stats(xy, area, F, t, h, ["H1"], d)
        assert r["hotspots"][0]["vol_peak_m3"] == _ref(xy, area, F, h[0], d)
    lo = hb.buffer_stats(xy, area, F, t, h, ["H1"], 0.05)["hotspots"][0]["vol_peak_m3"]
    hi = hb.buffer_stats(xy, area, F, t, h, ["H1"], 0.15)["hotspots"][0]["vol_peak_m3"]
    assert hi <= lo                                        # 阈值越高量越小
    assert r["hotspots"][0]["overlap_with"] == []


def test_peak_is_max_over_frames_not_sum():
    xy, area, F, t = _grid()
    r = hb.buffer_stats(xy, area, F, t, np.array([[250.0, 250.0]]), ["H1"], 0.15)["hotspots"][0]
    assert r["t_peak_h"] == 1.0                            # 第 1 帧圆内全 0.30
    assert r["hmax_m"] == pytest.approx(0.30)              # 圆（x 50–450）都在 x<500 一侧，0.40 那块在圆外


def test_overlap_pair_union_and_double_count():
    xy, area, F, t = _grid()
    h = np.array([[250.0, 250.0], [350.0, 250.0], [800.0, 800.0]])
    r = hb.buffer_stats(xy, area, F, t, h, ["A", "B", "C"], 0.15)
    assert r["n_pairs"] == 1 and r["n_overlap_hotspots"] == 2
    p = r["pairs"][0]
    assert {p["a"], p["b"]} == {"A", "B"} and p["dist_m"] == 100
    assert p["lens_area_m2"] == int(round(hb.lens_area(100.0, 200.0)))
    a, b = r["hotspots"][0], r["hotspots"][1]
    assert a["overlap_with"] == ["B"] and b["overlap_with"] == ["A"]
    # 并集每个单元只算一次，所以小于直接相加；重复量 = 相加 − 并集
    assert r["union"]["vol_peak_m3"] < r["sum_vol_peak_m3"]
    assert r["double_count_m3"] == r["sum_vol_peak_m3"] - r["union"]["vol_peak_m3"]
    assert a["vol_exclusive_peak_m3"] <= a["vol_peak_m3"]
    assert r["hotspots"][2]["overlap_with"] == []


def test_identical_hotspots_fully_overlap():
    xy, area, F, t = _grid()
    h = np.array([[250.0, 250.0], [250.0, 250.0]])
    r = hb.buffer_stats(xy, area, F, t, h, ["A", "B"], 0.15)
    assert r["pairs"][0]["lens_pct"] == 100.0
    assert r["union"]["vol_peak_m3"] == r["hotspots"][0]["vol_peak_m3"]


def test_skip_cells_are_not_counted():
    xy, area, F, t = _grid()
    h = np.array([[250.0, 250.0]])
    skip = xy[:, 0] < 250
    r = hb.buffer_stats(xy, area, F, t, h, ["H1"], 0.15, skip=skip)["hotspots"][0]
    assert r["vol_peak_m3"] == _ref(xy, area, F, h[0], 0.15, skip=skip)
    assert r["excluded_area_m2"] > 0


def test_lens_area_limits():
    assert hb.lens_area(400.0, 200.0) == 0.0
    assert hb.lens_area(0.0, 200.0) == pytest.approx(math.pi * 200 ** 2)


def test_points_in_polygons():
    sq = np.array([[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], float)
    x, y = np.array([5.0, 15.0, 5.0]), np.array([5.0, 5.0, -1.0])
    assert hb.points_in_polygons(x, y, [sq]).tolist() == [True, False, False]


def test_depth_limits():
    with pytest.raises(ValueError):
        hb.check_depth(0.01)
