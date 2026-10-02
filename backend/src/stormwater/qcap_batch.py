"""从管网拓扑批量反算逐点 Qcap（交接文档阻塞项 1）。

产出 `backend/data/processed/hotspot_qcap.csv`，由 `registry.py` 离线读取 ——
API 因此不依赖数据库可达，跟 `hotspots.py` 生成台账表是同一个套路。

**口径**：一个积水点的 Qcap 取 **250 m 内 LATERAL / SECONDARY 级管道的最大满流能力**。

为什么不是别的取法（三个都试过，数字见 §决策依据）：

* *最近一根管* —— 中位数只有 0.067 m³/s，那是支管管径，会把几乎所有点判成必淹；
* *缓冲区内全部管的最大值* —— 中位 1.08、最大 68 m³/s，被恰好路过的干管（TRUNK_MAIN）
  拉高。一条 3 m 的输水干管从路口边上过，并不代表这个路口的水能进去；
* *只保留与最近管同排放口的管* —— 中位降幅 0.0%，250 m 内本来就大多同排放口，没用。

取 LATERAL / SECONDARY 的理由是水文上的：积水点的地面径流进的是**收集系统**
（支管与次干管），不是过路的输水干管。排除 PRIMARY / TRUNK_MAIN 后
最大值从 68 降到 14.7 m³/s，中位 0.491 m³/s。

⚠ 这仍然是**筛查用的代理量**，不是下游瓶颈分析。真正的瓶颈要沿流向追到排放口取
  min(Qcap)，而 `sw_edge` 有 15,984 条边方向为 `unknown`、1,561 条 `dir_conflict`，
  在这样的图上追出来的数会看着权威但底下站不住。要做严格的，先修流向。

⚠ 曼宁糙率走 `manning.py` 的映射，而它**尚未按 ADQCC Table 4-1 更新**（README 已知项 2），
  现值偏低 → Qcap 偏大 → 偏不保守。改 `manning.py` 后重跑本脚本即可。
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .manning import (
    DiameterUnit,
    GradientConvention,
    circular_pipe_qcap,
    is_material_unusable,
    manning_n,
    normalize_diameter,
    normalize_gradient,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]
OUTPUT_CSV = BACKEND_DIR / "data" / "processed" / "hotspot_qcap.csv"

#: 认定「这根管可能收这个点的水」的半径（米）。
#: 与默认剖面假设的 12 ha 汇水区同量级（等面积圆半径约 195 m）。
SEARCH_RADIUS_M = 250.0

#: 超过这个距离仍找不到雨水管，判为**该区域没有管网数据**（而非该点没有管网）。
#: 艾因与西部区的管网至今未导出，846 点里有 339 个属于这种情况。
COVERAGE_RADIUS_M = 5000.0

#: 参与取值的干管等级（`sw_main.main_class`）。
LOCAL_MAIN_CLASSES = ("LATERAL", "SECONDARY")

#: 反算坡度的可信区间。`sw_edge.invert_valid` 已筛掉缺高程的，
#: 这里再挡住 ≤0（平坡/倒坡）与离群值（最大到 7.56）。
SLOPE_MIN, SLOPE_MAX = 0.0001, 0.2

_NETWORK_SCHEMA = "dmt_irrigationstormwater_abudhabi_network"

#: 默认的点表。反算本身与点是哪来的无关 —— 只要有 `uid` 与 EPSG:32640 的 `geom`，
#: 台账的 845 个上报点与 `model_cluster_batch.py` 灌进来的 107 个模型片区代表点
#: 走的是同一段 SQL、同一套判据。故这里只是个默认值，`compute_all()` 可换。
DEFAULT_POINTS_TABLE = "hotspot.hotspots_845"


def _segments_sql(points: str) -> str:
    """取积水点周边管段。几何全库已统一 EPSG:32640，此处不再 transform。"""
    return f"""
select h.uid,
       e.gid,
       e.pipe_diameter        as diameter_mm,
       e.invert_up,
       e.invert_dn,
       e.len_m,
       e.pipe_material        as material,
       e.invert_valid,
       m.main_class,
       st_distance(h.geom, e.geom) as distance_m
from {points} h
join {_NETWORK_SCHEMA}.sw_edge e
  on st_dwithin(h.geom, e.geom, %(radius)s)
 and e.subassetname = 'SW Network'
 and e.status in ('Active', 'Existing')
left join {_NETWORK_SCHEMA}.sw_main_edge me on me.edge_gid = e.gid
left join {_NETWORK_SCHEMA}.sw_main m       on m.main_id  = me.main_id
"""


def _nearest_sql(points: str) -> str:
    """每个点到最近雨水管的距离，**不设半径上限** —— 用来区分
    「这个点附近确实没管」和「这一片我们根本没有管网数据」。"""
    return f"""
select h.uid,
       (select st_distance(h.geom, e.geom)
          from {_NETWORK_SCHEMA}.sw_edge e
         where e.subassetname = 'SW Network'
           and e.status in ('Active', 'Existing')
         order by h.geom <-> e.geom
         limit 1) as nearest_any_m
