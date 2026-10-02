"""SWMM 演算成果反推 Qcap 的解析、归并与口径开关测试。

这套测试有两个职责，第二个比第一个重要：

1. 守住 `swmm_batch.py` 的解析与归并逻辑；
2. **守住「SWMM 口径默认关闭」这件事**。那份模型的管道内底 = DEM 地面减固定
   1.10 m，坡度即地形坡度，满流能力同管对照中位高估 2.4 倍。谁要是把它设成
   默认，`test_swmm_source_is_opt_in` 和 `test_swmm_is_systematically_optimistic`
   会一起红。理由见 `swmm_batch.py` 模块头注释。
"""

import csv
from dataclasses import replace
from pathlib import Path

import pytest

from stormwater.registry import (
    DEFAULT_PROFILES,
    HOTSPOT_QCAP_SWMM_CSV,
    CatchmentProfile,
    build_hotspot,
    load_registry,
    qcap_basis_for,
    resolve_qcap,
)
from stormwater.swmm_batch import (
    LOCAL_MAIN_CLASSES,
    MIN_FLOW_RATIO,
    SEARCH_RADIUS_M,
    SwmmLink,
    _read_link_flow,
    summarise,
)

RPT_SAMPLE = """\
  Link Flow Summary
  ********************

  -----------------------------------------------------------------------------
                                 Maximum  Time of Max   Maximum    Max/    Max/
                                  |Flow|   Occurrence   |Veloc|    Full    Full
  Link                 Type          CMS  days hr:min     m/sec    Flow   Depth
  -----------------------------------------------------------------------------
  c_1                  CONDUIT     0.100     0  00:05      1.51    0.35    1.00
  c_22                 CONDUIT     2.127     0  00:05     27.29    8.44    1.00
  p_9                  PUMP        0.500     0  00:05      0.00    0.00    0.00


  ***********************
  Flow Classification Summary
  ***********************
  c_1  ignored
"""


def _link(link_id="c_1", qfull=1.0, cls_ok=True, method="back_calculated", **kw):
    return SwmmLink(
        link_id=link_id, cx=kw.get("cx", 0.0), cy=kw.get("cy", 0.0),
        diameter_m=kw.get("diameter_m", 0.3), qfull_m3s=qfull,
        method=method, max_full_flow=kw.get("max_full_flow", 0.5),
    )


def _seg(gid=1, main_class="LATERAL", distance_m=10.0):
    return {"gid": gid, "main_class": main_class, "distance_m": distance_m,
            "cx": 0.0, "cy": 0.0, "diameter_mm": 300.0}


class TestReportParsing:
    def test_reads_conduits_and_stops_at_next_section(self, tmp_path: Path):
        f = tmp_path / "x.rpt"
        f.write_text(RPT_SAMPLE)
        flows = _read_link_flow(f)
        assert flows == {"c_1": (0.100, 0.35), "c_22": (2.127, 8.44)}

    def test_pumps_are_excluded(self, tmp_path: Path):
        """管段满流能力只对 CONDUIT 有意义；这批模型本来也没有泵。"""
        f = tmp_path / "x.rpt"
        f.write_text(RPT_SAMPLE)
        assert "p_9" not in _read_link_flow(f)

    def test_back_calculation_recovers_full_flow(self, tmp_path: Path):
        """Q_full = Q_max ÷ (Max/Full Flow) —— 反推的核心恒等式。"""
        f = tmp_path / "x.rpt"
        f.write_text(RPT_SAMPLE)
        qmax, ratio = _read_link_flow(f)["c_22"]
        assert qmax / ratio == pytest.approx(0.252, abs=0.001)


class TestSummarise:
    def test_picks_largest_local_class_pipe(self):
        pairs = [
            (_seg(1, "LATERAL"), _link("c_1", 0.4)),
            (_seg(2, "SECONDARY"), _link("c_2", 1.1)),
            (_seg(3, "TRUNK_MAIN"), _link("c_3", 9.9)),
        ]
        r = summarise("ADM-001", pairs, n_segments=3)
        assert r.qcap_m3s == 1.1
        assert r.qcap_source_class == "SECONDARY"
        assert r.basis == "swmm"

    def test_trunk_main_only_counts_in_the_diagnostic_column(self):
        """过路干管不代表这个点的水进得去 —— 与 `qcap_batch.py` 同口径。"""
        pairs = [(_seg(3, "TRUNK_MAIN"), _link("c_3", 9.9))]
        r = summarise("ADM-001", pairs, n_segments=1)
        assert r.qcap_m3s is None
        assert r.qcap_any_class_m3s == 9.9
        assert r.basis == "no_local_class"

    def test_pipes_present_but_outside_swmm_model(self):
        r = summarise("ADM-001", [], n_segments=7)
        assert r.basis == "out_of_model"
        assert r.qcap_m3s is None

    def test_no_pipes_within_radius(self):
        r = summarise("AAM-001", [], n_segments=0)
        assert r.basis == "no_pipes"

    def test_manning_fallback_share_is_reported(self):
        pairs = [
            (_seg(1), _link("c_1", 0.4, method="back_calculated")),
            (_seg(2), _link("c_2", 0.2, method="manning_from_inp")),
        ]
        assert summarise("ADM-001", pairs, 2).manning_fallback_share == 0.5


