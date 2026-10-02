"""调蓄设施的**深度与尺寸缺省值目录**——第二道防线缺数时的补数来源。

`storage_batch.py` 实测的结论是：250 m 内 139 条设施记录，**没有一条**的深度与尺寸
同时可用（`pond` 19/23 条盖底同高、`sw_reservoirstructure` 20 条水位≤床底、
`soakaway` 977 条里 923 条三个尺寸字段全 0）。本模块补的就是这一格，分三层：

1. **实测（measured）**——库里本来就有、且通过合理性校验的字段。
   ⚠ 原批算漏掉了 `pond.volume`：23 个池里 **21 个填了容量**，与 `shape_area`
   相除得到的隐含深度 1.00–4.42 m（中位 2.18 m），正好落在 ADQCC 的 1.8–2.4 m 带内。
   这是**库里就有的实测数据**，不是假设，优先级高于本目录的任何缺省值。
2. **反推（derived）**——`volume / shape_area` 反推深度，或深度 × 几何实测面积。
3. **假设（assumed）**——本目录，逐条注明出处，见 `SOURCES`。

**取值口径**：`low / typical / high` 是**同一件事的三档**（保守 / 常用 / 乐观），
不是统计置信区间。默认一律用 `typical`，`high` 只用于敏感性对照。
渗井默认**只计结构空腔**，不计砾石包裹层的孔隙容量——后者写在 `total_m3` 里，
是乐观上界，因为砾石层是否真的能在事件历时内充水没有证据。

⚠ **三条使用限制**（写进报告时必须带上）：
* 归属仍按距离判定（250 m），没有管网连通性证据——水能不能进得去是另一回事。
* 渗井多半已经在为它自己的汇水面服务，把它算成"额外可用调蓄"有重复计算的风险。
* ADQCC §4.2 要求调蓄容积按淤积另加 5%，模型里这 5% 已经加在**需求侧**
  （`Assumptions.sed_factor`），本目录不再从供给侧扣，避免重复。
"""

from __future__ import annotations

from dataclasses import dataclass
from math import pi
from typing import Literal

Level = Literal["low", "typical", "high"]

#: 可信深度区间（米）。挡住 0（底与盖同高）和把高程当深度的离群值（102–138 m）。
DEPTH_MIN_M, DEPTH_MAX_M = 0.3, 15.0

#: 逐类可信平面面积区间（m²）。`sw_reservoirstructure` 是地下构筑物，
#: 实测几何面积 15.7–801 m²，用调蓄池那档 100 m² 的下限会把小的全砍掉。
AREA_BANDS: dict[str, tuple[float, float]] = {
    "pond": (100.0, 2_000_000.0),
    "reservoir": (5.0, 2_000_000.0),
    "soakaway": (0.5, 500.0),
}

#: 兼容旧名（`storage_batch.py` 曾经从自己那边引用）。
POND_AREA_MIN_M2, POND_AREA_MAX_M2 = AREA_BANDS["pond"]
SOAKAWAY_AREA_MIN_M2, SOAKAWAY_AREA_MAX_M2 = AREA_BANDS["soakaway"]


