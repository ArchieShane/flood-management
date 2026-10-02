"""模型识别片区进计算器这条路（model_cluster_batch + model_registry + API 的 source）。

这件事的价值全在「**与台账走的是同一条链**」上，所以测试盯死的也是这个：

1. 107 个片区装配出来的是**同一个 `HotspotRecord` 类型**，故 `run_batch()` 对
   两套点走的是同一段代码 —— 真正跑一遍，逐字段核对算得出来；
2. 五个计算输入里**四项与台账同法**（C / tc / Qcap / 调蓄），只有汇水区边界不同；
   边界的出处必须逐点自述得清楚（`catchment_boundary`），且对照口径并列存着；
3. D8 汇流范围是**一个划分**：各片区的汇流格互不重叠，且各自包含自己的片区格 ——
   重叠就意味着同一块地的水被算了两遍；
4. 推理公式法 × 二维演算的并列对照**只在同一场雨下才允许下结论**，
   重现期不一致时必须把 `comparable` 打成 false，而不是让人以为可以直接比。
"""

import pytest
from fastapi.testclient import TestClient

from stormwater.api.main import app
from stormwater.constants import DEFAULT_ASSUMPTIONS
from stormwater.model_cluster_batch import (
    D8_CELL_TABLE,
    POINTS_TABLE,
    UID_FMT,
    _runs,
    uid_of,
)
from stormwater.model_ponding import load_features
from stormwater.model_registry import MUNICIPALITY, SOURCE, load_model_registry
from stormwater.registry import DEFAULT_PROFILES, load_registry
from stormwater.scenario import BatchOptions, run_batch

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(scope="module")
def records():
    rs = load_model_registry()
    if not rs:
        pytest.skip("本机没有跑过 model_cluster_batch.py")
    return rs


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestUid:
    def test_uid_tracks_rank(self):
        """uid 里的数就是页面上的 `#rank`，两边对不上号这条路就废了。"""
        assert uid_of(1) == "MDL-001"
        assert uid_of(107) == "MDL-107"
        assert UID_FMT.format(7) == "MDL-007"

    def test_prefix_cannot_collide_with_the_ledger(self):
        """`find_record()` 靠前缀区分两套点 —— 撞了就会张冠李戴。"""
        ledger_prefixes = {r.uid.split("-")[0] for r in load_registry()}
        assert "MDL" not in ledger_prefixes


class TestRuns:
    """格子集合 → 逐行连续段。灌库前的压缩，压错了汇流面就画错。"""

    def test_single_row_merges(self):
        import numpy as np

        # 第 2 行的第 3、4、5 列 + 第 7 列 —— 应压成两段
        width = 10
        cells = np.array([2 * width + 3, 2 * width + 4, 2 * width + 5, 2 * width + 7])
        assert _runs(cells, width) == [(2, 3, 5), (2, 7, 7)]

    def test_rows_do_not_merge_across(self):
        import numpy as np

        width = 10
        # 第 0 行末列与第 1 行首列在扁平下标上相邻，但**不是**同一段
        cells = np.array([width - 1, width])
        assert _runs(cells, width) == [(0, width - 1, width - 1), (1, 0, 0)]

    def test_covers_every_cell(self):
        import numpy as np

        rng = np.random.default_rng(0)
        width = 37
        cells = np.unique(rng.integers(0, width * 20, 200))
        covered = {
            r * width + c
            for r, a, b in _runs(cells, width)
            for c in range(a, b + 1)
        }
        assert covered == set(int(x) for x in cells)