class TestCalibrationConstants:
    def test_radius_and_classes_match_the_manning_batch(self):
        """两套 Qcap 必须同口径才可比 —— 半径和干管等级不许各走各的。"""
        from stormwater import qcap_batch

        assert SEARCH_RADIUS_M == qcap_batch.SEARCH_RADIUS_M
        assert LOCAL_MAIN_CLASSES == qcap_batch.LOCAL_MAIN_CLASSES

    def test_min_flow_ratio_bounds_rounding_error(self):
        """`Max/Full Flow` 只印两位小数，±0.005 的舍入在门槛处不超过 ±10%。"""
        assert 0.005 / MIN_FLOW_RATIO <= 0.10


@pytest.mark.skipif(
    not HOTSPOT_QCAP_SWMM_CSV.exists(), reason="未跑过 swmm_batch.py 批算"
)
class TestSourceSwitch:
    def test_swmm_source_is_opt_in(self):
        """默认必须是 manning。改默认 = 悄悄让全项目的结论偏乐观。"""
        record = next(r for r in load_registry() if r.qcap_swmm_m3s is not None)
        profile = CatchmentProfile()
        assert resolve_qcap(record, profile)[1] != "swmm"
        assert resolve_qcap(record, profile, qcap_source="swmm") == (
            record.qcap_swmm_m3s,
            "swmm",
        )

    def test_basis_label_travels_with_the_value(self):
        record = next(r for r in load_registry() if r.qcap_swmm_m3s is not None)
        assert qcap_basis_for(record, DEFAULT_PROFILES, qcap_source="swmm") == "swmm"
        assert qcap_basis_for(record, DEFAULT_PROFILES) != "swmm"

    def test_points_outside_the_model_fall_back_to_manning(self):
        """SWMM 只覆盖阿布扎比岛及周边，域外的点不能因为切口径就丢掉 Qcap。"""
        record = next(
            r for r in load_registry()
            if r.qcap_swmm_m3s is None and r.qcap_measured_m3s is not None
        )
        assert resolve_qcap(record, CatchmentProfile(), qcap_source="swmm") == (
            record.qcap_measured_m3s,
            "measured",
        )

    def test_build_hotspot_honours_the_switch(self):
        record = next(
            r for r in load_registry()
            if r.qcap_swmm_m3s is not None
            and r.qcap_measured_m3s is not None
            and r.qcap_swmm_m3s != r.qcap_measured_m3s
        )
        assert build_hotspot(record, DEFAULT_PROFILES).qcap_m3s == record.qcap_measured_m3s
        assert build_hotspot(
            record, DEFAULT_PROFILES, qcap_source="swmm"
        ).qcap_m3s == record.qcap_swmm_m3s

    def test_swmm_is_systematically_optimistic(self):
        """钉住「为什么默认关着」：SWMM 的坡度是地形坡度，Qcap 中位高出一倍以上。

        这条断言红了不代表代码坏了 —— 代表那份 SWMM 成果换了一版，
        该回去重读 `swmm_batch.py` 里那张同管对照表再决定默认口径。
        """
        pairs = [
            (r.qcap_swmm_m3s, r.qcap_measured_m3s)
            for r in load_registry()
            if r.qcap_swmm_m3s is not None and r.qcap_measured_m3s
        ]
        assert len(pairs) > 300
        ratios = sorted(s / m for s, m in pairs)
        assert ratios[len(ratios) // 2] > 2.0


@pytest.mark.skipif(
    not HOTSPOT_QCAP_SWMM_CSV.exists(), reason="未跑过 swmm_batch.py 批算"
)
class TestBatchOutput:
    def test_coverage_partition_matches_the_manning_batch(self):
        """SWMM 拿不到值的点，在 manning 那边要么也没管，要么是模型域外。

        两份 CSV 的 `pipes_in_radius` 同源（同一句 st_dwithin），
        对不上说明有一边的半径或过滤条件被人改了。
        """
        from stormwater.registry import HOTSPOT_QCAP_CSV

        sw = {r["uid"]: r for r in csv.DictReader(HOTSPOT_QCAP_SWMM_CSV.open())}
        mn = {r["uid"]: r for r in csv.DictReader(HOTSPOT_QCAP_CSV.open())}
        assert sw.keys() == mn.keys()
        for uid, row in sw.items():
            if row["basis"] == "no_pipes":
                assert mn[uid]["basis"] in ("no_coverage", "measured_no_network")

    def test_every_value_carries_its_method_and_source_pipe(self):
        for row in csv.DictReader(HOTSPOT_QCAP_SWMM_CSV.open()):
            if not row["qcap_m3s"]:
                continue
            assert row["qcap_source_link"]
            assert row["qcap_source_class"] in LOCAL_MAIN_CLASSES
            assert row["qcap_source_method"] in ("back_calculated", "manning_from_inp")
