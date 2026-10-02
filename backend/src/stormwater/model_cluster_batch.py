"""把 107 个模型识别片区补成**可进计算器**的点 —— 与台账 845 点同一条计算链。

`model_ponding.py` 只负责把二维演算的成果读出来展示；本模块解决的是另一件事：
那 107 个片区身上**一个计算器要的输入都没有**（没有汇水面积 A、径流系数 C、
集流时间 tc、管网能力 Qcap、可用调蓄），所以它们本来进不了三道防线。

做法是：把每个片区的代表点灌进库，然后跑**台账那一路一模一样的四个批算**
（`qcap_batch` / `storage_batch` / `district_batch` / `catchment_batch`），
只是把点表换成 `hotspot.model_clusters`。四个模块的 SQL 都已参数化，
一行判据都没改 —— 故同一个坐标上，模型片区与台账点反算出来的 Qcap 逐字段相等。

## 汇水面积：D8 实算为主，Voronoi 代理做对照

台账 845 点的 A 用的是「相邻点 Voronoi 等分 ∩ 250 m 圆」——纯几何代理，因为
台账点只是一个坐标，没有地形可依。模型片区不一样：它们来自一次二维演算，
**地形就在手上**（`terrain_grid.npz` 的 20 m DTM），故这里改用真汇流：

1. **priority-flood 填洼**（复用 `ponding_batch._fill_depressions`）得到水文修正 DEM；
2. **八连通标洼地**（`_label_depressions`）；
3. **D8 逐格追踪终点**（`_flow_terminals`）—— 每个陆地格算清楚它的水最终落进哪个洼地；
4. 片区 → 宿主洼地（片区代表格所在的洼地），洼地的汇水格按**最近片区格**切给各片区
   （一个洼地里有几个片区时才需要切，与 `ponding_batch._split_shared` 同一套路）；
5. 把切好的格子拼成多边形灌进 `hotspot.catchment_cell_model_d8`，
   下游三张表（下垫面 / 地块分类 / 管段）照常由 `catchment_batch` 按这份单元算。

于是 **A 的边界是实算汇流范围，C 与 tc 仍由 UDM 地物图层在该范围内加权** ——
两者都不是假设。同时另跑一遍 Voronoi 代理（`suffix="_model"`）做对照列，
`area_ha_voronoi` 与 `area_ha`（D8）差多少，一眼看得出代理偏到哪去。

⚠ 三件事必须说清楚：

* **D8 与 Voronoi 不是同一种边界**，故模型片区的 A 与台账点的 A 不可直接对比大小。
  可比的是它们各自算出的三道防线结论。
* 没有宿主洼地的片区（滨海那几个，水直排出区界）拿不到汇流范围，
  只能退回「片区自身范围」，`catchment_d8_basis` 记成 `cluster_only`。
* 本模块**会写库**（`hotspot.model_clusters` 与带 `_model*` 后缀的工作表）。
  写入范围锁死在这几张，来源图层一律只读。
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import numpy as np

from .model_ponding import OUTPUT_GEOJSON as CLUSTER_GEOJSON, RUN_META, load_features
from .ponding_batch import (
    DEFAULT_RUN_DIR,
    SETTLE_MINUTES,
    _fill_depressions,
    _flow_terminals,
    _label_depressions,
    _series_metrics,
    find_settle_time,
    load_depth_matrix,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BACKEND_DIR / "data" / "processed"

#: 片区代表点在库里的表。与 `hotspot.hotspots_845` 同构（uid + EPSG:32640 的 geom）。
POINTS_TABLE = "hotspot.model_clusters"

#: D8 汇流范围表。列与 `hotspot.catchment_cell` 对齐，故 `catchment_batch`
#: 的下游三张表不用改一个字就能按它算。
D8_CELL_TABLE = "hotspot.catchment_cell_model_d8"

#: Voronoi 对照那一路的工作表后缀（`catchment_batch` 自己建 cell 表）。
VORONOI_SUFFIX = "_model"
#: D8 主口径那一路的后缀（cell 表由本模块灌，故 `build_cells=False`）。
D8_SUFFIX = "_model_d8"

OUT_POINTS = PROCESSED_DIR / "model_cluster_points.csv"
OUT_CATCHMENT = PROCESSED_DIR / "model_cluster_catchment.csv"
OUT_QCAP = PROCESSED_DIR / "model_cluster_qcap.csv"
OUT_STORAGE = PROCESSED_DIR / "model_cluster_storage.csv"
OUT_DISTRICT = PROCESSED_DIR / "model_cluster_district.csv"
OUT_PONDING = PROCESSED_DIR / "model_cluster_ponding.csv"
#: 逐片区 × 逐时刻的积水量时程。**第一道防线直接读它**（`ponding_curve.py`），
#: 故这个文件不是可选的锦上添花 —— 没有它，片区一样「无水动力标定」不出结论。
OUT_PONDING_SERIES = PROCESSED_DIR / "model_cluster_ponding_series.csv"

#: uid 规则。`MDL` = model，后面是片区 rank（积水指数降序），与页面上的 `#1` 对得上。
UID_FMT = "MDL-{:03d}"


def uid_of(rank: int) -> str:
    return UID_FMT.format(int(rank))


# ---------------------------------------------------------------------------
# 片区 → 网格
# ---------------------------------------------------------------------------


def _grid(run_dir: Path) -> dict:
    """读地形网格，顺带把行列换算需要的几个量摆出来。"""
    t = np.load(run_dir / "terrain_grid.npz", allow_pickle=True)
    x0, _y0, _x1, y1 = t["bounds"]
    return {
        "dem": t["values"].astype(np.float64),
        "land": t["district_land_mask"],
        "cell": float(t["cell_size_m"]),
        "x0": float(x0),
        "y1": float(y1),
        "shape": t["values"].shape,
    }


def _rowcol(easting: np.ndarray, northing: np.ndarray, g: dict) -> tuple[np.ndarray, np.ndarray]:
    """EPSG:32640 坐标 → 网格行列。与报告 §1.2 的约定一致（已用 rank 2 校验）。"""
    col = np.floor((easting - g["x0"]) / g["cell"]).astype(int)
    row = np.floor((g["y1"] - northing) / g["cell"]).astype(int)
    return row, col


def cluster_cells(features: list[dict], g: dict) -> dict[int, np.ndarray]:
    """片区 rank → 它占的网格单元（扁平下标）。

    片区几何是一堆**未融合的 20 m 方格**，故取每个方格的中心点反解行列即可 ——
    不必做真正的栅格化。整批 1,378 个方格，一次 transform 解决。
    """
    from rasterio.warp import transform  # 延迟导入：没有 GDAL 也能 import 本模块

    lons: list[float] = []
    lats: list[float] = []
    owner: list[int] = []
    for f in features:
        rank = int(f["properties"]["rank"])
        polys = f["geometry"]["coordinates"]
        if f["geometry"]["type"] == "Polygon":
            polys = [polys]
        for poly in polys:
            ring = np.asarray(poly[0], dtype=float)[:-1]  # 末点与首点重合，去掉
            lons.append(float(ring[:, 0].mean()))
            lats.append(float(ring[:, 1].mean()))
            owner.append(rank)

    xs, ys = transform("EPSG:4326", "EPSG:32640", lons, lats)
    rows, cols = _rowcol(np.asarray(xs), np.asarray(ys), g)
    height, width = g["shape"]
    flat = rows * width + cols

    out: dict[int, list[int]] = {}
    for rank, idx, r, c in zip(owner, flat, rows, cols):
        if 0 <= r < height and 0 <= c < width:
            out.setdefault(rank, []).append(int(idx))
    return {k: np.unique(np.asarray(v, dtype=np.int64)) for k, v in out.items()}


# ---------------------------------------------------------------------------
# D8 汇流范围
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClusterCatchment:
    """一个片区的 D8 汇流范围。几何另外灌库，这里只留可核对的数。"""

    uid: str
    rank: int
    #: 宿主洼地号（本次填洼的标号，仅用于回溯）；None = 该片区不在任何洼地里
    depression_id: int | None
    #: 与它共用同一个洼地的片区数（含自己）。>1 说明这片汇水范围是切出来的
    shared_with: int
    #: 片区自身占的格数
    cluster_cells: int
    #: 汇流范围格数（含片区自身）
    catchment_cells: int
    catchment_ha: float
    #: 代表点到汇流范围最远点的距离（米）—— 与 Voronoi 那一路的 `flow_path_m` 同义
    flow_path_m: float
    #: d8_depression = 有宿主洼地，范围来自 D8；cluster_only = 无宿主洼地，只算片区自身
    basis: str


def d8_catchments(features: list[dict], run_dir: Path = DEFAULT_RUN_DIR) -> tuple[
    list[ClusterCatchment], dict[str, np.ndarray], dict
]:
    """逐片区实算 D8 汇流范围。

    Returns:
        (逐片区汇总, uid → 汇流范围的扁平格下标, 地形网格信息)
    """
    g = _grid(run_dir)
    dem, land, cell = g["dem"], g["land"], g["cell"]
    height, width = g["shape"]
    area = cell * cell

    filled = _fill_depressions(dem, land)
    fill_depth = np.where(land, filled - dem, 0.0)
    label = _label_depressions(fill_depth)
    term = _flow_terminals(filled, land, label)

    flat_label = label.ravel()
    flat_term = term.ravel()
    cells = cluster_cells(features, g)

    # 片区 → 宿主洼地：取该片区占的格里出现最多的那个洼地号（片区可能跨洼地边缘）
    host: dict[int, int | None] = {}
    for rank, idx in cells.items():
        labs = flat_label[idx]
        labs = labs[labs >= 0]
        host[rank] = int(np.bincount(labs).argmax()) if labs.size else None

    by_dep: dict[int, list[int]] = {}
    for rank, dep in host.items():
        if dep is not None:
            by_dep.setdefault(dep, []).append(rank)

    owned: dict[str, np.ndarray] = {}
    rows_out: list[ClusterCatchment] = []
    for f in sorted(features, key=lambda x: x["properties"]["rank"]):
        p = f["properties"]
        rank = int(p["rank"])
        uid = uid_of(rank)
        own = cells.get(rank, np.empty(0, dtype=np.int64))
        dep = host.get(rank)

        if dep is None:
            # 滨海那几个：水直排出区界，没有洼地可汇 —— 只认片区自身，不硬凑
            mine, basis, shared = own, "cluster_only", 1
        else:
            pool = np.where(flat_term == dep)[0]
            peers = sorted(by_dep[dep])
            shared = len(peers)
            if shared == 1:
                mine = np.union1d(pool, own)
            else:
                # 一个洼地里有几个片区：汇水格按**最近片区格**切，片区自身的格不参与切分
                others = np.concatenate([cells[r] for r in peers if r != rank])
                claimed = np.concatenate([cells[r] for r in peers])
                free = np.setdiff1d(pool, claimed)
                if free.size:
                    d_mine = _min_cell_distance(free, own, width)
                    d_other = _min_cell_distance(free, others, width)
                    mine = np.union1d(own, free[d_mine <= d_other])
                else:
                    mine = own
            basis = "d8_depression"

        owned[uid] = mine
        rows_out.append(
            ClusterCatchment(
                uid=uid,
                rank=rank,
                depression_id=dep,
                shared_with=shared,
                cluster_cells=int(own.size),
                catchment_cells=int(mine.size),
                catchment_ha=round(mine.size * area / 1e4, 4),
                flow_path_m=round(_flow_path(mine, p, g), 1),
                basis=basis,
            )
        )
    return rows_out, owned, g


def _min_cell_distance(pool: np.ndarray, targets: np.ndarray, width: int) -> np.ndarray:
    """`pool` 每个格到 `targets` 最近格的距离（格数）。全是小数组，直接开方阵。"""
    if targets.size == 0:
        return np.full(pool.size, np.inf)
    pr, pc = pool // width, pool % width
    tr, tc = targets // width, targets % width
    d = (pr[:, None] - tr[None, :]) ** 2 + (pc[:, None] - tc[None, :]) ** 2
    return np.sqrt(d.min(axis=1))


def _flow_path(cells_idx: np.ndarray, props: dict, g: dict) -> float:
    """代表点到汇流范围最远格的距离（米）—— `catchment_batch` 用它定坡面流长。"""
    if cells_idx.size == 0:
        return g["cell"]
    _height, width = g["shape"]
    r0, c0 = int(props["row"]), int(props["col"])
    rr, cc = cells_idx // width, cells_idx % width
    return float(np.sqrt((rr - r0) ** 2 + (cc - c0) ** 2).max() * g["cell"])


# ---------------------------------------------------------------------------
# 逐片区积水量时程 —— 与推理公式法并列对照的那一列
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClusterPonding:
    """`model_cluster_ponding.csv` 的一行。列名与 `ponding_batch.PointPonding`
    对齐，故 `registry._read_ponding()` 不改一个字就能读它。

    ⚠ 与台账那 18 个点的积水量有一处**本质区别**：那边的水量是把洼地的水按
    「最近点」切给台账点的（代理），这边的片区**本身就是积水范围**，水量是
    对它自己那些格逐帧求和，不需要任何归属代理。故 `attribution_basis`
    统一记成 `cluster`。
    """

    uid: str
    run_id: str
    district: str
    return_period_years: int
    criticality: str | None
    attribution_basis: str
    cell_id: int
    point_max_depth_m: float
    depression_id: int | None
    shared_point_count: int
    depression_capacity_m3: float | None
    peak_volume_m3: float
    peak_time_min: float
    settled_volume_m3: float
    settled_time_min: float | None
    volume_hours_m3h: float
    drain_time_min: float | None
    net_inflow_m3: float


def cluster_ponding(
    features: list[dict],
    d8_rows: list[ClusterCatchment],
    run_dir: Path = DEFAULT_RUN_DIR,
) -> tuple[list[ClusterPonding], list[dict]]:
    """逐片区实算积水量时程 V(t) = Σ_格 水深 × 400 m²。

    读 397 帧快照（约 204 MB），对每个片区自己的格逐帧求和，再走
    `ponding_batch._series_metrics` 那一套指标 —— 与台账那 18 个点**同一套口径**，
    两边的 `net_inflow_m3` 含义逐字相同，可以直接比。

    Returns:
        (逐片区汇总, 逐片区×逐时刻的时程行)。时程是**第一道防线的数据来源**
        （`ponding_curve.PondingCurve.state_at()` 按它插值），不是附属品：
        只有汇总没有时程，`rational.evaluate()` 读不出 V(T)。
        与台账那份一样，只写有水的帧（0 的帧不写，靠插值补）。
    """
    g = _grid(run_dir)
    cell = g["cell"]
    area = cell * cell
    dem, land = g["dem"], g["land"]

    filled = _fill_depressions(dem, land)
    fill_depth = np.where(land, filled - dem, 0.0)
    label = _label_depressions(fill_depth)
    flat_label = label.ravel()

    depth, times = load_depth_matrix(run_dir)
    n_dep = int(label.max()) + 1
    capacity = np.array([fill_depth.ravel()[flat_label == i].sum() * area for i in range(n_dep)])
    settle = find_settle_time(depth, times, label, capacity.sum(), area)

    cells = cluster_cells(features, g)
    by_rank = {r.rank: r for r in d8_rows}
    props = {int(f["properties"]["rank"]): f["properties"] for f in features}

    out: list[ClusterPonding] = []
    series_rows: list[dict] = []
    for rank in sorted(props):
        p = props[rank]
        idx = cells.get(rank, np.empty(0, dtype=np.int64))
        sub = depth[:, idx] if idx.size else np.zeros((len(times), 1))
        series = sub.sum(axis=1) * area
        m = _series_metrics(series, times, settle)
        d8 = by_rank[rank]
        uid = uid_of(rank)
        for i, v in enumerate(series):
            if v <= 0:
                continue
            wet = int((sub[i] > 0).sum())
            series_rows.append({
                "uid": uid,
                "run_id": RUN_META["run_id"],
                "time_min": int(times[i]),
                "time_h": round(float(times[i]) / 60.0, 2),
                "volume_m3": round(float(v), 2),
                "wet_cells": wet,
                "max_depth_m": round(float(sub[i].max()), 3),
            })
        out.append(
            ClusterPonding(
                uid=uid,
                run_id=RUN_META["run_id"],
                district=RUN_META["district"],
                return_period_years=int(RUN_META["return_period_yr"]),
                criticality=None,
                attribution_basis="cluster",
                cell_id=int(p["cell_id"]),
                point_max_depth_m=float(p["max_depth_m"]),
                depression_id=d8.depression_id,
                shared_point_count=d8.shared_with,
                depression_capacity_m3=(
                    round(float(capacity[d8.depression_id]), 2)
                    if d8.depression_id is not None else None
                ),
                **m,
            )
        )
    return out, series_rows


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------


def _runs(cells_idx: np.ndarray, width: int) -> list[tuple[int, int, int]]:
    """把格子集合压成逐行的连续段 `(row, col_start, col_end)`。

    直接把每个 20 m 方格当一个多边形灌进去，全区两万多个，`ST_Union` 要跑很久；
    压成行段之后通常少一个量级，而覆盖范围逐格相等。
    """
    rr, cc = cells_idx // width, cells_idx % width
    order = np.lexsort((cc, rr))
    rr, cc = rr[order], cc[order]
    out: list[tuple[int, int, int]] = []
    start = 0
    for i in range(1, len(rr) + 1):
        if i == len(rr) or rr[i] != rr[start] or cc[i] != cc[i - 1] + 1:
            out.append((int(rr[start]), int(cc[start]), int(cc[i - 1])))
            start = i
    return out


def load_db(features: list[dict], owned: dict[str, np.ndarray], g: dict) -> tuple[int, int]:
    """灌 `hotspot.model_clusters`（代表点）与 `hotspot.catchment_cell_model_d8`（汇流面）。

    ⚠ 两张表都是整表重建。与 `hotspots.load_db()` 同一套路：`db.connect()` 强制只读，
      写库单开一条连接，写入范围锁死在这两张表。
    """
    import psycopg

    from .config import db_settings

    _height, width = g["shape"]
    cell = g["cell"]
    x0, y1 = g["x0"], g["y1"]

    point_rows = [
        (
            uid_of(f["properties"]["rank"]),
            int(f["properties"]["rank"]),
            f["properties"]["mechanism_key"],
            float(f["properties"]["lat"]),
            float(f["properties"]["lon"]),
        )
        for f in sorted(features, key=lambda x: x["properties"]["rank"])
    ]

    with psycopg.connect(db_settings().conninfo) as conn, conn.cursor() as cur:
        cur.execute(f"""
            drop table if exists {POINTS_TABLE};
            create table {POINTS_TABLE} (
                uid text primary key,
                rank int not null,
                mechanism_key text,
                lat float8, lon float8,
                geom geometry(Point, 32640)
            );
        """)
        cur.executemany(
            f"insert into {POINTS_TABLE} (uid, rank, mechanism_key, lat, lon, geom) "
            "values (%s, %s, %s, %s, %s, "
            "st_transform(st_setsrid(st_makepoint(%s, %s), 4326), 32640))",
            [r + (r[4], r[3]) for r in point_rows],
        )
        cur.execute(f"create index on {POINTS_TABLE} using gist(geom)")

        # 汇流面：逐行段建方框 → 按 uid 合并。列与 hotspot.catchment_cell 对齐。
        cur.execute("drop table if exists hotspot.model_d8_run")
        cur.execute("create temp table _d8_run (uid text, x0 float8, y0 float8, x1 float8, y1 float8)")
        payload = []
        for uid, idx in owned.items():
            for row, ca, cb in _runs(idx, width):
                payload.append((
                    uid,
                    x0 + ca * cell, y1 - (row + 1) * cell,
                    x0 + (cb + 1) * cell, y1 - row * cell,
                ))
        cur.executemany("insert into _d8_run values (%s, %s, %s, %s, %s)", payload)
        cur.execute(f"""
            drop table if exists {D8_CELL_TABLE};
            create table {D8_CELL_TABLE} as
            select r.uid,
                   1::bigint as share_n,
                   st_maxdistance(p.geom, st_union(st_makeenvelope(r.x0, r.y0, r.x1, r.y1, 32640)))
                     as flow_path_m,
                   st_multi(st_union(st_makeenvelope(r.x0, r.y0, r.x1, r.y1, 32640)))
                     ::geometry(MultiPolygon, 32640) as geom
              from _d8_run r join {POINTS_TABLE} p using (uid)
             group by r.uid, p.geom;
            alter table {D8_CELL_TABLE} add primary key (uid);
            create index on {D8_CELL_TABLE} using gist(geom);
        """)
        conn.commit()
    return len(point_rows), len(payload)


# ---------------------------------------------------------------------------
# 跑批 + 落盘
# ---------------------------------------------------------------------------


def _write_csv(rows: list, path: Path, cls) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[f.name for f in fields(cls)])
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))
    return path


def _write_series(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["uid", "run_id", "time_min", "time_h", "volume_m3", "wet_cells", "max_depth_m"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return path


def run_batches(
    d8_rows: list[ClusterCatchment],
    ponding_rows: list[ClusterPonding] | None = None,
    series_rows: list[dict] | None = None,
) -> dict[str, int]:
    """跑台账那一路一模一样的四个批算，只是点表换成模型片区。"""
    from . import catchment_batch, district_batch, qcap_batch, storage_batch

    _write_csv(d8_rows, PROCESSED_DIR / "model_cluster_d8.csv", ClusterCatchment)
    if ponding_rows:
        _write_csv(ponding_rows, OUT_PONDING, ClusterPonding)
    if series_rows is not None:
        _write_series(series_rows, OUT_PONDING_SERIES)

    qcap = qcap_batch.compute_all(points_table=POINTS_TABLE)
    _write_csv(qcap, OUT_QCAP, qcap_batch.HotspotQcap)

    storage = storage_batch.compute_all(points_table=POINTS_TABLE)
    _write_csv(storage, OUT_STORAGE, storage_batch.HotspotStorage)

    district = district_batch.stamp(points_table=POINTS_TABLE)
    _write_csv(district, OUT_DISTRICT, district_batch.HotspotDistrict)

    # A 的主口径：D8 汇流范围（cell 表已由 load_db 灌好，故不重建）
    d8 = catchment_batch.compute_all(
        points_table=POINTS_TABLE, suffix=D8_SUFFIX, build_cells=False
    )
    _write_csv(d8, OUT_CATCHMENT, catchment_batch.HotspotCatchment)

    # 对照口径：与台账同法的 Voronoi 代理
    vor = catchment_batch.compute_all(points_table=POINTS_TABLE, suffix=VORONOI_SUFFIX)
    _write_csv(vor, PROCESSED_DIR / "model_cluster_catchment_voronoi.csv",
               catchment_batch.HotspotCatchment)

    return {
        "qcap": len(qcap), "storage": len(storage), "district": len(district),
        "catchment_d8": len(d8), "catchment_voronoi": len(vor),
        "ponding": len(ponding_rows or []),
        "ponding_series": len(series_rows or []),
    }


def main() -> None:
    features = load_features()
    if not features:
        raise SystemExit(f"找不到片区成果：{CLUSTER_GEOJSON}")

    print(f"片区 {len(features)} 个 · run {RUN_META['run_id']}")
    d8_rows, owned, g = d8_catchments(features)

    lonely = [r for r in d8_rows if r.basis == "cluster_only"]
    shared = [r for r in d8_rows if r.shared_with > 1]
    areas = sorted(r.catchment_ha for r in d8_rows)
    print(f"D8 汇流范围：合计 {sum(r.catchment_ha for r in d8_rows):.1f} ha · "
          f"中位 {areas[len(areas) // 2]:.2f} ha · 最大 {areas[-1]:.2f} ha")
    print(f"  无宿主洼地（只算片区自身）{len(lonely)} 个；与他人共用洼地 {len(shared)} 个")

    print("读 397 帧快照，逐片区实算积水量时程…")
    ponding_rows, series_rows = cluster_ponding(features, d8_rows)
    wet = [r for r in ponding_rows if r.net_inflow_m3 > 0]
    print(f"积水量：{len(wet)} 个片区有水 · 净累计进水合计 "
          f"{sum(r.net_inflow_m3 for r in wet):,.0f} m³ · 时程 {len(series_rows)} 行")

    n_pt, n_run = load_db(features, owned, g)
    print(f"落库：{POINTS_TABLE} {n_pt} 行 · {D8_CELL_TABLE} 由 {n_run} 个行段合并")

    tally = run_batches(d8_rows, ponding_rows, series_rows)
    print("批算完成：" + " · ".join(f"{k} {v}" for k, v in tally.items()))
    print(f"CSV 写到 {PROCESSED_DIR.relative_to(BACKEND_DIR)}/model_cluster_*.csv")


if __name__ == "__main__":
    main()