class TestRecords:
    def test_same_type_as_the_ledger(self, records):
        """同一个 dataclass —— 这是「同一条计算链」的全部前提。"""
        assert type(records[0]) is type(load_registry()[0])

    def test_one_record_per_cluster(self, records):
        feats = load_features()
        assert len(records) == len(feats)
        assert {r.cluster_rank for r in records} == {f["properties"]["rank"] for f in feats}
        assert all(r.source == SOURCE and r.municipality == MUNICIPALITY for r in records)

    def test_ledger_only_columns_are_left_empty(self, records):
        """严重度、成因、已配泵车、预算是**行政记录**，演算成果里没有对应物 ——
        留空，不许拿演算出来的东西去填。"""
        assert all(r.criticality is None for r in records)
        assert all(r.root_cause is None for r in records)
        assert all(r.pumps_qty is None and r.tankers_qty is None for r in records)
        assert all(r.budget_required_aed is None for r in records)
        assert all(r.network_available is None for r in records)

    def test_every_calculation_input_has_a_source(self, records):
        """A / C / tc / Qcap / 调蓄 —— 五项都要有逐点出处，不能落回剖面假设。"""
        assert all(r.area_measured_ha is not None for r in records)
        assert all(r.runoff_c_measured is not None for r in records)
        assert all(r.tc_measured_min is not None for r in records)
        assert all(r.catchment_basis != "unknown" for r in records)
        assert all(r.qcap_basis != "unknown" for r in records)
        assert all(r.storage_basis != "unknown" for r in records)

    def test_catchment_boundary_is_self_describing(self, records):
        """A 的边界口径与台账不同，必须逐点说得出是哪一种 —— 否则两套的 A
        被人拿去直接比大小，而它们根本不是同一种边界。"""
        assert all(r.catchment_boundary in ("d8_depression", "cluster_only") for r in records)
        # 台账那一路自述成 Voronoi 代理，两边的取值域不重叠
        assert {r.catchment_boundary for r in load_registry()} == {"voronoi_250m"}

    def test_voronoi_comparison_is_kept(self, records):
        """对照口径并列存着 —— 代理偏多少要看得见，不能只给主口径。"""
        with_both = [r for r in records if r.area_voronoi_ha is not None]
        assert len(with_both) == len(records)
        # 实测下来代理整体偏大（107 个片区挤在一个区里，等分会把不汇入的地也算进来）
        d8 = sum(r.area_measured_ha for r in records)
        vor = sum(r.area_voronoi_ha for r in records)
        assert vor > d8

    def test_every_cluster_has_a_simulated_volume(self, records):
        """片区身上最硬的那个量 —— 107 个全覆盖，且不经归属代理。"""
        assert all(r.ponding_net_inflow_m3 is not None for r in records)
        assert all(r.ponding_basis == "cluster" for r in records)
        assert all(r.ponding_rp_yr == 100 for r in records)


class TestHydrodynamicCoverage:
    """第一道防线现在只认二维演算的积水量时程（`defence_basis="hydrodynamic"`）。

    这一改把覆盖率变成了决定性的东西：台账 845 点里只有 18 个跑过演算（2.1%），
    其余 827 个**整块不出结论**；而模型片区 107 个全部跑过（100%）—— 它们本来
    就是从这次演算里识别出来的。片区那一路因此是目前唯一能全员出结论的点集。
    """

    def test_every_cluster_has_a_curve(self, records):
        from stormwater.ponding_curve import curve_for

        assert all(curve_for(r.uid) is not None for r in records)

    def test_curve_carries_a_time_series(self, records):
        """只有汇总没有时程，`state_at()` 插不出 V(T) —— 第一道防线就成了空。"""
        from stormwater.ponding_curve import curve_for

        curves = [curve_for(r.uid) for r in records]
        assert all(c.samples for c in curves), "每个片区都该有逐帧时程"
        assert sum(len(c.samples) for c in curves) > 1000

    def test_uids_do_not_collide_with_the_ledger_curves(self):
        """两套曲线并在同一张表里，uid 撞了就会张冠李戴。"""
        from stormwater.ponding_curve import load_curves, MODEL_PONDING_CSV, MODEL_PONDING_SERIES_CSV

        ledger = set(load_curves())
        model = set(load_curves(MODEL_PONDING_CSV, MODEL_PONDING_SERIES_CSV))
        assert ledger and model
        assert ledger.isdisjoint(model)

    def test_every_cluster_reaches_a_verdict(self, records, client):
        """全员有曲线 ⇒ 全员出结论，一个 `uncalibrated` 都不该有。"""
        d = client.post(
            "/api/scenario", json={"source": "model", "return_period_yr": 100}
        ).json()
        assert d["summary"]["line_counts"].get("uncalibrated", 0) == 0
        assert all(p["runoff_volume_m3"] is not None for p in d["points"])
        assert all(p["l1_basis"] == "hydrodynamic" for p in d["points"])


class TestSameChain:
    """真跑一遍 —— 「同一条计算链」不能只靠类型相同来声称。"""

    def test_batch_computes_every_cluster(self, records):  # noqa: D102
        batch = run_batch(
            list(records),
            BatchOptions(
                dataset="auto",
                return_period_yr=100,
                assumptions=DEFAULT_ASSUMPTIONS,
                profiles=dict(DEFAULT_PROFILES),
            ),
        )
        assert len(batch["points"]) == len(records)
        assert not batch["skipped"], "五项输入齐全，一个都不该被跳过"
        # 逐点输入就是 registry 里那几列，不是剖面假设
        by_uid = {r.uid: r for r in records}
        for p in batch["points"]:
            r = by_uid[p["uid"]]
            assert p["area_ha"] == pytest.approx(r.area_measured_ha)
            assert p["tc_min"] == pytest.approx(r.tc_measured_min)

    def test_point_curve_matches_the_batch(self, client, records):
        """单点曲线与批算逐字段相等 —— 与台账那边由 test_point_curve.py 锁的是同一件事。"""
        uid = records[0].uid
        curve = client.post(
            "/api/point-curve", json={"uid": uid, "return_periods": [100]}
        ).json()
        row = curve["scenarios"][0]
        batch = client.post(
            "/api/scenario", json={"source": "model", "return_period_yr": 100}
        ).json()
        hit = next(p for p in batch["points"] if p["uid"] == uid)
        for k in ("area_ha", "tc_min", "qcap_m3s", "peak_flow_m3s", "runoff_volume_m3",
                  "shortfall_m3", "pumps_required", "line"):
            assert row[k] == pytest.approx(hit[k]), k


