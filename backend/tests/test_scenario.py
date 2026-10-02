"""台账落图与批量场景计算（registry.py + scenario.py）。

这两个模块给指挥中心页面供数，最容易悄悄出错的是三件事，逐一锁死：

1. **假设不能伪装成实测，实测也不能被当成假设**：A / C / tc、Qcap、可用调蓄
   三组量现在都由批算逐点反算，逐点差异**必须**有出处
   （`catchment_basis` / `qcap_basis` / `storage_basis`），批不到的点必须一字不差地
   落回剖面假设，且「实测没有」与「没有数据」要分得开。
2. **分区不能丢**：`auto` 时艾因山区的点必须真的走 Zone A 公式，
   否则页面上「自动分区」这个开关就是摆设。
3. **汇总必须等于逐点之和**：车队数字是要拿去调度的，汇总口径不能自成一套。
"""

import pytest
from dataclasses import replace

from stormwater.constants import (
    DEFAULT_ASSUMPTIONS,
    LEGACY_PUMP_CAPACITY,
    Assumptions,
)
from stormwater.idf import CatchmentPriority, get_dataset
from stormwater.ponding_curve import curve_for
from stormwater.rational import ScenarioResult, evaluate
from stormwater.registry import (
    DEFAULT_PROFILES,
    ZONE_A_MIN_ELEVATION_M,
    CatchmentProfile,
    build_hotspot,
    dataset_key_for,
    load_registry,
    profile_key_for,
    resolve_catchment,
    resolve_pond,
    resolve_qcap,
    zone_for_elevation,
)
from stormwater.scenario import (
    CUSTOM_RETURN_PERIOD,
    BatchOptions,
    CustomStormIdf,
    defence_line,
    fleet_gap,
    run_batch,
)


@pytest.fixture(scope="module")
def records():
    return load_registry()


@pytest.fixture(scope="module")
def calibrated(records):
    """跑过二维演算、出得了三道防线结论的那批点 —— 当前 18 个，全在 Al Bateen。

    其余点 `defence_line` 为 None，水量与泵数一律不并进汇总（见
    `scenario._accumulate`），所以凡是断言车队数字的测试都必须用这个 fixture，
    否则断言的是一堆 0。
    """
    return [r for r in records if curve_for(r.uid) is not None]


class TestRegistry:
    def test_row_count_matches_the_standard_table(self, records):
        """845 而非 846 —— 口径见 hotspots.py，这里防止落图时又混进汇总行。"""
        assert len(records) == 845

    def test_every_point_can_be_placed_on_the_map(self, records):
        assert all(r.lat and r.lon for r in records)
        assert len({r.uid for r in records}) == len(records)

    def test_coordinates_are_inside_the_uae(self, records):
        """经纬度写反或单位错会立刻把点甩到地图外，这里兜住。"""
        assert all(22.0 < r.lat < 26.5 for r in records)
        assert all(51.0 < r.lon < 56.5 for r in records)

    def test_zone_split_follows_the_200m_contour(self):
        assert zone_for_elevation(ZONE_A_MIN_ELEVATION_M + 1) == "adqcc_zone_a"
        assert zone_for_elevation(ZONE_A_MIN_ELEVATION_M) == "adqcc_zone_b"
        assert zone_for_elevation(None) is None

    def test_zone_a_points_are_essentially_all_in_al_ain(self, records):
        """DEM 缺失时这条会退化为 0 == 0，故先断言 DEM 真的采到了值。"""
        zone_a = [r for r in records if r.idf_zone == "adqcc_zone_a"]
        assert zone_a, "DEM 没采到高程，自动分区会整体退回 Zone B"
        assert sum(1 for r in zone_a if r.municipality == "Al Ain") / len(zone_a) > 0.95

    def test_auto_dataset_falls_back_when_elevation_is_missing(self, records):
        # 用 replace 而不是 as_json() 回灌：as_json 带派生字段（in_coverage），不是构造器入参
        no_dem = replace(records[0], idf_zone=None)
        assert dataset_key_for(no_dem, "auto") == "adqcc_zone_b"
        assert dataset_key_for(no_dem, "dubai_dm") == "dubai_dm"


