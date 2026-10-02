"""从 EPA SWMM 全城演算成果反推逐点 Qcap —— `qcap_batch.py` 的水动力版本。

产出 `backend/data/processed/hotspot_qcap_swmm.csv`。**默认不参与计算**：
`registry.resolve_qcap()` 要显式传 `qcap_source="swmm"` 才会用它，原因见下方
「⚠ 为什么默认不开」。

**怎么取**：`Q_full = Q_max ÷ (Max/Full Flow)`，两个量都在 `.rpt` 的
Link Flow Summary 里，是从**演算结果**反推，不是我们自己再算一遍。

⚠ `Max/Full Flow` 只印到两位小数，比值越小反推误差越大。低于
`MIN_FLOW_RATIO` 的管段改用 `.inp` 的管径/糙率/坡度直接算曼宁满流兜底
（方法记在 `qcap_source_method` 列）。两条路径在 80,327 根管上交叉验证过：
反推/曼宁 = p10 0.99 / p50 1.00 / p90 1.01，可以混用。

⚠ **筛选口径与 `qcap_batch.py` 完全一致** —— 250 m 内、干管等级为
LATERAL / SECONDARY 的最大满流能力。等级不在 SWMM 模型里，靠把管段中点
匹配回 `sw_edge` 继承（匹配距离 p50 = 0.01 m，SWMM 模型就是从这批几何导出的）。
半径、等级、到点距离三件事都沿用原口径，换掉的只有 Qcap 本身的算法。

⚠ **SWMM 模型只覆盖阿布扎比岛及周边**（X 227–274 km / Y 2687–2724 km，
93,669 管段），而 `sw_edge` 有 261,847 条。845 个点里 411 个取得到值。

────────────────────────────────────────────────────────────────────────
⚠⚠ **为什么默认不开：这份模型的管道坡度是地形坡度，不是实测管道坡度**

本脚本原本是要拿水动力成果替掉 `qcap_batch.py` 那个偏乐观的代理量。
实测下来**替不得**。把两套 Qcap 在同一根管上拆开对照（n = 4,000）：

| 输入 | SWMM `.inp` | `sw_edge` 实测 | 判断 |
|---|---|---|---|
| 管径 | — | — | 完全一致，比值 1.000 |
| 糙率 | 0.013 统一值 | 0.010–0.013 按材质 | SWMM 略保守，可接受 |
| 坡度 | 中位 **0.01274** | 中位 **0.00247** | **差 5.2 倍** |

坡度差从哪来 —— 两个铁证：

* `DEM 地面高程 − SWMM 节点内底 = 1.10 m，标准差 0.00 m`（全样本恒定）；
* `SWMM 坡度 ↔ DEM 地形坡度` 相关系数 **+1.000**，中位数完全相等；
  同一批管上 `sw_edge 实测坡度 ↔ DEM 地形坡度` 只有 **+0.101**。

也就是说 SWMM 的管道内底 = **Copernicus GLO-30 地面高程减去固定埋深 1.10 m**，
管道坡度直接等于地形坡度。真实管道会调坡，和地形只有弱相关，所以这份模型
系统性地把管道做陡了 5 倍，满流能力随之高估 —— 同管对照中位 **2.4 倍**。
`.inp` 的 TITLE 注释自己也写了 "maximum depth ... are assumptions"，
`[JUNCTIONS]` 的 MaxDepth 全库统一 3.000 m，是同一套假设的另一半。

切过去的后果（25 年一遇 · T=2h · window 口径 · 501 点）：

| | 一道排完 | 峰值溢流 | 需车队 | 泵 | L1 排水时间中位 |
|---|---:|---:|---:|---:|---:|
| 现行（曼宁 + 实测内底） | 407 | 459 | 92 | 128 | 0.53 h |
| 本脚本（SWMM 反推） | 435 | 351 | 64 | 90 | 0.22 h |

**全面偏乐观**，410 个点里 353 个排水时间变短。所以这份成果不能用来定 L1。

**那它还有什么用**：① 本脚本是可复现的对照口径，做敏感性分析时一行开关切过去；
② 它给出的糙率 0.013 是建模方对同一批管的取值，可作为 `manning.py` 按
ADQCC Table 4-1 更新糙率（README 已知项 2）的旁证；③ 反过来读，这份模型在
**偏陡 5 倍的坡度**下跑 100 年一遇，仍然 94% 的雨水从检查井溢出、只有 0.5%
到排放口 —— 真实管网只会更差，这个定性结论是站得住的。
────────────────────────────────────────────────────────────────────────

⚠ 本脚本**不使用**该 run 的溢流、水深、退水时序。那部分输出受求解器发散污染
（99.99% 的时间步不收敛、路由连续性误差 −58.3%），且仿真只有 4 h 而绝大多数
节点到结束仍在溢流（历时中位 3.79 h / 满程 4.00 h），退水时刻整体右删失。
"""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
OUTPUT_CSV = BACKEND_DIR / "data" / "processed" / "hotspot_qcap_swmm.csv"

