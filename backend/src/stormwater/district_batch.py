"""按**官方行政边界**给 845 个积水点打片区标签（供「只看某个区」这类筛选用）。

产出两份文件，都由 API 离线读取，页面不依赖数据库可达 ——
和 `qcap_batch.py` / `storage_batch.py` / `coverage_batch.py` 是同一个套路：

* `backend/data/processed/hotspot_district.csv` —— 逐点的片区归属，`registry.py` 合并进 `HotspotRecord`；
* `backend/data/processed/district_boundaries.geojson` —— 含积水点的片区轮廓，落图用。

**为什么不用台账的 `area` 列**：那一列是各市政区自己填的自由文本，同一个名字
在不同市政区下指的不是同一片地方。最典型的就是「Al Bateen」—— 台账里只有 3 行
写着这个名字，全在**艾因**（Ghafat Al Shwaihi 一带），而大家日常说的阿布扎比
**岛上的**巴廷区，在台账里被并进了 `area='Island'` 的 149 个点里，一个字都没提。
按 `area` 筛「Al Bateen」会把岛上真正的巴廷区 18 个点全漏掉，
还会拿 3 个无管网数据、结论全是假设值的艾因点冒充结论。

所以片区一律**按几何判**：`udm_community` 的社区面 → `districtnameeng` 聚合成片区，
积水点落在哪个面里就是哪个区。845 个点全部命中，且每个点恰好命中一个面
（社区面之间不重叠），不存在归属歧义。

⚠ 片区只回答**这个点在哪个行政区里**，不回答**这个点有没有管网数据**。
  两者是正交的：AAM / WRM 的片区照样打得出标签，但那些点的 Qcap 仍然算不出
  （`in_coverage` 为假）。筛完片区还要看 `coverage_only`，别把「筛出来了」
  当成「算得准」。
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
OUTPUT_CSV = BACKEND_DIR / "data" / "processed" / "hotspot_district.csv"
OUTPUT_GEOJSON = BACKEND_DIR / "data" / "processed" / "district_boundaries.geojson"

#: 官方社区面所在的 schema。`udm_district` 也有面，但它的 `nameenglish`
#: 粒度比社区表的 `districtnameeng` 粗，岛上多个片区会并成一个，故取社区表聚合。
_GEO_SCHEMA = "geoserver_ref"

#: 轮廓简化容差（米）。片区面只用来落图（看清楚筛的是哪一片），
#: 判定一律以逐点的 `district` 标签为准 —— 和覆盖面一样，面是给人看的。
SIMPLIFY_M = 25.0

#: 默认的点表。见 `qcap_batch.DEFAULT_POINTS_TABLE`。
DEFAULT_POINTS_TABLE = "hotspot.hotspots_845"


def _stamp_sql(points: str) -> str:
    """逐点归属。社区面互不重叠，845 个点各命中一个；`distinct on` 只是防御性写法，
    万一将来数据更新出现重叠面，取面积最小的那个（最细粒度的那一层）。"""
    return f"""
select distinct on (h.uid)
       h.uid,
       c.districtnameeng   as district,
       c.districtara       as district_ar,
       c.communitynameeng  as community,
       c.municipality      as district_municipality
from {points} h
join {_GEO_SCHEMA}.udm_community c on st_contains(c.geom, h.geom)
order by h.uid, st_area(c.geom)
"""

#: 含积水点的片区轮廓。只导有点的片区 —— 全库 216 个片区导出来 185 KB，
#: 其中一大半跟积水点无关，页面载了也用不上。
BOUNDARY_SQL = f"""
with hit as (
    select distinct on (h.uid) h.uid, c.districtnameeng, c.municipality
      from hotspot.hotspots_845 h
      join {_GEO_SCHEMA}.udm_community c on st_contains(c.geom, h.geom)
     order by h.uid, st_area(c.geom)
),
tally as (
    select districtnameeng, municipality, count(*) as hotspots
      from hit group by 1, 2
)
select t.districtnameeng as district,
       max(c.districtara) as district_ar,
       t.municipality,
       t.hotspots,
       st_area(st_union(c.geom)) / 1e6 as area_km2,
       st_asgeojson(
           st_transform(
               st_simplifypreservetopology(st_union(c.geom), %(simplify)s), 4326
           ), 6
       ) as geojson
  from tally t
  join {_GEO_SCHEMA}.udm_community c
    on c.districtnameeng = t.districtnameeng
   and c.municipality = t.municipality
 group by t.districtnameeng, t.municipality, t.hotspots
 order by t.hotspots desc, t.districtnameeng
