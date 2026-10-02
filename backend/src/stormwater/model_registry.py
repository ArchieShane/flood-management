"""模型识别片区的只读台账 —— 与 `registry.py` 并列的第二套 `HotspotRecord`。

`registry.load_registry()` 出的是 845 个**历史上报**的台账点；本模块出的是 107 个
**二维演算识别**出来的易积水片区，装配成**同一个 `HotspotRecord` 类型**，
于是 `build_hotspot()` / `run_batch()` / `evaluate_all()` 以及
`/api/scenario`、`/api/point-curve` 一个字都不用改就能算它们。

## 为什么能装配成同一种记录

计算链要的五个输入，107 个片区现在**全部有实测/实算来源**（见
`model_cluster_batch.py`，跑的是台账那一路一模一样的四个批算）：

| 输入 | 来源 | 与台账 845 点的差别 |
|---|---|---|
| 汇水面积 A | 20 m DTM 上 D8 汇流**实算**边界 ∩ UDM 地物 | 台账是 Voronoi 几何代理 |
| 径流系数 C | UDM 地物图层面积加权（ADQCC Table 3-8） | **完全相同** |
| 集流时间 tc | 坡面流 + 管内流行（同一套公式） | **完全相同** |
| 管网能力 Qcap | `sw_edge` 实测内底反算（`qcap_batch`） | **完全相同** |
| 可用调蓄 | 250 m 内 pond/soakaway/reservoir（`storage_batch`） | **完全相同** |

即：**五项里四项与台账逐字段同法**，只有汇水区边界不同 —— 而那一项模型片区
反而更实在（台账点只是一个坐标，没有地形可依，只能等分；片区来自一次二维演算，
地形就在手上）。故两套记录的三道防线结论可以并排看，差别归因是清楚的。

## 两件必须说清楚的事

1. **A 的边界口径不同，不要直接比大小。** 逐点自述在 `catchment_boundary`：
   台账是 `voronoi_250m`，片区是 `d8_depression`（或无宿主洼地时 `cluster_only`）。
   片区那一路另带 `area_voronoi_ha` —— 同一批点按台账方法算一遍的对照值。
   实测下来 D8 合计 363 ha、Voronoi 代理合计 859 ha，代理高估 2.4 倍。

2. **片区有一个台账点拿不到的量：实算积水量。** `ponding_*` 那一组字段对 107 个
   片区**全覆盖**（台账 845 点里只有 18 个有），且口径更硬 —— 台账点的水量是把
   洼地的水按「最近点」切过去的代理，片区本身就是积水范围，水量是对它自己那些格
   逐帧求和，不经任何归属代理。页面拿它和推理公式法算出的来水量并列对照。
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache

from .model_cluster_batch import (
    OUT_CATCHMENT,
    OUT_DISTRICT,
    OUT_PONDING,
    OUT_QCAP,
    OUT_STORAGE,
    PROCESSED_DIR,
    uid_of,
)
from .model_ponding import RUN_META, load_features
from .registry import (
    HotspotRecord,
    _read_catchment,
    _read_district,
    _read_ponding,
    _read_qcap,
    _read_storage,
    sample_elevations,
    zone_for_elevation,
)

OUT_CATCHMENT_VORONOI = PROCESSED_DIR / "model_cluster_catchment_voronoi.csv"

#: 片区记录的 `source`。与台账的 ADM / AAM / DRM 并列，一眼看得出不是上报来的。
SOURCE = "MDL"

#: 片区记录的市政区。这一个 run 整个落在阿布扎比市（ADM），逐点片区归属
#: 仍由 `district_batch` 按社区面几何判（104 个 AL BATEEN，另有 3 个落在邻区）。
MUNICIPALITY = "Abu Dhabi"

#: D8 汇流范围的出处 → `catchment_boundary` 取值。见 `model_cluster_batch.ClusterCatchment`。
_BOUNDARY = {"d8_depression": "d8_depression", "cluster_only": "cluster_only"}


def _d8_basis() -> dict[str, str]:
    """读 `model_cluster_d8.csv` 的 `basis` 列 —— 汇水区边界是实算还是退化。"""
    import csv

    path = PROCESSED_DIR / "model_cluster_d8.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return {r["uid"]: _BOUNDARY.get(r["basis"], r["basis"]) for r in csv.DictReader(fh)}


def _voronoi_areas() -> dict[str, float]:
    """对照口径：同一批片区按台账那套 Voronoi 代理算出来的汇水面积。"""
    import csv

    if not OUT_CATCHMENT_VORONOI.exists():
        return {}
    with OUT_CATCHMENT_VORONOI.open(encoding="utf-8-sig", newline="") as fh:
        return {
            r["uid"]: float(r["area_ha"])
            for r in csv.DictReader(fh)
            if (r.get("area_ha") or "").strip()
        }


def _base_record(props: dict) -> HotspotRecord:
    """片区的 GeoJSON 属性 → 一条「还没合并批算」的记录。

    ⚠ 台账特有的那几列（严重度、成因、已配泵车、预算、干预计划）片区**一律留空**：
    那是行政记录，演算成果里没有对应物，填个数进去就是编的。页面因此在片区这一路
    不显示「与台账对照」那一栏 —— 没有台账可对。
    """
    rank = int(props["rank"])
    return HotspotRecord(
        uid=uid_of(rank),
        source=SOURCE,
        municipality=MUNICIPALITY,
        area=RUN_META["district"],
        # 位置只给一个稳定标识：片区没有门牌，硬编一句中文描述会绕过 i18n
        location=f"{RUN_META['district']} #{rank}",
        lat=float(props["lat"]),
        lon=float(props["lon"]),
        criticality=None,
        network_available=None,
        root_cause=None,
        intervention_type=None,
        intervention_status=None,
        pumps_qty=None,
        pump_12in_qty=None,
        pump_8in_qty=None,
        pump_6in_qty=None,
        tankers_qty=None,
        budget_required_aed=None,
        coord_precision_m=float(RUN_META["grid_m"]),  # 代表点落在 20 m 格心
        qc_flags=(),
        cluster_rank=rank,
        mechanism_key=props.get("mechanism_key"),
    )


@lru_cache(maxsize=1)
def load_model_registry() -> tuple[HotspotRecord, ...]:
    """读片区成果 + 合并四路批算，出一批与台账同构的记录。

    与 `registry.load_registry()` 同一套路，各份输入互相独立：批算缺哪一份，
    对应字段退回 None / "unknown"，`build_hotspot()` 会按剖面假设兜底 ——
    只是那样就失去了「五项里四项实测」这个前提，故 `main()` 会把覆盖率打出来。
    """
    features = load_features()
    if not features:
        return ()
    records = [_base_record(f["properties"]) for f in features]
    elevations = sample_elevations(records)
    qcap = _read_qcap(OUT_QCAP)
    storage = _read_storage(OUT_STORAGE)
    catchment = _read_catchment(OUT_CATCHMENT)
    district = _read_district(OUT_DISTRICT)
    ponding = _read_ponding(OUT_PONDING)
    boundary = _d8_basis()
    voronoi = _voronoi_areas()
    return tuple(
        replace(
            r,
            elevation_m=e,
            idf_zone=zone_for_elevation(e),
            catchment_boundary=boundary.get(r.uid),
            area_voronoi_ha=voronoi.get(r.uid),
            **qcap.get(r.uid, {}),
            **storage.get(r.uid, {}),
            **catchment.get(r.uid, {}),
            **district.get(r.uid, {}),
            **ponding.get(r.uid, {}),
        )
        for r, e in zip(records, elevations)
    )


def main() -> None:
    records = load_model_registry()
    if not records:
        raise SystemExit("没有片区成果 —— 先跑 model_cluster_batch.py")
    tally: dict[str, dict[str, int]] = {}
    for attr in ("qcap_basis", "storage_basis", "catchment_basis",
                 "catchment_boundary", "district_basis", "ponding_basis"):
        t: dict[str, int] = {}
        for r in records:
            k = str(getattr(r, attr))
            t[k] = t.get(k, 0) + 1
        tally[attr] = t
    print(f"模型识别片区 {len(records)} 条")
    for attr, t in tally.items():
        print(f"  {attr:20s} " + " · ".join(f"{k} {v}" for k, v in sorted(t.items())))
    areas = sorted(r.area_measured_ha for r in records if r.area_measured_ha)
    vor = sorted(r.area_voronoi_ha for r in records if r.area_voronoi_ha)
    print(f"  A(D8)      合计 {sum(areas):.1f} ha · 中位 {areas[len(areas) // 2]:.2f}")
    print(f"  A(Voronoi) 合计 {sum(vor):.1f} ha · 中位 {vor[len(vor) // 2]:.2f}")
    net = [r.ponding_net_inflow_m3 for r in records if r.ponding_net_inflow_m3]
    print(f"  演算积水量 {len(net)} 条有值 · 净累计进水合计 {sum(net):,.0f} m³")


if __name__ == "__main__":
    main()