#: 默认取哪个 run。100 年一遇 —— 满流能力与重现期无关，选它只是因为
#: 这一档管段全程有流量的比例最高，反推路径覆盖最广。
DEFAULT_RUN_DIR = BACKEND_DIR / "data" / "2" / "abu-zone-b-ddf-180m-20260826-v2-rp100"

#: 与 `qcap_batch.SEARCH_RADIUS_M` 同值 —— 两套 Qcap 必须同口径才可比。
SEARCH_RADIUS_M = 250.0

#: 参与取值的干管等级，同 `qcap_batch.LOCAL_MAIN_CLASSES`。
LOCAL_MAIN_CLASSES = ("LATERAL", "SECONDARY")

#: `Max/Full Flow` 低于此值就不反推，改走曼宁。0.05 对应两位小数舍入
#: 带来的 ±5% 误差上限。
MIN_FLOW_RATIO = 0.05

#: sw_edge 中点 ↔ SWMM 管段中点的匹配容差（米）。实测 p90 = 0.03 m，
#: 放宽到 20 m 是为了容忍折线质心与两端直线中点的差。
MATCH_TOLERANCE_M = 20.0

#: 曼宁兜底时可信的坡度区间，同 `qcap_batch`。
SLOPE_MIN, SLOPE_MAX = 0.0001, 0.2

_NETWORK_SCHEMA = "dmt_irrigationstormwater_abudhabi_network"

#: 取积水点周边管段 —— 等级与到点距离都在库里算，Qcap 留给 SWMM。
#: 中点用 `st_lineinterpolatepoint` 沿线取 50%，`st_linemerge` 失败时退回质心。
SEGMENTS_SQL = f"""
select h.uid,
       e.gid,
       m.main_class,
       e.pipe_diameter as diameter_mm,
       st_distance(h.geom, e.geom) as distance_m,
       st_x(p.pt) as cx,
       st_y(p.pt) as cy
from hotspot.hotspots_845 h
join {_NETWORK_SCHEMA}.sw_edge e
  on st_dwithin(h.geom, e.geom, %(radius)s)
 and e.subassetname = 'SW Network'
 and e.status in ('Active', 'Existing')
left join {_NETWORK_SCHEMA}.sw_main_edge me on me.edge_gid = e.gid
left join {_NETWORK_SCHEMA}.sw_main m       on m.main_id  = me.main_id
cross join lateral (
  select case
           when st_geometrytype(st_linemerge(e.geom)) = 'ST_LineString'
             then st_lineinterpolatepoint(st_linemerge(e.geom), 0.5)
           else st_centroid(e.geom)
         end as pt
) p
"""


# ---------------------------------------------------------------------------
# SWMM 成果解析
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SwmmLink:
    """一根 SWMM 管段反推出来的满流能力。"""

    link_id: str
    cx: float
    cy: float
    diameter_m: float
    qfull_m3s: float
    #: back_calculated（Q_max ÷ 比值）/ manning_from_inp（比值太小时兜底）
    method: str
    max_full_flow: float


def _read_inp(path: Path) -> tuple[dict, dict, dict, dict]:
    """一趟读完 `.inp` 需要的四段：节点内底、节点坐标、管段、断面。"""
    inverts: dict[str, float] = {}
    coords: dict[str, tuple[float, float]] = {}
    conduits: dict[str, tuple[str, str, float, float, float, float]] = {}
    xsections: dict[str, tuple[str, float]] = {}
    section = None
    with path.open() as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("["):
                section = s.strip("[]").upper()
                continue
            if not s or s.startswith(";"):
                continue
            p = s.split()
            if section in ("JUNCTIONS", "OUTFALLS", "STORAGE") and len(p) >= 2:
                try:
                    inverts[p[0]] = float(p[1])
                except ValueError:
                    pass
            elif section == "COORDINATES" and len(p) == 3:
                coords[p[0]] = (float(p[1]), float(p[2]))
            elif section == "CONDUITS" and len(p) >= 7:
                # Name From To Length Roughness InOffset OutOffset
                conduits[p[0]] = (p[1], p[2], float(p[3]), float(p[4]),
                                  float(p[5]), float(p[6]))
            elif section == "XSECTIONS" and len(p) >= 3:
                xsections[p[0]] = (p[1].upper(), float(p[2]))
    return inverts, coords, conduits, xsections


