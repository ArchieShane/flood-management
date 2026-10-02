"""单点多情景接口（`/api/point-curve`）—— 页面默认交互的供数口径。

页面现在是「点一个积水点，看它在 5 / 10 / 25 / 50 / 100 年一遇下各是什么结论」。
这条接口最容易悄悄出错的是两件事，逐一锁死：

1. **不能算出两套数**：同一个点、同一场雨，单点接口与全域批算必须逐字段相等 ——
   否则指挥员在两个页面上会看到两个答案。
2. **「撑到第几级」不能猜**：`first_line3_rp` 必须是真正第一个触发第三道的重现期；
   自定义雨没有级差，必须是 null，不能拿占位的 0 冒充。
"""

import pytest
from fastapi.testclient import TestClient

from stormwater.api.main import app
from stormwater.idf import FLEET_RETURN_PERIODS
from stormwater.registry import load_registry
from stormwater.scenario import BatchOptions, run_batch


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def sample_uid():
    """取一个落在有管网数据区域内、且会触发第三道的点。"""
    for r in load_registry():
        if r.in_coverage and r.qcap_basis == "measured_no_network":
            return r.uid
    pytest.skip("台账里没有可用于本测试的点")


class TestPointCurve:
    def test_returns_one_row_per_return_period(self, client, sample_uid):
        d = client.post("/api/point-curve", json={"uid": sample_uid}).json()
        assert [r["return_period_yr"] for r in d["scenarios"]] == list(
            FLEET_RETURN_PERIODS
        )

    def test_rows_match_the_batch_run_field_by_field(self, client, sample_uid):
        """单点接口与全域批算不能算出两套数。"""
        record = next(r for r in load_registry() if r.uid == sample_uid)
        d = client.post("/api/point-curve", json={"uid": sample_uid}).json()
        for row in d["scenarios"]:
            batch = run_batch(
                [record], BatchOptions(return_period_yr=row["return_period_yr"])
            )["points"][0]
            for field, value in batch.items():
                assert row[field] == value, f"{field} 在 {row['return_period_yr']} 年一遇对不上"

    def test_bigger_storm_never_yields_less_water(self, client, sample_uid):
        """雨越大峰值流量越大 —— 锁在 `peak_flow_m3s` 上。

        ⚠ 不能锁 `runoff_volume_m3`：第一道防线改读二维演算时程之后，那一列
        只有与演算 run 同重现期的那一档有值，其余为 None（见下一个用例）。
        """
        rows = client.post("/api/point-curve", json={"uid": sample_uid}).json()["scenarios"]
        flows = [r["peak_flow_m3s"] for r in rows]
        assert flows == sorted(flows)

    def test_only_the_simulated_return_period_gets_a_defence_conclusion(
        self, client, sample_uid
    ):
        """演算是按某一场雨跑的 —— 重现期对不上就不出结论，不拿它当别的雨用。

        当前唯一的 run 是 100 年一遇，所以这条曲线上最多只有那一档有防线结论；
        该点若根本没跑过演算，则五档全是「无标定」。两种情形都不许出数字。
        """
        rows = client.post("/api/point-curve", json={"uid": sample_uid}).json()["scenarios"]
        for row in rows:
            if row["return_period_yr"] != 100:
                assert row["l1_basis"] == "uncalibrated"
                assert row["line"] is None and row["runoff_volume_m3"] is None
            # 峰值诊断不依赖演算，每一档都该有
            assert row["peak_flow_m3s"] > 0

    def test_first_line3_rp_is_the_lowest_one_that_needs_the_fleet(
        self, client, sample_uid
    ):
        d = client.post("/api/point-curve", json={"uid": sample_uid}).json()
        needs = [r["return_period_yr"] for r in d["scenarios"] if r["line"] == 3]
        assert d["first_line3_rp"] == (needs[0] if needs else None)

    def test_custom_storm_has_no_ladder_to_climb(self, client, sample_uid):
        """自定义雨只有一场，没有「撑到第几级」可言 —— 该字段必须是 null。"""
        d = client.post(
            "/api/point-curve",
            json={
                "uid": sample_uid,
                "dataset": "custom_storm",
                "custom_depth_mm": 50,
                "custom_duration_min": 120,
            },
        ).json()
        assert len(d["scenarios"]) == 1
        assert d["scenarios"][0]["dataset_key"] == "custom_storm"
        assert d["first_line3_rp"] is None

    def test_points_outside_the_network_coverage_say_so(self, client):
        """区域外的点照算，但必须自报「这不是实测」—— 页面据此挂警示。"""
        uid = next(r.uid for r in load_registry() if not r.in_coverage)
        d = client.post("/api/point-curve", json={"uid": uid}).json()
        assert d["in_scope"] is False
        assert d["scenarios"][0]["qcap_basis"].startswith(("assumed", "ledger"))

    def test_unknown_uid_is_a_404(self, client):
        assert client.post("/api/point-curve", json={"uid": "没有这个点"}).status_code == 404
