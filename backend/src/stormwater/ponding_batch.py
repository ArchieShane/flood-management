"""从 ANUGA 二维演算成果批量反算逐点**积水量时程**（项目此前完全缺失的量）。

产出三个文件，由 `registry.py` 离线读取，与 `qcap_batch.py` / `storage_batch.py`
同一套路：

| 文件 | 粒度 | 行数（Al Bateen RP100） |
|---|---|---|
| `hotspot_ponding.csv`        | 逐台账点汇总 | 18 |
| `hotspot_ponding_series.csv` | 台账点 × 时刻 | ~1.4k |
| `ponding_zones.csv`          | 逐洼地（不依赖台账） | 249 |

在此之前项目里**没有任何积水量数据** —— 三道防线只算得出「来水 Q」「管道能力
Qcap」「已有调蓄容量」，缺口是按流量差×时限估的，从来没有一个实测或演算出来的
「这个点当时积了多少方水」。本模块用二维水动力成果把这个量补上。

## 归属怎么做的（这是本模块的全部难点）

51.7 万方水要切给各个点，且**不重不漏**。连通域做不到 —— 按最大水深 0.05 m 连通，
Al Bateen 的 12 个台账点里有 9 个会并进同一个 303 ha 的大片区。改用地形洼地：

1. **priority-flood 填洼**（`_fill_depressions`）——以区界/海岸为出口种子，得到
   水文修正 DEM。`fill − dem > 0.01 m` 的单元即洼地，8 邻域连通标号。
   Al Bateen 得 **249 个洼地，静态容积合计 166,716 m³**。
2. **D8 汇流**（`_flow_terminals`）——在填洼后 DEM 上求最陡下坡指针，逐格追踪到
   终点：落进某个洼地，或流出区界。59.8% 的陆地单元归入洼地，40.2% 直排出区。
3. **台账点挂接**（`_attach_hotspots`）——三级判定，逐点记在 `attribution_basis`：
   `点内` 点落在洼地格上（9 个）> `汇流` 点所在格 D8 汇入某洼地（5 个）>
   `坡面直排` 两者都不是（4 个，**只报本格水量，不挂洼地**）。
4. **共用洼地再切分**——一个洼地含多个台账点时（Al Bateen 有 3 处，最多的洼地 5
   占了 5 个点），洼地内各格按**最近点**划给某一个点，逐帧按格求和。这与
   `catchment_batch.py` 的 Voronoi 是同一个代理思路，`shared_point_count` 列标出来。

## 两个口径的积水量，必须一起看

峰值时刻（t=180 min）洼地内蓄水 307,125 m³，是静态洼地容积 166,716 m³ 的
**1.84 倍** —— 那一刻洼地全在漫溢，水连成片在流，「属于某个点的积水量」这句话
在物理上不成立。洼地内蓄水回落到静态容积以下发生在 **t=285 min（4.8 h）**，
此后洼地内占全区比例升到 88–91%，水才真正落回各自的坑里。所以每个点给两个数：

* `peak_volume_m3` —— 全程瞬时峰值。含过路水，**系统性偏大**，用于「最不利时刻
  地面上有多少水」。
* `settled_volume_m3` —— `SETTLE_MINUTES`(285) 之后的峰值。这是**可归属的积水量**，
  用于抽排作业量估算。全区口径下它只有瞬时峰值的 60%。

另给 `volume_hours_m3h`（∫V dt，梯形积分）—— 排水作业量和这个成正比，比单看峰值更
适合排泵车。

## 「总共积了多少水」用净值口径，不回算排掉的水

* `net_inflow_m3`（m³，**精确**）—— Σ 正的 ΔV，即净累计进水量。18 点合计 57,527 m³。
  Al Bateen 这场雨下 16 个有水的点里 15 个是单峰过程（单调涨、单调退），故
  `net_inflow_m3` 与 `peak_volume_m3` 相等；**ADM-398 是例外**，它在 t=180 min
  降雨结束时有一次 +0.53 m³ 的回涨，净值 624.76 比峰值 624.23 高 0.57 m³。
  量很小，但正说明实现必须按 Σ 正 ΔV 算 —— 图省事直接取峰值，换一场双峰的雨
  就会整段少算第二次上涨的水。
* `volume_hours_m3h`（**m³·h**，不是 m³）—— 时程逐帧相加得到的是这个，不是水量。
  排泵车看它，算抽排总量看 `net_inflow_m3`。

**不回算上涨期排掉的水**。曾试过用各点退水段拟合线性水库常数 τ 把这部分加回去（τ
落在 61–154 min，对照文档值 120 min，退水段拟合相关系数 −0.95 ~ −1.00，本身很好），
但外推到上涨期站不住：同样做法在全区口径下算出通过量 995,150 m³，比实际入流
（降雨 537,117 + 管网 123,263 = 660,379 m³）高 **51%** —— 上涨期水摊在两倍面积上
（21,440 格 vs 峰值时 9,479 格），大部分是过路水而非滞蓄，线性水库律会高估流失。
真要毛通量得从 `.sww` 的 `xmomentum`/`ymomentum` 算，不能靠存量外推。

同理，run 自己的 `surface_drainage_outflow_m3`(509,216) 与快照积分也对不上：按文档的
汇排定律（`q = d/120min`，下限 2 mm/h）在快照上积分得 1,022,174 m³，正好是它的
**2.007 倍**。ANUGA 的内部记账口径与快照积分不一致，不能拿它当锚点。

⚠ 五条口径限制，引用数字前必须一起说：

* **只覆盖 Al Bateen 一个区，845 点里只挂得上 18 个**（2.1%）。这个 run 的边界框内
  有 67 个台账点，但 49 个落在海域或区外。要覆盖全市必须逐区重跑 ANUGA。
* **81% 的积水量落在台账里没有点的洼地上**。249 个洼地只有 12 个挂得上台账点，
  峰值蓄水 32.3 万方（81.2%）在另外 237 个洼地里。`ponding_zones.csv` 里
  `hotspot_uids` 为空的行就是**台账漏报的候选积水点**，落定后蓄水最大的一个
  （洼地 215，449 格 / 19,316 m³ 容积 / 落定峰值 20,843 m³）比任何一个有台账点的
  洼地都大。这条结论本身比逐点数值更值得跟进。
* **20 m 计算网格会把洼地并粗**。源数据是 5 m DTM，聚合到 20 m 后路缘、分隔带被抹平，
  相邻但实际隔开的积水坑会并成一个。洼地 5（478 格 / 19 ha）含 5 个台账点，多半
  就是这么并出来的。逐点切分因此**只可用于筛查和排序，不可作为单点设计依据**。
* **绝对量受上游耦合 bug 拖累**。该 run 的 SWMM 注入实际只进了 123,263 m³，比
  `prescribed_swmm_to_anuga_volume_m3`(288,838) 少 165,575 m³，缺口是峰值蓄水量的
  32%。修好之前这批数只能用于**相对排序和过程分析**。
* **快照只存 ≥0.01 m 的格子**，薄于 1 cm 的水被截掉。这与 run 自己的
  `final_surface_volume_m3` 同口径（末帧 95.81 vs 95.809，对得上），不是额外误差，
  但要说清这是「≥1 cm 的地表滞蓄量」。

另注：t≈1200 min 之后残留的 4–7 格水**不在任何洼地内**，是 ANUGA 在平坦湿格上的
数值残留，不是真实积水，`ponding_zones.csv` 里不会出现。
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import numpy as np

from .db import query

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BACKEND_DIR / "data" / "processed"

#: 默认的 ANUGA 成果目录。换 run 用 --run-dir 覆盖。
DEFAULT_RUN_DIR = (
    BACKEND_DIR / "data" / "al-bateen-library-rp100-20m-20260920T122942Z-96h-priority"
)

OUT_POINTS = PROCESSED_DIR / "hotspot_ponding.csv"
OUT_SERIES = PROCESSED_DIR / "hotspot_ponding_series.csv"
OUT_ZONES = PROCESSED_DIR / "ponding_zones.csv"

#: 判定洼地的最小填洼深度。低于 1 cm 的是 DEM 噪声，且与快照的 0.01 m 存储阈值同量级。
DEPRESSION_MIN_DEPTH_M = 0.01

#: 水「落定」的时刻（分钟）。见模块文档：洼地内蓄水回落到静态容积以下的时刻，
#: 由 `find_settle_time()` 从成果自己算出来，这里是 Al Bateen RP100 的取值，
#: 换 run 会被实算值覆盖。
SETTLE_MINUTES = 285.0

_NB = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))
_NBDIST = (2**0.5, 1.0, 2**0.5, 1.0, 1.0, 2**0.5, 1.0, 2**0.5)

_HOTSPOT_SQL = """
select uid, municipality, area, location, criticality, network_available,
       st_x(geom) as easting, st_y(geom) as northing
