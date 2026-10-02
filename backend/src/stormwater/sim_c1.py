"""把「C1 热点群」四态一二维交付抽成仿真系统认的交付形状，再登记成一个多态仿真任务。

交付是 `data/temp260929/C1_61mm2h/`（2026-09-29，算力侧「C1 热点群 · 61 mm / 2 h」，在线报告
https://claude.ai/artifact/NZKLeppNDkvRx593PSjrYJ ）：

    C1_61mm2h/
        readme.md  计算设置.md                          四态口径与全部输入参数、局限
        L1_现状管网+现状泵站/一二维/L1_二维水深帧与最大水深.npz   875,510 个三角单元：xy / area / elev / hmax /
                                                       frames(72) / uh / vh / t_h / rain_mask
        L1_…/一二维/L1_耦合运行记录.json                逐 5 min 水量、1D↔2D 交换累计、直接落地的雨
        L1_…/一二维/耦合的一维/*.rpt|inp                与二维同进程耦合的 SWMM（9,211 个节点）
        L1_…/设施.csv  摘要.md                          这一态包含的设施（WGS84）与指标
        L2_加OP-02移动泵/  L2+planned_Parsons方案/  L2+suggested_转输与地面取水泵/   同 L1 的结构
        统计值/C1统计值.xlsx                            各热点与全域的积水统计（每项带口径）

npz 与全市（`sim_city.py`）同一个格式，所以抽取走同一套：非结构三角网 → 按面积平均到规则格，最大水深 / 积水面积按三角
单元统计，地表**直接受雨**（二维直接降雨 659,883 m³），二维从 0 h 起算、帧 t = 5 … 360 min。和全市不同的地方：

- 计算域只有 42.8 km²（8 个热点汇水区外扩 300 m），落图格网取 **15 m**（= 模型标称网格，格内约 4–5 个三角单元），
  不是 250 m。
- npz 带 `uh / vh`（单宽流量），格内最大流速照 `sim_sww` 的口径（Σ动量×面积 / Σ水深×面积）写进最大水深图层的
  `maximum_speed_m_s`，`sim_ponding` 不再亮 `no_speed`。
- 四态都是**真算**的（没有 ≡ L1 的硬链，`same_as` 为空）：
  L1 现状管网 + 6 座现状泵站 → L2 加 OP-02 的 23 台移动泵 → L2+planned Parsons 方案（27 座固定泵站 + 12 座 1 m 围堤塘）
  → L2+suggested 在 L2+planned 上加转输 / 地面取水泵。
  L2+planned 用固定泵站取代了同址的 22 台移动泵（只留 MP-16），所以它的 `parent` 是 L1 不是 L2；
  「新增调蓄」（储水设施落图 / 效果分析）都按这个父态比。
- 没有 `五态统计值.csv` 那样的逐态对账表，不写 `analysis/state_stats.csv`（`sim_perf` 缺了不报错，只是没有
  「系统储水能力」一行的交付原值）。
- 耦合 SWMM 的 .rpt / .inp 各四十 / 十七 MB，硬链到输出目录（同卷零拷贝），不另拷。

任务记最高一道（第二道规划），操作人按用户要求记 AR（`simulation.PROTECTED_OPERATORS`，不能删）。

用法：

    PYTHONPATH=src .venv/bin/python -m stormwater.sim_c1 import data/temp260929/C1_61mm2h --by AR
    PYTHONPATH=src .venv/bin/python -m stormwater.sim_c1 extract data/temp260929/C1_61mm2h   # 只抽不登记
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from .sim_city import _extract_grid, _link, _overflow_series
from .sim_sww import (DATA_ROOT, DELIVERY_WET_M, OUT_ROOT, WET_M, SwwError, _cell_polys, _dump, _node_coords,
                      _one, _outfalls, _parse_name)

SCHEMA = "flood_management.c1_state_delivery.v1"
CELL_M = 15.0             # 落图格网 = 模型标称网格
MODEL_RES_M = 15.0
REPORT_URL = "https://claude.ai/artifact/NZKLeppNDkvRx593PSjrYJ"
EXTENT = "C1"

#: 态 → (子目录前缀, 防线, 中文名)；中文名改了要同步 i18n.EN
STATES = {
    "L1": ("L1_", "line1", "现状管网 + 现状泵站"),
    "L2": ("L2_", "line2_current", "加 OP-02 移动泵"),
    "L2+planned": ("L2+planned", "line2_planned", "Parsons 方案"),
    "L2+suggested": ("L2+suggested", "line2_planned", "转输与地面取水泵"),
}
COLUMNS = {"L1": "line1", "L2": "line2_current", "L2+planned": "line2_planned",
           "L2+suggested": "line2_suggested"}
PARENT = {"L1": None, "L2": "L1", "L2+planned": "L1", "L2+suggested": "L2+planned"}

#: 每态一句话口径（进 claim_boundary）
_NOTE = {
    "L1": "客户 GDB 重建的现状管网 + 6 座现状泵站",
    "L2": "L1 + Parsons OP-02 的 23 台 12 英寸移动泵（雨前布设，排到下游不溢流的井）",
    "L2+planned": "L1 + Parsons PDF 版方案：27 座固定泵站（只开主用）+ 12 座 1 m 围堤塘（443,274 m³），保留 MP-16",
    "L2+suggested": "L2+planned + 按 L2+planned 残余积水设计的转输 / 地面取水泵（挡水土堤方案已弃用）",
}


def state_label(state: str) -> str:
    return f"{state} {STATES[state][2]}"


def _state_dir(root: Path, state: str) -> Path | None:
    hits = [p for p in root.iterdir() if p.is_dir() and p.name.startswith(STATES[state][0])]
    return hits[0] if len(hits) == 1 else None


def extract_state(root: Path, state: str, out: Path) -> dict[str, Any]:
    region, depth_mm, dur_h = _parse_name(root)
    sd = _state_dir(root, state)
    if sd is None:
        raise SwwError(f"{root} 下没有 {state} 的目录")
    d2 = sd / "一二维"
    npz = _one(d2, "*_二维水深帧与最大水深.npz")
    rec = json.loads(_one(d2, "*_耦合运行记录.json").read_text(encoding="utf-8"))
    rpt = _one(d2 / "耦合的一维", "*.rpt")
    inp = _one(d2 / "耦合的一维", "*.inp")

    g = _extract_grid(npz, CELL_M)
    out.mkdir(parents=True, exist_ok=True)
    (out / "temporal_snapshots").mkdir(exist_ok=True)
    nc, cs = g["nc"], g["cs"]
    cell_a = cs * cs

    ids = np.where(g["maxd"] >= WET_M)[0]
    feats = []
    for cid, ring in zip(ids.tolist(), _cell_polys(g, ids)):
        props = {
            "cell_id": cid,
            "depth_m": round(float(g["maxd"][cid]), 4),
            "maximum_depth_m": round(float(g["maxd"][cid]), 4),
            "maximum_depth_time_minutes": round(float(g["peak_min"][cid]), 2),
            "final_depth_m": round(float(g["final"][cid]), 4),
            "model_cell_size_m": cs,
        }
        if g["maxsp"] is not None:
            props["maximum_speed_m_s"] = round(float(g["maxsp"][cid]), 3)
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": props})
    _dump(out / "maximum_depth_wgs84.geojson",
          {"type": "FeatureCollection", "name": f"{region}_{state}_maximum_depth", "features": feats})

    snaps = []
    for i, (ts, d) in enumerate(g["frames"]):
        w = np.where(d >= WET_M)[0]
        name = f"temporal_snapshots/surface_depth_t{i:03d}.geojson"
        _dump(out / name, {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": None,
                          "properties": {"cell_id": int(c), "depth_m": round(float(d[c]), 4)}} for c in w],
            "metadata": {"time_index": i, "time_seconds": ts, "time_minutes": ts / 60},
        })
        snaps.append({"index": i, "time_seconds": ts, "time_minutes": ts / 60, "path": name,
                      "feature_count": int(len(w))})
    _dump(out / "temporal_snapshots" / "manifest.json", {"schema": SCHEMA, "snapshots": snaps})
    _dump(out / "surface_series.json", {
        "schema": SCHEMA, "wet_threshold_m": DELIVERY_WET_M,
        "note": "逐 5 min 帧、按三角单元（npz）：wet_area_m2 = 水深 ≥ 阈值的单元面积之和，max_depth_m = 该帧单元最大水深，"
                "volume_m3 = Σ 水深 × 单元面积；time_minutes 从降雨起算。地表直接受雨，面积含雨水膜",
        **g["series"],
        "overflow": _overflow_series(rec),
    })

    has = g["has"].reshape(g["nr"], nc)
    np.savez_compressed(
        out / "terrain_grid.npz",
        values=np.nan_to_num(g["dem"], nan=0.0).reshape(g["nr"], nc),
        transform=np.array([cs, 0.0, g["x0"], 0.0, -cs, g["ytop"]]),
        land_mask=has, permanent_water_mask=np.zeros_like(has), source=np.array("sww"),
    )

    coords = _node_coords(inp)
    binds = []
    for k, (nid, (xx, yy)) in enumerate(coords.items()):
        c = int(np.floor((xx - g["x0"]) / cs))
        r = int(np.floor((g["ytop"] - yy) / cs))
        if 0 <= r < g["nr"] and 0 <= c < nc:
            binds.append(f'{{"swmm_node_id": {json.dumps(nid)}, "swmm_node_index": {k}, "anuga_cell_index": {r * nc + c}}}')
    (out / "node_cell_binding.json").write_text(
        '{"schema": "' + SCHEMA + '", "note": "节点坐标取耦合 SWMM 的 [COORDINATES]，落到 15 m 格", "bindings": [\n'
        + ",\n".join(binds) + "\n]}\n", encoding="utf-8")
    _link(rpt, out / "swmm_coupled.rpt")
    _link(inp, out / "coupled_scenario.inp")

    outf = _outfalls(inp)
    _dump(out / "scenario.json", {
        "scope": "hotspot_cluster",
        # 有管网覆盖的地面按客户汇水区 CN 82 / Tc 30 min 产流注入一维；离井 > 46 m 的地面净雨直接下在二维上
        "spatial_pattern": "Client catchments + direct rain on 2D",
        "rainfall_profile": {"profile_id": f"R{depth_mm:g}D{dur_h:g}",
                             "provenance": {"temporal_assumption": "client 2 h design storm"}},
        "outfall_mode": "free",
        "outfall_level_m": None,
        "outfalls": [{"name": o[0], "type": o[1], "stage_m": o[2]} for o in outf],
        "start_time": None,
    })

    acc = rec.get("acc_m3") or {}
    summary = {
        "schema": SCHEMA,
        "run_id": f"{root.name}/{state}",
        "scenario_label": f"{region} · {depth_mm:g} mm / {dur_h:g} h · {state_label(state)}",
        "state": state,
        "status": "completed",
        "solver": "ANUGA 2D + SWMM 5.2",
        "claim_boundary": (
            f"{state_label(state)}：{_NOTE[state]}。SWMM 与 ANUGA 双向耦合（{rec.get('dt_c', 60):g} s 交换），"
            f"非结构三角网 {g['n_tri']:,} 个单元（模型网格 15 m）、5 m DTM 原值，计算域 42.8 km²（8 个热点汇水区外扩 300 m、"
            f"自由出流），演算 0 → {g['end_min'] / 60:g} h；离井 > 46 m 的地面直接受雨（CN 82）。"
            "糙率全域未分下垫面；交付方未标定、未经工程认可。ADM-90 的地表汇水区碰到窗口边未收敛、计算域外的来水算不进，"
            "计算域外的管网只算一维、冒出的水记为损失；地道线性调蓄未建。"
            "页面格网是三角单元按面积平均到 15 m，最大水深 / 积水面积按三角单元统计。"
        ),
        "source": {"delivery": str(root.relative_to(DATA_ROOT)) if DATA_ROOT in root.parents else str(root),
                   "state_dir": sd.name, "native_npz": npz.name, "coupling_record": rec.get("tag"),
                   "report_url": REPORT_URL},
        "domain": {
            "bounds_epsg32640": g["bounds"],
            "area_m2": round(g["domain_m2"], 1),
            "cell_size_m": cs,
            "rectangular_cells": g["nr"] * nc,
            "active_land_cells": int(g["has"].sum()),
            "triangle_count": g["n_tri"],
            "coupling_start_minutes": 0.0,
            "simulation_duration_minutes": g["end_min"],
            "simulation_duration_hours": g["end_min"] / 60,
            "output_step_minutes": 5.0,
        },
        "results": {
            "maximum_depth_m": round(g["tri_hmax"], 4),
            "maximum_depth_xy_epsg32640": g["tri_hmax_xy"],
            "peak_inundated_area_m2": round(g["tri_wet_max_m2"], 1),
            "peak_inundated_area_minutes": g["tri_wet_max_min"],
            "peak_inundated_threshold_m": DELIVERY_WET_M,
            "maximum_depth_cell_m": round(float(g["maxd"].max()), 4),
            "maximum_depth_triangle_m": round(g["tri_hmax"], 4),
            "inundated_cells_ge_0_01m": int(len(ids)),
            "inundated_area_ge_0_01m2": float(len(ids) * cell_a),
            "inundated_area_ge_0_05m2": float((g["maxd"] >= 0.05).sum() * cell_a),
            "final_inundated_cell_count_ge_0_01m": int((g["final"] >= WET_M).sum()),
            "final_inundated_area_ge_0_01m2": float((g["final"] >= WET_M).sum() * cell_a),
            # 交付口径（三角单元），只为与耦合记录 / 统计值对账，页面卡片不用
            "delivery_ever_wet_area_ge_0_02m2": round(g["tri_ever"][0.02], 1),
            "delivery_max_area_ge_0_10m2": round(g["tri_ever"][0.10], 1),
            "delivery_max_area_ge_0_30m2": round(g["tri_ever"][0.30], 1),
            "delivery_max_area_ge_0_80m2": round(g["tri_ever"][0.80], 1),
            "delivery_wet_record_max_m2": rec.get("max_wet_m2"),
            "peak_surface_volume_m3": g["tri_vol_max_m3"],
            "final_surface_volume_m3": g["tri_vol_end_m3"],
            "minimum_published_depth_m": WET_M,
        },
        "coupling": {
            "coupling_mode": "bidirectional",
            "coupled_node_count": rec.get("n_nodes"),
            "exchange_step_seconds": rec.get("dt_c"),
            "total_swmm_to_anuga_m3": acc.get("1to2"),
            "total_anuga_to_swmm_m3": acc.get("2to1"),
            "boundary_outflow_m3": rec.get("boundary_out_m3"),
        },
        "model_configuration": {
            "coupling_mode": "bidirectional",
            "return_period_years": None,
            "rainfall_total_mm": depth_mm,
            "rainfall_duration_minutes": dur_h * 60,
            "exchange_quantity": "node overflow to surface and surface return to node (bidirectional)",
            "dynamic_head_feedback": True,
            "simulation_duration_minutes": g["end_min"],
            "output_interval_minutes": 5.0,
            "model_cell_size_m": MODEL_RES_M,
            "terrain_product": "customer 5 m DTM (raw), unstructured mesh (mean 49 m²)",
            # 直接落在二维地面的净雨（耦合记录 acc_m3.rain）：> 0，sim_ponding 不亮 no_surface_rain
            "surface_rainfall_inflow_m3": acc.get("rain"),
            "surface_rain_cell_fraction": g["rain_mask_fraction"],
        },
        "outputs": {
            "maximum_depth": "maximum_depth_wgs84.geojson",
            "timeline_manifest": "temporal_snapshots/manifest.json",
            "swmm_report": "swmm_coupled.rpt",
            "swmm_input": "coupled_scenario.inp",
            "coupling_receipt": "node_cell_binding.json",
            "surface_series": "surface_series.json",
        },
    }
    _dump(out / "delivery_summary.json", summary)
    print(f"  {state}：{len(ids):,} 格 ≥ {WET_M} m｜最大水深 {g['tri_hmax']:.2f} m｜"
          f"同刻 ≥ 0.02 m 最大 {g['tri_wet_max_m2'] / 1e4:,.0f} ha @ {g['tri_wet_max_min']:g} min"
          f"（记录 {(rec.get('max_wet_m2') or 0) / 1e4:,.0f} ha）｜≥0.30 m 全程 {g['tri_ever'][0.30] / 1e4:,.2f} ha")
    return summary


#: 统计值表里「口径」列 → 协议 key；指标名 → 协议 key
_SCOPES = {"热点汇水区": "catchment", "热点 200 m": "near_200m",
           "热点汇水区（并集）": "catchment"}
_METRICS = {"最大水深 m": "max_depth_m", "积水面积 ≥0.10 m（ha）": "area_ge_0_10_ha",
            "积水面积 ≥0.30 m（ha）": "area_ge_0_30_ha", "最大积水量 m³": "max_volume_m3",
            "最大积水量出现时刻 h": "max_volume_h"}
_TOTAL_ROW = "C1 八个热点"
#: 「全域」行的口径 → 协议 key（管网服务区 / 直接降雨区 / 全域）
_ZONES = {"管网服务区": "network_zone", "直接降雨区": "direct_rain_zone", "全域": "domain"}


def _round_coords(c: Any) -> Any:
    return [round(c[0], 5), round(c[1], 5)] if c and isinstance(c[0], (int, float)) else [_round_coords(x) for x in c]


def extract_hotspots(root: Path, base: Path, states: list[str]) -> Path | None:
    """交付的 8 个热点（页面叫「积水点」）：坐标取台账 `hotspots_845.csv`（uid 补零，按数字对上统计值表的区域名），
    汇水区面取 `公共/8个热点的地表与管网汇水区.geojson`，逐态数取 `统计值/C1统计值.xlsx` 的「热点汇水区」/「热点 200 m」
    两个口径（水量对账等全域行不在这里）。交付缺任何一样就不写、返回 None。"""
    import openpyxl

    xlsx = root / "统计值" / "C1统计值.xlsx"
    geo = root / "公共" / "8个热点的地表与管网汇水区.geojson"
    ledger = DATA_ROOT / "processed" / "hotspots_845.csv"
    if not (xlsx.is_file() and geo.is_file() and ledger.is_file()):
        return None
    ws = openpyxl.load_workbook(xlsx, data_only=True)["统计值"]
    hdr = [c for c in next(ws.iter_rows(values_only=True))]
    cols = {st: hdr.index(st) for st in states if st in hdr}
    stats: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        area, scope, metric = r[0], r[1], r[2]
        key = _ZONES.get(scope) if area == "全域" else _SCOPES.get(scope)
        if key is None or metric not in _METRICS:
            continue
        for st, i in cols.items():
            if r[i] in (None, ""):
                continue
            stats.setdefault(area, {}).setdefault(st, {}).setdefault(key, {})[_METRICS[metric]] = float(r[i])
    with ledger.open(encoding="utf-8-sig", newline="") as f:
        # 台账 uid 补零（ADM-021），统计值表不补（ADM-21），按数字对
        led = {f'ADM-{int(r["uid"].split("-")[1])}': r for r in csv.DictReader(f) if r["uid"].startswith("ADM-")}
    fc = json.loads(geo.read_text(encoding="utf-8"))
    cat: dict[str, dict[str, Any]] = {}
    feats = []
    for ft in fc["features"]:
        pr = ft["properties"]
        cat.setdefault(pr["hotspot_id"], {})["surface" if pr["kind"] == "地表" else "network"] = pr["area_ha"]
        if pr.get("unconverged"):
            cat[pr["hotspot_id"]]["unconverged"] = True
        feats.append({"type": "Feature", "properties": {"hotspot_id": pr["hotspot_id"],
                                                        "kind": "surface" if pr["kind"] == "地表" else "network",
                                                        "area_ha": pr["area_ha"]},
                      "geometry": {"type": ft["geometry"]["type"],
                                   "coordinates": _round_coords(ft["geometry"]["coordinates"])}})
    ids = sorted((h for h in stats if h in led), key=lambda x: int(x.split("-")[1]))
    points = [{
        "id": h, "district": led[h]["area"], "location": led[h]["location"],
        "lat": round(float(led[h]["lat"]), 6), "lon": round(float(led[h]["lon"]), 6),
        "catchment_ha": cat.get(h, {}), "stats": stats[h],
    } for h in ids]
    out = base / "hotspots.json"
    _dump(out, {"schema": SCHEMA, "note": "交付的 8 个热点（积水点）：逐态数取自 C1统计值.xlsx",
                "states": list(cols), "points": points, "total": stats.get(_TOTAL_ROW, {}), "zones": stats.get("全域", {}),
                "catchments": {"type": "FeatureCollection", "features": feats}})
    print(f"  积水点 {len(points)} 个 → {out.name}")
    return out


# 交付旁边的 planned/ sugg/ 目录（与 C1_61mm2h 同级）：各态的设施 GIS（GeoJSON 已是 WGS84）
FACILITY_DIRS = {"L2+planned": "planned", "L2+suggested": "sugg"}
FACILITY_LAYERS = {"ponds": "蓄水池_规划塘", "pumps": "泵站与泵点", "outlets": "排水去向", "intake": "地面取水片"}


def extract_facilities(root: Path, base: Path) -> None:
    """把 `<root>/../planned|sugg/设施GIS/*.geojson` 收成各态的 facilities.json（落图用，`/layers/facilities`）。"""
    for st, sub in FACILITY_DIRS.items():
        src = root.parent / sub / "设施GIS"
        if not src.is_dir():
            continue
        layers = {}
        for key, stem in FACILITY_LAYERS.items():
            f = src / f"{stem}.geojson"
            if f.is_file():
                layers[key] = json.loads(f.read_text(encoding="utf-8"))
        out = base / st.replace("+", "_") / "facilities.json"
        _dump(out, {"state": st, "layers": layers})
        print(f"  设施 GIS {st}: " + " / ".join(f"{k} {len(v['features'])}" for k, v in layers.items()))


def extract(root: Path, only: list[str] | None = None) -> Path:
    root = root.resolve()
    base = OUT_ROOT / root.name
    for state in STATES:
        if only and state not in only:
            continue
        if _state_dir(root, state) is None:
            continue
        extract_state(root, state, base / state.replace("+", "_"))
    present = [st for st in STATES if (base / st.replace("+", "_") / "delivery_summary.json").is_file()]
    extract_facilities(root, base)
    extract_hotspots(root, base, present)
    _dump(base / "states.json", {
        "schema": "flood_management.sww_states.v1",
        "delivery": root.name,
        "default": "L1" if "L1" in present else present[0],
        "states": [{"key": st, "label": state_label(st), "defence_line_key": STATES[st][1],
                    "column": COLUMNS[st], "dir": st.replace("+", "_"),
                    "parent": PARENT[st] if PARENT[st] in present else None,
                    "same_as": None} for st in present],
    })
    hp = base / "hotspots.json"
    if hp.is_file():        # 口径切换要按态（要 states.json、各态的 .inp / .rpt / 溢水点）拆指标，所以放在最后
        from . import sim_scope

        hot = json.loads(hp.read_text(encoding="utf-8"))
        hot["scopes"] = sim_scope.compute(root, base, hot)
        _dump(hp, hot)
        print(f"  口径 {len(hot['scopes'])} 个 → hotspots.json")
    return base


def import_all(root: Path, by: str | None = None, only: list[str] | None = None) -> int:
    from . import sim_results
    from . import simulation as sim

    base = extract(root, only)
    keys = [s["key"] for s in json.loads((base / "states.json").read_text(encoding="utf-8"))["states"]]
    top = max((STATES[k][1] for k in keys), key=sim.LINE_ORDER.index)
    with sim.connect() as conn:
        return sim_results.import_delivery(conn, base, by, line_key=top, extent=EXTENT,
                                           variant_label=f"{len(keys)} 态：{' / '.join(keys)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, hlp in (("extract", "只从 npz 抽出交付形状"), ("import", "抽取并登记为仿真任务")):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("path", type=Path)
        p.add_argument("--state", action="append", choices=list(STATES), help="只处理这几态（可重复）")
        if name == "import":
            p.add_argument("--by", help="操作人缩写，如 AR")
    args = ap.parse_args()
    if args.cmd == "extract":
        extract(args.path, args.state)
        return
    print(f"已登记为仿真 #{import_all(args.path, args.by, args.state)}")


if __name__ == "__main__":
    main()