class TestProfilesAreAssumptionsNotMeasurements:
    def test_catchment_varies_only_where_it_was_actually_measured(self, records):
        """A / C / tc 的逐点差异必须有出处 —— 没实测的点还是得落在剖面假设上。

        这条原来守的是反向命题（同成因必须完全一致，出现差异就是有人造数）。
        `catchment_batch.py` 上线后差异变成**应该**有的，但边界没松：
        出处不是 measured 的点，三项必须一字不差地等于剖面值。
        """
        for r in records:
            profile = DEFAULT_PROFILES.get(profile_key_for(r), DEFAULT_PROFILES["_default"])
            area, c, tc, basis = resolve_catchment(r, profile)
            if basis in ("measured", "measured_undeveloped"):
                assert (area, c, tc) == (
                    r.area_measured_ha, r.runoff_c_measured, r.tc_measured_min
                )
            else:
                assert (area, c, tc) == (profile.area_ha, profile.runoff_c, profile.tc_min), (
                    f"{r.uid} 出处为 {basis} 却给了非假设值"
                )

    def test_measured_catchment_is_not_one_number_in_disguise(self, records):
        """反过来守：实测的点之间必须真的有差异，否则等于换了个标签的假设值。"""
        measured = [r for r in records if r.catchment_basis == "measured"]
        assert len(measured) > 500
        areas = {r.area_measured_ha for r in measured}
        assert len(areas) > 400, "逐点汇水面积几乎没有差异，批算结果可能没载进来"

    def test_qcap_varies_only_where_it_was_actually_measured(self, records):
        """逐点 Qcap 的差异必须有出处 —— 没实测的点还是得落在剖面假设上。"""
        assumed = {p.qcap_m3s for p in DEFAULT_PROFILES.values()}
        for r in records:
            profile = DEFAULT_PROFILES.get(profile_key_for(r), DEFAULT_PROFILES["_default"])
            qcap, basis = resolve_qcap(r, profile)
            if basis == "measured":
                assert r.qcap_measured_m3s is not None and qcap == r.qcap_measured_m3s
            elif basis in ("measured_no_network", "ledger_no_network"):
                assert qcap == 0.0
            else:
                assert qcap in assumed, f"{r.uid} 出处为 {basis} 却给了非假设值 {qcap}"

    def test_measured_absence_of_pipes_forces_zero_qcap(self, records):
        """实测确认 250 m 内无管的点，Qcap 为 0。"""
        no_net = next(r for r in records if r.qcap_basis == "measured_no_network")
        assert build_hotspot(no_net, DEFAULT_PROFILES).qcap_m3s == 0.0

    def test_ledger_claim_no_longer_overrides_measured_pipes(self, records):
        """回归守卫：台账写「无管网」但实测 250 m 内有管的点，不得被判成 Qcap=0。

        改之前这类点有 130 个被强制清零，全部低估了排水能力。
        """
        contradicted = [r for r in records
                        if r.network_available is False and r.qcap_measured_m3s is not None]
        assert contradicted, "台账与管网几何的矛盾点消失了，说明批算结果没载进来"
        for r in contradicted:
            assert build_hotspot(r, DEFAULT_PROFILES).qcap_m3s == r.qcap_measured_m3s

    def test_pond_capacity_varies_only_where_it_was_actually_measured(self, records):
        """第二道防线同理：0 也要有出处，不能是「默认就是 0」。"""
        assumed = {p.pond_available_m3 for p in DEFAULT_PROFILES.values()}
        for r in records:
            profile = DEFAULT_PROFILES.get(profile_key_for(r), DEFAULT_PROFILES["_default"])
            pond, basis = resolve_pond(r, profile)
            if basis == "measured":
                assert r.storage_measured_m3 is not None and pond == r.storage_measured_m3
            elif basis == "assumed_dimensions":
                # 设施位置实测、深度尺寸查 storage_dims.py 的缺省值目录 —— 是假设，
                # 但有出处，且值必须等于批算给出的那一条，不能是剖面兜底值
                assert r.storage_assumed_m3 is not None and pond == r.storage_assumed_m3
            elif basis in ("measured_none", "measured_no_asset"):
                assert pond == 0.0
            else:
                assert pond in assumed, f"{r.uid} 出处为 {basis} 却给了非假设值 {pond}"

    def test_no_storage_data_is_distinguished_from_no_storage_facility(self, records):
        """「实测确认周边没有设施」和「这一片没有设施数据」必须是两种不同的 0。

        艾因与西部区最近的调蓄设施在 28 km / 78 km 外，把它们判成「实测无设施」
        等于拿没有数据当证据。
        """
        by_basis = {}
        for r in records:
            profile = DEFAULT_PROFILES.get(profile_key_for(r), DEFAULT_PROFILES["_default"])
            by_basis.setdefault(resolve_pond(r, profile)[1], []).append(r)
        assert "measured_no_asset" in by_basis, "没有任何点被判为实测无设施，批算结果没载进来"
        assert "assumed_no_coverage" in by_basis, "没有任何点被判为无设施数据"
        # 无设施数据的点应当集中在管网库覆盖不到的艾因 / 西部区
        outside = [r for r in by_basis["assumed_no_coverage"] if r.source != "ADM"]
        assert len(outside) / len(by_basis["assumed_no_coverage"]) > 0.8

    def test_the_zero_qcap_rule_can_be_switched_off_for_sensitivity_runs(self, records):
        no_net = next(r for r in records
                      if r.qcap_basis == "no_coverage" and r.network_available is False)
        profiles = {**DEFAULT_PROFILES, "Absence of Drainage Network": CatchmentProfile(qcap_m3s=0.9)}
        assert build_hotspot(no_net, DEFAULT_PROFILES).qcap_m3s == 0.0
        assert build_hotspot(no_net, profiles, zero_qcap_without_network=False).qcap_m3s == 0.9

    def test_unknown_root_cause_uses_the_fallback_profile(self, records):
        """当前 845 行的成因都落在三组里；台账以后加新成因时必须走兜底而不是崩。"""
        assert all(profile_key_for(r) in DEFAULT_PROFILES for r in records)
        future = replace(records[0], root_cause="Sea Level Rise")
        assert profile_key_for(future) == "_default"