from hotspot.hotspots_845
where geom && st_makeenvelope(%s, %s, %s, %s, 32640)
order by uid
"""


@dataclass(frozen=True)
class PointPonding:
    """`hotspot_ponding.csv` 的一行。"""

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


@dataclass(frozen=True)
class ZonePonding:
    """`ponding_zones.csv` 的一行 —— 不依赖台账的物理积水单元。"""

    depression_id: int
    run_id: str
    cells: int
    area_ha: float
    centroid_e_32640: float
    centroid_n_32640: float
    capacity_m3: float
    max_fill_depth_m: float
    catchment_cells: int
    peak_volume_m3: float
    peak_time_min: float
    settled_volume_m3: float
    settled_time_min: float | None
    volume_hours_m3h: float
    drain_time_min: float | None
    net_inflow_m3: float
    hotspot_uids: str


def _fill_depressions(dem: np.ndarray, land: np.ndarray) -> np.ndarray:
    """priority-flood 填洼，返回水文修正 DEM（非陆地格为 nan）。

    出口种子 = 贴区界或贴非陆地格的陆地单元。标准 Barnes et al. (2014) 实现。
    """
    height, width = dem.shape
    filled = np.where(land, dem, np.nan)
    closed = ~land.copy()
    heap: list[tuple[float, int, int]] = []
    for y, x in zip(*np.where(land)):
        on_edge = y in (0, height - 1) or x in (0, width - 1) or any(
            not land[y + dy, x + dx]
            for dy, dx in _NB
            if 0 <= y + dy < height and 0 <= x + dx < width
        )
        if on_edge:
            heapq.heappush(heap, (float(dem[y, x]), int(y), int(x)))
            closed[y, x] = True
    while heap:
        elev, y, x = heapq.heappop(heap)
        for dy, dx in _NB:
            p, q = y + dy, x + dx
            if 0 <= p < height and 0 <= q < width and land[p, q] and not closed[p, q]:
                closed[p, q] = True
                filled[p, q] = max(float(dem[p, q]), elev)
                heapq.heappush(heap, (float(filled[p, q]), p, q))
    return filled


def _label_depressions(fill_depth: np.ndarray) -> np.ndarray:
    """把 `fill_depth > DEPRESSION_MIN_DEPTH_M` 的格子 8 邻域连通标号，非洼地为 −1。"""
    height, width = fill_depth.shape
    mask = fill_depth > DEPRESSION_MIN_DEPTH_M
    label = np.full((height, width), -1, np.int32)
    count = 0
    for y, x in zip(*np.where(mask)):
        if label[y, x] >= 0:
            continue
        stack = [(int(y), int(x))]
        label[y, x] = count
        while stack:
            a, b = stack.pop()
            for dy, dx in _NB:
                p, q = a + dy, b + dx
                if 0 <= p < height and 0 <= q < width and mask[p, q] and label[p, q] < 0:
                    label[p, q] = count
                    stack.append((p, q))
        count += 1
    return label


def _flow_terminals(filled: np.ndarray, land: np.ndarray, label: np.ndarray) -> np.ndarray:
    """D8 逐格追踪终点：返回每格归属的洼地号，−1 表示直排出区。

    洼地内的格子终点即自身所属洼地。洼地外的格子沿最陡下坡走，走到洼地或走出区界为止。
    """
    height, width = filled.shape
    nxt = np.full(height * width, -1, np.int64)
    for y, x in zip(*np.where(land)):
        if label[y, x] >= 0:
            continue
        best_slope, best_idx, drains_out = 0.0, -1, False
        for k, (dy, dx) in enumerate(_NB):
            p, q = y + dy, x + dx
            if not (0 <= p < height and 0 <= q < width):
                continue
            if not land[p, q]:
                drains_out = True
                break
            slope = (filled[y, x] - filled[p, q]) / _NBDIST[k]
            if slope > best_slope:
                best_slope, best_idx = slope, p * width + q
        nxt[y * width + x] = -1 if drains_out else best_idx

    flat_label = label.ravel()
    term = np.full(height * width, -1, np.int64)
    for start in np.where(land.ravel())[0]:
        if flat_label[start] >= 0:
            term[start] = flat_label[start]
            continue
        cur, seen = start, set()
        while True:
            step = nxt[cur]
            if step < 0 or step in seen:
                term[start] = -1
                break
            if flat_label[step] >= 0:
                term[start] = flat_label[step]
                break
            seen.add(step)
            cur = step
    return term.reshape(height, width)


def load_depth_matrix(run_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """读 `temporal_snapshots/`，返回 (帧 × 全网格) 水深矩阵和各帧时刻（分钟）。"""
    manifest = json.loads((run_dir / "temporal_snapshots" / "manifest.json").read_text())
    snaps = sorted(manifest["snapshots"], key=lambda s: s["index"])
    terrain = np.load(run_dir / "terrain_grid.npz", allow_pickle=True)
    n_cells = terrain["values"].size
    depth = np.zeros((len(snaps), n_cells), np.float32)
    times = np.zeros(len(snaps))
    for i, snap in enumerate(snaps):
        times[i] = snap["time_minutes"]
        payload = json.loads((run_dir / snap["path"]).read_text())
        for feature in payload["features"]:
            props = feature["properties"]
            depth[i, props["cell_id"]] = props["depth_m"]
    return depth, times


def find_settle_time(
    depth: np.ndarray, times: np.ndarray, label: np.ndarray, capacity_total: float, cell_area: float
) -> float:
    """洼地内蓄水回落到静态容积以下的时刻 —— 此后逐点归属才是良定义的。"""
    inside = np.where(label.ravel() >= 0)[0]
    stored = depth[:, inside].sum(axis=1) * cell_area
    peak = int(stored.argmax())
    for i in range(peak, len(times)):
        if stored[i] < capacity_total:
            return float(times[i])
    return float(times[-1])


def _series_metrics(series: np.ndarray, times: np.ndarray, settle: float) -> dict:
    """峰值 / 落定峰值 / ∫V dt / 退空时刻 / 净累计进水。"""
    peak = int(series.argmax())
    late_mask = times >= settle
    late = series[late_mask]
    late_times = times[late_mask]
    late_peak = int(late.argmax()) if late.size else None
    after = np.where((series <= 0.0) & (np.arange(len(series)) > peak))[0]

    # 净累计进水：Σ 正的 ΔV，首尾补零（点在窗口起止时都是干的）。
    padded = np.concatenate(([0.0], series, [0.0]))
    net = float(np.diff(padded).clip(min=0.0).sum())

    return {
        "peak_volume_m3": round(float(series[peak]), 2),
        "peak_time_min": float(times[peak]),
        "settled_volume_m3": round(float(late[late_peak]), 2) if late_peak is not None else 0.0,
        "settled_time_min": float(late_times[late_peak]) if late_peak is not None else None,
        # 梯形积分，时间换算成小时
        "volume_hours_m3h": round(float(np.trapezoid(series, times) / 60.0), 2),
        "drain_time_min": float(times[after[0]]) if after.size else None,
        "net_inflow_m3": round(net, 2),
    }


def _attach_hotspots(
    run_dir: Path, label: np.ndarray, term: np.ndarray, depth_max: np.ndarray
) -> list[dict]:
    """从库里取落在 run 边界框内的台账点，判定归属，返回逐点记录。"""
    terrain = np.load(run_dir / "terrain_grid.npz", allow_pickle=True)
    x0, _y0, _x1, y1 = terrain["bounds"]
    cell = float(terrain["cell_size_m"])
    land = terrain["district_land_mask"]
    height, width = land.shape
    rows = query(_HOTSPOT_SQL, tuple(float(v) for v in terrain["bounds"]))

    out: list[dict] = []
    for row in rows:
        col = int((row["easting"] - x0) // cell)
        line = int((y1 - row["northing"]) // cell)
        if not (0 <= line < height and 0 <= col < width) or not land[line, col]:
            continue  # 落在海域或区外，本 run 管不着
        idx = line * width + col
        in_label = int(label.ravel()[idx])
        terminal = int(term.ravel()[idx])
        if in_label >= 0:
            basis, dep = "点内", in_label
        elif terminal >= 0:
            basis, dep = "汇流", terminal
        else:
            basis, dep = "坡面直排", None
        out.append(
            {
                "uid": row["uid"],
                "criticality": row["criticality"],
                "cell_id": idx,
                "row": line,
                "col": col,
                "basis": basis,
                "depression_id": dep,
                "point_max_depth_m": round(float(depth_max[idx]), 4),
            }
        )
    return out


def _split_shared(
    points: list[dict], label: np.ndarray, width: int
) -> dict[str, np.ndarray]:
    """共用同一洼地的点，按最近点把洼地内的格子分掉；返回 uid → 格号数组。

    这是几何代理，不是汇水边界 —— 与 `catchment_batch.py` 的 Voronoi 同一性质。

    切分范围是**洼地格 ∪ 各成员自己所在格**。带上自己那一格是必须的：`汇流` 类
    成员本身不在洼地内，若只切洼地格，两个相邻成员里靠外的那个会一格都分不到，
    算出 0 方（ADM-380 与 ADM-383 只隔 2 格，就踩过这个坑）。自己那一格到自己的
    距离是 0，因此每个成员至少拿得到一格。代价是 `汇流` 成员多带的那一格不在
    洼地行的统计口径里，逐点求和会略高于洼地行 —— 差额就是这些格的水量，
    它们正在流向该洼地，不构成重复计算。
    """
    by_dep: dict[int, list[dict]] = {}
    for p in points:
        if p["depression_id"] is not None:
            by_dep.setdefault(p["depression_id"], []).append(p)
    owned: dict[str, np.ndarray] = {}
    flat = label.ravel()
    for dep, members in by_dep.items():
        cells = np.union1d(
            np.where(flat == dep)[0], np.array([m["cell_id"] for m in members])
        )
        if len(members) == 1:
            owned[members[0]["uid"]] = cells
            continue
        rows_, cols_ = cells // width, cells % width
        dist = np.stack(
            [((rows_ - m["row"]) ** 2 + (cols_ - m["col"]) ** 2) for m in members]
        )
        nearest = dist.argmin(axis=0)
        for i, m in enumerate(members):
            owned[m["uid"]] = cells[nearest == i]
    return owned


def build(run_dir: Path) -> tuple[list[PointPonding], list[ZonePonding], list[dict]]:
    terrain = np.load(run_dir / "terrain_grid.npz", allow_pickle=True)
    receipt = json.loads((run_dir / "run_receipt.json").read_text())
    summary = receipt["summary"]
    run_id = receipt["run_id"]
    district = summary["scope"]["name"]
    rp = int(receipt["return_period_years"])

    dem = terrain["values"].astype(np.float64)
    land = terrain["district_land_mask"]
    cell = float(terrain["cell_size_m"])
    area = cell * cell
    x0, _y0, _x1, y1 = terrain["bounds"]
    height, width = dem.shape

    filled = _fill_depressions(dem, land)
    fill_depth = np.where(land, filled - dem, 0.0)
    label = _label_depressions(fill_depth)
    term = _flow_terminals(filled, land, label)
    n_dep = int(label.max()) + 1

    depth, times = load_depth_matrix(run_dir)
    depth_max = depth.max(axis=0)
    flat_label = label.ravel()
    capacity = np.array(
        [fill_depth.ravel()[flat_label == i].sum() * area for i in range(n_dep)]
    )
    settle = find_settle_time(depth, times, label, capacity.sum(), area)

    points = _attach_hotspots(run_dir, label, term, depth_max)
    owned = _split_shared(points, label, width)
    dep_members: dict[int, list[str]] = {}
    for p in points:
        if p["depression_id"] is not None:
            dep_members.setdefault(p["depression_id"], []).append(p["uid"])

    # ---- 逐洼地 ----
    zones: list[ZonePonding] = []
    flat_term = term.ravel()
    for i in range(n_dep):
        cells = np.where(flat_label == i)[0]
        series = depth[:, cells].sum(axis=1) * area
        m = _series_metrics(series, times, settle)
        rows_, cols_ = cells // width, cells % width
        zones.append(
            ZonePonding(
                depression_id=i,
                run_id=run_id,
                cells=len(cells),
                area_ha=round(len(cells) * area / 1e4, 4),
                centroid_e_32640=round(float(x0 + (cols_.mean() + 0.5) * cell), 1),
                centroid_n_32640=round(float(y1 - (rows_.mean() + 0.5) * cell), 1),
                capacity_m3=round(float(capacity[i]), 2),
                max_fill_depth_m=round(float(fill_depth.ravel()[cells].max()), 3),
                catchment_cells=int((flat_term == i).sum()),
                hotspot_uids=";".join(sorted(dep_members.get(i, []))),
                **m,
            )
        )

    # ---- 逐台账点 ----
    records: list[PointPonding] = []
    series_rows: list[dict] = []
    for p in points:
        if p["depression_id"] is None:
            cells = np.array([p["cell_id"]])  # 坡面直排：只报本格
            cap_i: float | None = None
            shared = 0
        else:
            cells = owned[p["uid"]]
            dep_cells = np.where(flat_label == p["depression_id"])[0]
            frac = len(np.intersect1d(cells, dep_cells)) / max(1, len(dep_cells))
            cap_i = round(float(capacity[p["depression_id"]] * frac), 2)
            shared = len(dep_members[p["depression_id"]])
        series = depth[:, cells].sum(axis=1) * area
        m = _series_metrics(series, times, settle)
        records.append(
            PointPonding(
                uid=p["uid"],
                run_id=run_id,
                district=district,
                return_period_years=rp,
                criticality=p["criticality"],
                attribution_basis=p["basis"],
                cell_id=p["cell_id"],
                point_max_depth_m=p["point_max_depth_m"],
                depression_id=p["depression_id"],
                shared_point_count=shared,
                depression_capacity_m3=cap_i,
                **m,
            )
        )
        for j, value in enumerate(series):
            if value > 0:
                series_rows.append(
                    {
                        "uid": p["uid"],
                        "run_id": run_id,
                        "time_min": f"{times[j]:.0f}",
                        "time_h": f"{times[j] / 60:.2f}",
                        "volume_m3": f"{value:.2f}",
                        "wet_cells": int((depth[j, cells] > 0).sum()),
                        "max_depth_m": f"{depth[j, cells].max():.3f}",
                    }
                )
    return records, zones, series_rows


def _write(path: Path, rows: list, header: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row if isinstance(row, dict) else asdict(row))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    args = parser.parse_args()

    records, zones, series = build(args.run_dir)
    _write(OUT_POINTS, records, [f.name for f in fields(PointPonding)])
    _write(OUT_ZONES, zones, [f.name for f in fields(ZonePonding)])
    _write(
        OUT_SERIES,
        series,
        ["uid", "run_id", "time_min", "time_h", "volume_m3", "wet_cells", "max_depth_m"],
    )
    unmapped = [z for z in zones if not z.hotspot_uids]
    print(f"台账点 {len(records)} 个 → {OUT_POINTS}")
    print(f"洼地 {len(zones)} 个（其中 {len(unmapped)} 个无台账点）→ {OUT_ZONES}")
    print(f"时程 {len(series)} 行 → {OUT_SERIES}")


if __name__ == "__main__":
    main()
