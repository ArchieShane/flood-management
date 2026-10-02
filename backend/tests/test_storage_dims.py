"""第二道防线的深度/尺寸补数：出处分层不能串味。

这一套守的不是数值本身（数值会随 DMT 补数变），而是**口径**：
实测优先于反推、反推优先于目录缺省；假设值不许悄悄混进实测列。
"""

import pytest

from stormwater.storage_batch import summarise
from stormwater.storage_dims import (
    AREA_BANDS,
    DEFAULTS,
    SOURCES,
    assumed_volume_m3,
    resolve_asset,
)


def pond(**kw):
    row = {"kind": "pond", "footprint_m2": 10_000.0, "depth_m": None, "volume_m3": None}
    return row | kw


def soakaway(**kw):
    row = {"kind": "soakaway", "footprint_m2": None, "depth_m": None, "volume_m3": None,
           "dim_diameter": None, "dim_length": None, "dim_width": None}
    return row | kw


class TestCatalogue:
    def test_every_default_cites_a_listed_source(self):
        """目录里的每个数都要能追到 SOURCES 里的一条引文。"""
        for kind, dim in DEFAULTS.items():
            assert dim.source, f"{kind} 没有出处"
            for key in dim.source:
                assert key in SOURCES, f"{kind} 引了不存在的出处 {key}"

    def test_three_levels_are_ordered(self):
        for kind, dim in DEFAULTS.items():
            assert dim.depth_low_m <= dim.depth_typical_m <= dim.depth_high_m, kind

    def test_pond_typical_depth_sits_in_the_adqcc_band(self):
        """明式池的常用深度必须落在 ADQCC §4.14.1(b) 的 1.8–2.4 m 带内。

        它同时是本库 19 个池的实测中位（2.18 m）—— 标准与实测互相印证，
        这一档才敢用。哪天有人把它改到带外，说明依据变了，得改文档。
        """
        assert 1.8 <= DEFAULTS["pond"].depth_typical_m <= 2.4

    def test_soakaway_gravel_surround_is_upside_only(self):
        """渗井默认只计结构空腔，砾石层容量只进乐观上界，不进默认值。"""
        structure, total, depth, area = assumed_volume_m3("soakaway")
        assert total > structure
        assert structure == pytest.approx(area * depth)

    def test_reservoir_area_band_admits_the_small_underground_boxes(self):
        """地下构筑物实测面积 15.7–801 m²，不能套明式池 100 m² 的下限。"""
        assert AREA_BANDS["reservoir"][0] <= 15.7 < AREA_BANDS["pond"][0]


class TestLadder:
    def test_ledger_volume_beats_level_difference(self):
        """两者都在时取台账 volume —— 盖底高差量的是开挖深度，含堤顶超高。"""
        res = resolve_asset(pond(volume_m3=22_000.0, depth_m=4.7))
        assert res.tier == "measured"
        assert res.volume_m3 == 22_000.0
        assert "⚠" in res.reason, "两者相差 2 倍以上却没有在 reason 里点名"

    def test_implausible_ledger_volume_falls_back_to_levels(self):
        """pond #4 的 volume=129 m³ 隐含深度 1.7 cm —— 明显笔误，退回高差。"""
        res = resolve_asset(pond(volume_m3=129.0, depth_m=5.873))
        assert res.tier == "derived"
        assert res.volume_m3 == pytest.approx(10_000.0 * 5.873)

    def test_missing_depth_falls_back_to_catalogue(self):
        res = resolve_asset(pond(volume_m3=0.0, depth_m=0.0))
        assert res.tier == "assumed"
        assert res.depth_m == DEFAULTS["pond"].depth_typical_m

    def test_elevation_masquerading_as_depth_is_rejected(self):
        """把高程当深度的 102–138 m 一律不认，退到目录缺省。"""
        res = resolve_asset(soakaway(depth_m=102.86))
        assert res.tier == "assumed"
        assert res.depth_m == DEFAULTS["soakaway"].depth_typical_m

    def test_ambiguous_soakaway_units_do_not_produce_a_measured_value(self):
        """diameter=160 配 length=2.0：单位自相矛盾，不猜，走目录缺省。"""
        res = resolve_asset(soakaway(dim_diameter=160.0, dim_length=2.0,
                                     dim_width=1.5, depth_m=1.5))
        assert res.tier == "assumed"

    def test_allow_assumed_false_keeps_the_pure_measured_view(self):
        """纯实测口径要能一键切回去 —— 补数不许把旧口径弄丢。"""
        res = resolve_asset(soakaway(depth_m=102.86), allow_assumed=False)
        assert res.volume_m3 is None and res.tier == "rejected"


class TestPerHotspotRollup:
    def test_assumed_volume_never_enters_the_measured_column(self):
        """整点的 available_m3 只装实测/反推；假设量另立一列。"""
        row = summarise("ADM-X", [soakaway(depth_m=0.0)], nearest_any_m=30.0)
        assert row.available_m3 is None
        assert row.assumed_m3 > 0
        assert row.available_with_assumed_m3 == row.assumed_m3
        assert row.basis == "assumed_dimensions"

    def test_mixed_point_reports_both_and_keeps_measured_separable(self):
        row = summarise("ADM-Y", [pond(volume_m3=22_000.0, depth_m=2.2),
                                  soakaway(depth_m=0.0)], nearest_any_m=10.0)
        assert row.available_m3 == 22_000.0
        assert row.assumed_m3 == pytest.approx(5.3, abs=0.05)
        assert row.available_with_assumed_m3 == pytest.approx(22_005.3, abs=0.05)
        assert row.basis == "measured"

    def test_no_facility_and_no_data_stay_two_different_zeros(self):
        """这条是老口径，补数不许把它抹平。"""
        near = summarise("ADM-Z", [], nearest_any_m=900.0)
        far = summarise("AAM-Z", [], nearest_any_m=28_000.0)
        assert near.basis == "no_asset"
        assert far.basis == "no_coverage"
        assert near.available_with_assumed_m3 is None