class TestBatch:
    def test_summary_equals_the_sum_of_its_points(self, records):
        """汇总 = 逐点之和，**但只加有标定的点** —— 无标定的点没有水量与泵数。

        给无标定点补 0 再求和会让总账看起来比实际乐观：少算的正是没算的那部分。
        故 `calibrated_hotspots` 与 `hotspots` 是两个数，两个都要对得上。
        """
        batch = run_batch(records, BatchOptions(dataset="adqcc_zone_b", return_period_yr=25))
        s = batch["summary"]
        done = [p for p in batch["points"] if p["is_calibrated"]]
        assert s["hotspots"] == len(batch["points"]) == 845
        assert s["calibrated_hotspots"] == len(done)
        assert s["pumps_required"] == sum(p["pumps_required"] for p in done)
        assert s["tanker_loads"] == sum(p["tanker_loads"] for p in done)
        # uncalibrated 与 1/2/3 并列，四个数之和才是全部点
        assert sum(s["line_counts"].values()) == 845
        assert s["line_counts"]["uncalibrated"] == 845 - len(done)
        # 分档台数同样要等于逐点之和，且三档相加等于总台数
        for key, qty in s["pumps_by_tier"].items():
            assert qty == sum(p["pumps_by_tier"].get(key, 0) for p in done)
        assert sum(s["pumps_by_tier"].values()) == s["pumps_required"]

    def test_uncalibrated_points_carry_no_defence_numbers_at_all(self, records):
        """没跑过二维演算的点：防线各量必须是 None，不能是 0。

        0 的意思是「算过，结果是零」，None 的意思是「没算」。这两件事在指挥中心
        页面上差着一个调度决定，不许混。
        """
        batch = run_batch(records, BatchOptions(dataset="adqcc_zone_b", return_period_yr=25))
        blank = [p for p in batch["points"] if not p["is_calibrated"]]
        assert blank, "台账里应当仍有没跑过演算的点"
        for p in blank[:50]:
            assert p["line"] is None and p["l1_basis"] == "uncalibrated"
            for field in ("runoff_volume_m3", "residual_after_network_m3",
                          "shortfall_m3", "pumps_required", "pumps_by_tier",
                          "tankers_required", "tankers_to_feed_pumps",
                          "pumps_configured", "tankers_configured",
                          "pump_configured_m3hr", "tanker_configured_m3hr",
                          "chain_configured_m3hr", "chain_bottleneck",
                          "chain_residual_m3", "configured_fleet_suffice"):
                assert p[field] is None, f"{p['uid']}.{field}"
            # 峰值诊断不依赖演算，照常给
            assert p["peak_flow_m3s"] > 0