def _read_link_flow(path: Path) -> dict[str, tuple[float, float]]:
    """`.rpt` 的 Link Flow Summary → {link_id: (Q_max, Max/Full Flow)}。

    报告有 100+ MB，只顺序扫到这一节结束就停。
    """
    out: dict[str, tuple[float, float]] = {}
    state = 0
    with path.open() as fh:
        for line in fh:
            t = line.strip()
            if state == 0:
                if t == "Link Flow Summary":
                    state = 1
                continue
            if state == 1:
                if t.startswith("---"):
                    state = 2
                continue
            if not t:
                continue
            if t.startswith("***") or t.startswith("Flow Classification"):
                break
            p = t.split()
            if len(p) == 8 and p[1] == "CONDUIT":
                out[p[0]] = (float(p[2]), float(p[6]))
    return out


def _manning_full_flow(
    link_id: str,
    conduits: dict,
    xsections: dict,
    inverts: dict,
) -> float | None:
    """用 `.inp` 自己的参数算圆管满流能力，给反推不可靠的管段兜底。"""
    if link_id not in conduits or link_id not in xsections:
        return None
    from_node, to_node, length, roughness, in_off, out_off = conduits[link_id]
    shape, geom1 = xsections[link_id]
    if shape != "CIRCULAR" or geom1 <= 0 or length <= 0 or roughness <= 0:
        return None
    if from_node not in inverts or to_node not in inverts:
        return None
    slope = ((inverts[from_node] + in_off) - (inverts[to_node] + out_off)) / length
    if not SLOPE_MIN <= slope <= SLOPE_MAX:
        return None
    area = math.pi * geom1 * geom1 / 4.0
    hyd_radius = geom1 / 4.0
    return area * hyd_radius ** (2.0 / 3.0) * math.sqrt(slope) / roughness


