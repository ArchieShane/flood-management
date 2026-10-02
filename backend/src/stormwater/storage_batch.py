"""从管网库批量反算逐点**已有可用调蓄容量**（第二道防线）。

产出 `backend/data/processed/hotspot_storage.csv`，由 `registry.py` 离线读取，
与 `qcap_batch.py` 同一套路。容量的深度/尺寸来源分三层，判定逻辑在
`storage_dims.resolve_asset()`：**实测 > 反推 > 目录缺省**。

**2026-09-19 改了两处，把原先的「全库 0」推翻了**：

1. 原批算漏读 `pond.volume` —— 23 个调蓄池里 **20 个填了台账容量**，与几何面积
   相除得到的隐含深度 1.00–4.42 m（中位 2.18 m），落在 ADQCC §4.14.1(b) 推荐的
   1.8–2.4 m 带内。这是**库里本来就有的实测数据**，不是假设。原来只看
   `cover_level − bottom_floor_level`，19 条盖底同高就判了深度为 0。
2. 深度/尺寸实在没有的（渗井 949 条、地下蓄水构筑物 17 条），改用
   `storage_dims.py` 的**缺省值目录**补，逐条带出处（ADQCC WA-726-1/-2、
   Ashghal PWA IAN 048/14、BS 5911-3 等）。这类容量单独统计在 `assumed_m3`，
   **不混进 `available_m3`** —— 想只用实测的口径随时能切回去。

⚠ 三条口径限制，引用数字前必须一起说：

* **归属按距离判定**（250 m，与 `qcap_batch.py` 一致），没有管网连通性证据。
  一个 66 万 m³ 的调蓄池若按「1 km 内」判给某个点，会一次性抹平该点的全部缺口，
  而我们并不知道水能否进去。放宽半径必须先有连通性判据。
* **渗井多半已在为自己的汇水面服务**，把它算成「额外可用调蓄」有重复计算风险，
  而且单座只有 5.3 m³，对车队结论基本不起作用。
* **`status='Expired'` 一律排除**：`sw_reservoirstructure` 的 3 条过期记录是
  `pond` 5/6/10 的副本（几何完全重合），其中 2 条落在积水点 250 m 内。
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .storage_dims import (  # noqa: F401 —— 常量在这里再导出，旧引用不破
    DEPTH_MAX_M,
    DEPTH_MIN_M,
    POND_AREA_MAX_M2,
    POND_AREA_MIN_M2,
    SOAKAWAY_AREA_MAX_M2,
    SOAKAWAY_AREA_MIN_M2,
    STATUS_FILTER,
    Level,
    resolve_asset,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]
OUTPUT_CSV = BACKEND_DIR / "data" / "processed" / "hotspot_storage.csv"

#: 认定「这个设施可能服务这个点」的半径（米）。与 qcap_batch 保持一致。
SEARCH_RADIUS_M = 250.0

#: 超过这个距离仍找不到任何调蓄设施，判为**该区域没有设施数据**（而非该点周边没有设施）。
#: 三张设施表与管网一样只覆盖 ADM：艾因最近的渗井在 28 km 外，扎夫拉在 78 km 外。
COVERAGE_RADIUS_M = 5000.0

_SCHEMA = "dmt_irrigationstormwater_abudhabi"

#: 三类调蓄设施统一成 (uid, kind, 距离, 面积, 深度, 台账容量, 原始尺寸) 再在 Python 里判。
#: 默认的点表。见 `qcap_batch.DEFAULT_POINTS_TABLE` —— 同一段 SQL 也用来跑
#: `model_cluster_batch.py` 灌进来的模型片区代表点。
DEFAULT_POINTS_TABLE = "hotspot.hotspots_845"


def _assets_sql(points: str) -> str:
    """列名与 `storage_dims.ALL_ASSETS_SQL` 对齐，两边共用 `resolve_asset()`。"""
    return f"""
select h.uid, 'pond' as kind,
       st_distance(h.geom, a.geom)              as distance_m,
       a.shape_area                             as footprint_m2,
       a.cover_level - a.bottom_floor_level     as depth_m,
       a.volume                                 as volume_m3,
       null::float8 as dim_diameter, null::float8 as dim_length, null::float8 as dim_width
from {points} h
join {_SCHEMA}.pond a on st_dwithin(h.geom, a.geom, %(radius)s)
where {STATUS_FILTER}

union all
select h.uid, 'reservoir',
       st_distance(h.geom, a.geom),
       a.shape_area,
       a.max_water_level - a.bed_level,
       null::float8,
       null, null, null
from {points} h
join {_SCHEMA}.sw_reservoirstructure a on st_dwithin(h.geom, a.geom, %(radius)s)
where {STATUS_FILTER}

union all
select h.uid, 'soakaway',
       st_distance(h.geom, a.geom),
       null::float8,
       a.cover_level - a.bottom_level,
       null::float8,
       a.soakaway_diameter::float8, a.soakaway_length, a.soakaway_width
from {points} h
join {_SCHEMA}.soakaway a on st_dwithin(h.geom, a.geom, %(radius)s)
where {STATUS_FILTER}
"""


def _nearest_sql(points: str) -> str:
    """每个点到最近调蓄设施的距离，**不设半径上限** —— 用来区分
    「这个点周边没有设施」和「这一片我们根本没有设施数据」。"""
    return f"""
select h.uid, least(
    (select min(st_distance(h.geom, a.geom)) from {_SCHEMA}.pond a),
    (select min(st_distance(h.geom, a.geom)) from {_SCHEMA}.soakaway a),
    (select min(st_distance(h.geom, a.geom)) from {_SCHEMA}.sw_reservoirstructure a)
  ) as nearest_any_m
