"""三份 Hotspot Analysis 台账合并清洗成一张标准表（§5 / 阶段一）。

输入：docs/ 下三份 Excel（ADM 507 行 / AAM 184 行 / DRM 155 行，表头在第 3 行），
外加 `backend/data/FW__Hot_Spots_506/506 Hot Spots AUH.kmz` —— DMT 2026-09-20 交来的
最新 ADM 清单，**ADM 的坐标以它为准**，原因见下面「ADM 坐标整体错位一行」。
输出：backend/data/processed/hotspots_845.csv（UTF-8 BOM，位置描述含阿拉伯语）。

## ADM 坐标整体错位一行（2026-09-21 发现）

ADM v4.4 Excel 里 `Latitude`/`Longitude` 两列相对名称列**整体上移了一行**：
第 n 行的名称配的是第 n+1 个点的坐标。最直白的证据是第 1 行 —— 名称
`Al Shahama Tunnel`（نفق الشهامة），坐标却是第 2 个点「جسر ياس」（亚斯桥）的；
末尾 `ايكاد 3`（ICAD 3，在穆萨法工业区 54.49°E）被配上了 54.83°E 的
「طريق الحفار」（哈法尔路，在瓦特巴）坐标，两地相距 35 km。

KMZ 每个 Placemark 自带名称 + 坐标 + `LATIDUE`/`LONGITUDE` 属性，三者同出一行、
互相自洽，不存在错位的可能。按序号 `م` 与台账 `#` 对齐后：

* 名称：506 行里 350 行与 KMZ 逐字相同，其余是中英/写法差异，**顺序完全一致**；
* 服务中心 `المركز` 与台账 `Hotspot_Area` 按同一序号对照，506 行里 499 行落在对角线上；
* 坐标：台账第 n 行 = KMZ 第 n+1 点，505 组里 494 组**逐位相同**。

所以错的只有坐标列，本模块按 KMZ 逐点改回，打 `coord_fixed_by_fw506` 标记。
**修正前的 ADM 逐点空间批算结果（Qcap / 汇水 / 调蓄 / 片区 / 积水量归属）全部作废，
必须重跑。** 中位位移 1.86 km，506 个点里 505 个动了。

为什么是 845 而不是文档里的 846 —— ADM 表 Excel 第 510 行 `#` 列写的是
`Outfalls`、区域写 `Across`，只填了 72 台泵和待命费用，是一行跨排放口的汇总行，
不是积水点。本模块把它剔除。

清洗动作全部可追溯：每一行的 `qc_flags` 列记录对该行做过什么修复或打过什么疑点标记。
本模块只做「对齐 + 归一 + 标记」，不做任何插值或猜测：拿不准的值一律保留原文到
`*_raw` 列，由下游显式决策。
"""

from __future__ import annotations

import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parents[2]
#: 三份台账原件放在仓库的 docs/ 下，不在后端包里 —— 本脚本只在开发机上重跑
DOCS = BACKEND_DIR.parent / "docs"
OUT_CSV = BACKEND_DIR / "data" / "processed" / "hotspots_845.csv"
#: DMT 2026-09-20 交来的最新 ADM 清单（506 点）。ADM 坐标的唯一真源，见模块头注释。
FW_KMZ = BACKEND_DIR / "data" / "FW__Hot_Spots_506" / "506 Hot Spots AUH.kmz"
#: KMZ 的 `SimpleField` 名是阿拉伯语，这里集中记一次，别散落在解析代码里。
FW_FIELD = {
    "seq": "م",                 # 序号，与 ADM 台账的 `#` 一一对应
    "priority": "الاولوية",      # Very Important / Important，与台账 Criticality 不是一套
    "center": "المركز",          # 服务中心：الشهامة / المدينة / الوثبة / مدينة زايد / مصفح
    "desc": "الوصف",             # 位置描述
}
#: 位移超过这个值才算「坐标被改过」，低于它只是浮点尾数差异。
COORD_FIX_TOLERANCE_M = 1.0