#: 出处清单。键是 `Dimension.source` 引用的短名，值是完整引文。
SOURCES: dict[str, str] = {
    "WA-726-1": (
        "ADQCC/DMT《Stormwater & Subsoil Drainage Systems Volume I – Design Manual》"
        "WA-726-1, Third Edition, April 2022（本地副本 docs/standards/）。"
        "§4.14.1(b)：池体进水口至出水口的高差**推荐 1.8–2.4 m**，小场地可更低。"
        "§4.12：渗井按设计重现期 24 h 径流量定容，事件结束后 24 h 内渗完；"
        "约**每 500 m² 汇水面设一座**；井底须高出最高地下水位 **≥1.0 m**；"
        "砾石包裹层孔隙率 **30–40%**（底面按淤堵计，不计入渗透面）。"
        "§4.2：调蓄湖/离线调蓄按淤积**另加 5%** 容积；土工格室系统孔隙率约 90%。"
    ),
    "WA-726-2": (
        "ADQCC/DMT《Stormwater & Subsoil Drainage Systems Volume II – Standard Drawings》"
        "WA-726-2, Third Edition, April 2022，Storm Water Lagoon 图 901–905。"
        "边坡 n:1，**n 常用 2.5–4**；堤顶 BTL = 正常水位 TWL + **1 m 超高**；"
        "溢流堰高于 TWL **≥200 mm**，紧急工况绝对最小超高 **600 mm**；"
        "池底纵坡约 1:100；图 901 注 4：**池深 ≤1.8 m 用表面曝气、更深用池底曝气**"
        "（反证常见池深就在 1.8 m 上下）。全卷**没有渗井标准图**，"
        "与 §4.12「新建系统原则上不许用渗井」一致。"
    ),
    "PWA-IAN-048": (
        "Qatar Ashghal《PWA IAN 048/14 – Design Criteria for Drainage Structures》："
        "标准渗坑内径 **3000 mm**、最小深度 **3000 mm**，双层干砌砖壁 500 mm，"
        "顶部 1 m 砌浆。海湾同类做法，用作尺寸上界（阿布扎比无对应标准图）。"
    ),
    "BS-5911-3": (
        "英标预制渗井环（BS 5911-3 / BS EN 1917，JDP、Marshalls 产品目录）："
        "内径 **900–3000 mm**，环高 500 / 750 / 1000 mm，穿孔 Ø75 mm，"
        "每米直径每米深度提供 ≥50,000 mm² 渗透面。用作圆形渗井几何的合理区间。"
    ),
    "HST-500-004": (
        "Hertfordshire County Council 标准图 HST/500/004"
        "《Typical Precast Concrete Chamber Soakaway》（Rev A, Aug 2023）："
        "井壁外 **400 mm 级配砾石包裹层**、底部 150 mm 透水层，穿孔 Ø50 mm @300 mm。"
        "本目录的包裹层厚度取自此图。"
    ),
    "BRE-365": (
        "BRE Digest 365《Soakaway Design》(2016) / CIRIA R156 —— "
        "WA-726-1 §4.12 指名的渗井水力设计依据（渗透面按侧壁计、底面按淤堵剔除）。"
    ),
    "US-DETENTION": (
        "美国各州雨洪手册（Greenville County WQ-01 / Mississippi Erosion & Stormwater "
        "Manual Vol.2 §4.6）：干式滞蓄池**最大水深 10 ft ≈ 3.0 m**，超过需做边坡稳定分析。"
        "用作明式池深的上界。"
    ),
    "MEASURED-POND": (
        "本库实测：`pond.volume / pond.shape_area` 得隐含深度 1.00–4.42 m，"
        "n=19（剔除 2 条 volume=0 与 1 条 volume=129 m³ 明显笔误），中位 **2.18 m**。"
    ),
}


@dataclass(frozen=True)
class Dimension:
    """一类设施的深度/尺寸缺省值。三档口径见模块头注释。"""

    kind: str
    depth_low_m: float
    depth_typical_m: float
    depth_high_m: float
    #: 出处短名，键见 `SOURCES`
    source: tuple[str, ...]
    note: str
    #: 圆形点状设施（渗井）的内径三档；面状设施为 None，一律用几何实测面积
    diameter_low_m: float | None = None
    diameter_typical_m: float | None = None
    diameter_high_m: float | None = None
    #: 砾石包裹层厚度（米）与孔隙率——只进 `total_m3`，不进默认容量
    surround_m: float = 0.0
    surround_void: float = 0.0

    def depth_m(self, level: Level = "typical") -> float:
        return {"low": self.depth_low_m, "typical": self.depth_typical_m,
                "high": self.depth_high_m}[level]

    def diameter_m(self, level: Level = "typical") -> float | None:
        return {"low": self.diameter_low_m, "typical": self.diameter_typical_m,
                "high": self.diameter_high_m}[level]