"""


@dataclass(frozen=True)
class HotspotDistrict:
    """一个积水点的官方片区归属。全部来自几何判定，没有台账文本参与。"""

    uid: str
    #: `udm_community.districtnameeng`，全大写，如 `AL BATEEN`
    district: str | None
    district_ar: str | None
    #: 命中的社区面名（比片区细一级，如 `W33`），留着便于回溯是哪块面判的
    community: str | None
    #: 面自带的市政区代码（ADM / AAM / WRM）。⚠ 与台账 `municipality` 各说各话，
    #: 不一致时以面为准 —— 台账那一列是人填的
    district_municipality: str | None
    #: measured = 几何判定命中；outside = 全库社区面都没盖住这个点
    basis: str


def stamp(points_table: str = DEFAULT_POINTS_TABLE) -> list[HotspotDistrict]:
    """逐点判片区。要连数据库。"""
    from .db import query

    hit = {row["uid"]: row for row in query(_stamp_sql(points_table))}
    uids = [row["uid"] for row in query(f"select uid from {points_table} order by uid")]
    out: list[HotspotDistrict] = []
    for uid in uids:
        row = hit.get(uid)
        if row is None:
            out.append(HotspotDistrict(uid, None, None, None, None, "outside"))
            continue
        out.append(
            HotspotDistrict(
                uid=uid,
                district=row["district"],
                district_ar=row["district_ar"],
                community=row["community"],
                district_municipality=row["district_municipality"],
                basis="measured",
            )
        )
    return out


def build_boundaries() -> dict:
    """含积水点的片区轮廓，FeatureCollection。要连数据库。"""
    features = []
    for row in query_boundaries():
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "district": row["district"],
                    "district_ar": row["district_ar"],
                    "municipality": row["municipality"],
                    "hotspots": row["hotspots"],
                    "area_km2": round(float(row["area_km2"]), 2),
                },
                "geometry": json.loads(row["geojson"]),
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "source": f"{_GEO_SCHEMA}.udm_community（按 districtnameeng 聚合）",
            "crs": "EPSG:4326（由 32640 转出）",
            "simplify_m": SIMPLIFY_M,
            "caveat": (
                "轮廓只用于落图。逐点属于哪个片区以 hotspot_district.csv 的标签为准 —— "
                "面简化过 25 m，贴边的点会显示到面外。"
            ),
        },
    }


def query_boundaries() -> list[dict]:
    from .db import query

    return query(BOUNDARY_SQL, {"simplify": SIMPLIFY_M})


def write_csv(rows: list[HotspotDistrict], path: Path = OUTPUT_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [f.name for f in fields(HotspotDistrict)]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))
    return path


def write_geojson(fc: dict, path: Path = OUTPUT_GEOJSON) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> None:
    rows = stamp()
    csv_path = write_csv(rows)
    tally: dict[str, int] = {}
    for r in rows:
        key = r.district or "（不在任何片区面内）"
        tally[key] = tally.get(key, 0) + 1
    stamped = sum(1 for r in rows if r.basis == "measured")
    print(f"逐点片区：{stamped}/{len(rows)} 个点命中，共 {len(tally)} 个片区")
    for name, n in sorted(tally.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {name:<28} {n:>3} 个点")
    print(f"→ {csv_path}")

    fc = build_boundaries()
    geo_path = write_geojson(fc)
    print(f"→ {geo_path}（{len(fc['features'])} 个片区轮廓，{geo_path.stat().st_size / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
