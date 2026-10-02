"""把雨水管网本身画到指挥中心地图上（`coverage_batch.py` 的里子）。

覆盖面回答「哪一片有管网数据」，这里回答「管网长什么样」——
同一批 `sw_edge`，一个出面，一个出线。

产出两个文件，由 API 离线读取，页面不依赖数据库可达：

* `network_mains.geojson` —— TRUNK_MAIN / PRIMARY / SECONDARY 三级干管，约 1.5 MB，
  按下按钮就加载。
* `network_laterals.geojson` —— LATERAL 支管，约 3 MB，**放大到街区尺度才加载**。
  支管占全网 3,290 km（38%）却细如发丝，在市域尺度上只会糊成一片蓝，
  既看不出东西又白下 3 MB。

**口径与 `qcap_batch.py` 一致**：`subassetname='SW Network'` +
`status in ('Active','Existing')`。落图与批算看的是同一批管，
图上有线的地方就是 Qcap 反算够得着的地方。
（注意反过来不成立：`qcap_batch` 只取 LATERAL/SECONDARY 两级反算本地管网能力，
干管的 TRUNK/PRIMARY 两级画在图上但不参与逐点 Qcap。）

**为什么从 `sw_main` 出而不是直接 `sw_edge`**：`sw_edge` 是 26 万条独立管段，
逐段落图 21 MB，且相邻段的公共端点要存两遍。`sw_main` 已经把它们串成 6.6 万条
干管，`st_linemerge` 后公共端点只存一次，同样的线省掉 40% 体积。
代价是 `sw_main` 聚合时没有按 `subassetname` 分——66,783 条干管里有 2,072 条
**完全不含**雨水管段（全是 SurfcDrain / CivilStrct），这里按 `pure` 子查询剔掉；
另有 339 条以雨水管为主、掺了个别非雨水段的，整条保留（掺入量在 1% 以下，
为它们把 `sw_main` 拆开重组不值当）。

**每一级只出一个 Feature**（几何是 MultiLineString），不是逐条干管一个 Feature。
Leaflet 画 6.6 万个 Polyline 对象要卡好几秒，画 4 个各含几万段的对象则是一次
canvas path。代价是图上的线点不动、没有逐条 tooltip —— 管网在这里是**底图性质的
参照**，用来看积水点周边有没有管、管往哪去，逐条属性该去 Qcap 面板看。

⚠ 几何按 1 m 容差简化过（`SIMPLIFY_DEG`），只为落图省体积。**不要拿这份 GeoJSON
  量长度、算坡度或做空间判断** —— 那些一律回 `sw_edge`。
"""

from __future__ import annotations

import json
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
OUTPUT_MAINS = BACKEND_DIR / "data" / "processed" / "network_mains.geojson"
OUTPUT_LATERALS = BACKEND_DIR / "data" / "processed" / "network_laterals.geojson"

_NETWORK_SCHEMA = "dmt_irrigationstormwater_abudhabi_network"

#: 落图简化容差（**度**，几何已转 4326 后再简化）。1e-5° ≈ 1.1 m —— 管网线宽
#: 在屏幕上最粗也就 2 px（zoom 16 下约 2 m），1 m 的位移看不出来，体积省三成。
SIMPLIFY_DEG = 0.00001

#: 坐标小数位。5 位 ≈ 1.1 m，与 `SIMPLIFY_DEG` 同量级，再多就是存噪声。
COORD_DECIMALS = 5

#: 四级干管的画法参数。`min_zoom` 是前端起画的缩放级，写在这里而不是前端，
#: 是为了让「这一级什么时候该出现」跟着数据口径一起版本化。
CLASSES: dict[str, dict] = {
    "TRUNK_MAIN": {"label": "主干管", "min_zoom": 9, "file": "mains"},
    "PRIMARY": {"label": "一级管", "min_zoom": 11, "file": "mains"},
    "SECONDARY": {"label": "二级管", "min_zoom": 12, "file": "mains"},
    "LATERAL": {"label": "支管", "min_zoom": 14, "file": "laterals"},
}

#: 含至少一条雨水管段的干管。完全不含的（2,072 条纯 SurfcDrain / CivilStrct）剔掉。
_PURE_SQL = f"""
select me.main_id
  from {_NETWORK_SCHEMA}.sw_main_edge me
  join {_NETWORK_SCHEMA}.sw_edge e on e.gid = me.edge_gid
 group by 1
having count(*) filter (
         where e.subassetname = 'SW Network' and e.status in ('Active', 'Existing')
       ) > 0
"""