from {points} h
"""


@dataclass(frozen=True)
class HotspotQcap:
    """一个积水点反算出来的管网能力与它的出处。"""

    uid: str
    #: 最近雨水管距离（米），不设上限；None 表示全库都没有
    nearest_any_m: float | None
    #: 搜索半径内的管段数
    pipes_in_radius: int
    #: 其中算得出 Qcap 的条数（有管径 + 高程可信 + 坡度在区间内）
    pipes_computable: int
    #: **本列是给 registry 用的结果**：LATERAL/SECONDARY 最大满流能力（m³/s）
    qcap_m3s: float | None
    #: 对照口径，供敏感性分析，不参与计算
    qcap_nearest_m3s: float | None
    qcap_any_class_m3s: float | None
    #: 取到 qcap_m3s 的那根管
    qcap_source_gid: int | None
    qcap_source_class: str | None
    qcap_source_diameter_mm: float | None
    qcap_source_distance_m: float | None
    #: 半径内材质为 Undefined/Other/空的管段占比 —— 这些管的糙率是兜底值不是实测
    material_unknown_share: float | None
    #: measured / measured_no_network / no_coverage / uncomputable
    basis: str


def _segment_qcap(row: dict) -> float | None:
    """单根管的满流 Qcap。算不出返回 None（缺管径、缺高程、坡度离谱）。"""
    diameter_mm = row.get("diameter_mm")
    if not diameter_mm or diameter_mm <= 0:
        return None
    if not row.get("invert_valid") or not row.get("len_m"):
        return None
    slope = (row["invert_up"] - row["invert_dn"]) / row["len_m"]
    if not SLOPE_MIN <= slope <= SLOPE_MAX:
        return None
    return circular_pipe_qcap(
        normalize_diameter(diameter_mm, DiameterUnit.MM),
        normalize_gradient(slope, GradientConvention.DECIMAL),
        manning_n(row.get("material")),
    )


def summarise(uid: str, segments: list[dict], nearest_any_m: float | None) -> HotspotQcap:
    """把一个点周边的管段归并成一条结论。"""
    scored = [(s, _segment_qcap(s)) for s in segments]
    computable = [(s, q) for s, q in scored if q is not None]

    def _pick(rows: list[tuple[dict, float]]) -> tuple[dict, float] | None:
        return max(rows, key=lambda sq: sq[1]) if rows else None

    local = _pick([sq for sq in computable if sq[0].get("main_class") in LOCAL_MAIN_CLASSES])
    any_class = _pick(computable)
    nearest = min(computable, key=lambda sq: sq[0]["distance_m"]) if computable else None

    if not segments:
        # 半径内没有管。是「真没有」还是「没数据」，看最近管有多远。
        basis = (
            "no_coverage"
            if nearest_any_m is None or nearest_any_m > COVERAGE_RADIUS_M
            else "measured_no_network"
        )
    elif local is None:
        # 有管但一根都算不出（缺管径 / 缺高程 / 坡度离谱 / 没有收集系统级管道）
        basis = "uncomputable"
    else:
        basis = "measured"

    unknown = [s for s in segments if is_material_unusable(s.get("material"))]
    return HotspotQcap(
        uid=uid,
        nearest_any_m=round(nearest_any_m, 1) if nearest_any_m is not None else None,
        pipes_in_radius=len(segments),
        pipes_computable=len(computable),
        qcap_m3s=round(local[1], 4) if local else None,
        qcap_nearest_m3s=round(nearest[1], 4) if nearest else None,
        qcap_any_class_m3s=round(any_class[1], 4) if any_class else None,
        qcap_source_gid=local[0]["gid"] if local else None,
        qcap_source_class=local[0].get("main_class") if local else None,
        qcap_source_diameter_mm=local[0].get("diameter_mm") if local else None,
        qcap_source_distance_m=round(local[0]["distance_m"], 1) if local else None,
        material_unknown_share=round(len(unknown) / len(segments), 3) if segments else None,
        basis=basis,
    )


def compute_all(
    radius_m: float = SEARCH_RADIUS_M,
    points_table: str = DEFAULT_POINTS_TABLE,
) -> list[HotspotQcap]:
    """连库取数 + 逐点归并。需要 `points_table` 已落库（uid + EPSG:32640 的 geom）。"""
    from .db import query  # 延迟导入：没有数据库也能 import 本模块

    by_uid: dict[str, list[dict]] = {}
    for row in query(_segments_sql(points_table), {"radius": radius_m}):
        by_uid.setdefault(row["uid"], []).append(row)

    nearest = {r["uid"]: r["nearest_any_m"] for r in query(_nearest_sql(points_table))}
    return [
        summarise(uid, by_uid.get(uid, []), dist)
        for uid, dist in sorted(nearest.items())
    ]


def write_csv(results: list[HotspotQcap], path: Path = OUTPUT_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [f.name for f in fields(HotspotQcap)]
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
        print(f"   {basis:<22} {n:>4}")


if __name__ == "__main__":
    main()