#: 逐类缺省值。**改这里不改计算口径**——所有取值都在 `SOURCES` 里有出处。
DEFAULTS: dict[str, Dimension] = {
    # 明式调蓄池 / 调蓄湖。深度用实测中位 2.18 m 取整，低档取 ADQCC 推荐带下沿，
    # 高档取美标干式滞蓄池上限 3.0 m（本库实测最深 4.42 m，属个例，不进默认）。
    "pond": Dimension(
        kind="pond",
        depth_low_m=1.8, depth_typical_m=2.2, depth_high_m=3.0,
        source=("MEASURED-POND", "WA-726-1", "WA-726-2", "US-DETENTION"),
        note="有效蓄水深（正常水位−池底），不含 WA-726-2 要求的 1 m 堤顶超高；"
             "平面面积一律用几何实测值，不用本目录。",
    ),
    # 地下蓄水构筑物。阿布扎比标准里没有对应尺寸，取值锚定在池体高差带 1.8–2.4 m 的
    # 下半段——地下构筑物受开挖深度与地下水位限制，通常比明式池浅。⚠ 这一条是
    # 工程判断，置信度低于 pond，DMT 清单里应当点名索要。
    "reservoir": Dimension(
        kind="reservoir",
        depth_low_m=1.5, depth_typical_m=2.0, depth_high_m=3.0,
        source=("WA-726-1", "MEASURED-POND"),
        note="⚠ 无当地标准直接支持，锚定 ADQCC §4.14.1(b) 高差带下半段的工程判断值；"
             "平面面积用几何实测值。",
    ),
    # 渗井。库里是点，尺寸与深度都得假设。内径取英标预制环常用中档 1.5 m
    # （区间 0.9–3.0 m），有效深 3.0 m 取 Ashghal 的最小深度，同时满足
    # WA-726-1 的「井底高出最高地下水位 ≥1.0 m」在浅地下水区仍可施工。
    "soakaway": Dimension(
        kind="soakaway",
        depth_low_m=2.0, depth_typical_m=3.0, depth_high_m=3.0,
        diameter_low_m=1.0, diameter_typical_m=1.5, diameter_high_m=3.0,
        surround_m=0.4, surround_void=0.30,
        source=("BS-5911-3", "PWA-IAN-048", "HST-500-004", "WA-726-1", "BRE-365"),
        note="有效深 = 进水管管底至井底。默认容量**只算结构空腔**；"
             "砾石包裹层（0.4 m 厚、孔隙率 0.30）的容量单列在 total_m3，是乐观上界。",
    ),
}


@dataclass(frozen=True)
class AssetVolume:
    """一条设施记录的深度/尺寸/容量结论，带出处分层。"""

    #: 默认口径容量（渗井不含砾石层）；算不出为 None
    volume_m3: float | None
    #: 含砾石包裹层的乐观上界；非渗井与 volume_m3 相同
    total_m3: float | None
    depth_m: float | None
    footprint_m2: float | None
    #: measured / derived / assumed / rejected
    tier: str
    #: 细分出处或剔除原因
    reason: str

    @property
    def usable(self) -> bool:
        return self.volume_m3 is not None


def assumed_volume_m3(kind: str, footprint_m2: float | None = None,
                      level: Level = "typical") -> tuple[float, float, float, float]:
    """按目录给一条设施的假设容量。

    返回 `(volume_m3, total_m3, depth_m, footprint_m2)`。
    面状设施（pond / reservoir）必须传几何实测面积；渗井传 None，用目录内径。
    """
    dim = DEFAULTS[kind]
    depth = dim.depth_m(level)

    diameter = dim.diameter_m(level)
    if diameter is not None:                      # 圆形点状设施：尺寸也来自目录
        area = pi * (diameter / 2.0) ** 2
        structure = area * depth
        outer = diameter + 2 * dim.surround_m
        surround = (pi * (outer ** 2 - diameter ** 2) / 4.0) * depth * dim.surround_void
        return structure, structure + surround, depth, area

    if footprint_m2 is None:
        raise ValueError(f"{kind} 是面状设施，必须给几何实测面积")
    vol = footprint_m2 * depth
    return vol, vol, depth, footprint_m2


def _soakaway_footprint_m2(diameter: float | None, length: float | None,
                           width: float | None) -> tuple[float | None, str]:
    """渗井平面面积（m²）。返回 (面积, 单位判读说明)；判不出返回 (None, 原因)。

    尺寸字段单位没有任何声明，实测取值自相矛盾 —— 例如同一条记录
    `diameter=160` 配 `length=2.0 / width=1.5`（前者像 mm、后者像 m），
    又有 `diameter=1200` 配 `length=6000 / width=6000`（全像 mm）。

    因此这里**不猜**：分别按「全 mm」和「全 m」两种口径算一遍，
    只有恰好一种落在可信面积区间内才采用；两种都成立或都不成立 → 判定为单位歧义。
    与 `manning.py` 拒绝自动猜测管径/坡度单位是同一条原则。
    """
    if diameter and diameter > 0:
        raw = pi * (diameter / 2.0) ** 2          # 圆形
        as_mm, as_m = raw / 1_000_000.0, raw
    elif length and width and length > 0 and width > 0:
        raw = length * width                      # 矩形
        as_mm, as_m = raw / 1_000_000.0, raw
    else:
        return None, "no_dimension"

    ok_mm = SOAKAWAY_AREA_MIN_M2 <= as_mm <= SOAKAWAY_AREA_MAX_M2
    ok_m = SOAKAWAY_AREA_MIN_M2 <= as_m <= SOAKAWAY_AREA_MAX_M2
    if ok_mm and not ok_m:
        return as_mm, "mm"
    if ok_m and not ok_mm:
        return as_m, "m"
    return None, "ambiguous_units"


