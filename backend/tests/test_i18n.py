"""中英切换的护栏。

`i18n.EN` 是**按原串精确匹配**的，所以任何人改了 `idf.py` / `pumps.py` /
`registry.py` / `api/main.py` 里的一句中文，翻译就会悄悄退回中文 —— 屏幕上不报错，
只是英文界面里多出一段中文。这组测试把「哪些串必须有英文」钉死，改了就红。
"""

import re

import pytest
from fastapi.testclient import TestClient

from stormwater.api.main import LIMITATIONS, app
from stormwater.i18n import resolve_lang, tr
from stormwater.idf import (
    DESIGN_RETURN_PERIOD_BY_FACILITY,
    IDF_DATASETS,
    CatchmentPriority,
)
from stormwater.pumps import DEFAULT_PUMP_TIERS, uniform_tier
from stormwater.registry import PROFILE_FIELD_BASIS
from stormwater.scenario import CustomStormIdf

CJK = re.compile(r"[一-鿿]")

client = TestClient(app)


def _translated(text: str) -> bool:
    """英文模式下这一串必须不再含汉字。"""
    return not CJK.search(tr(text, "en") or "")


# ---------------------------------------------------------------------------
# 语言判定
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lang, header, expected",
    [
        (None, None, "zh"),
        ("en", None, "en"),
        ("zh", "en-GB", "zh"),            # ?lang= 压过 Accept-Language
        (None, "en-GB,en;q=0.9", "en"),
        (None, "zh-CN,zh;q=0.9", "zh"),
        ("fr", None, "zh"),               # 不认的语言回落中文
        ("", "", "zh"),
    ],
)
def test_resolve_lang(lang, header, expected):
    assert resolve_lang(lang, header) == expected


def test_tr_is_identity_in_chinese():
    assert tr("使用推理公式法 + 简化三角形过程线，属筛查与排序工具，非最终设计。", "zh") == (
        "使用推理公式法 + 简化三角形过程线，属筛查与排序工具，非最终设计。"
    )


def test_tr_passes_unknown_strings_through():
    """匹配不上就原样返回 —— 宁可漏一句中文，也不要吞掉一句口径说明。"""
    assert tr("这一句没进过翻译表", "en") == "这一句没进过翻译表"


# ---------------------------------------------------------------------------
# 领域模块里那批会出现在页面上的中文串，逐个必须有英文
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("priority", list(CatchmentPriority))
def test_priority_labels_translated(priority):
    assert _translated(priority.label)


@pytest.mark.parametrize("key", sorted(IDF_DATASETS))
def test_idf_dataset_description_translated(key):
    ds = IDF_DATASETS[key]
    assert _translated(ds.label)
    assert _translated(ds.source)
    for note in ds.notes:
        assert _translated(note), note


def test_custom_storm_translated():
    ds = CustomStormIdf(50.0, 120.0)
    assert _translated(ds.label)
    assert _translated(ds.source)
    for note in ds.notes:
        assert _translated(note), note


@pytest.mark.parametrize("_, desc", DESIGN_RETURN_PERIOD_BY_FACILITY)
def test_design_return_periods_translated(_, desc):
    assert _translated(desc)


@pytest.mark.parametrize("tier", [*DEFAULT_PUMP_TIERS, uniform_tier(300.0)])
def test_pump_tiers_translated(tier):
    assert _translated(tier.label)
    assert _translated(tier.basis)
    assert _translated(tier.reference)


@pytest.mark.parametrize("field", sorted(PROFILE_FIELD_BASIS))
def test_profile_field_basis_translated(field):
    assert _translated(PROFILE_FIELD_BASIS[field])


@pytest.mark.parametrize("line", LIMITATIONS)
def test_limitations_translated(line):
    assert _translated(line)


# ---------------------------------------------------------------------------
# 端到端：英文模式下，展示字段里一个汉字都不该剩
# ---------------------------------------------------------------------------


def test_idf_datasets_endpoint_fully_english():
    body = client.get("/api/idf-datasets?lang=en").json()
    for ds in body["datasets"]:
        assert not CJK.search(ds["label"] + ds["source"] + "".join(ds["notes"]))
    assert not CJK.search("".join(p["label"] for p in body["priorities"]))
    assert not CJK.search("".join(d["applies_to"] for d in body["design_return_periods"]))


def test_idf_datasets_endpoint_stays_chinese_by_default():
    body = client.get("/api/idf-datasets").json()
    assert CJK.search(body["datasets"][0]["label"])


def test_hotspots_endpoint_fully_english():
    body = client.get("/api/hotspots?lang=en").json()
    # `points` 与 `facets` 里是台账原值与协议值，本来就不该翻
    for block in ("coverage", "district", "zone", "catchment", "storage"):
        for value in body[block].values():
            if isinstance(value, str):
                assert not CJK.search(value), (block, value)
    assert not CJK.search("".join(body["profile_field_basis"].values()))
    assert not CJK.search("".join(body["caveats"]))


def test_unfilled_sentinel_is_never_translated():
    """`未填写` 是协议值：后端生成它、`ScenarioRequest.matches()` 拿它比对筛选条件。
    翻了它，英文模式下按「严重度」筛就一个点都筛不到。"""
    crit = client.get("/api/hotspots?lang=en").json()["facets"]["criticality"]
    values = {row["value"] for row in crit}
    assert "未填写" in values or all(not CJK.search(v) for v in values)

    scoped = client.post(
        "/api/scenario?lang=en",
        json={"return_period_yr": 25, "criticality": ["Medium"]},
    ).json()
    assert scoped["summary"]["hotspots"] > 0


def test_scenario_endpoint_text_fields_english():
    body = client.post("/api/scenario?lang=en", json={"return_period_yr": 25}).json()
    assert not CJK.search("".join(body["limitations"]))
    for tier in body["summary"]["pump_tiers"]:
        assert not CJK.search(tier["label"] + tier["basis"] + tier["reference"])
    for tier in body["fleet_gap"]["by_tier"]:
        assert not CJK.search(tier["label"])
    for ds in body["datasets_used"]:
        assert not CJK.search(ds["label"] + ds["source"] + "".join(ds["notes"]))


def test_numbers_do_not_change_with_language():
    """语言只换文案。同一套输入两种语言跑出来，数字必须逐字段相等。"""
    payload = {"return_period_yr": 25, "district": ["ADM / AL BATEEN"]}
    zh = client.post("/api/scenario?lang=zh", json=payload).json()["summary"]
    en = client.post("/api/scenario?lang=en", json=payload).json()["summary"]
    numeric = {k: v for k, v in zh.items() if isinstance(v, (int, float))}
    assert numeric == {k: v for k, v in en.items() if isinstance(v, (int, float))}
    assert numeric, "summary 里应当有数值字段，否则这条测试没在测东西"


def test_error_detail_follows_language():
    zh = client.post("/api/point-curve?lang=zh", json={"uid": "NO-SUCH"})
    en = client.post("/api/point-curve?lang=en", json={"uid": "NO-SUCH"})
    assert zh.status_code == en.status_code == 404
    assert CJK.search(zh.json()["detail"])
    assert not CJK.search(en.json()["detail"])
