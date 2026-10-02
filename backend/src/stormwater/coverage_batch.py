"""把「哪一片有雨水管网数据」画成面，供指挥中心地图落图（DMT 清单 §01 的镜像）。

产出 `backend/data/processed/network_coverage.geojson`，由 API 离线读取 ——
和 `qcap_batch.py` / `storage_batch.py` 一样，页面不依赖数据库可达。

**为什么不用行政边界代替**：管网数据的边界不是阿布扎比市的行政边界。
`sw_edge` 的空间包络只覆盖市区建成区，市域内也有大片没有管段的空白
（岛间水域、沙漠、机场以南）。拿 ADM 行政面当「有数据区」会把这些空白
一并说成有数据，正是本项目一直在避免的那类含糊。所以覆盖面直接从管段几何生成。

**口径**：直接把管段按半径缓冲后并起来，不走网格。
半径 250 m 与 `qcap_batch.SEARCH_RADIUS_M` 同值 —— 一个积水点落在覆盖面内，
**等价于**它 250 m 内够得着管段，也就是够得着 Qcap 反算，两者判定完全一致。
（起初用 250 m 网格取有管段经过的格子，快得多，但「格子里有管」不等于
「离管 250 m 内」：451 个够得着管的点里有 22 个被判到面外。落图与批算口径
必须严丝合缝，故改回真缓冲。）

三层面各表一件事，不要混用：

* `extent` —— **数据区**：距任一雨水管 5 km 以内（`qcap_batch.COVERAGE_RADIUS_M` 同值）。
  **参与计算与否以这一层为准。** 落在外面 = 我们没有这一片的管网数据，
  Qcap 不是 0 而是算不出。845 个点里 339 个在外面（艾因 184 + 西部区 155），
  另有 5 个台账记为阿布扎比市的点也在外面 —— 这正是不能拿行政边界当数据边界的实例。
* `network` —— 距管段 250 m 以内，即**够得着 Qcap 反算**的范围。
* `computable` —— 其中管段还须有管径、管底高程可信、坡度落在 [0.0001, 0.2]、
  且属 LATERAL / SECONDARY 级。落在 `network` 内但 `computable` 外的点，
  是「有管但算不出」，跟「没数据」是两回事。

⚠ 覆盖面只回答**有没有数据**，不回答**这个点淹不淹**。落在 `extent` 内、`network` 外的
  50 个点，Qcap 为 0 是**实测结论**（周边确实没有雨水管），不是缺口。

⚠ **面是画给人看的，不是用来判定的。** 逐点算不算、算得出算不出，一律以
  `registry.HotspotRecord.qcap_basis` 为准（它来自 `qcap_batch.py` 的逐点距离计算）。
  面经过 25 m / 250 m 简化，边界上会有几米的出入 —— 实测 451 个「250 m 内有管」的点
  里有 3 个落在 `network` 面外、1 个「5 km 内有管」的点落在 `extent` 面外。
  拿面做点在面内判断，会和批算对不上号。
"""

from __future__ import annotations

import json
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
OUTPUT_GEOJSON = BACKEND_DIR / "data" / "processed" / "network_coverage.geojson"

_NETWORK_SCHEMA = "dmt_irrigationstormwater_abudhabi_network"

#: 管段缓冲半径（米）。与 `qcap_batch.SEARCH_RADIUS_M` 同值，改一处要改两处。
RADIUS_M = 250.0

#: 数据区半径（米）。与 `qcap_batch.COVERAGE_RADIUS_M` 同值 ——
#: 超过这个距离仍找不到管，判为「这一片没有管网数据」而非「此处没有管」。
EXTENT_RADIUS_M = 5000.0

#: 管段层的简化容差（米）。给得很小：面的边界就是判定边界，削一点就会
#: 把贴边的积水点显示到面外，看图会以为它们没管网数据。
SIMPLIFY_M = 25.0

#: 数据区是 3,000 km² 量级的大面，只用来分「有数据 / 没数据」，可以粗简。
EXTENT_SIMPLIFY_M = 250.0

#: 与 qcap_batch 完全一致的可反算条件 —— 两处口径必须同步改。
_COMPUTABLE_WHERE = """
      and e.invert_valid and e.pipe_diameter > 0 and e.len_m > 0
      and m.main_class in ('LATERAL', 'SECONDARY')
      and (e.invert_up - e.invert_dn) / e.len_m between 0.0001 and 0.2
"""

