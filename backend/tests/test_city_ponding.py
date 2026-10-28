"""全市一二维任务的模拟积水点（`city_ponding`）：和交付自带的热点统计对账。没抽过 `points/`（缺 .sww 的网格邻接）时整体 skip。"""

import pytest

from stormwater import city_ponding
from stormwater.sim_sww import OUT_ROOT

PDIR = OUT_ROOT / "ADM_City_61mm1h_100m_after" / city_ponding.POINTS_DIR
pytestmark = pytest.mark.skipif(not (PDIR / city_ponding.SOURCE_FILE).is_file(), reason="没有 ADM 全市的 points/（先跑 city_ponding prepare）")


def _cover(state, depth):
    r = city_ponding.ponding_points(str(PDIR), state, depth, 100.0, 0.5)     # 默认阈值同 RD-A / 客户文档
    return r, {h["hotspot"] for p in r["points"] for h in p["near_hotspots"]}


def test_hotspot_bins_follow_client_document():
    """客户文档第二节：热点到最近积水片边界的距离 ≤0 / 50 / 100 / 200 m 的热点个数，逐档累计，且 200 m 档 = 近邻表里的热点数。"""
    for st in ("L1", "L2"):
        r, near = _cover(st, 0.15)
        b = r["hotspot_bins"]
        assert b["total"] == 470 and b["0"] <= b["50"] <= b["100"] <= b["200"] <= 470
        assert b["200"] == len(near)
        assert b["0"] > 0                                  # 有热点就落在积水片里


def test_point_to_triangle_distance():
    import numpy as np
    T = np.array([[[0, 0], [10, 0], [0, 10]]], float)
    for (x, y), want in (((1, 1), 0.0), ((-5, 0), 5.0), ((20, 0), 10.0), ((10, 10), 7.0710678), ((11, -1), 1.4142136)):
        assert abs(float(city_ponding._pt_tri_dist(x, y, T)[0]) - want) < 1e-5


def test_meta_has_470_hotspots_and_36_outside_domain():
    m = city_ponding.meta(PDIR)
    assert m["states"] == ["L1", "L2"] and len(m["hotspots"]) == 470 and len(m["outside_domain"]) == 36


def test_hotspots_flooded_match_delivery_summary():
    """交付 README：≥0.30 m 的热点（200 m 内）L1 50 个、L2 44 个；本模块按形心距离，允许差 1–2 个。"""
    assert abs(len(_cover("L1", 0.30)[1]) - 50) <= 2
    assert abs(len(_cover("L2", 0.30)[1]) - 44) <= 2


def test_peak_fields_are_consistent():
    r, _ = _cover("L1", 0.15)
    assert r["count"] > 0 and r["points"][0]["vol_peak_m3"] >= r["points"][-1]["vol_peak_m3"]
    for p in r["points"][:200]:
        assert 0 < p["area_peak_m2"] <= p["area_m2"] + 1
        assert 0 <= p["t_area_peak_h"] <= p["t_end_h"] and 0 <= p["t_hmax_h"] <= p["t_end_h"] and 0 <= p["t_peak_h"] <= p["t_end_h"]
    assert abs(max(p["hmax_m"] for p in r["points"]) - 3.76) < 0.02       # 交付：L1 全域最大水深 3.765 m


def test_point_series_peaks_match_list():
    """单点过程的曲线峰值 = 清单里的峰值积水量 / 最大面积；清单走 lru 缓存之后连片结果被挤出去也要能补回来。"""
    r, _ = _cover("L1", 0.15)
    for p in r["points"][:3]:
        s = city_ponding.point_series(str(PDIR), "L1", p["id"], 0.15, 100.0, 0.5)
        assert len(s["t_h"]) == len(s["vol_m3"]) == len(s["area_m2"]) == len(s["depth_m"])
        assert abs(max(s["vol_m3"]) - p["vol_peak_m3"]) <= 1 and abs(max(s["area_m2"]) - p["area_peak_m2"]) <= 1
    city_ponding._LABELS.clear()
    assert city_ponding.point_series(str(PDIR), "L1", r["points"][0]["id"], 0.15, 100.0, 0.5)["n_cells"] == r["points"][0]["cells"]
    with pytest.raises(city_ponding.PointsError):
        city_ponding.point_series(str(PDIR), "L1", "SIM-L1-999999", 0.15, 100.0, 0.5)


def test_hotspot_circle_series_peak_matches_buffer():
    """热点单点过程的曲线峰值 = 热点圆内峰值积水量（`hotspot_buffer`）。"""
    buf = city_ponding.hotspot_buffer(str(PDIR), "L1", 0.15)
    for h in buf["hotspots"][:20]:
        s = city_ponding.hotspot_circle_series(str(PDIR), "L1", h["id"], 0.15)
        assert abs(max(s["vol_m3"]) - h["vol_peak_m3"]) <= 1 and s["n_cells"] == h["n_cells"], h["id"]
    with pytest.raises(city_ponding.PointsError):
        city_ponding.hotspot_circle_series(str(PDIR), "L1", "NOPE", 0.15)


def test_params_checked():
    with pytest.raises(ValueError):
        city_ponding.ponding_points(str(PDIR), "L1", 9.0, 100.0, 0.5)
    with pytest.raises(city_ponding.PointsError):
        city_ponding.ponding_points(str(PDIR), "ZZ", 0.15, 100.0, 0.5)
