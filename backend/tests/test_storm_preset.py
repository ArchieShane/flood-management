"""算之前先摆出来的那一屏（`/api/storm-preset`）—— 页面交互的第二步。

页面现在是「先选点 → 选一级重现期，看清这一级默认落多少雨、落多久 → 再按计算」。
中间那一屏上摆的雨量与历时，**必须就是按下计算后真正用的那两个数**，
否则等于给指挥员看了一份和结果对不上的口径。这里锁死三件事：

1. 预览的历时与强度，与 `/api/point-curve` 同一级的那一行逐字段相等；
2. 逐点输入（A / C / tc / Qcap / 调蓄）与出处标签也一并相等 —— 这一屏在算之前
   就要摆出来，不能算完才知道用的是实测还是假设；
3. 数据集没有的重现期，这一步就要报错，不能让人按了计算才发现算不了。
"""

import pytest
from fastapi.testclient import TestClient

from stormwater.api.main import app
from stormwater.registry import load_registry

PREVIEW_FIELDS = ("duration_min", "intensity_mm_hr")
INPUT_FIELDS = (
    "area_ha", "c_adjusted", "tc_min", "qcap_m3s", "pond_available_m3",
    "catchment_basis", "qcap_basis", "storage_basis",
)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def sample_uid():
    for r in load_registry():
        if r.in_coverage and r.qcap_basis == "measured":
            return r.uid
    pytest.skip("台账里没有可用于本测试的点")


class TestStormPreset:
    @pytest.mark.parametrize("rp", [5, 10, 25, 50, 100])
    def test_preview_matches_what_the_calculation_uses(self, client, sample_uid, rp):
        """摆出来的雨 = 算出来用的雨。这一条一旦破，整个交互就是骗人的。"""
        pre = client.post(
            "/api/storm-preset", json={"uid": sample_uid, "return_period_yr": rp}
        ).json()
        row = client.post(
            "/api/point-curve", json={"uid": sample_uid, "return_periods": [rp]}
        ).json()["scenarios"][0]
        for f in PREVIEW_FIELDS + INPUT_FIELDS:
            assert pre[f] == row[f], f"{f}：预览 {pre[f]} ≠ 计算 {row[f]}"

    def test_depth_is_intensity_times_duration(self, client, sample_uid):
        """雨量 P 是派生量：P = I × D / 60，不是另取一套数。"""
        d = client.post(
            "/api/storm-preset", json={"uid": sample_uid, "return_period_yr": 25}
        ).json()
        assert d["depth_mm"] == pytest.approx(
            d["intensity_mm_hr"] * d["duration_min"] / 60.0, rel=1e-3
        )

    def test_custom_storm_duration_floors_at_tc(self, client, sample_uid):
        """自定义雨：给定历时短于 tc × M 时，实际设计历时取 tc × M —— 预览就要说清。"""
        d = client.post("/api/storm-preset", json={
            "uid": sample_uid, "dataset": "custom_storm",
            "custom_depth_mm": 50, "custom_duration_min": 1,
        }).json()
        assert d["return_period_yr"] is None
        assert d["duration_min"] == pytest.approx(d["tc_min"])
        assert d["dataset"]["key"] == "custom_storm"

    def test_unknown_return_period_fails_before_calculating(self, client, sample_uid):
        d = client.post(
            "/api/storm-preset", json={"uid": sample_uid, "return_period_yr": 7}
        )
        assert d.status_code == 422
        assert "7 年重现期" in d.json()["detail"]

    def test_unknown_uid_is_404(self, client):
        assert client.post(
            "/api/storm-preset", json={"uid": "没有这个点"}
        ).status_code == 404