#: 阿布扎比酋长国的经纬度包络（WGS84）。超出即判为坐标错误，不静默接受。
LAT_RANGE = (22.4, 25.2)
LON_RANGE = (51.0, 56.1)

#: 小数位 ≤ 此值视为低精度（3 位 ≈ 110 m，2 位 ≈ 1.1 km），
#: 按经纬度匹配最近管段时会挂错，必须单独标记。
LOW_PRECISION_DECIMALS = 3


@dataclass(frozen=True)
class Source:
    key: str            # ADM / AAM / DRM
    municipality: str
    filename: str
    sheet: str
    id_col: str
    drop_tail_rows: int  # 从末尾剔除的非积水点行数


SOURCES = (
    Source("ADM", "Abu Dhabi", "20260909 ADM Stormwater Hotspot Analysis v4.4.xlsx",
           "ADM Hotspot Inventory", "#", 1),
    Source("AAM", "Al Ain", "20260909_AAM_Stormwater_Hotspot_Analysis_v4.2.xlsx",
           "Analysis", "Hotspot_ID", 0),
    Source("DRM", "Al Dhafra", "20260909_DRM_Stormwater_Hotspot_Analysis_v4.2.xlsx",
           "Analysis", "Hotspot_ID", 0),
)

#: 标准列名 -> 各区原始列名。None 表示该区没有这一列。
#: 注意 `IDD Interventoin Planned` 是 AAM/DRM 原表的拼写错误，照抄不改。
COLUMN_MAP: dict[str, dict[str, str | None]] = {
    "area":                    {"ADM": "Hotspot_Area", "AAM": "Hotspot_Area", "DRM": "Hotspot_Area"},
    "location":                {"ADM": "Hotspot_Location", "AAM": "Hotspot_Location", "DRM": "Hotspot_Location"},
    "criticality_raw":         {"ADM": "Criticality", "AAM": "Criticality", "DRM": "Criticality"},
    "developer_private_raw":   {"ADM": "Developer_Private_Area", "AAM": "Developer_Private_Area", "DRM": "Developer_Private_Area"},
    "developer_name":          {"ADM": "Developer Name", "AAM": "Developer Name", "DRM": "Developer Name"},
    "network_available_raw":   {"ADM": "Network_Available", "AAM": "Network_Available", "DRM": "Network_Available"},
    "root_cause_raw":          {"ADM": "Root_Cause", "AAM": "Root_Cause", "DRM": "Root_Cause"},
    "root_cause_details":      {"ADM": "Root_Cause_Details", "AAM": "Root_Cause_Details", "DRM": "Root_Cause_Details"},
    # ---- 应急响应计划 A（≤1-in-10yr）----
    "manpower_qty":            {"ADM": "Manpower_Qty", "AAM": "Manpower_Qty", "DRM": "Manpower_Qty"},
    "manpower_budget_aed":     {"ADM": "Total Manpower_Budget_AED", "AAM": "Total Manpower_Budget_AED", "DRM": "Total Manpower_Budget_AED"},
    "pumps_qty":               {"ADM": "Pumps_Qty", "AAM": "Pumps_Qty", "DRM": "Pumps_Qty"},
    "pump_12in_qty":           {"ADM": "Diesel Pump 12 inch Qty", "AAM": "Diesel Pump 12 inch Qty", "DRM": "Diesel Pump 12 inch Qty"},
    "pump_8in_qty":            {"ADM": "Diesel Pump 8 inch Qty", "AAM": "Diesel Pump 8 inch Qty", "DRM": "Diesel Pump 8 inch Qty"},
    "pump_6in_qty":            {"ADM": "Diesel Pump 6 inch Qty", "AAM": "Diesel Pump 6 inch Qty", "DRM": "Diesel Pump 6 inch Qty"},
    "pumps_budget_aed":        {"ADM": "Pumps_Budget_AED", "AAM": "Pumps_Budget_AED", "DRM": "Pumps_Budget_AED"},
    # ADM 的罐车列名和 AAM/DRM 完全不同（且拆成了 duty / standby 多列），这里只取数量与总预算
    "tankers_qty":             {"ADM": "Suction Tankers (NO'S)", "AAM": "Tankers_Qty", "DRM": "Tankers_Qty"},
    "tankers_budget_aed":      {"ADM": "Suction Tankers Budget Required (AED)", "AAM": "Tankers_Budget_AED", "DRM": "Tankers_Budget_AED"},
    "concrete_barrier_aed":    {"ADM": "Concrete_Barrier_AED", "AAM": "Concrete_Barrier_AED", "DRM": "Concrete_Barrier_AED"},
    "sand_barrier_aed":        {"ADM": "Sand_Barrier_AED", "AAM": "Sand_Barrier_AED", "DRM": "Sand_Barrier_AED"},
    "detention_ponds_aed":     {"ADM": "Detention_Ponds_AED", "AAM": "Detention_Ponds_AED", "DRM": "Detention_Ponds_AED"},
    "collection_chamber_aed":  {"ADM": "Collection_Chamber_AED", "AAM": "Collection_Chamber_AED", "DRM": "Collection_Chamber_AED"},
    # ---- 应急响应计划 B（>1-in-10yr）----
    "manpower_qty_b":          {"ADM": "Manpower_Qty2", "AAM": "Manpower_Qty2", "DRM": "Manpower_Qty2"},
    "manpower_budget_aed_b":   {"ADM": "Manpower_Budget_AED3", "AAM": "Manpower_Budget_AED3", "DRM": "Manpower_Budget_AED3"},
    "pumps_qty_b":             {"ADM": "Pumps_Qty4", "AAM": "Pumps_Qty4", "DRM": "Pumps_Qty4"},
    "pumps_budget_aed_b":      {"ADM": "Pumps_Budget_AED5", "AAM": "Pumps_Budget_AED5", "DRM": "Pumps_Budget_AED5"},
    "tankers_qty_b":           {"ADM": "Tankers_Qty6", "AAM": "Tankers_Qty6", "DRM": "Tankers_Qty6"},
    "tankers_budget_aed_b":    {"ADM": "Tankers_Budget_AED7", "AAM": "Tankers_Budget_AED7", "DRM": "Tankers_Budget_AED7"},
    # ---- IDD 干预计划 ----
    "idd_planned_raw":         {"ADM": "IDD Intervention Planned", "AAM": "IDD Interventoin Planned", "DRM": "IDD Interventoin Planned"},
    "idd_design_category_raw": {"ADM": "IDD_Design_Category", "AAM": "IDD_Design_Category", "DRM": "IDD_Design_Category"},
    "design_note":             {"ADM": "Design Description", "AAM": "Design Solution", "DRM": "Design Solution"},
    "intervention_type_raw":   {"ADM": "Type of Intervention", "AAM": "Type of Intervention", "DRM": "Type of Intervention"},
    "budget_required_aed":     {"ADM": "Additional Budget Requirment", "AAM": "Additional Budget Requirment", "DRM": "Additional Budget Requirment"},
    "budget_requested_aed":    {"ADM": "Additional Budget Requested", "AAM": "Additional Budget Requested", "DRM": "Additional Budget Requested"},
    "rain_event_current":      {"ADM": "Hotspot Network Rain Design Event (Current)", "AAM": "Hotspot Network Rain Design Event (Current)", "DRM": "Hotspot Network Rain Design Event (Current)"},
    "capacity_current_raw":    {"ADM": "Hotspot Network Design Technical Capacity (Current)", "AAM": "Hotspot Network Design Technical Capacity (Current)", "DRM": "Hotspot Network Design Technical Capacity (Current)"},
    "rain_event_future":       {"ADM": "Hotspot Network Rain Design Event (Future)", "AAM": "Hotspot Network Rain Design Event (Future)", "DRM": "Hotspot Network Rain Design Event (Future)"},
    "capacity_future_raw":     {"ADM": "Hotspot Network Design Technical Capacity (Future)", "AAM": "Hotspot Network Design Technical Capacity (Future)", "DRM": "Hotspot Network Design Technical Capacity (Future)"},
    "flood_volume_after":      {"ADM": "Flood Volume Capacity after Intervention", "AAM": "Flood Volume Capacity after Intervention", "DRM": "Flood Volume Capacity after Intervention"},
    "recovery_time_after":     {"ADM": "Associated recovery time after intervention", "AAM": "Associated recovery time after intervention", "DRM": "Associated recovery time after intervention"},
    "planned_mobilization_date": {"ADM": "Planned_IDD_Mobilization_Date", "AAM": "Planned_IDD_Mobilization_Date", "DRM": "Planned_IDD_Mobilization_Date"},
    "planned_completion_date": {"ADM": "Planned_IDD_Completion_Date", "AAM": "Planned_IDD_Completion_Date", "DRM": "Planned_IDD_Completion_Date"},
    "actual_mobilization_date": {"ADM": "Actual_Mobilization_Date", "AAM": "Actual_Mobilization_Date", "DRM": "Actual_Mobilization_Date"},
    "actual_completion_date":  {"ADM": "Actual_Completion_Date", "AAM": "Actual_Completion_Date", "DRM": "Actual_Completion_Date"},
    "phase1_completion_date":  {"ADM": "Critical Infrastructure Area Phase1 Solution Completion Date", "AAM": None, "DRM": None},
    "project_stage_raw":       {"ADM": "Project Stage", "AAM": "Project Stage", "DRM": "Project Stage"},
    "idas_approval_raw":       {"ADM": "Approval from IDAS secured (Yes/No)", "AAM": "Approval from IDAS secured (Yes/No)", "DRM": "Approval from IDAS secured (Yes/No)"},
    "intervention_status_raw": {"ADM": "Intervention status", "AAM": "Intervention status", "DRM": "Intervention status"},
    "idd_owner":               {"ADM": "IDD_Owner_Name", "AAM": "IDD_Owner_Name", "DRM": "IDD_Owner_Name"},
    "drm_project":             {"ADM": None, "AAM": None, "DRM": "Project"},
    "drm_notes":               {"ADM": None, "AAM": None, "DRM": "Notes"},
}

