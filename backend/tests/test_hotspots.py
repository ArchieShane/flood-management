"""台账合并清洗测试（§5）。

清洗规则一旦回退，下游的逐点 Qcap 和空间关联全部作废，所以这里把三类东西
锁死：行数口径（845 而非 846）、坐标修复的四种脏写法、跨区枚举归一。
"""

import pandas as pd
import pytest

from stormwater.hotspots import (
    STANDARD_COLUMNS, build, decimal_places, haversine_m, load_fw506,
    normalize_criticality, normalize_idd_planned, normalize_intervention_type,
    normalize_root_cause, normalize_status, normalize_yes_no, parse_coordinate,
    precision_metres,
)


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return build()


@pytest.fixture(scope="module")
def fw() -> dict:
    return load_fw506()


class TestFw506:
    """`FW__Hot_Spots_506` 的解析口径 —— ADM 坐标的真源，错一个数就全线错位。"""

    def test_506_points_numbered_1_to_506(self, fw):
        """同一份 KMZ 里还有 28 个多边形和 3 条线（人工圈的积水范围草图），不能算进来。"""
        assert len(fw) == 506
        assert sorted(fw) == list(range(1, 507))

    def test_geometry_agrees_with_the_declared_attributes(self, fw):
        """KMZ 自洽是整个修正的立论基础：属性里的 LATIDUE/LONGITUDE 与点几何必须一致。

        `load_fw506()` 自己会校验并抛错，这里再从外面确认一次量级 ——
        属性是 4 位小数，与全精度几何的偏差不该超过半个最低位。
        """
        assert all(22.4 <= p["lat"] <= 25.2 and 51.0 <= p["lon"] <= 56.1 for p in fw.values())

    def test_first_point_is_the_shahama_tunnel(self, fw):
        """错位的最直白证据：Excel 第 1 行名字是 Al Shahama Tunnel，坐标却在 5 km 外的亚斯桥。"""
        assert fw[1]["desc"] == "نفق الشهامة"
        assert haversine_m(fw[1]["lat"], fw[1]["lon"], 24.546011, 54.691033) < 5.0
        assert haversine_m(fw[1]["lat"], fw[1]["lon"], fw[2]["lat"], fw[2]["lon"]) > 5000

    def test_priority_and_center_are_kept_raw(self, fw):
        """`Very Important` / `Important` 与台账的 Criticality 四档不是一套，不做映射。"""
        assert {p["priority"] for p in fw.values()} == {"Very Important", "Important"}
        assert len({p["center"] for p in fw.values()}) == 5


class TestCoordinateParsing:
    """台账里实际出现过的四种脏写法，每种都必须能修好并留痕。"""

    def test_plain_float(self):
        assert parse_coordinate(24.303228) == (24.303228, None)

    def test_non_breaking_space(self):
        """ADM 4 处：前置 \\xa0 会让 pd.to_numeric 直接判 NaN。"""
        assert parse_coordinate("\xa024.303228") == (24.303228, "coord_repaired_nbsp")

    def test_degree_suffix(self):
        """AAM 15 处。"""
        assert parse_coordinate(" 24.260988°") == (24.260988, "coord_repaired_degree")

    def test_lat_lon_pasted_into_one_cell(self):
        """AAM Hotspot_ID 174：整串 `24.516553,55.498937` 粘进了纬度格，取前半段。"""
        assert parse_coordinate("24.516553,55.498937") == (24.516553, "coord_repaired_pair_split")

    def test_unparseable_is_flagged_not_guessed(self):
        assert parse_coordinate("N/A") == (None, "coord_unparseable")

    def test_blank(self):
        assert parse_coordinate(None) == (None, None)


class TestPrecision:
    @pytest.mark.parametrize("value,decimals,metres", [
        (24.36, 2, 1110.0),      # ≈ 1.1 km，匹配最近管段必然挂错
        (24.353, 3, 111.0),
        (24.303228, 6, 0.1),
    ])
    def test_decimals_and_metres(self, value, decimals, metres):
        assert decimal_places(value) == decimals
        assert precision_metres(decimals) == pytest.approx(metres)


class TestEnumNormalisation:
    def test_criticality_case_variants_collapse(self):
        """DRM 混用了 `high` / `very high` 小写。"""
        assert normalize_criticality("high") == "High"
        assert normalize_criticality(" very high ") == "Very High"

    def test_root_cause_three_regional_wordings_map_to_one_taxonomy(self):
        """ADM 的『管网需升级』与 AAM/DRM 的『设计能力不足』判定为同义（唯一一处跨区语义合并）。"""
        assert normalize_root_cause("The network needs an upgrade") == "Inadequate Design Capacity"
        assert normalize_root_cause("Inadequate design capacity") == "Inadequate Design Capacity"
        # absense / absence 两种拼写
        assert normalize_root_cause("Absense of Drainage Network") == "Absence of Drainage Network"
        assert normalize_root_cause("Absence of drainage network") == "Absence of Drainage Network"

    def test_unknown_root_cause_is_none_not_guessed(self):
        assert normalize_root_cause("Something new") is None

    def test_intervention_type_typo(self):
        assert normalize_intervention_type("Permenent") == "Permanent"
        assert normalize_intervention_type("Permanent") == "Permanent"

    def test_status_typo(self):
        assert normalize_status("On Tack") == "On Track"

    def test_idd_planned_case_variants(self):
        assert normalize_idd_planned("NO") == "No"
        assert normalize_idd_planned("YES") == "Yes"
        assert normalize_idd_planned("Under Assessment") == "Under Assessment"

    def test_yes_no(self):
        assert normalize_yes_no("Yes") is True
        assert normalize_yes_no("no") is False
        assert normalize_yes_no("Applicable with (AACM)") is None