def _plausible_depth(depth: float | None) -> bool:
    return depth is not None and DEPTH_MIN_M <= depth <= DEPTH_MAX_M


def _plausible_area(area: float | None, kind: str) -> bool:
    lo, hi = AREA_BANDS[kind]
    return area is not None and lo <= area <= hi


def resolve_asset(row: dict, level: Level = "typical",
                  allow_assumed: bool = True) -> AssetVolume:
    """一条设施记录 → 容量结论。**实测 > 反推 > 假设**，逐层降级。

    `row` 的字段由 `ALL_ASSETS_SQL` / `storage_batch.ASSETS_SQL` 对齐：
    `kind` / `depth_m`（盖或最高水位 − 底）/ `footprint_m2` / `volume_m3`
    / `dim_diameter` / `dim_length` / `dim_width`。
    """
    kind = row["kind"]
    area = row.get("footprint_m2")
    depth = row.get("depth_m")
    volume = row.get("volume_m3")

    # ---- 第 1 层：实测 ---------------------------------------------------
    # 渗井：尺寸字段 + 盖底高差都可用才算实测（全库 0 条通过，见模块头注释）。
    if kind == "soakaway":
        measured_area, why = _soakaway_footprint_m2(
            row.get("dim_diameter"), row.get("dim_length"), row.get("dim_width")
        )
        if measured_area is not None and _plausible_depth(depth):
            v = measured_area * depth
            return AssetVolume(v, v, depth, measured_area, "measured", f"尺寸+深度实测({why})")
    else:
        # 面状设施：`pond.volume` 是台账直接填的**蓄水容量**，比「盖底高差 × 面积」
        # 更贴近可用调蓄 —— 后者量的是开挖深度，含 WA-726-2 要求的 1 m 堤顶超高，
        # 会系统性高估。两者都在时以 volume 为准，差 2 倍以上在 reason 里点名。
        area_ok = _plausible_area(area, kind)
        implied = volume / area if (volume and volume > 0 and area_ok) else None
        level_ok = area_ok and _plausible_depth(depth)

        if implied is not None and _plausible_depth(implied):
            reason = "台账 volume（直接量）"
            if level_ok and not (0.5 <= implied / depth <= 2.0):
                reason += f"；⚠ 与盖底高差 {depth:.2f} m 不符（隐含 {implied:.2f} m），已取前者"
            return AssetVolume(volume, volume, implied, area, "measured", reason)

        # ---- 第 2 层：反推 ------------------------------------------------
        if level_ok:
            v = area * depth
            reason = "几何实测面积 × 盖底高差"
            if volume is not None and (not volume or volume <= 0):
                reason += "（台账 volume 为空或 0）"
            elif implied is not None:
                reason += f"；台账 volume={volume:,.0f} m³ 隐含深度 {implied:.3f} m 不可信，已弃"
            return AssetVolume(v, v, depth, area, "derived", reason)

    # ---- 第 3 层：假设 ---------------------------------------------------
    if not allow_assumed:
        return AssetVolume(None, None, None, area, "rejected", "深度或尺寸不可用")

    if kind == "soakaway":
        v, total, d, a = assumed_volume_m3(kind, None, level)
        return AssetVolume(v, total, d, a, "assumed", f"目录缺省值({level})：尺寸+深度")

    if not _plausible_area(area, kind):
        # 面状设施连几何面积都不可信——没有可假设的底
        return AssetVolume(None, None, None, area, "rejected", "几何面积缺失或不合理")

    v, total, d, a = assumed_volume_m3(kind, area, level)
    return AssetVolume(v, total, d, a, "assumed", f"目录缺省深度({level})×几何实测面积")


# ---------------------------------------------------------------------------
# 全量设施清单 —— 逐条落成 CSV，供人工核对与 DMT 反馈
# ---------------------------------------------------------------------------

_SCHEMA = "dmt_irrigationstormwater_abudhabi"

#: ⚠ 一律排除 `status='Expired'`：`sw_reservoirstructure` 的 18/19/20 三条是
#: `pond` 5/6/10 的过期副本（几何 Hausdorff 距离 0），其中 2 条落在积水点 250 m 内，
#: 不排会把同一个池算两遍。
STATUS_FILTER = "coalesce(a.status,'') <> 'Expired'"