DATE_COLUMNS = (
    "planned_mobilization_date", "planned_completion_date",
    "actual_mobilization_date", "actual_completion_date", "phase1_completion_date",
)

NUMERIC_COLUMNS = (
    "manpower_qty", "manpower_budget_aed", "pumps_qty",
    "pump_12in_qty", "pump_8in_qty", "pump_6in_qty", "pumps_budget_aed",
    "tankers_qty", "tankers_budget_aed", "concrete_barrier_aed", "sand_barrier_aed",
    "detention_ponds_aed", "collection_chamber_aed",
    "manpower_qty_b", "manpower_budget_aed_b", "pumps_qty_b", "pumps_budget_aed_b",
    "tankers_qty_b", "tankers_budget_aed_b",
    "budget_required_aed", "budget_requested_aed",
)

#: 最终输出的列顺序。
STANDARD_COLUMNS = (
    "uid", "source", "municipality", "hotspot_id_raw", "area", "location",
    "lat", "lon", "coord_decimals", "coord_precision_m", "coord_source",
    "fw_priority_raw", "fw_center_raw",
    "criticality", "criticality_raw",
    "network_available", "network_available_raw",
    "root_cause", "root_cause_raw", "root_cause_details",
    "developer_private_raw", "developer_name",
    *NUMERIC_COLUMNS[:13],
    *NUMERIC_COLUMNS[13:19],
    "idd_planned", "idd_planned_raw", "idd_design_category_raw", "design_note",
    "intervention_type", "intervention_type_raw",
    "budget_required_aed", "budget_requested_aed",
    "rain_event_current", "capacity_current_raw",
    "rain_event_future", "capacity_future_raw",
    "flood_volume_after", "recovery_time_after",
    *DATE_COLUMNS,
    "project_stage_raw", "idas_approval",
    "intervention_status", "intervention_status_raw", "idd_owner",
    "drm_project", "drm_notes",
    "qc_flags",
)