#: 一级干管 → 一个 MultiLineString。`st_linemerge` 先把每条干管内部的管段串起来
#: （省掉重复端点），`st_dump` 拆成 LineString 再 `st_collect`，避免 `st_collect`
#: 直接吃 MultiLineString 时吐出 GeometryCollection（GeoJSON 里没法当线画）。
_LAYER_SQL = f"""
with pure as ({_PURE_SQL}
), picked as (
    select m.main_id, m.length_m, m.diameter_rep,
           st_linemerge(st_force2d(m.geom)) as geom
      from {_NETWORK_SCHEMA}.sw_main m
      join pure p on p.main_id = m.main_id
     where m.main_class = %(cls)s
), dumped as (
    select (st_dump(geom)).geom as geom from picked
)
select (select count(*)                           from picked) as mains,
       (select round(sum(length_m)::numeric / 1000, 1) from picked) as length_km,
       (select round(min(diameter_rep))           from picked where diameter_rep > 0) as dia_min_mm,
       (select round(max(diameter_rep))           from picked where diameter_rep > 0) as dia_max_mm,
       (select round(avg(diameter_rep))           from picked where diameter_rep > 0) as dia_avg_mm,
       st_asgeojson(
           st_simplify(st_transform(st_collect(geom), 4326), %(tol)s), %(dec)s
       ) as geojson
  from dumped
"""


def _layer(cls: str, spec: dict, query) -> dict:
    rows = query(_LAYER_SQL, {"cls": cls, "tol": SIMPLIFY_DEG, "dec": COORD_DECIMALS})
    if not rows or not rows[0]["geojson"]:
        raise RuntimeError(f"管网分级 {cls} 查不到任何干管，检查 schema 与筛选条件")
    row = rows[0]
    return {
        "type": "Feature",
        "properties": {
            "key": cls,
            "label": spec["label"],
            "min_zoom": spec["min_zoom"],
            "mains": int(row["mains"]),
            "length_km": float(row["length_km"]),
            "diameter_min_mm": float(row["dia_min_mm"]),
            "diameter_max_mm": float(row["dia_max_mm"]),
            "diameter_avg_mm": float(row["dia_avg_mm"]),
        },
        "geometry": json.loads(row["geojson"]),
    }


def _wrap(features: list[dict], note: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "source": f"{_NETWORK_SCHEMA}.sw_main（口径同 sw_edge：SW Network / Active·Existing）",
            "crs": "EPSG:4326（由 32640 转出）",
            "simplify_m": round(SIMPLIFY_DEG * 111_320),
            "note": note,
            # 支管的起画级别随干管一起下发：前端拿到干管时才知道
            # 放大到哪一级该去取那 3.2 MB，不必在前端另写一个魔数。
            "lateral_min_zoom": CLASSES["LATERAL"]["min_zoom"],
            "caveat": (
                "落图用，几何简化过 1 m。量长度、算坡度、做空间判断一律回 sw_edge，"
                "不要用这份数据。"
            ),
        },
    }


def build() -> dict[str, dict]:
    """连库生成两份 FeatureCollection（EPSG:4326，供 Leaflet 直接落图）。"""
    from .db import query  # 延迟导入：没有数据库也能 import 本模块

    buckets: dict[str, list[dict]] = {"mains": [], "laterals": []}
    for cls, spec in CLASSES.items():
        buckets[spec["file"]].append(_layer(cls, spec, query))

    return {
        "mains": _wrap(
            buckets["mains"],
            "三级干管，按下管网按钮即加载；每一级到各自的 min_zoom 才起画。",
        ),
        "laterals": _wrap(
            buckets["laterals"],
            "支管，放大到 min_zoom 才由前端按需加载 —— 市域尺度上画它只会糊成一片。",
        ),
    }


def write_geojson(fcs: dict[str, dict]) -> dict[str, Path]:
    paths = {"mains": OUTPUT_MAINS, "laterals": OUTPUT_LATERALS}
    for key, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fcs[key], ensure_ascii=False), encoding="utf-8")
    return paths


def main() -> None:
    fcs = build()
    paths = write_geojson(fcs)
    for key, fc in fcs.items():
        for f in fc["features"]:
            p = f["properties"]
            print(
                f"{p['key']:<11} {p['mains']:>6} 条 · {p['length_km']:>7.1f} km · "
                f"φ{p['diameter_min_mm']:.0f}–{p['diameter_max_mm']:.0f} mm · "
                f"zoom≥{p['min_zoom']} · {p['label']}"
            )
        print(f"→ {paths[key]}（{paths[key].stat().st_size / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
