"""多套 IDF 数据集的行为与口径锁定。

核心断言分三类：
1. ADQCC 的连续公式必须能还原标准里已公布的 DDF 表（Table 3-4 / 3-6）
2. 台账引用的 44.88 / 51.12 / 69.60 / 81.84 必须能从 Zone B 复现
3. 两套数据集的**方法差异**不能被静默抹平（Cf、tc 乘数、历时语义）
"""

import pytest

from stormwater.idf import (
    ADQCC_TABLE_DURATIONS_MIN,
    ADQCC_ZONE_A,
    ADQCC_ZONE_B,
    DEFAULT_DATASET_KEY,
    DUBAI_DM,
    IDF_DATASETS,
    CatchmentPriority,
    get_dataset,
)
from stormwater.rational import Hotspot, compare_datasets, evaluate, evaluate_all

ADQCC_SETS = [ADQCC_ZONE_A, ADQCC_ZONE_B]

H1 = Hotspot(hotspot_id="H1", area_ha=12.0, runoff_c=0.75, tc_min=20.0, qcap_m3s=1.8)


# ---------------------------------------------------------------------------
# 1. 公式 vs 标准已公布表
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ds", ADQCC_SETS, ids=lambda d: d.key)
def test_equations_reproduce_published_ddf_table(ds):
    """i = α/(t·M)^β 必须还原 Table 3-4 / 3-6，残差只应来自表格取整。"""
    for rp, row in ds.published_table.items():
        for duration_min, published in zip(ADQCC_TABLE_DURATIONS_MIN, row):
            got = ds.intensity(rp, duration_min).intensity_mm_hr
            assert got == pytest.approx(published, rel=0.005), (
                f"{ds.key} {rp}yr @ {duration_min}min: 公式 {got:.2f} vs 表 {published}"
            )


@pytest.mark.parametrize("ds", ADQCC_SETS, ids=lambda d: d.key)
def test_24h_depth_matches_published(ds):
    """24 小时降雨深度 = 该档强度 × 24。台账引用的就是这一列。"""
    for rp, depth_mm in ds.depth_24h_mm.items():
        got = ds.intensity(rp, 1440).intensity_mm_hr * 24.0
        assert got == pytest.approx(depth_mm, rel=0.005)


def test_ledger_design_events_come_from_zone_b():
    """台账 Hotspot Network Rain Design Event 的四个数字。"""
    assert ADQCC_ZONE_B.depth_24h_mm[5] == 44.88
    assert ADQCC_ZONE_B.depth_24h_mm[10] == 51.12
    assert ADQCC_ZONE_B.depth_24h_mm[25] == 69.60
    assert ADQCC_ZONE_B.depth_24h_mm[50] == 81.84


def test_future_target_is_10yr_plus_20_percent():
    """台账「1-in-10 yr + 20% climate change factor」= 61.34 mm/24hr。"""
    assert ADQCC_ZONE_B.depth_24h_mm[10] * 1.2 == pytest.approx(61.34, abs=0.01)


def test_zone_a_is_wetter_than_zone_b():
    """东北山区降雨显著高于平原区 —— 分区弄反会被这条抓住。"""
    for rp in (5, 10, 25, 50, 100):
        assert ADQCC_ZONE_A.intensity(rp, 60).intensity_mm_hr > ADQCC_ZONE_B.intensity(rp, 60).intensity_mm_hr


def test_zone_b_has_15yr_but_zone_a_does_not():
    """标准里两区的公式表重现期集合不一致，这不是笔误。"""
    assert 15 in ADQCC_ZONE_B.return_periods
    assert 15 not in ADQCC_ZONE_A.return_periods


# ---------------------------------------------------------------------------
# 2. 方法差异不可被静默抹平
# ---------------------------------------------------------------------------


def test_adqcc_has_no_cf_adjustment():
    """ADQCC 不设频率调整系数，C 直接用 Table 3-8/3-9。"""
    for ds in ADQCC_SETS:
        assert ds.supports_cf is False
        for rp in ds.return_periods:
            assert ds.runoff_adjustment_factor(rp) == 1.0
    # 同一个 C=0.75 的点，100 年一遇时迪拜会放大到 0.9375，ADQCC 不动
    assert evaluate(H1, 100, dataset="dubai_dm").c_adjusted == pytest.approx(0.9375)
    assert evaluate(H1, 100, dataset="adqcc_zone_b").c_adjusted == pytest.approx(0.75)