class TestMergedTable:
    def test_row_count_is_845_not_846(self, df):
        """ADM 末行 `#`=Outfalls / 区域=Across 是跨排放口汇总行（72 台泵），不是积水点。"""
        assert len(df) == 845

    def test_outfalls_summary_row_is_gone(self, df):
        assert not (df["area"] == "Across").any()
        # 剔除后 ADM 泵车合计 772；文档里的 844 = 772 + 汇总行的 72
        assert df.loc[df["source"] == "ADM", "pumps_qty"].sum() == 772

    def test_每个点都有坐标(self, df):
        assert df[["lat", "lon"]].notna().all().all()

    def test_坐标全部落在阿布扎比境内(self, df):
        assert df["lat"].between(22.4, 25.2).all()
        assert df["lon"].between(51.0, 56.1).all()

    def test_uid_unique(self, df):
        assert df["uid"].is_unique

    def test_columns_and_order(self, df):
        assert list(df.columns) == list(STANDARD_COLUMNS)

    def test_criticality_matches_official_totals(self, df):
        """§5.2 的官方分级口径，归一不能把总数改掉。"""
        assert df["criticality"].value_counts().to_dict() == {
            "Medium": 407, "High": 251, "Very High": 133, "Low": 54,
        }

    def test_no_enum_left_unmapped(self, df):
        flags = df["qc_flags"].fillna("")
        assert not flags.str.contains("unmapped").any()

    def test_adm_numeric_status_is_dropped_not_kept(self, df):
        """ADM 的 `Intervention status` 装的是数字（'122.0'），与 AAM/DRM 的状态词不是一回事。"""
        adm = df[df["source"] == "ADM"]
        assert adm["intervention_status"].isna().all()
        assert adm["qc_flags"].fillna("").str.contains("status_numeric_dropped").sum() == 53
        assert set(df["intervention_status"].dropna()) <= {"Not Started", "On Track", "Completed"}

    def test_low_precision_points_are_flagged(self, df):
        """8 个 ADM 点只有 ≤3 位小数，必须标出来，否则会挂到错的管段上。

        改坐标源之前是 29 个 —— KMZ 的 `<coordinates>` 是全精度的，
        原 Excel 里那批 2–3 位小数的点大多在换源后精度就够了，剩下这 8 个
        是 KMZ 自己也只给了 2–3 位。
        """
        low = df["qc_flags"].fillna("").str.contains("coord_low_precision")
        assert low.sum() == 8
        assert (df.loc[low, "coord_decimals"] <= 3).all()
        assert (df.loc[low, "source"] == "ADM").all()

    def test_duplicate_coordinates_are_flagged_not_merged(self, df):
        """17 个 ADM 点两两（或三三）同坐标，必有一处重复录入，留给人工核实。

        这批重复是 `FW__Hot_Spots_506` 自带的，不是清洗引入的：同一个位置
        在 DMT 的清单里被登记了两次（如 `مصفح صناعية - قطاع MW3` 出现两行）。
        换坐标源之前只有 ADM-505 / ADM-506 一对，那一对是 Excel 错位的产物
        （最后一行没有「下一行」可挪，坐标被重复），换源后自然消失。
        """
        dup = df[df["qc_flags"].fillna("").str.contains("coord_duplicate")]
        assert len(dup) == 17
        assert (dup["source"] == "ADM").all()
        assert dup.groupby(["lat", "lon"]).ngroups == 8

    def test_adm_coordinates_come_from_the_kmz_not_the_excel(self, df):
        """ADM 坐标一律以 `FW__Hot_Spots_506` 为准 —— Excel 的坐标列整体错位一行。

        506 个点里 505 个位置变了（唯一没动的是与 KMZ 恰好同坐标的那个），
        中位位移 1.86 km，所以任何逐点空间批算都必须在换源之后重跑。
        """
        adm = df[df["source"] == "ADM"]
        assert (adm["coord_source"] == "506 Hot Spots AUH.kmz").all()
        assert adm["qc_flags"].fillna("").str.contains("coord_fixed_by_fw506").sum() == 505
        other = df[df["source"] != "ADM"]
        assert other["coord_source"].str.endswith(".xlsx").all()
        assert not other["qc_flags"].fillna("").str.contains("fw506").any()

    def test_kmz_only_covers_adm(self, df):
        """KMZ 带来的优先级 / 服务中心两列只有 ADM 有，AAM / DRM 必须留空。"""
        adm = df[df["source"] == "ADM"]
        assert set(adm["fw_priority_raw"]) == {"Very Important", "Important"}
        assert adm["fw_center_raw"].notna().all()
        assert adm["fw_center_raw"].nunique() == 5
        other = df[df["source"] != "ADM"]
        assert other["fw_priority_raw"].isna().all()
        assert other["fw_center_raw"].isna().all()