class TestConfiguredFleet:
    """页面上那两个旋钮在全网口径上的表现。

    锁的是**两个问题并列**这件事：`pumps_required` 答「该配几台」，
    `pumps_configured` / `pump_residual_m3` 答「已配的够不够」。

    ⚠ 一律跑 **RP100** —— 唯一一场二维演算就是这一档，选别的级别一个点都没有
    结论，各量全是 0，断言会空转成永真。
    """

    def test_configured_total_is_points_times_per_point(self, records):
        opts = BatchOptions(dataset="auto", return_period_yr=100,
                            assumptions=Assumptions(pumps_per_point=2))
        s = run_batch(records, opts)["summary"]
        assert s["pumps_per_point"] == 2
        assert s["pumps_configured"] == 2 * s["calibrated_hotspots"]

    def test_bigger_pumps_alone_leave_the_same_water_on_the_ground(self, records):
        """**泵和罐车串联**：车不动，泵调大十倍也一滴水都多排不出去。

        小泵 150 → 大泵 1500，泵侧能力翻了十倍，但每点只配 1 辆罐车 ——
        链的外运能力恒等于罐车侧，残量一模一样。这正是「不是或的关系」。
        """
        def run(capacity, tankers=1):
            return run_batch(records, BatchOptions(
                dataset="auto", return_period_yr=100,
                assumptions=Assumptions(pump_capacity=capacity,
                                        tankers_per_point=tankers)))["summary"]

        small, big = run(150.0), run(1500.0)
        assert big["chain_residual_m3"] == small["chain_residual_m3"]
        assert big["points_under_served"] == small["points_under_served"]
        assert big["points_tanker_bound"] == big["points_under_served"]
        # 「该配几台」仍跟着反向走 —— 泵越大，要的台数越少
        assert big["pumps_required"] < small["pumps_required"]

    def test_more_tankers_do_leave_less_water_on_the_ground(self, records):
        """瓶颈在罐车侧时，加车才减残量 —— 加到头瓶颈换到泵侧。"""
        def run(tankers):
            return run_batch(records, BatchOptions(
                dataset="auto", return_period_yr=100,
                assumptions=Assumptions(pump_capacity=300.0,
                                        tankers_per_point=tankers)))["summary"]

        few, many = run(1), run(40)
        assert many["chain_residual_m3"] < few["chain_residual_m3"]
        assert many["points_under_served"] <= few["points_under_served"]
        # 1 辆 15 vs 泵侧 300 → 卡罐车；40 辆 600 > 300 → 卡泵
        assert few["chain_bottleneck"] == "tanker"
        assert many["chain_bottleneck"] == "pump"

    def test_tanker_capacity_is_per_truck(self, records):
        """罐车单车容量翻倍 → 车次大致减半（逐点向上取整，故不是严格一半）。"""
        def loads(capacity):
            return run_batch(records, BatchOptions(
                dataset="auto", return_period_yr=100,
                assumptions=Assumptions(tanker_capacity=capacity),
            ))["summary"]["tanker_loads"]

        assert 0.45 < loads(30.0) / loads(15.0) < 0.55

    def test_tanker_vehicles_are_derived_from_loads_and_turnaround(self, records):
        """全域口径：车次不随时限动，辆数动 —— 两个量分列，别混着报。"""
        def run(hours, turnaround=60.0):
            return run_batch(records, BatchOptions(
                dataset="auto", return_period_yr=100,
                assumptions=Assumptions(drawdown_hours=hours,
                                        tanker_turnaround_min=turnaround),
            ))["summary"]

        base = run(2.0)
        assert base["tanker_trips_per_vehicle"] == 2
        assert base["tankers_required"] < base["tanker_loads"]
        assert base["points_tanker_infeasible"] == 0
        # 周转减半 → 每辆多跑一倍趟数 → 辆数减少，车次不变
        quick = run(2.0, 30.0)
        assert quick["tanker_loads"] == base["tanker_loads"]
        assert quick["tankers_required"] < base["tankers_required"]

    def test_turnaround_longer_than_window_is_counted_not_zeroed(self, records):
        """跑不满一趟的点计进 `points_tanker_infeasible`，辆数里不补 0。"""
        batch = run_batch(records, BatchOptions(
            dataset="auto", return_period_yr=100,
            assumptions=Assumptions(drawdown_hours=1.0, tanker_turnaround_min=90.0),
        ))
        s = batch["summary"]
        # 不出数的只是**要出车的**那些点；R2 = 0 的点辆数是实打实的 0，不算受阻
        hauling = [p for p in batch["points"]
                   if p["is_calibrated"] and p["tanker_loads"] > 0]
        assert s["tanker_trips_per_vehicle"] == 0
        assert s["points_tanker_infeasible"] == len(hauling) > 0
        assert s["tankers_required"] == 0      # 一个点都没折算出辆数
        assert s["tanker_loads"] > 0           # 但水还是那么多水
        assert all(p["tankers_required"] is None for p in hauling)

    def test_gap_reports_tanker_vehicles_against_ledger(self, records):
        batch = run_batch(records, BatchOptions(
            dataset="auto", return_period_yr=100))
        s, g = batch["summary"], fleet_gap(batch["summary"])
        assert g["tankers_required"] == s["tankers_required"]
        # 缺口按**约束更紧**的那个算：按水量算的辆数 vs 喂饱泵要的辆数，取大
        assert g["tankers_required_binding"] == max(
            s["tankers_required"], s["tankers_to_feed_pumps"])
        assert g["tankers_gap"] == max(
            0, g["tankers_required_binding"] - g["tankers_on_ledger"])
        # 「每辆跑几趟」是拿**台账在册辆数**去除车次，与需求侧的辆数不是一回事
        assert g["tanker_loads_required"] == s["tanker_loads"]

    def test_tankers_needed_are_not_an_alternative_to_pumps(self, records):
        """泵和罐车是**同时都要**的一对 —— 要出泵的点必然也要出车。"""
        batch = run_batch(records, BatchOptions(
            dataset="auto", return_period_yr=100))
        pumping = [p for p in batch["points"]
                   if p["is_calibrated"] and p["pumps_required"] > 0]
        assert pumping
        assert all(p["tanker_loads"] > 0 for p in pumping)
        assert all(p["tankers_required"] > 0 for p in pumping)
        # 喂饱这些泵所需的车数，按「每台泵 N 辆车」折算而来
        per_pump = batch["summary"]["tankers_per_pump"]
        assert all(p["tankers_to_feed_pumps"] == p["pumps_required"] * per_pump
                   for p in pumping)

    def test_gap_reports_configured_against_required(self, records):
        batch = run_batch(records, BatchOptions(
            dataset="auto", return_period_yr=100))
        s = batch["summary"]
        gap = fleet_gap(s)
        assert gap["pumps_configured"] == s["pumps_configured"]
        assert gap["pumps_configured_gap"] == max(
            0, s["pumps_required"] - s["pumps_configured"])
        assert gap["points_under_served"] == s["points_under_served"]
        # 清不完的点数与清不完的水量必须同进同退，不能一个 0 一个非 0
        assert (gap["points_under_served"] > 0) == (gap["chain_residual_m3"] > 0)
        # 卡在罐车侧的是「清不完」的一个子集，不是另一批点
        assert gap["points_tanker_bound"] <= gap["points_under_served"]