from {points} h
"""


@dataclass(frozen=True)
class HotspotStorage:
    """一个积水点周边可用调蓄容量与它的出处。"""

    uid: str
    #: 到最近调蓄设施的距离（米），不设上限；None 表示全库都没有
    nearest_any_m: float | None
    #: 半径内找到的设施数（不论可不可用）
    assets_in_radius: int
    #: 其中深度/尺寸实测或可反推的条数
    assets_usable: int
    #: 其中靠 `storage_dims` 缺省值目录补的条数
    assets_assumed: int
    pond_m3: float
    soakaway_m3: float
    reservoir_m3: float
    #: **实测口径结果**（measured + derived），给 registry 用
    available_m3: float | None
    #: 目录缺省值补出来的那部分容量
    assumed_m3: float
    #: 实测 + 假设的合计 —— registry 在没有实测时退到这一列
    available_with_assumed_m3: float | None
    #: 渗井含砾石包裹层的乐观上界（其余设施与 available 相同）
    optimistic_m3: float
    #: 被剔除的条数（连缺省值都补不了：几何面积缺失或不合理）
    rejected: int
    #: measured / assumed_dimensions / measured_none / no_asset / no_coverage
    basis: str


def summarise(uid: str, assets: list[dict], nearest_any_m: float | None,
              level: Level = "typical") -> HotspotStorage:
    """把一个点周边的设施归并成一条结论。"""
    vol = {"pond": 0.0, "soakaway": 0.0, "reservoir": 0.0}
    measured = assumed = rejected = 0
    measured_m3 = assumed_m3 = optimistic_m3 = 0.0

    for a in assets:
        res = resolve_asset(a, level)
        if not res.usable:
            rejected += 1
            continue
        vol[a["kind"]] += res.volume_m3
        optimistic_m3 += res.total_m3 or res.volume_m3
        if res.tier == "assumed":
            assumed += 1
            assumed_m3 += res.volume_m3
        else:
            measured += 1
            measured_m3 += res.volume_m3

    if not assets:
        # 半径内没设施。是「真没有」还是「这一片没数据」，看最近设施有多远。
        basis = (
            "no_coverage"
            if nearest_any_m is None or nearest_any_m > COVERAGE_RADIUS_M
            else "no_asset"
        )
    elif measured:
        basis = "measured"
    elif assumed:
        # 周边有设施，深度/尺寸一条都没实测，容量整个来自缺省值目录
        basis = "assumed_dimensions"
    else:
        basis = "measured_none"

    total = measured_m3 + assumed_m3
    return HotspotStorage(
        uid=uid,
        nearest_any_m=round(nearest_any_m, 1) if nearest_any_m is not None else None,
        assets_in_radius=len(assets),
        assets_usable=measured,
        assets_assumed=assumed,
        pond_m3=round(vol["pond"], 1),
        soakaway_m3=round(vol["soakaway"], 1),
        reservoir_m3=round(vol["reservoir"], 1),
        available_m3=round(measured_m3, 1) if measured else None,
        assumed_m3=round(assumed_m3, 1),
        available_with_assumed_m3=round(total, 1) if (measured or assumed) else None,
        optimistic_m3=round(optimistic_m3, 1),
        rejected=rejected,
        basis=basis,
    )


def compute_all(radius_m: float = SEARCH_RADIUS_M,
                level: Level = "typical",
                points_table: str = DEFAULT_POINTS_TABLE) -> list[HotspotStorage]:
    """连库取数 + 逐点归并。需要 `points_table` 已落库（uid + EPSG:32640 的 geom）。"""
    from .db import query  # 延迟导入：没有数据库也能 import 本模块

    by_uid: dict[str, list[dict]] = {}
    for row in query(_assets_sql(points_table), {"radius": radius_m}):
        by_uid.setdefault(row["uid"], []).append(row)

    nearest = {r["uid"]: r["nearest_any_m"] for r in query(_nearest_sql(points_table))}
    return [
        summarise(uid, by_uid.get(uid, []), dist, level)
        for uid, dist in sorted(nearest.items())
    ]


def write_csv(results: list[HotspotStorage], path: Path = OUTPUT_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [f.name for f in fields(HotspotStorage)]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))
    return path


def main() -> None:
    results = compute_all()
    path = write_csv(results)
    tally: dict[str, int] = {}
    for r in results:
        tally[r.basis] = tally.get(r.basis, 0) + 1

    print(f"{len(results)} 个积水点 → {path}")
    for basis, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"   {basis:<20} {n:>4}")

    found = sum(r.assets_in_radius for r in results)
    usable = sum(r.assets_usable for r in results)
    assumed = sum(r.assets_assumed for r in results)
    meas_m3 = sum(r.available_m3 or 0.0 for r in results)
    asm_m3 = sum(r.assumed_m3 for r in results)
    print(f"\n{SEARCH_RADIUS_M:.0f} m 内共 {found} 条设施："
          f"实测/反推 {usable} 条、目录缺省 {assumed} 条、剔除 "
          f"{sum(r.rejected for r in results)} 条")
    print(f"逐点可用调蓄：实测口径 {meas_m3:,.0f} m³，"
          f"加上目录缺省值 {meas_m3 + asm_m3:,.0f} m³（其中假设 {asm_m3:,.0f} m³）")
    with_any = [r for r in results if (r.available_with_assumed_m3 or 0) > 0]
    print(f"有可用调蓄的点：{len(with_any)} 个"
          f"（其中实测 {sum(1 for r in results if r.available_m3)} 个）")


if __name__ == "__main__":
    main()