# ---------------------------------------------------------------------------
# FW__Hot_Spots_506 —— ADM 坐标的真源
# ---------------------------------------------------------------------------

def load_fw506(path: Path = FW_KMZ) -> dict[int, dict[str, object]]:
    """解析 506 点 KMZ，返回 `{序号: {...}}`。

    只取带 `ExtendedData` 的 Placemark —— 同一份 KMZ 里还有 28 个多边形和 3 条线，
    是人工圈的积水范围草图（名字里那些 `63,000`、`6,000 m2` 是面积标注），
    没有属性表，不是积水点，本函数一律跳过。

    坐标取 `<Point><coordinates>`（全精度），并用 `LATIDUE`/`LONGITUDE` 属性
    （4 位小数）对拍一遍：两者不一致说明这份 KMZ 自身就乱了，直接报错，
    不静默择一 —— 整个修正的立论就建立在「KMZ 自洽」上。
    """
    with zipfile.ZipFile(path) as zf:
        kml = zf.read("doc.kml").decode("utf-8")

    out: dict[int, dict[str, object]] = {}
    for pm in re.findall(r"<Placemark>.*?</Placemark>", kml, re.S):
        if "<ExtendedData>" not in pm or "<Point>" not in pm:
            continue
        data = dict(re.findall(r'<SimpleData name="(.*?)">(.*?)</SimpleData>', pm, re.S))
        lon, lat, *_ = re.search(
            r"<Point>\s*<coordinates>(.*?)</coordinates>", pm, re.S
        ).group(1).strip().split(",")
        lat, lon = float(lat), float(lon)
        for value, attr in ((lat, "LATIDUE"), (lon, "LONGITUDE")):
            declared = data.get(attr)
            if declared is not None and abs(value - float(declared)) > 5e-4:
                raise ValueError(f"{path.name}：{attr} 属性与几何对不上（{declared} vs {value}）")
        seq = int(data[FW_FIELD["seq"]])
        if seq in out:
            raise ValueError(f"{path.name}：序号 {seq} 重复")
        out[seq] = {
            "lat": lat,
            "lon": lon,
            "desc": _text(data.get(FW_FIELD["desc"])),
            "center": _text(data.get(FW_FIELD["center"])),
            "priority": _text(data.get(FW_FIELD["priority"])),
        }
    return out


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点距离（米）。只用来量修正前后的位移，几百公里内够用。"""
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------

def _text(value: object) -> str | None:
    """去掉不间断空格、换行、首尾空白；空串返回 None。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).replace("\xa0", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def normalize_criticality(value: object) -> str | None:
    """DRM 用了 `high` / `very high` 等小写变体，统一成四档官方口径。"""
    s = _text(value)
    if s is None:
        return None
    key = s.lower()
    return {
        "very high": "Very High", "high": "High",
        "medium": "Medium", "low": "Low",
    }.get(key)


def normalize_yes_no(value: object) -> bool | None:
    s = _text(value)
    if s is None:
        return None
    key = s.lower()
    if key in ("yes", "y", "true"):
        return True
    if key in ("no", "n", "false"):
        return False
    return None


def normalize_root_cause(value: object) -> str | None:
    """三区用了三套说法，归到 AAM/DRM 的 `Root_Cause_Category` 三分类。

    ADM 的 `The network needs an upgrade` 与 AAM/DRM 的
    `Inadequate Design Capacity` 判定为同义（现有管网能力不足），这是本模块唯一
    一处跨区语义合并；原文保留在 `root_cause_raw`，不认可可直接改这里。
    """
    s = _text(value)
    if s is None:
        return None
    key = s.lower()
    if "absen" in key and "drainage" in key:      # absense / absence 两种拼写
        return "Absence of Drainage Network"
    if "inadequate design capacity" in key or "needs an upgrade" in key:
        return "Inadequate Design Capacity"
    if "topography" in key:
        return "Topography & Road Engineering"
    return None


def normalize_intervention_type(value: object) -> str | None:
    """`Permenent` 是三区通用的拼写错误。"""
    s = _text(value)
    if s is None:
        return None
    key = s.lower()
    if key.startswith("perm"):
        return "Permanent"
    if key.startswith("intermediate"):
        return "Intermediate"
    if key.startswith("temporary"):
        return "Temporary"
    if key.replace(".", "").startswith("tbc"):
        return "TBC"
    return None


def normalize_idd_planned(value: object) -> str | None:
    s = _text(value)
    if s is None:
        return None
    key = s.lower()
    if key == "yes":
        return "Yes"
    if key == "no":
        return "No"
    if "assessment" in key:
        return "Under Assessment"
    return None


def normalize_status(value: object) -> str | None:
    """AAM 的 `On Tack` 是 `On Track` 的笔误。ADM 此列作废，见 load_source。"""
    s = _text(value)
    if s is None:
        return None
    key = s.lower().replace(" ", "")
    if key in ("ontrack", "ontack"):
        return "On Track"
    if key == "notstarted":
        return "Not Started"
    if key == "completed":
        return "Completed"
    return None


def _number(value: object) -> float | None:
    """从可能带千分位/货币符号/单位的单元格里抽数值；抽不出返回 None。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = _text(value)
    if s is None:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", s.replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 坐标
# ---------------------------------------------------------------------------

def parse_coordinate(value: object) -> tuple[float | None, str | None]:
    """解析一个经度或纬度单元格，返回 (值, 修复标记)。

    台账里实际出现过四种写法：
      1. 正常浮点
      2. `'\\xa024.303228'`        —— 前置不间断空格（ADM 4 处）
      3. `' 24.260988°'`           —— 带度数符号（AAM 15 处）
      4. `'24.516553,55.498937'`   —— 经纬度整串粘进纬度格（AAM 1 处）
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None, None
    if isinstance(value, (int, float)):
        return float(value), None

    raw = str(value)
    flag = None
    s = raw.replace("\xa0", " ")
    if s != raw:
        flag = "coord_repaired_nbsp"
    if "°" in s:
        s = s.replace("°", "")
        flag = "coord_repaired_degree"
    s = s.strip()
    if "," in s:
        s = s.split(",")[0].strip()
        flag = "coord_repaired_pair_split"
    try:
        return float(s), flag
    except ValueError:
        return None, "coord_unparseable"


def decimal_places(value: float | None) -> int | None:
    if value is None:
        return None
    text = repr(float(value))
    return len(text.split(".")[1].rstrip("0")) if "." in text else 0


def precision_metres(decimals: int | None) -> float | None:
    """纬度 1 度 ≈ 111 km，据此把小数位折算成定位误差量级。"""
    if decimals is None:
        return None
    return round(111_000 / (10 ** decimals), 1)


# ---------------------------------------------------------------------------
# 读取与组装
# ---------------------------------------------------------------------------

def load_source(src: Source) -> pd.DataFrame:
    """读一份台账，做列对齐与逐行归一，返回标准列的 DataFrame。"""
    path = DOCS / src.filename
    raw = pd.read_excel(path, sheet_name=src.sheet, header=2)
    raw.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in raw.columns]
    if src.drop_tail_rows:
        raw = raw.iloc[: len(raw) - src.drop_tail_rows]

    out = pd.DataFrame(index=raw.index)
    out["source"] = src.key
    out["municipality"] = src.municipality
    out["hotspot_id_raw"] = raw[src.id_col]

    for std, per_source in COLUMN_MAP.items():
        col = per_source[src.key]
        out[std] = raw[col] if col and col in raw.columns else None

    flags: list[list[str]] = [[] for _ in out.index]

    lats, lons = [], []
    for pos, idx in enumerate(raw.index):
        lat, lat_flag = parse_coordinate(raw.at[idx, "Latitude"])
        lon, lon_flag = parse_coordinate(raw.at[idx, "Longitude"])
        for f in (lat_flag, lon_flag):
            if f and f not in flags[pos]:
                flags[pos].append(f)
        if lat is None or lon is None:
            flags[pos].append("coord_missing")
        elif not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            flags[pos].append("coord_out_of_emirate")
        lats.append(lat)
        lons.append(lon)
    out["lat"], out["lon"] = lats, lons
    out["coord_source"] = src.filename

    # ---- ADM：坐标列整体错位一行，按 FW__Hot_Spots_506 逐点改回（见模块头注释）----
    out["fw_priority_raw"] = None
    out["fw_center_raw"] = None
    if src.key == "ADM":
        fw = load_fw506()
        seqs = [int(_number(v) or 0) for v in out["hotspot_id_raw"]]
        if sorted(seqs) != sorted(fw):
            raise ValueError(
                f"ADM 台账序号与 {FW_KMZ.name} 对不上："
                f"台账 {len(seqs)} 个 / KMZ {len(fw)} 个，差集 "
                f"{sorted(set(seqs) ^ set(fw))[:10]}"
            )
        priorities, centers = [], []
        for pos, seq in enumerate(seqs):
            point = fw[seq]
            priorities.append(point["priority"])
            centers.append(point["center"])
            old_lat, old_lon = lats[pos], lons[pos]
            lats[pos], lons[pos] = point["lat"], point["lon"]
            if old_lat is None or old_lon is None:
                flags[pos].append("coord_filled_by_fw506")
                continue
            moved = haversine_m(old_lat, old_lon, point["lat"], point["lon"])
            if moved > COORD_FIX_TOLERANCE_M:
                flags[pos].append("coord_fixed_by_fw506")
        out["lat"], out["lon"] = lats, lons
        out["coord_source"] = FW_KMZ.name
        out["fw_priority_raw"] = priorities
        out["fw_center_raw"] = centers

    out["coord_decimals"] = [decimal_places(v) for v in lats]
    out["coord_precision_m"] = [precision_metres(d) for d in out["coord_decimals"]]
    for pos, d in enumerate(out["coord_decimals"]):
        if d is not None and d <= LOW_PRECISION_DECIMALS:
            flags[pos].append("coord_low_precision")

    out["criticality"] = out["criticality_raw"].map(normalize_criticality)
    out["network_available"] = out["network_available_raw"].map(normalize_yes_no)
    out["root_cause"] = out["root_cause_raw"].map(normalize_root_cause)
    out["intervention_type"] = out["intervention_type_raw"].map(normalize_intervention_type)
    out["idd_planned"] = out["idd_planned_raw"].map(normalize_idd_planned)
    out["idas_approval"] = out["idas_approval_raw"].map(normalize_yes_no)
    out["intervention_status"] = out["intervention_status_raw"].map(normalize_status)

    # pandas 3 的 str dtype 用 NaN 表示缺失，不能用 `is None` 判空。
    for std in ("criticality", "root_cause"):
        for pos, (v, rawv) in enumerate(zip(out[std], out[f"{std}_raw"])):
            if pd.isna(v) and _text(rawv) is not None:
                flags[pos].append(f"{std}_unmapped")

    for col in NUMERIC_COLUMNS:
        out[col] = out[col].map(_number)
    for col in DATE_COLUMNS:
        out[col] = pd.to_datetime(out[col], errors="coerce", format="mixed").dt.date

    for col in ("area", "location", "root_cause_details", "developer_name",
                "developer_private_raw", "design_note", "idd_design_category_raw",
                "project_stage_raw", "rain_event_current", "capacity_current_raw",
                "rain_event_future", "capacity_future_raw", "flood_volume_after",
                "recovery_time_after", "intervention_status_raw", "idd_owner",
                "drm_project", "drm_notes", "criticality_raw", "root_cause_raw",
                "network_available_raw", "idd_planned_raw", "intervention_type_raw",
                "idas_approval_raw"):
        out[col] = out[col].map(_text)

    # ADM 的 `Intervention status` 装的是数字（'122.0' 之类），与 AAM/DRM 的
    # Not Started / On Track / Completed 完全不是一回事，判定为错列，置空并标记。
    if src.key == "ADM":
        for pos, v in enumerate(out["intervention_status_raw"]):
            if pd.notna(v):
                flags[pos].append("status_numeric_dropped")
        out["intervention_status"] = None
        out["intervention_status_raw"] = None

    width = len(str(len(out)))
    out["uid"] = [f"{src.key}-{int(_number(v) or 0):0{max(width, 3)}d}"
                  for v in out["hotspot_id_raw"]]
    out["qc_flags"] = [";".join(f) or None for f in flags]
    return out