ALL_ASSETS_SQL = f"""
select a.uid, a.objectid, 'pond' as kind, a.status, a.unittype,
       a.zone_or_district_name as district,
       a.shape_area                          as footprint_m2,
       a.cover_level - a.bottom_floor_level  as depth_m,
       a.volume                              as volume_m3,
       null::float8 as dim_diameter, null::float8 as dim_length, null::float8 as dim_width
from {_SCHEMA}.pond a where {STATUS_FILTER}

union all
select a.uid, a.objectid, 'reservoir', a.status, a.unittype,
       a.zone_or_district_name,
       a.shape_area,
       a.max_water_level - a.bed_level,
       null::float8,
       null, null, null
from {_SCHEMA}.sw_reservoirstructure a where {STATUS_FILTER}

union all
select a.uid, a.objectid, 'soakaway', a.status, a.unittype,
       a.zone_or_district_name,
       null::float8,
       a.cover_level - a.bottom_level,
       null::float8,
       a.soakaway_diameter::float8, a.soakaway_length, a.soakaway_width
from {_SCHEMA}.soakaway a where {STATUS_FILTER}
order by 3, 2
"""


#: 相对 backend/ 的路径，写出时与 BACKEND_DIR 拼接（见下面的 write_csv）
OUTPUT_CSV = "data/processed/storage_asset_dims.csv"

#: CSV 列顺序。每条设施一行，深度/尺寸/容量各自带出处分层。
_CSV_COLUMNS = (
    "uid", "objectid", "kind", "status", "unittype", "district",
    "footprint_m2", "depth_m", "volume_m3", "total_m3",
    "volume_low_m3", "volume_high_m3", "tier", "reason", "source",
)


def build_rows(level: Level = "typical") -> list[dict]:
    """连库取全部三类设施，逐条给出深度/尺寸/容量与出处。"""
    from .db import query  # 延迟导入：没有数据库也能 import 本模块

    rows: list[dict] = []
    for a in query(ALL_ASSETS_SQL):
        res = resolve_asset(a, level)
        low = resolve_asset(a, "low")
        high = resolve_asset(a, "high")
        dim = DEFAULTS[a["kind"]]
        rows.append({
            "uid": a["uid"],
            "objectid": a["objectid"],
            "kind": a["kind"],
            "status": a["status"],
            "unittype": a["unittype"],
            "district": a["district"],
            "footprint_m2": None if res.footprint_m2 is None else round(res.footprint_m2, 2),
            "depth_m": None if res.depth_m is None else round(res.depth_m, 2),
            "volume_m3": None if res.volume_m3 is None else round(res.volume_m3, 1),
            "total_m3": None if res.total_m3 is None else round(res.total_m3, 1),
            "volume_low_m3": None if low.volume_m3 is None else round(low.volume_m3, 1),
            "volume_high_m3": None if high.volume_m3 is None else round(high.volume_m3, 1),
            "tier": res.tier,
            "reason": res.reason,
            "source": "; ".join(dim.source) if res.tier == "assumed" else "库内字段",
        })
    return rows


def write_csv(rows: list[dict], path: str | None = None):
    import csv
    from pathlib import Path

    target = Path(path) if path else Path(__file__).resolve().parents[2] / OUTPUT_CSV
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(_CSV_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return target


def main() -> None:
    rows = build_rows()
    path = write_csv(rows)
    print(f"{len(rows)} 条设施 → {path}\n")

    by = {}
    for r in rows:
        by.setdefault((r["kind"], r["tier"]), []).append(r)
    print(f"{'设施':<10}{'出处层':<10}{'条数':>6}{'合计容量 m³':>16}{'深度中位 m':>12}")
    for (kind, tier), rs in sorted(by.items()):
        vols = [r["volume_m3"] for r in rs if r["volume_m3"] is not None]
        depths = sorted(r["depth_m"] for r in rs if r["depth_m"] is not None)
        med = depths[len(depths) // 2] if depths else float("nan")
        print(f"{kind:<10}{tier:<10}{len(rs):>6}{sum(vols):>16,.0f}{med:>12.2f}")

    total = sum(r["volume_m3"] or 0 for r in rows)
    lo = sum(r["volume_low_m3"] or 0 for r in rows)
    hi = sum(r["volume_high_m3"] or 0 for r in rows)
    print(f"\n全库合计（默认口径）{total:,.0f} m³，保守 {lo:,.0f} / 乐观 {hi:,.0f} m³")
    print("⚠ 这是全库总量，不是任何一个积水点可用的量 —— 逐点归属见 storage_batch.py")


if __name__ == "__main__":
    main()
