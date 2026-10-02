"""官方行政片区筛选（district_batch.py + registry.py + /api/scenario）。

这个功能存在的理由只有一个：**台账的 `area` 列不能当片区用**。
所以测试盯死的也是这一件事的三个侧面：

1. 片区来自几何判定，845 个点全部有归属，且台账 `area` 写什么都不影响它；
2. 片区 key **必须**带市政区前缀 —— `AL BATEEN` 在阿布扎比岛（ADM）与艾因（AAM）
   下各有一个，相距约 130 km，只按名字筛会把两地的点混成一堆；
3. 筛选与覆盖口径正交：筛出来 ≠ 算得准，艾因那个巴廷区在默认口径下必须被剔光
   且给出说得清的报错，而不是悄悄返回一份用假设值凑出来的结论。
"""

import pytest
from fastapi.testclient import TestClient

from stormwater.api.main import app
from stormwater.registry import district_facet, load_registry

ISLAND = "ADM / AL BATEEN"   # 阿布扎比岛上的巴廷区
AL_AIN = "AAM / AL BATEEN"   # 艾因 Ghafat Al Shwaihi 的巴廷区


@pytest.fixture(scope="module")
def records():
    return load_registry()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestDistrictStamp:
    """逐点片区标签 —— 来自社区面几何，不是台账文本。"""

    def test_every_point_lands_in_exactly_one_district(self, records):
        """社区面不重叠且盖满三个市政区，845 个点应当一个不漏。"""
        assert all(r.district for r in records)
        assert all(r.district_basis == "measured" for r in records)

    def test_key_is_municipality_qualified(self, records):
        r = next(r for r in records if r.uid == "ADM-405")
        assert r.district == "AL BATEEN"
        assert r.district_key == ISLAND

    def test_ledger_area_column_does_not_decide_the_district(self, records):
        """岛上巴廷区的点，台账 `area` 写的是 Island —— 按 area 筛会全部漏掉。"""
        island = [r for r in records if r.district_key == ISLAND]
        assert island, "岛上巴廷区应当有点"
        assert all(r.area != "Al Bateen" for r in island)
        assert {r.area for r in island} <= {"Island", "Al Wathbah"}


class TestAmbiguousName:
    """同名片区是这个功能最容易出事的地方，单独锁死。"""

    def test_al_bateen_exists_under_two_municipalities(self, records):
        keys = {r.district_key for r in records if r.district == "AL BATEEN"}
        assert keys == {ISLAND, AL_AIN}

    def test_the_two_are_far_apart(self, records):
        """相距约 130 km —— 混在一起算不是精度问题，是算错了地方。"""
        lon_island = [r.lon for r in records if r.district_key == ISLAND]
        lon_al_ain = [r.lon for r in records if r.district_key == AL_AIN]
        assert min(lon_al_ain) - max(lon_island) > 1.0   # 经度差 1° ≈ 100 km

    def test_only_the_island_one_has_network_data(self, records):
        island = [r for r in records if r.district_key == ISLAND]
        al_ain = [r for r in records if r.district_key == AL_AIN]
        assert all(r.in_coverage for r in island)
        assert not any(r.in_coverage for r in al_ain)


class TestFacet:
    """页面筛选器的取值清单。"""

    def test_facet_separates_the_two_al_bateens(self, records):
        rows = {x["value"]: x for x in district_facet(records)}
        assert rows[ISLAND]["count"] == 18
        assert rows[ISLAND]["in_coverage"] == 18
        assert rows[AL_AIN]["count"] == 3
        assert rows[AL_AIN]["in_coverage"] == 0

    def test_facet_counts_sum_to_the_whole_ledger(self, records):
        assert sum(x["count"] for x in district_facet(records)) == len(records)


class TestScenarioFilter:
    """批算按片区筛 —— 结论只能覆盖这个片区。"""

    def test_island_district_computes(self, client):
        r = client.post("/api/scenario", json={"return_period_yr": 25, "district": [ISLAND]})
        assert r.status_code == 200
        body = r.json()
        assert len(body["points"]) == 18
        assert body["summary"]["points_computed"] == 18
        assert list(body["by_district"]) == [ISLAND]

    def test_rollup_matches_the_points_in_that_district(self, client):
        body = client.post(
            "/api/scenario", json={"return_period_yr": 25, "district": [ISLAND]}
        ).json()
        rolled = body["by_district"][ISLAND]
        assert rolled["hotspots"] == len(body["points"])
        assert rolled["shortfall_m3"] == pytest.approx(body["summary"]["shortfall_m3"])

    def test_district_rollup_is_available_without_filtering(self, client):
        """不筛也要能按片区汇总 —— 否则「哪个区最吃紧」得靠人自己分组。"""
        body = client.post("/api/scenario", json={"return_period_yr": 25}).json()
        assert ISLAND in body["by_district"]
        assert sum(v["hotspots"] for v in body["by_district"].values()) == len(body["points"])

    def test_al_ain_al_bateen_is_refused_not_faked(self, client):
        """无管网数据的片区，默认口径下必须报错说清，而不是拿假设值凑一份结论。"""
        r = client.post("/api/scenario", json={"return_period_yr": 25, "district": [AL_AIN]})
        assert r.status_code == 422
        assert AL_AIN in r.json()["detail"]

    def test_al_ain_al_bateen_computes_only_when_coverage_is_waived(self, client):
        body = client.post(
            "/api/scenario",
            json={"return_period_yr": 25, "district": [AL_AIN], "coverage_only": False},
        ).json()
        assert len(body["points"]) == 3
        # 出处必须自己招认是假设，不能混进 measured
        assert all(p["qcap_basis"] != "measured" for p in body["points"])

    def test_filtering_by_name_alone_is_impossible(self, client):
        """裸名字不是合法 key —— 想混着筛两地，接口层面就拿不到点。"""
        r = client.post("/api/scenario", json={"return_period_yr": 25, "district": ["AL BATEEN"]})
        assert r.status_code == 422


class TestHotspotsPayload:
    """页面一次性拿到的那份数据里，片区信息要够用且自带警告。"""

    def test_points_carry_the_district_key(self, client):
        body = client.get("/api/hotspots").json()
        p = next(x for x in body["points"] if x["uid"] == "ADM-405")
        assert p["district_key"] == ISLAND
        assert p["district_municipality"] == "ADM"

    def test_ambiguous_names_are_declared(self, client):
        body = client.get("/api/hotspots").json()
        assert body["district"]["ambiguous_names"] == ["AL BATEEN"]
        assert body["district"]["stamped"] == body["count"]

    def test_boundaries_carry_the_same_key_as_the_filter(self, client):
        body = client.get("/api/districts").json()
        if not body["available"]:
            pytest.skip("尚未跑过 district_batch.py，没有轮廓文件")
        keys = {f["properties"]["key"] for f in body["features"]}
        assert {ISLAND, AL_AIN} <= keys