class TestPumpTiers:
    """移动泵分档（DMT 数据需求清单 §02）在全网口径上的表现。"""

    def test_legacy_single_capacity_stays_pinned(self, records):
        """旧口径（全车队统一 300 m³/h + 峰值判定）的全网数必须一字不差地钉住。

        ⚠ 这个数在 `catchment_batch.py` 上线时**从 1,470 变成了 1,381**：逐点
        A / C / tc 换成实测后 Q 变了，泵数跟着变，这是预期内的。1,470 是
        「12 ha / C 0.75 / tc 20 min 全网同值」那一版的数字，已不可复现。
        ⚠ 2026-09-19 又从 1,381 变成 **1,369**：`storage_batch.py` 补上了
        `pond.volume` 与 `storage_dims.py` 的深度/尺寸缺省值目录，第二道防线
        不再全库为 0，43 个点吸收掉一部分缺口，泵数相应少 12 台。
        ⚠ 2026-09-21 再从 1,369 变成 **1,360**：ADM 的 506 个坐标按
        `FW__Hot_Spots_506` 改回（原 Excel 坐标列整体错位一行，见
        `hotspots.py` 模块文档），点挪了位置，Qcap / 汇水 / 调蓄三个批算
        全部重跑，泵数跟着变。**1,369 及更早的数字都是在错误位置上算的，
        不可复现也不该复现。**

        断言留着的意义不变 —— 它一旦再动，说明动的不只是排量假设。
        """
        batch = run_batch(records, BatchOptions(
            dataset="auto", return_period_yr=25,
            assumptions=Assumptions(pump_capacity=LEGACY_PUMP_CAPACITY,
                                    defence_basis="peak")))
        assert batch["summary"]["pumps_required"] == 1360
        assert batch["summary"]["pumps_by_tier"] == {"uniform": 1360}

    def test_tiered_dispatch_shifts_composition_not_magnitude(self, records):
        """分档后总量同量级，但需求被拆成了可对照在册构成的三档。

        同量级这件事要在**同一个判定口径**下比，故这里显式走峰值口径 ——
        1,470 本身就是峰值口径的数字。

        ⚠ 分档已不是默认（默认是页面那个单泵抽排能力），故还要显式
        `pump_capacity=None` 才走得到分档派车。
        """
        batch = run_batch(records, BatchOptions(
            dataset="auto", return_period_yr=25,
            assumptions=Assumptions(defence_basis="peak", pump_capacity=None)))
        s = batch["summary"]
        assert set(s["pumps_by_tier"]) == {"12in", "8in", "6in"}
        assert 0.7 < s["pumps_required"] / 1381 < 1.3      # 与旧口径同量级
        # 6″ 在册最多（579 台），需求也该以 6″ 为主
        assert s["pumps_by_tier"]["6in"] > s["pumps_by_tier"]["12in"]

    def test_deployed_capacity_covers_every_point(self, records):
        # RP100 —— 唯一一个跑过二维演算的 run 就是这一档，选别的级别没有点出结论
        batch = run_batch(records, BatchOptions(dataset="auto", return_period_yr=100))
        done = [p for p in batch["points"] if p["is_calibrated"]]
        assert done
        assert all(p["pump_deployed_m3hr"] >= p["pumping_rate_m3hr"] - 0.05
                   for p in done)

    def test_gap_is_reported_per_bore(self, records):
        tiered = Assumptions(pump_capacity=None)
        batch = run_batch(records, BatchOptions(
            dataset="auto", return_period_yr=25, assumptions=tiered))
        gap = fleet_gap(batch["summary"], tiered.effective_tiers)
        assert [t["key"] for t in gap["by_tier"]] == ["12in", "8in", "6in"]
        assert gap["fleet_total"] == 144 + 121 + 579
        for row in gap["by_tier"]:
            assert row["gap"] == max(0, row["required"] - row["on_fleet"])

    def test_default_gap_collapses_to_one_mobile_pump_row(self, records):
        """默认（页面配置式）下只有一行 —— 在册台数是三档合计，不假装拆得开。"""
        batch = run_batch(records, BatchOptions(dataset="auto", return_period_yr=25))
        gap = fleet_gap(batch["summary"])
        assert [t["key"] for t in gap["by_tier"]] == ["uniform"]
        assert gap["by_tier"][0]["on_fleet"] == 144 + 121 + 579 == gap["fleet_total"]
        assert gap["by_tier"][0]["on_fleet_in_scope"] == sum(
            batch["summary"]["ledger_pumps_by_tier"].values()
        )

    def test_auto_really_routes_mountain_points_through_zone_a(self, records):
        batch = run_batch(records, BatchOptions(dataset="auto", return_period_yr=25))
        assert batch["dataset_usage"]["adqcc_zone_a"] > 100
        by_uid = {p["uid"]: p for p in batch["points"]}
        zone_a = next(r for r in records if r.idf_zone == "adqcc_zone_a")
        assert by_uid[zone_a.uid]["dataset_key"] == "adqcc_zone_a"
        # Zone A 的系数更大，同一历时下强度必须真的更高，不能只是换了个标签。
        # ⚠ 不能拿另一个点比：逐点 tc 已经是实测值，两点历时不同，强度本就没法直接比。
        got = by_uid[zone_a.uid]
        zone_b_same_duration = get_dataset("adqcc_zone_b").intensity(
            25, got["duration_min"]
        ).intensity_mm_hr
        assert got["intensity_mm_hr"] > zone_b_same_duration

    def test_batch_matches_single_point_evaluation(self, records):
        """批算只是循环，不得自带一套算法。"""
        opts = BatchOptions(dataset="adqcc_zone_b", return_period_yr=50)
        batch = run_batch(records[:20], opts)
        r = records[3]
        one = evaluate(build_hotspot(r, DEFAULT_PROFILES), 50, opts.assumptions, get_dataset("adqcc_zone_b"))
        got = next(p for p in batch["points"] if p["uid"] == r.uid)
        # 出参按页面展示需要做了四舍五入，故按位数比
        assert got["peak_flow_m3s"] == pytest.approx(one.peak_flow_m3s, abs=5e-4)
        assert got["pumps_required"] == one.pumps_required

    def test_filters_do_not_leak_into_other_points(self, records):
        al_ain = [r for r in records if r.municipality == "Al Ain"]
        batch = run_batch(al_ain, BatchOptions(dataset="auto"))
        assert batch["summary"]["hotspots"] == len(al_ain)
        assert set(batch["by_municipality"]) == {"Al Ain"}

    def test_priority_multiplier_stretches_the_design_duration(self, records):
        base = run_batch(records[:5], BatchOptions(dataset="adqcc_zone_b"))
        slow = run_batch(records[:5], BatchOptions(
            dataset="adqcc_zone_b", priority=CatchmentPriority.OPEN_AREA))
        # 12× 的历时 → 强度更低，但积水体积算的是更长的历时
        assert slow["points"][0]["duration_min"] == pytest.approx(
            base["points"][0]["duration_min"] * 12)
        assert slow["points"][0]["intensity_mm_hr"] < base["points"][0]["intensity_mm_hr"]

    def test_dubai_dataset_skips_return_periods_it_lacks_instead_of_guessing(self, records):
        batch = run_batch(records[:5], BatchOptions(dataset="dubai_dm", return_period_yr=15))
        assert batch["points"] == []
        assert len(batch["skipped"]) == 5

    def test_the_total_does_not_move_with_the_window(self, calibrated):
        """总量与 T 解耦 —— T 是工期，改工期不改这 18 个点一共积了多少水。

        ⚠ 这是 V(T) → 全程净入流那次口径变更的锁：旧口径下总量随 T 变（T 落
        在上涨段时放宽时限反而让总量变大），一个「要处置多少水」的量却跟着
        排班走，读的人无从判断。现在它恒为 57,527 m³（见 `ponding_batch`）。
        """
        totals = [
            run_batch(calibrated, BatchOptions(
                return_period_yr=100,
                assumptions=Assumptions(drawdown_hours=h),
            ))["summary"]["runoff_volume_m3"]
            for h in (0.5, 1.0, 2.0, 4.0, 12.0)
        ]
        assert totals == pytest.approx([57_527.0] * 5, abs=1.0)

    def test_fleet_size_falls_as_the_window_widens(self, calibrated):
        """总量固定之后，放宽时限就少派泵 —— 单调不增。

        两头都在往下压：第一道 = R × T 随 T 变大，剩给第三道的少了；第三道要
        的速率 R2/T 又被 T 摊薄。Al Bateen RP100 这 18 个点：

            T(h)   0.5     1     2     3     4     6    12    24
            泵     348   145    43    13     3     2     2     2

        ⚠ 曲线的形状本身就是「T 该定多少」的依据，但**别读成「时限拖长就没事」**：
        T=6 h 之后泵数不再降，那 2 台是退水段压根排不掉的残量；而 T 拖长意味着
        水在地面上多待几小时，这个代价不在本量纲里。
        """
        def pumps(hours):
            return run_batch(calibrated, BatchOptions(
                return_period_yr=100,
                assumptions=Assumptions(drawdown_hours=hours),
            ))["summary"]["pumps_required"]

        series = [pumps(h) for h in (0.5, 1.0, 2.0, 4.0, 12.0)]
        assert series == sorted(series, reverse=True)
        assert series[0] > series[-1]      # 两端确实拉开，不是一条平线