def load_links(run_dir: Path = DEFAULT_RUN_DIR) -> list[SwmmLink]:
    """解析一个 run，返回所有能定出满流能力的管段。"""
    inp = run_dir / "full_city" / "scenario.inp"
    rpts = sorted((run_dir / "full_city" / "native_swmm_results").glob("*.rpt"))
    if not inp.exists() or not rpts:
        raise FileNotFoundError(f"{run_dir} 里没有 scenario.inp 或 .rpt")

    inverts, coords, conduits, xsections = _read_inp(inp)
    flows = _read_link_flow(rpts[0])

    out: list[SwmmLink] = []
    for link_id, (qmax, ratio) in flows.items():
        if link_id not in conduits:
            continue
        from_node, to_node = conduits[link_id][0], conduits[link_id][1]
        if from_node not in coords or to_node not in coords:
            continue
        if ratio >= MIN_FLOW_RATIO and qmax > 0:
            qfull, method = qmax / ratio, "back_calculated"
        else:
            fallback = _manning_full_flow(link_id, conduits, xsections, inverts)
            if fallback is None:
                continue
            qfull, method = fallback, "manning_from_inp"
        out.append(
            SwmmLink(
                link_id=link_id,
                cx=(coords[from_node][0] + coords[to_node][0]) / 2.0,
                cy=(coords[from_node][1] + coords[to_node][1]) / 2.0,
                diameter_m=xsections.get(link_id, ("", 0.0))[1],
                qfull_m3s=qfull,
                method=method,
                max_full_flow=ratio,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 逐点归并
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HotspotQcapSwmm:
    """一个积水点从 SWMM 成果取到的管网能力与出处。"""

    uid: str
    #: 250 m 内的 sw_edge 条数（与 `hotspot_qcap.csv` 的 pipes_in_radius 同源）
    pipes_in_radius: int
    #: 其中匹配上 SWMM 管段的条数
    pipes_matched: int
    #: 匹配上且等级为 LATERAL/SECONDARY 的条数
    pipes_local_class: int
    #: **本列是给 registry 用的结果**：LATERAL/SECONDARY 最大满流能力（m³/s）
    qcap_m3s: float | None
    #: 对照口径，不参与计算 —— 不筛等级的最大值
    qcap_any_class_m3s: float | None
    qcap_source_link: str | None
    qcap_source_gid: int | None
    qcap_source_class: str | None
    qcap_source_diameter_m: float | None
    qcap_source_distance_m: float | None
    #: back_calculated / manning_from_inp
    qcap_source_method: str | None
    #: 取值管段的 Max/Full Flow，<1 表示这根管在该场次没跑满
    qcap_source_max_full_flow: float | None
    #: 半径内靠曼宁兜底（而非反推）的管段占比
    manning_fallback_share: float | None
    #: swmm / out_of_model / no_local_class / no_pipes
    basis: str


def _match(segments: list[dict], links: list[SwmmLink]) -> list[tuple[dict, SwmmLink]]:
    """把库里的 sw_edge 逐条匹配到最近的 SWMM 管段中点。"""
    import numpy as np

    if not segments or not links:
        return []
    lx = np.fromiter((l.cx for l in links), dtype=float, count=len(links))
    ly = np.fromiter((l.cy for l in links), dtype=float, count=len(links))
    pairs = []
    for seg in segments:
        if seg["cx"] is None:
            continue
        d2 = (lx - seg["cx"]) ** 2 + (ly - seg["cy"]) ** 2
        i = int(d2.argmin())
        if d2[i] <= MATCH_TOLERANCE_M ** 2:
            pairs.append((seg, links[i]))
    return pairs


def summarise(uid: str, pairs: list[tuple[dict, SwmmLink]], n_segments: int) -> HotspotQcapSwmm:
    """把一个点周边的匹配结果归并成一条结论。"""
    local = [p for p in pairs if p[0].get("main_class") in LOCAL_MAIN_CLASSES]

    def _pick(rows):
        return max(rows, key=lambda p: p[1].qfull_m3s) if rows else None

    best = _pick(local)
    any_class = _pick(pairs)

    if n_segments == 0:
        basis = "no_pipes"
    elif not pairs:
        basis = "out_of_model"
    elif best is None:
        basis = "no_local_class"
    else:
        basis = "swmm"

    fallback = [p for p in pairs if p[1].method == "manning_from_inp"]
    return HotspotQcapSwmm(
        uid=uid,
        pipes_in_radius=n_segments,
        pipes_matched=len(pairs),
        pipes_local_class=len(local),
        qcap_m3s=round(best[1].qfull_m3s, 4) if best else None,
        qcap_any_class_m3s=round(any_class[1].qfull_m3s, 4) if any_class else None,
        qcap_source_link=best[1].link_id if best else None,
        qcap_source_gid=best[0]["gid"] if best else None,
        qcap_source_class=best[0].get("main_class") if best else None,
        qcap_source_diameter_m=round(best[1].diameter_m, 3) if best else None,
        qcap_source_distance_m=round(best[0]["distance_m"], 1) if best else None,
        qcap_source_method=best[1].method if best else None,
        qcap_source_max_full_flow=best[1].max_full_flow if best else None,
        manning_fallback_share=round(len(fallback) / len(pairs), 3) if pairs else None,
        basis=basis,
    )


def compute_all(
    run_dir: Path = DEFAULT_RUN_DIR,
    radius_m: float = SEARCH_RADIUS_M,
) -> list[HotspotQcapSwmm]:
    """连库取周边管段 + 解析 SWMM 成果 + 逐点归并。"""
    from .db import query  # 延迟导入：没有数据库也能 import 本模块

    links = load_links(run_dir)
    by_uid: dict[str, list[dict]] = {}
    for row in query(SEGMENTS_SQL, {"radius": radius_m}):
        by_uid.setdefault(row["uid"], []).append(row)

    all_uids = {r["uid"] for r in query("select uid from hotspot.hotspots_845")}
    return [
        summarise(uid, _match(by_uid.get(uid, []), links), len(by_uid.get(uid, [])))
        for uid in sorted(all_uids)
    ]


def write_csv(results: list[HotspotQcapSwmm], path: Path = OUTPUT_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [f.name for f in fields(HotspotQcapSwmm)]
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
        print(f"   {basis:<18} {n:>4}")


if __name__ == "__main__":
    main()