_COVERAGE_SQL = """
with picked as (
    select e.geom
      from {schema}.sw_edge e
      {join}
     where e.subassetname = 'SW Network'
       and e.status in ('Active', 'Existing')
       {extra}
), merged as (
    select {shape} as geom,
           (select count(*) from picked) as edges
      from (select st_union(st_buffer(geom, %(radius)s, 'quad_segs=2')) as geom
              from picked) u
)
select m.edges                                             as edges,
       round((st_area(m.geom) / 1e6)::numeric, 1)          as area_km2,
       st_asgeojson(
           st_transform(st_simplifypreservetopology(m.geom, %(tol)s), 4326), 6
       )                                                   as geojson
  from merged m
"""

_MAIN_JOIN = f"""
      join {_NETWORK_SCHEMA}.sw_main_edge me on me.edge_gid = e.gid
      join {_NETWORK_SCHEMA}.sw_main m       on m.main_id  = me.main_id
"""

#: 三层面的取数口径。顺序即绘制顺序（大的在下）。
LAYERS: dict[str, dict] = {
    "extent": {
        "label": "有管网数据的区域",
        "join": "",
        "extra": "",
        "shape": "u.geom",
        "radius": EXTENT_RADIUS_M,
        "tol": EXTENT_SIMPLIFY_M,
        "note": (
            f"距任一雨水管 {EXTENT_RADIUS_M:.0f} m 以内。"
            "落在这一层之外的点没有管网数据，Qcap 算不出（不是 0）"
        ),
        "decides_inclusion": True,
    },
    "network": {
        "label": "管段 250 m 可及",
        "join": "",
        "extra": "",
        "shape": "u.geom",
        "radius": RADIUS_M,
        "tol": SIMPLIFY_M,
        "note": "sw_edge 中 subassetname='SW Network' 且状态为 Active/Existing 的管段 250 m 范围",
        "decides_inclusion": False,
    },
    "computable": {
        "label": "可反算管网能力 Qcap",
        "join": _MAIN_JOIN,
        "extra": _COMPUTABLE_WHERE,
        "shape": "u.geom",
        "radius": RADIUS_M,
        "tol": SIMPLIFY_M,
        "note": "上述管段中还须有管径、管底高程可信、坡度可信，且为 LATERAL/SECONDARY 级",
        "decides_inclusion": False,
    },
}


def _layer_sql(spec: dict) -> str:
    return _COVERAGE_SQL.format(
        schema=_NETWORK_SCHEMA,
        join=spec["join"],
        extra=spec["extra"],
        shape=spec["shape"],
    )


def build() -> dict:
    """连库生成覆盖面 FeatureCollection（EPSG:4326，供 Leaflet 直接落图）。"""
    from .db import query  # 延迟导入：没有数据库也能 import 本模块

    features = []
    for key, spec in LAYERS.items():
        rows = query(_layer_sql(spec), {"radius": spec["radius"], "tol": spec["tol"]})
        if not rows:
            raise RuntimeError(f"覆盖面 {key} 查不到任何管段，检查 schema 与筛选条件")
        row = rows[0]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "key": key,
                    "label": spec["label"],
                    "note": spec["note"],
                    "edges": row["edges"],
                    "area_km2": float(row["area_km2"]),
                    "radius_m": spec["radius"],
                    "decides_inclusion": spec["decides_inclusion"],
                },
                "geometry": json.loads(row["geojson"]),
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "source": f"{_NETWORK_SCHEMA}.sw_edge",
            "crs": "EPSG:4326（由 32640 转出）",
            "radius_m": RADIUS_M,
            "extent_radius_m": EXTENT_RADIUS_M,
            "caveat": (
                "覆盖面只表示有无管网数据，不表示该处不淹。面外的积水点"
                "（艾因 AAM / 西部区 DRM）缺的是数据本身，其 Qcap 无法反算。"
            ),
        },
    }


def write_geojson(fc: dict, path: Path = OUTPUT_GEOJSON) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> None:
    fc = build()
    path = write_geojson(fc)
    for f in fc["features"]:
        p = f["properties"]
        print(f"{p['key']:<12} {p['edges']:>7} 段 · {p['area_km2']:>8.1f} km² · {p['label']}")
    print(f"→ {path}（{path.stat().st_size / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