def test_dubai_rejects_tc_multiplier():
    """迪拜没有 Table 3-3 这个概念 —— 不能假装支持。"""
    with pytest.raises(ValueError, match="没有设计历时乘数"):
        DUBAI_DM.intensity(10, 20, tc_multiplier=2.0)


def test_dubai_ignores_priority_but_says_so():
    """切到迪拜时优先级被忽略，但必须在结果里留痕，不能静默。"""
    hs = Hotspot(**{**H1.__dict__, "priority": CatchmentPriority.HIGH_DENSITY})
    r = evaluate(hs, 10, dataset="dubai_dm")
    assert r.tc_multiplier == 1.0
    assert any("已忽略优先级" in n for n in r.notes)


def test_priority_multiplier_lengthens_storm_and_lowers_intensity():
    """ADQCC Table 3-3：低优先级 → 历时更长 → 强度更低。"""
    base = evaluate(H1, 10, dataset="adqcc_zone_b")
    low = evaluate(
        Hotspot(**{**H1.__dict__, "priority": CatchmentPriority.OPEN_AREA}),
        10, dataset="adqcc_zone_b",
    )
    assert low.tc_multiplier == 12.0
    assert low.duration_min == pytest.approx(base.duration_min * 12)
    assert low.intensity_mm_hr < base.intensity_mm_hr


def test_duration_semantics_differ_between_datasets():
    """迪拜的历时是取档后的档位值，ADQCC 是 tc×M —— 语义不同，不能互换。"""
    tc = 23.0   # 落在迪拜 20/30 两档之间
    dubai = evaluate(Hotspot(**{**H1.__dict__, "tc_min": tc}), 10, dataset="dubai_dm")
    adqcc = evaluate(Hotspot(**{**H1.__dict__, "tc_min": tc}), 10, dataset="adqcc_zone_b")
    assert dubai.duration_min == 20.0        # 向下取档
    assert adqcc.duration_min == pytest.approx(23.0)   # 原样用


def test_continuous_equation_needs_no_snapping():
    """ADQCC 对档位之间的 tc 给出严格单调的强度，不存在取档阶跃。"""
    intensities = [ADQCC_ZONE_B.intensity(10, tc).intensity_mm_hr for tc in range(6, 60)]
    assert all(a > b for a, b in zip(intensities, intensities[1:]))


# ---------------------------------------------------------------------------
# 3. 注册表 / 切换
# ---------------------------------------------------------------------------


def test_registry_exposes_three_datasets_with_default_on_zone_b():
    assert set(IDF_DATASETS) == {"adqcc_zone_b", "adqcc_zone_a", "dubai_dm"}
    assert DEFAULT_DATASET_KEY == "adqcc_zone_b"
    assert get_dataset(None) is ADQCC_ZONE_B


def test_unknown_dataset_key_rejected():
    with pytest.raises(ValueError, match="未知 IDF 数据集"):
        get_dataset("sharjah")


@pytest.mark.parametrize("key", list(IDF_DATASETS))
def test_every_dataset_is_describable_for_the_ui(key):
    d = IDF_DATASETS[key].describe()
    assert d["key"] == key
    assert d["label"] and d["source"] and d["return_periods"]
    assert isinstance(d["notes"], list)


def test_results_carry_their_dataset_key():
    """两套数字会同屏出现，结果必须自己说清是哪套算的。"""
    for key in IDF_DATASETS:
        for r in evaluate_all(H1, dataset=key):
            assert r.dataset_key == key


def test_evaluate_all_skips_return_periods_the_dataset_lacks():
    """ADQCC 没有 20 年一遇，传了也不该报错，跳过即可。"""
    rps = (5, 10, 20, 25)
    assert [r.return_period_yr for r in evaluate_all(H1, rps, dataset="adqcc_zone_b")] == [5, 10, 25]
    assert [r.return_period_yr for r in evaluate_all(H1, rps, dataset="dubai_dm")] == [5, 10, 20, 25]


def test_compare_datasets_runs_both_sides():
    out = compare_datasets(H1)
    assert set(out) == {"adqcc_zone_b", "dubai_dm"}
    assert all(r.dataset_key == "adqcc_zone_b" for r in out["adqcc_zone_b"])


def test_dubai_overstates_intensity_versus_adqcc_at_h1():
    """§6.1 的量化结论：同样 tc=20min，迪拜 10 年一遇高出约 46%。"""
    dubai = evaluate(H1, 10, dataset="dubai_dm").intensity_mm_hr
    adqcc = evaluate(H1, 10, dataset="adqcc_zone_b").intensity_mm_hr
    assert dubai / adqcc == pytest.approx(1.46, abs=0.02)