class TestDefenceLines:
    """三道防线共用一个时限 T —— 判定与归类在批算里不能各说一套。"""

    def _result(self, cleared_net, cleared_storage, l1_basis="hydrodynamic"):
        """只带判定用得着的三个量 —— 归类不许偷偷依赖别的字段。"""
        class R:
            pass
        R.cleared_by_network = cleared_net
        R.cleared_by_storage = cleared_storage
        R.l1_basis = l1_basis
        R.is_calibrated = property(ScenarioResult.is_calibrated.fget)
        R.defence_line = property(ScenarioResult.defence_line.fget)
        return R()

    def test_line_assignment(self):
        assert defence_line(self._result(True, True)) == 1
        assert defence_line(self._result(False, True)) == 2
        assert defence_line(self._result(False, False)) == 3

    def test_uncalibrated_is_none_not_a_fourth_line(self):
        """没跑过演算 → None。它不是「第四道防线」，也不能当 3 用。"""
        assert defence_line(self._result(None, None, "uncalibrated")) is None

    def test_every_point_answers_all_three_questions(self, calibrated):
        """逐点结果必须逐条给出三道防线各自的答案，缺一列页面就没法落地。"""
        batch = run_batch(calibrated, BatchOptions(
            dataset="adqcc_zone_b", return_period_yr=100))
        needed = {
            "window_hours", "l1_basis", "is_calibrated", "runoff_volume_m3",
            "network_drained_m3",
            "residual_after_network_m3", "drain_hours", "cleared_by_network",
            "required_storage_m3", "storage_used_m3", "cleared_by_storage",
            "shortfall_m3", "pumping_rate_m3hr", "pumps_required", "pumps_by_tier",
        }
        assert batch["points"]
        for p in batch["points"]:
            assert needed <= set(p)
            assert p["window_hours"] == DEFAULT_ASSUMPTIONS.drawdown_hours
            assert p["l1_basis"] == "hydrodynamic"
            # 归类与两个布尔量必须自洽
            assert p["line"] == (1 if p["cleared_by_network"]
                                 else 2 if p["cleared_by_storage"] else 3)
            assert (p["pumps_required"] > 0) == (p["line"] == 3)
            # 第一道的水量账闭合：T 内入流 = 已退走 + T 时刻残留
            assert p["runoff_volume_m3"] == pytest.approx(
                p["network_drained_m3"] + p["residual_after_network_m3"], abs=0.2)

    def test_the_first_line_no_longer_depends_on_qcap(self, calibrated):
        """把全部点的 Qcap 归零，三道防线的水量一个都不动 —— 全域口径的**总闸**。

        第一道读的是二维演算的积水时程（实测 Σ 负 ΔV），管网在 T 内的贡献已含
        在里面。Qcap 只喂 `peak_exceeds_capacity` 这一个峰值诊断量。

        ⚠ 这条曾被换成反向断言（Qcap 归零则第一道塌掉），配套把 `rational.py`
        改成 `max(Qcap×T, drained)`。默认 T=2 h 下那会抹掉 18 个标定点 69% 的
        残留水量、12/16 个点从「地面有水」翻成「一道退完」。别再改回去。
        """
        opts = dict(dataset="adqcc_zone_b", return_period_yr=100)
        base = run_batch(calibrated, BatchOptions(**opts))["summary"]
        no_pipe = run_batch(
            [replace(r, qcap_measured_m3s=0.0, network_available=False)
             for r in calibrated],
            BatchOptions(**opts),
        )["summary"]
        for key in ("runoff_volume_m3", "line1_m3", "line2_m3", "line3_m3",
                    "shortfall_m3", "required_storage_m3", "pumps_required",
                    "tankers_required", "chain_residual_m3"):
            assert no_pipe[key] == pytest.approx(base[key]), key
        assert no_pipe["line_counts"] == base["line_counts"]
        # Qcap 仅存的用途：峰值诊断，它照常跟着变
        assert no_pipe["peak_exceeds_capacity"] >= base["peak_exceeds_capacity"]

    def test_the_window_is_shared_by_the_first_and_third_line(self, calibrated):
        """同一个 T 同时定第一道的取值时刻和第三道的抽排速率，不能各用一个。"""
        for hours in (0.5, 2.0, 6.0):
            batch = run_batch(calibrated, BatchOptions(
                dataset="adqcc_zone_b", return_period_yr=100,
                assumptions=Assumptions(drawdown_hours=hours)))
            for p in batch["points"]:
                assert p["window_hours"] == hours
                # 两个量各自 round 到 1 位小数，除以 T 会把误差放大 1/T 倍
                assert p["pumping_rate_m3hr"] == pytest.approx(
                    p["shortfall_m3"] / hours, abs=0.05 / hours + 0.05)

    def test_the_hydrodynamic_basis_is_not_the_peak_basis(self, records):
        """两个口径回答两个问题，数字不能被当成同一个来用。

        水动力口径只对跑过演算的点出结论，峰值口径（原 Excel）对每个点都出 ——
        所以两者连**点数**都不一样，混用会把 845 个点的车队和 18 个点的车队
        放在一张表里比。
        """
        recs = [r for r in records if r.in_coverage]
        opts = dict(dataset="auto", return_period_yr=25)
        hydro = run_batch(recs, BatchOptions(**opts))["summary"]
        peak = run_batch(recs, BatchOptions(
            **opts, assumptions=Assumptions(defence_basis="peak")))["summary"]
        assert hydro["calibrated_hotspots"] < peak["calibrated_hotspots"]
        assert hydro["line_counts"]["uncalibrated"] > 0
        assert peak["line_counts"]["uncalibrated"] == 0
        # 「峰值会不会溢流」是同一件事，不随判定口径变
        assert hydro["peak_exceeds_capacity"] == peak["peak_exceeds_capacity"]

    def test_water_balance_holds_across_the_three_lines(self, records):
        """三道防线分掉的水量合计 = 径流总量（二三道多出淤积裕量）。"""
        s = run_batch([r for r in records if r.in_coverage],
                      BatchOptions(dataset="auto"))["summary"]
        moved = s["line1_m3"] + (s["line2_m3"] + s["line3_m3"]) / DEFAULT_ASSUMPTIONS.sed_factor
        assert moved == pytest.approx(s["runoff_volume_m3"], rel=1e-9)

    def test_fleet_gap_never_reports_a_negative_shortage(self):
        gap = fleet_gap({"pumps_required": 10, "ledger_pumps_qty": 40,
                         "tanker_loads": 9, "ledger_tankers_qty": 0})
        assert gap["pumps_gap"] == 0
        assert gap["loads_per_tanker"] is None   # 台账没有罐车时不能除零


