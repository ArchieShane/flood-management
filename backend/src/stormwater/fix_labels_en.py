"""一次性：把已抽取交付里的态标签 / 点名改成英文（`states.json` 的 label、`hotspots.json` 的 name）。幂等。

    PYTHONPATH=src python -m stormwater.fix_labels_en [data/processed/sim_deliveries]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .i18n import en_label

_FIELDS = {"states.json": ("label",), "hotspots.json": ("name",)}


def _fix(o, keys) -> int:
    n = 0
    if isinstance(o, dict):
        for k, v in o.items():
            if k in keys and isinstance(v, str) and en_label(v) != v:
                o[k], n = en_label(v), n + 1
            else:
                n += _fix(v, keys)
    elif isinstance(o, list):
        n = sum(_fix(v, keys) for v in o)
    return n


def main(root: Path) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    total = 0
    for fn, keys in _FIELDS.items():
        for p in sorted(root.glob(f"*/{fn}")):
            d = json.loads(p.read_text(encoding="utf-8"))
            n = _fix(d, keys)
            if n:
                p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                print(f"{p.parent.name}/{fn}：改 {n} 处")
                total += n
    print(f"共改 {total} 处")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "data" / "processed" / "sim_deliveries")