class TestApiSource:
    def test_hotspots_switches_set(self, client):
        led = client.get("/api/hotspots?source=ledger").json()
        mdl = client.get("/api/hotspots?source=model").json()
        assert led["source"] == "ledger" and mdl["source"] == "model"
        assert led["count"] == 845
        assert {p["uid"] for p in led["points"]}.isdisjoint({p["uid"] for p in mdl["points"]})
        # 结构相同 —— 页面两路共用同一段载入逻辑全靠这一点
        assert set(led) == set(mdl)

    def test_unknown_source_is_refused(self, client):
        """认不出的 source 报错，**不悄悄退回台账** —— 那会让人对着错的一套下结论。"""
        r = client.post("/api/scenario", json={"source": "nope"})
        assert r.status_code == 422
        assert "nope" in r.json()["detail"]

    def test_scenario_echoes_the_source(self, client):
        d = client.post("/api/scenario", json={"source": "model", "return_period_yr": 25}).json()
        assert d["source"] == "model"
        assert all(p["uid"].startswith("MDL-") for p in d["points"])


class TestPondingCheck:
    """推理公式法 × 二维演算的并列对照。"""

    def test_present_for_both_sources(self, client):
        mdl = client.post(
            "/api/scenario", json={"source": "model", "return_period_yr": 100}
        ).json()["ponding_check"]
        led = client.post(
            "/api/scenario",
            json={"source": "ledger", "return_period_yr": 100,
                  "district": ["ADM / AL BATEEN"]},
        ).json()["ponding_check"]
        assert mdl and led
        # 片区全覆盖；台账只有跑过 ANUGA 的那 18 个
        assert mdl["points"] == 107
        assert led["points"] == 18

    def test_flags_a_different_storm(self, client):
        """页面选 25 年、run 是 100 年 —— 两个数不是同一场雨，必须说破。"""
        same = client.post(
            "/api/scenario", json={"source": "model", "return_period_yr": 100}
        ).json()["ponding_check"]
        diff = client.post(
            "/api/scenario", json={"source": "model", "return_period_yr": 25}
        ).json()["ponding_check"]
        assert same["comparable"] is True
        assert diff["comparable"] is False
        # 演算那一侧不随页面选的级别变 —— 它是那一个 run 的成果
        assert same["anuga_net_inflow_m3"] == diff["anuga_net_inflow_m3"]
        assert same["run_return_period_yr"] == diff["run_return_period_yr"] == 100
        # 推理那一侧自己按 shape × Qp × D 重算，故仍跟着重现期走 ——
        # ⚠ 这一条正是「不能读 runoff_volume_m3」的守门测试：水动力口径下
        # 那一列是演算读出来的 V(T)，两级之间完全相等，这个断言会立刻炸。
        assert diff["rational_runoff_m3"] < same["rational_runoff_m3"]

    def test_absent_where_no_simulation_was_run(self, client):
        """艾因没跑过 ANUGA —— 不给对照块，而不是给一个 0。"""
        d = client.post(
            "/api/scenario",
            json={"source": "ledger", "return_period_yr": 100,
                  "coverage_only": False, "district": ["AAM / AL BATEEN"]},
        ).json()
        assert d.get("ponding_check") is None


class TestWriteScope:
    """本模块会写库。写哪几张表是口径的一部分，改了要有人知道。"""

    def test_table_names_are_namespaced(self):
        assert POINTS_TABLE.startswith("hotspot.")
        assert D8_CELL_TABLE.startswith("hotspot.")
        # 绝不能撞上台账那张点表
        assert POINTS_TABLE != "hotspot.hotspots_845"

    def test_catchment_worktables_do_not_collide(self):
        """两套点各有一套工作表 —— 后缀撞了就会互相覆盖，结果静默串味。"""
        from stormwater.catchment_batch import _work_tables
        from stormwater.model_cluster_batch import D8_SUFFIX, VORONOI_SUFFIX

        ledger = set(_work_tables(""))
        assert ledger.isdisjoint(_work_tables(D8_SUFFIX))
        assert ledger.isdisjoint(_work_tables(VORONOI_SUFFIX))
        assert set(_work_tables(D8_SUFFIX)).isdisjoint(_work_tables(VORONOI_SUFFIX))
