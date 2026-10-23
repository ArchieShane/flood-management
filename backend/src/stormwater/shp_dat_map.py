"""shp+dat 导出目录 ↔ 仿真任务 id 对照表（只读，不写库、不改文件）。

服务器 `shp_dat/<主机>/<交付名>/<态>/{shp, dat, h2d_index.json}` 是从 `result/<主机>/<交付名>/<态目录>/二维/*.sww`
导出的。`h2d_index.json` 的 `source_sww` 记着出处，据此得到交付名与态；交付名再按
`sim_sww.output_key` 推出任务的成果目录键（`sim_deliveries/<键>`），与库里 `run.output_dir` 对上，得到任务 id。
没对上的再退回按（范围、雨深、历时、网格）唯一匹配；多个或没有就留空并写明原因，不挑一个顶替。

用法：
  cd backend && PYTHONPATH=src .venv/bin/python -m stormwater.shp_dat_map /media/pop-fs/flood_data/shp_dat --out 对照.csv
  服务器上库在 flood-aio 容器里、shp_dat 没挂进去：用 ../docker-shp-map.sh。
  加 --no-db 只出「shp+dat 目录 ↔ 交付 / 态 / 成果键」，不连库（run_id 留空）。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

FIELDS = ["run_id", "extent", "state", "delivery", "result_key", "depth_mm", "duration_h", "grid_m",
          "run_status", "match", "shp_dat_dir", "source_sww", "triangles_total", "triangles_in_shp",
          "frames", "max_depth_m", "note"]


def _read_index(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _locate(idx: dict, d: Path) -> tuple[str, str, str]:
    """(交付名, 态目录名, 主机)。优先取 source_sww（…/result/<主机>/<交付>/<态>/二维/x.sww），缺则取 shp_dat 的目录层级。"""
    sww = (idx.get("source_sww") or "").replace("\\", "/").split("/")
    if len(sww) >= 5:
        return sww[-4], sww[-3], sww[-5]
    return d.parent.name, d.name, d.parent.parent.name


def scan(root: Path) -> list[dict]:
    from .sim_c1 import extent_of
    from .sim_sww import output_key, parse_delivery_name

    rows = []
    for p in sorted(root.rglob("h2d_index.json")):
        if p.name.startswith("._"):
            continue
        d = p.parent
        row = {k: "" for k in FIELDS}
        row["shp_dat_dir"] = str(d)
        try:
            idx = _read_index(p)
            delivery, state_dir, _host = _locate(idx, d)
            region, depth, dur, grid = parse_delivery_name(delivery)
        except Exception as e:       # 目录名不是「片区_雨深mm历时h[_网格m]」形状等
            row["note"] = f"无法解析：{e}"
            rows.append(row)
            continue
        ts = idx.get("timesteps") or []
        row.update(
            extent=extent_of(Path(delivery)), state=state_dir, delivery=delivery,
            result_key=output_key(Path(delivery)), depth_mm=f"{depth:g}", duration_h=f"{dur:g}",
            grid_m="" if grid is None else f"{grid:g}", source_sww=idx.get("source_sww", ""),
            triangles_total=idx.get("triangles_total", ""), triangles_in_shp=idx.get("triangles_in_shp", ""),
            frames=len(ts), max_depth_m=(idx.get("depth_summary") or {}).get("max_depth_m", ""),
        )
        rows.append(row)
    return rows


def attach_runs(rows: list[dict]) -> None:
    from . import simulation as sim

    with sim.connect() as conn:
        runs = conn.execute(
            "select id, status, extent, depth_mm, duration_h, grid_m, output_dir from run "
            "where output_dir is not null order by id").fetchall()
    by_key: dict[str, list[dict]] = {}
    for r in runs:
        by_key.setdefault(Path(r["output_dir"]).name, []).append(r)
    for row in rows:
        if not row["result_key"]:
            continue
        hit, how = by_key.get(row["result_key"], []), "output_dir"
        if not hit:
            hit = [r for r in runs if r["extent"] == row["extent"]
                   and abs(float(r["depth_mm"] or -1) - float(row["depth_mm"])) < 1e-6
                   and abs(float(r["duration_h"] or -1) - float(row["duration_h"])) < 1e-6
                   and row["grid_m"] != "" and abs(float(r["grid_m"] or -1) - float(row["grid_m"])) < 1e-6]
            how = "extent+rain+grid"
        if len(hit) == 1:
            row.update(run_id=hit[0]["id"], run_status=hit[0]["status"], match=how)
        elif hit:
            ids = "/".join(str(r["id"]) for r in hit)
            row.update(match="ambiguous", note=f"多个任务同口径：{ids}，未挑选")
        else:
            row.update(match="none", note="库里没有对应任务（未登记，或登记时网格 / 范围与目录名不同）")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", type=Path, help="shp_dat 根目录（含 <主机>/<交付名>/<态>/h2d_index.json）")
    ap.add_argument("--out", type=Path, help="写 CSV（utf-8-sig，Excel 可直接开）；不给只打印")
    ap.add_argument("--show-root", help="CSV 里 shp_dat_dir 列显示的根路径（目录是拷进容器的副本时，写服务器上的真实路径）")
    ap.add_argument("--no-db", action="store_true", help="不连库，只出目录 ↔ 交付 / 态 / 成果键")
    a = ap.parse_args()
    rows = scan(a.root)
    if a.show_root:
        for r in rows:
            r["shp_dat_dir"] = a.show_root.rstrip("/") + "/" + Path(r["shp_dat_dir"]).relative_to(a.root).as_posix()
    if not rows:
        sys.exit(f"{a.root} 下没找到 h2d_index.json")
    if not a.no_db:
        attach_runs(rows)
    rows.sort(key=lambda r: (str(r["extent"]), str(r["state"])))
    for r in rows:
        print(f"run_id={r['run_id'] or '-':>4}  {r['extent'] or '?':<14} {r['state']:<22} {r['match'] or '-':<17} {r['shp_dat_dir']}"
              + (f"  [{r['note']}]" if r["note"] else ""))
    if a.out:
        with a.out.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"→ {a.out}（{len(rows)} 行）")


if __name__ == "__main__":
    main()