class TestCustomStorm:
    def test_intensity_is_depth_over_duration(self):
        ds = CustomStormIdf(depth_mm=60.0, duration_min=120.0)
        lookup = ds.intensity(CUSTOM_RETURN_PERIOD, tc_min=20.0)
        assert lookup.duration_min == 120.0      # tc 短于给定历时时按给定历时算
        assert lookup.intensity_mm_hr == pytest.approx(30.0)

    def test_long_tc_wins_over_the_given_duration(self):
        ds = CustomStormIdf(depth_mm=60.0, duration_min=30.0)
        lookup = ds.intensity(CUSTOM_RETURN_PERIOD, tc_min=45.0, tc_multiplier=2.0)
        assert lookup.duration_min == 90.0
        assert lookup.intensity_mm_hr == pytest.approx(40.0)

    def test_it_declares_itself_as_non_standard(self, records):
        batch = run_batch(records[:5], BatchOptions(
            custom_storm=CustomStormIdf(50.0, 120.0)))
        assert batch["return_period_yr"] == CUSTOM_RETURN_PERIOD
        assert all(p["dataset_key"] == "custom_storm" for p in batch["points"])

    def test_rejects_impossible_storms(self):
        with pytest.raises(ValueError):
            CustomStormIdf(depth_mm=0.0, duration_min=60.0)
        with pytest.raises(ValueError):
            CustomStormIdf(depth_mm=50.0, duration_min=-1.0)