def build() -> pd.DataFrame:
    """合并三份台账，补上跨区才能判定的标记（坐标重复）。"""
    df = pd.concat([load_source(s) for s in SOURCES], ignore_index=True)

    dup = df[["lat", "lon"]].dropna().duplicated(keep=False)
    for idx in dup[dup].index:
        prev = df.at[idx, "qc_flags"]
        parts = [p for p in (prev, "coord_duplicate") if pd.notna(p) and p]
        df.at[idx, "qc_flags"] = ";".join(parts)

    return df.reindex(columns=list(STANDARD_COLUMNS))


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------

#: 本模块**唯一**允许写的表。`db.connect()` 是强制只读的，落库单开一条可写连接，
#: 与 `catchment_batch.build_tables()` 同一套路。
DB_TABLE = "hotspot.hotspots_845"

#: 落库只带空间批算真正用得上的列，不是台账的镜像 —— 预算、日期、干预计划留在 CSV 里。
DB_COLUMNS = (
    "uid", "source", "municipality", "area", "location", "lat", "lon",
    "criticality", "network_available", "root_cause", "pumps_qty", "tankers_qty",
)


def load_db(df: pd.DataFrame | None = None) -> int:
    """把台账重灌进 `hotspot.hotspots_845`，几何按 WGS84 → EPSG:32640 投影。

    ⚠ 整表清空后重灌。灌完必须重跑全部逐点空间批算（qcap / catchment / storage /
    coverage / district / ponding），否则库里的点动了、CSV 里的结果还是旧的。
    """
    import psycopg

    from .config import db_settings

    df = build() if df is None else df
    rows = [
        tuple(None if pd.isna(v) else v for v in r)
        for r in df[list(DB_COLUMNS)].itertuples(index=False, name=None)
    ]
    placeholders = ", ".join(["%s"] * len(DB_COLUMNS))
    sql = (
        f"insert into {DB_TABLE} ({', '.join(DB_COLUMNS)}, geom) values ({placeholders}, "
        "st_transform(st_setsrid(st_makepoint(%s, %s), 4326), 32640))"
    )
    lon_i, lat_i = DB_COLUMNS.index("lon"), DB_COLUMNS.index("lat")
    with psycopg.connect(db_settings().conninfo) as conn, conn.cursor() as cur:
        cur.execute(f"delete from {DB_TABLE}")
        cur.executemany(sql, [r + (r[lon_i], r[lat_i]) for r in rows])
        conn.commit()
    return len(rows)


def main() -> None:
    df = build()
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print(f"写出 {OUT_CSV.relative_to(BACKEND_DIR)} —— {len(df)} 行 × {len(df.columns)} 列")
    print("\n按区域：")
    print(df.groupby(["source", "municipality"]).size().to_string())
    print("\n按 Criticality：")
    print(df["criticality"].value_counts(dropna=False).to_string())
    print("\n按 Root_Cause：")
    print(df["root_cause"].value_counts(dropna=False).to_string())
    print("\nQC 标记计数：")
    exploded = df["qc_flags"].dropna().str.split(";").explode()
    print(exploded.value_counts().to_string() if len(exploded) else "（无）")
    n_cap = df["capacity_current_raw"].notna().sum()
    print(f"\n目标列 capacity_current_raw 有值 {n_cap} / {len(df)}（均为区域级估值，待逐点 Qcap 替换）")


if __name__ == "__main__":
    import sys

    main()
    if "--load-db" in sys.argv:
        print(f"\n落库 {DB_TABLE} —— {load_db()} 行；"
              "记得重跑 qcap / catchment / storage / coverage / district / ponding 六个批算")
