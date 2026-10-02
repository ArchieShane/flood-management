"""拟建调蓄池接口：32640 → WGS84 落在 Mussafah 一带，属性原样透传；文件缺失 404。"""

import pytest
from fastapi.testclient import TestClient

from stormwater import sim_results
from stormwater.api.main import app

client = TestClient(app)

pytestmark = pytest.mark.skipif(not sim_results.PROPOSED_PONDS_FILE.is_file(), reason="缺 proposed_ponds.geojson")


def test_proposed_ponds_wgs84():
    r = client.get("/api/simulations/layers/proposed-ponds")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection" and body["features"]
    for f in body["features"]:
        for lon, lat in f["geometry"]["coordinates"][0]:
            assert 54.0 < lon < 55.0 and 24.0 < lat < 25.0
        assert f["properties"]["pond"].startswith("PN-")


def test_proposed_ponds_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(sim_results, "PROPOSED_PONDS_FILE", tmp_path / "none.geojson")
    r = client.get("/api/simulations/layers/proposed-ponds?lang=en")
    assert r.status_code == 404
    assert "No proposed pond data" in r.text