class TestCoverageScope:
    """只算「有管网数据的区域」—— 范围判定与随之而来的口径一致性。"""

    def test_inclusion_follows_measured_distance_not_the_municipality(self, records):
        """行政区不是数据边界：台账记为阿布扎比市的点里有 5 个在数据区外。"""
        inside = [r for r in records if r.in_coverage]
        assert len(inside) == 501
        outside = [r for r in records if not r.in_coverage]
        assert {r.municipality for r in outside} == {"Abu Dhabi", "Al Ain", "Al Dhafra"}
        assert sum(1 for r in outside if r.municipality == "Abu Dhabi") == 5
        # 区域内的点，Qcap 全部有实测出处（实算 / 实测确认无管 / 有管但算不出）
        assert {r.qcap_basis for r in inside} == {
            "measured", "measured_no_network", "uncomputable"
        }

    def test_outside_points_are_the_ones_dmt_still_owes_us(self, records):
        """区域外 = DMT 清单 §01 的 339 个点，加上 5 个离管网 5 km 以外的市区点。"""
        outside = [r for r in records if not r.in_coverage]
        assert len(outside) == 344
        assert all(r.qcap_basis == "no_coverage" for r in outside)
        assert all(r.qcap_measured_m3s is None for r in outside)

    def test_scoping_shrinks_the_point_count_not_the_fleet(self, records):
        """把范围缩到数据区，点数缩、车队不缩 —— 有标定的点本来就全在数据区内。

        旧口径下每个点都出数字，所以缩范围车队必然跟着缩。水动力口径下车队只由
        那 18 个跑过演算的点决定，它们全部落在数据区内，所以这里断言的是
        **两个口径的差别本身**：`hotspots` 变了，`calibrated_hotspots` 没变。
        """
        opts = BatchOptions(dataset="adqcc_zone_b", return_period_yr=25)
        full = run_batch(records, opts)["summary"]
        scoped = run_batch([r for r in records if r.in_coverage], opts)["summary"]
        assert scoped["hotspots"] == 501 < full["hotspots"]
        assert scoped["calibrated_hotspots"] == full["calibrated_hotspots"]
        assert scoped["pumps_required"] == full["pumps_required"]
        assert scoped["line_counts"]["uncalibrated"] < full["line_counts"]["uncalibrated"]

    def test_ledger_comparison_scopes_with_the_points(self, records):
        """在册台数也要跟着缩，不然缺口会被系统性低估。"""
        opts = BatchOptions(dataset="adqcc_zone_b", return_period_yr=25)
        scoped = run_batch([r for r in records if r.in_coverage], opts)["summary"]
        full = run_batch(records, opts)["summary"]
        for tier in ("12in", "8in", "6in"):
            assert scoped["ledger_pumps_by_tier"][tier] <= full["ledger_pumps_by_tier"][tier]
        # 逐档对照只在分档口径下才有 —— 默认的单档只有一行合计
        gap = fleet_gap(scoped, Assumptions(pump_capacity=None).effective_tiers)
        by_key = {t["key"]: t for t in gap["by_tier"]}
        # 全网在册口径固定不随范围变，故必须另给一个随范围走的口径
        assert by_key["8in"]["on_fleet"] == 121
        assert by_key["8in"]["on_fleet_in_scope"] == scoped["ledger_pumps_by_tier"]["8in"]
        assert by_key["8in"]["gap_in_scope"] >= by_key["8in"]["gap"]
