"""从地籍与地物图层批量反算逐点汇水面积 A、径流系数 C、集流时间 tc（阻塞项 3）。

产出 `backend/data/processed/hotspot_catchment.csv`，由 `registry.py` 离线读取 ——
和 `qcap_batch.py` / `storage_batch.py` 一样，API 因此不依赖数据库可达。

在此之前这三项是**全网按成因分三组的拍脑袋值**（501 个点共用一个 12 ha）。
本模块把它们换成逐点算出来的数，用的是 `geoserver_ref` 里四套 UDM 地物图层
加 ADM 地籍：

| 图层 | 要素数 | 用途 |
|---|---:|---|
| `udm_plot`        | 410,421 | 地块（含用地性质）→ 院落/空地的 C，兼作「有无地籍数据」的判据 |
| `udm_building`    | 382,692 | 建筑屋面 |
| `udm_roadedge`    | 1,048,973 | 道路边线，缓冲 12 m 当路面 |
| `udm_landscape`   | 197,467 | 绿化 |
| `udm_parking`     | 169,865 | 停车场 |
| `udm_pedestrianarea` | 275,640 | 人行区 |

**三个量各自的口径**（每一步的取值都能追到 ADQCC WA-726-1 第三版）：

* **A（汇水面积）** —— 积水点的 Voronoi 单元 ∩ 250 m 圆，再**只取其中的已开发部分**。
  Voronoi 保证相邻积水点不重复计算同一块地；250 m 与 `qcap_batch.py` 的搜索半径
  同口径（对应 19.6 ha 上限，远在推理公式法 80 ha 适用范围内）。
  沙地/未开发部分按 `area_bare_ha` 单列，**不计入 A** —— ADQCC §3.3.1 明说
  Table 3-8 的取值适用于「contributing to the network」的范围，而这些地块既无
  管网接入证据、砂土入渗也快。要做敏感性对照就用 `area_incl_bare_ha` 那一列。

* **C（径流系数）** —— 面积加权，分项取值全部来自 **ADQCC Table 3-8**（见 `SURFACE_C`）。
  地块的未建部分按用地性质分档（`PLOT_CLASS_C`）：住宅院落取「Walled plot;
  not connected to network」0.20，商业/投资地块取 Interlocking 0.78，依此类推。
  未开发沙地取 **Table 3-9** 的四项累加（平缓 0.14 + 深厚砂土 0.06 + 无植被 0.16
  + 一般洼地滞蓄 0.08 = 0.44），只在 `runoff_c_incl_bare` 里生效。

* **tc（集流时间）** —— 按 ADQCC §3.2.3「城市汇水区 tc = 入网时间 + 管内流行时间」：
  入网时间 = 坡面流长 / 坡面流速，**下限 10 分钟**（导则对不透水汇水区的规定）；
  管内时间 = 剩余流程 / 曼宁满流流速（n = 0.015，导则指定值）。
  坡面流长取 A /(4 × 单元内管长) —— 管网把汇水区切成宽 A/L 的条带，
  条带内到中心线的平均距离是 1/4 宽。单元内没有管的点全程按坡面流走。

⚠ **这不是汇水区划分成果**。真正的汇水边界要靠高精度地形（DMT 清单 §09）或
  二维演算定，本模块用的是「相邻积水点等分 + 250 m 半径截断」这一几何代理。
  它解决的是「501 个点共用同一个数」的问题，不解决「边界画在哪」的问题。
  逐点数值可用于筛查与排序，**不可作为单点设计依据**。

⚠ 道路面积是 `udm_roadedge` 边线缓冲 12 m 得到的，不是实测路面多边形；
  缓冲后与地块重叠的部分判给地块（见 `SURFACE_SQL` 的扣减顺序）。
"""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
OUTPUT_CSV = BACKEND_DIR / "data" / "processed" / "hotspot_catchment.csv"
DEM_TIF = BACKEND_DIR / "data" / "DEM_UAE_UTM40" / "DEM_UAE_UTM40.tif"

#: 汇水单元的截断半径（米）。与 `qcap_batch.SEARCH_RADIUS_M` 同口径。
CELL_RADIUS_M = 250.0

#: 道路边线的缓冲半宽（米）—— 双侧边线各缓冲 12 m 覆盖典型城市道路红线。
ROAD_BUFFER_M = 12.0

#: 超过这个距离仍找不到地块，判为**该片没有地籍数据**（而非该点周边真的没有地块）。
COVERAGE_RADIUS_M = 5000.0

#: 已开发面积低于此值（公顷）时，认为该点周边根本没有城市下垫面，
#: 改按整个单元（含沙地）取值，出处标 `measured_undeveloped`。
MIN_DEVELOPED_HA = 0.5

#: ADQCC Table 3-8 —— 城市地表的推荐径流系数。**逐条对得上原表**。
SURFACE_C: dict[str, float] = {
    "bldg": 0.85,        # Roofs
    "road": 0.90,        # Asphaltic
    "parking": 0.90,     # Asphaltic
    "pedestrian": 0.78,  # Interlocking
    "landscape": 0.15,   # > 70% irrigated grass & plantings
}

#: 地块未建部分按用地性质取 Table 3-8 的对应行。
#: 住宅按「Walled plot; not connected to network」（阿布扎比独栋住宅普遍带围墙）。
PLOT_CLASS_C: dict[str, float] = {
    "residential": 0.20,    # Walled plot; not connected to network
    "investment": 0.78,     # Interlocking（多层/综合开发地块的铺装院落）
    "commercial": 0.78,     # Interlocking
    "industrial": 0.85,     # 硬化堆场，按 Roofs/Asphaltic 之间取
    "institutional": 0.70,  # 政府/公建/市政用地，铺装与绿化各半
    "openspace": 0.15,      # > 70% irrigated grass & plantings
    "agricultural": 0.15,   # 同上
    "unspecified": 0.20,    # Poor ground cover
}
DEFAULT_PLOT_C = 0.20

#: ADQCC Table 3-9 的四项累加 —— 未开发沙地：
#: 平缓地形 0.14 + 深厚砂土（入渗高）0.06 + 基本无植被 0.16 + 一般洼地滞蓄 0.08。
BARE_C = 0.44

#: 视为不透水的分项（算不透水率用，决定 Table 3-3 的优先级建议）。
IMPERVIOUS_KEYS = ("bldg", "road", "parking", "pedestrian")

#: 曼宁满流流速用的糙率 —— ADQCC §3.2.3 对估算管内流行时间指定 n = 0.015。
PIPE_MANNING_N = 0.015

#: 坡面流速系数（m/s，乘 √S）—— SCS 浅层集中流，对应导则 Figure 3-1 的两条线。
OVERLAND_V_PAVED = 6.19
OVERLAND_V_UNPAVED = 2.13

#: 入网时间下限（分钟）—— ADQCC §3.2.3 对不透水汇水区的规定。
MIN_ENTRY_MIN = 10.0

#: tc 的截断区间（分钟）。上限只是防离群，超过 30 分钟会在 `tc_exceeds_rational` 标出。
TC_MIN_CLAMP, TC_MAX_CLAMP = 10.0, 60.0

#: 坡度的可信区间与兜底值。城区街道纵坡实测中位数约 0.25%。
SLOPE_MIN, SLOPE_MAX, SLOPE_FALLBACK = 0.0015, 0.05, 0.003

_REF = "geoserver_ref"
_NETWORK = "dmt_irrigationstormwater_abudhabi_network"

# ---------------------------------------------------------------------------
# 工作表：几何运算全部在库内做，Python 只拿汇总数
# ---------------------------------------------------------------------------

#: 几何清洗：先修复 → 降到 1 cm 精度 → 再修复。
#: 不做这一步，UDM 图层里的自相交会让 ST_Difference 抛 TopologyException。
CLEAN_FN_SQL = """
create or replace function hotspot.clean(g geometry) returns geometry as $$
  select st_makevalid(st_reduceprecision(st_makevalid($1), 0.01))
$$ language sql immutable
"""

#: 默认的点表与工作表后缀。见 `qcap_batch.DEFAULT_POINTS_TABLE` ——
#: 同一套几何运算也用来跑 `model_cluster_batch.py` 灌进来的模型片区代表点，
#: 那一路的工作表带 `_model` / `_model_d8` 后缀，与台账这四张互不覆盖。
DEFAULT_POINTS_TABLE = "hotspot.hotspots_845"


def _cell_sql(points: str, suffix: str = "") -> str:
    """汇水单元 = 积水点的 Voronoi 多边形 ∩ 250 m 圆。
    `share_n` 记录同一单元里有几个重合点（全网 1 对），面积按它等分。"""
    return f"""
drop table if exists hotspot.catchment_cell{suffix};
create table hotspot.catchment_cell{suffix} as
with pts as (select uid, geom from {points}),
vor as (
  select (st_dump(st_voronoipolygons(st_collect(geom), 0.0,
            st_buffer(st_envelope(st_collect(geom)), 10000)))).geom as cell
  from pts
),
paired as (
  select p.uid, p.geom as pt, v.cell,
         count(*) over (partition by v.cell) as share_n
  from pts p join vor v on st_intersects(p.geom, v.cell)
)
select uid,
       share_n,
       st_maxdistance(pt, st_intersection(cell, st_buffer(pt, {CELL_RADIUS_M})))
         as flow_path_m,
       st_multi(st_intersection(cell, st_buffer(pt, {CELL_RADIUS_M})))
         ::geometry(MultiPolygon, 32640) as geom
from paired;
alter table hotspot.catchment_cell{suffix} add primary key (uid);
create index on hotspot.catchment_cell{suffix} using gist(geom);
"""

#: 下垫面分项。**扣减顺序就是口径**：地表性质压过权属 ——
#: 建筑 > 停车 > 人行 > 绿化 > 地块剩余 > 道路红线 > 沙地。
#: 道路排在地块之后，缓冲进地块的那部分判给地块，不重复计。
def _surface_sql(suffix: str = "") -> str:
    return f"""
drop table if exists hotspot.catchment_surface{suffix};
create table hotspot.catchment_surface{suffix} as
with c as (select uid, hotspot.clean(geom) as geom from hotspot.catchment_cell{suffix}),
e as (select st_setsrid('POLYGON EMPTY'::geometry, 32640) as g),
raw_bld as (
  select c.uid, hotspot.clean(st_union(st_intersection(c.geom, hotspot.clean(st_force2d(b.geom))))) as g
  from c join {_REF}.udm_building b on st_intersects(c.geom, b.geom) group by 1),
raw_prk as (
  select c.uid, hotspot.clean(st_union(st_intersection(c.geom, hotspot.clean(st_force2d(b.geom))))) as g
  from c join {_REF}.udm_parking b on st_intersects(c.geom, b.geom) group by 1),
raw_ped as (
  select c.uid, hotspot.clean(st_union(st_intersection(c.geom, hotspot.clean(st_force2d(b.geom))))) as g
  from c join {_REF}.udm_pedestrianarea b on st_intersects(c.geom, b.geom) group by 1),
raw_lsc as (
  select c.uid, hotspot.clean(st_union(st_intersection(c.geom, hotspot.clean(st_force2d(b.geom))))) as g
  from c join {_REF}.udm_landscape b on st_intersects(c.geom, b.geom) group by 1),
raw_plt as (
  select c.uid, hotspot.clean(st_union(st_intersection(c.geom, hotspot.clean(st_force2d(b.geom))))) as g
  from c join {_REF}.udm_plot b on st_intersects(c.geom, b.geom) group by 1),
raw_rd as (
  select c.uid, hotspot.clean(st_union(st_intersection(c.geom,
           hotspot.clean(st_buffer(st_force2d(b.geom), {ROAD_BUFFER_M}))))) as g
  from c join {_REF}.udm_roadedge b on st_dwithin(c.geom, b.geom, {ROAD_BUFFER_M}) group by 1),
s0 as (
  select c.uid, c.geom as cell,
         coalesce(raw_bld.g, e.g) as r_bld, coalesce(raw_prk.g, e.g) as r_prk,
         coalesce(raw_ped.g, e.g) as r_ped, coalesce(raw_lsc.g, e.g) as r_lsc,
         coalesce(raw_plt.g, e.g) as r_plt, coalesce(raw_rd.g,  e.g) as r_rd
  from c cross join e
  left join raw_bld on raw_bld.uid = c.uid
  left join raw_prk on raw_prk.uid = c.uid
  left join raw_ped on raw_ped.uid = c.uid
  left join raw_lsc on raw_lsc.uid = c.uid
  left join raw_plt on raw_plt.uid = c.uid
  left join raw_rd  on raw_rd.uid  = c.uid),
stack as (
  select s0.uid, s0.cell, a.g_bld, b.g_prk, c2.g_ped, d.g_lsc, f.g_plt, g.g_rd, h.acc
  from s0,
  lateral (select s0.r_bld as g_bld) a,
  lateral (select hotspot.clean(st_difference(s0.r_prk, a.g_bld)) as g_prk,
                  hotspot.clean(st_union(a.g_bld, s0.r_prk))      as acc1) b,
  lateral (select hotspot.clean(st_difference(s0.r_ped, b.acc1))  as g_ped,
                  hotspot.clean(st_union(b.acc1, s0.r_ped))       as acc2) c2,
  lateral (select hotspot.clean(st_difference(s0.r_lsc, c2.acc2)) as g_lsc,
                  hotspot.clean(st_union(c2.acc2, s0.r_lsc))      as acc3) d,
  lateral (select hotspot.clean(st_difference(s0.r_plt, d.acc3))  as g_plt,
                  hotspot.clean(st_union(d.acc3, s0.r_plt))       as acc4) f,
  lateral (select hotspot.clean(st_intersection(
                    hotspot.clean(st_difference(s0.cell, f.acc4)), s0.r_rd)) as g_rd) g,
  lateral (select hotspot.clean(st_union(f.acc4, g.g_rd)) as acc) h
)
select uid,
       st_area(cell)  as cell_m2,
       st_area(g_bld) as bldg_m2,
       st_area(g_prk) as parking_m2,
       st_area(g_ped) as pedestrian_m2,
       st_area(g_lsc) as landscape_m2,
       st_area(g_plt) as plot_m2,
       st_area(g_rd)  as road_m2,
       greatest(st_area(cell) - st_area(hotspot.clean(st_intersection(acc, cell))), 0) as bare_m2
from stack;
alter table hotspot.catchment_surface{suffix} add primary key (uid);
"""

#: 地块按用地性质分类的**毛**面积（未扣建筑等），只用来定地块剩余部分的加权 C。
#: 取值词表混了三套（大小写、阿拉伯语、旧口径），故按关键词归一而不是枚举。
def _plotclass_sql(suffix: str = "") -> str:
    return f"""
drop table if exists hotspot.catchment_plotclass{suffix};
create table hotspot.catchment_plotclass{suffix} as
with c as (select uid, hotspot.clean(geom) as geom from hotspot.catchment_cell{suffix}),
p as (
  select c.uid,
         case
           when v ~ 'industr'                                     then 'industrial'
           when v ~ 'invest'                                      then 'investment'
           when v ~ 'commerc|shops|hotel|tourist'                 then 'commercial'
           when v ~ 'recreat|publicopenspace|park|ترفيهي'         then 'openspace'
           when v ~ 'farm|agricult'                               then 'agricultural'
           when v ~ 'resid|ranch'                                 then 'residential'
           when v ~ ('govern|public|facilit|educat|health|religio|masajed|cultural|'
                     || 'diplomat|historic|archaeo|transport|communicat|utility|service')
                                                                  then 'institutional'
           else 'unspecified'
         end as landuse_class,
         st_area(st_intersection(c.geom, hotspot.clean(st_force2d(b.geom)))) as m2
  from c
  join {_REF}.udm_plot b on st_intersects(c.geom, b.geom)
  cross join lateral (select lower(trim(coalesce(b.elms_parentlanduse_e, ''))) as v) t
)
select uid, landuse_class, sum(m2) as m2 from p group by 1, 2;
alter table hotspot.catchment_plotclass{suffix} add primary key (uid, landuse_class);
"""

#: 单元内的雨水管：总长定坡面流长，中位管径与中位坡度定满流流速。
def _pipe_sql(suffix: str = "") -> str:
    return f"""
drop table if exists hotspot.catchment_pipe{suffix};
create table hotspot.catchment_pipe{suffix} as
with c as (select uid, geom from hotspot.catchment_cell{suffix}),
seg as (
  select c.uid,
         st_length(st_intersection(c.geom, e.geom)) as len_in_cell,
         e.pipe_diameter as dia_mm,
         case when e.invert_valid and e.len_m > 0
              then (e.invert_up - e.invert_dn) / e.len_m end as slope
  from c
  join {_NETWORK}.sw_edge e
    on st_intersects(c.geom, e.geom)
   and e.subassetname = 'SW Network'
   and e.status in ('Active', 'Existing')
)
select uid,
       sum(len_in_cell) as pipe_len_m,
       percentile_cont(0.5) within group (order by dia_mm)
         filter (where dia_mm > 0)                             as dia_med_mm,
       percentile_cont(0.5) within group (order by slope)
         filter (where slope between {SLOPE_MIN} and {SLOPE_MAX}) as slope_med
from seg group by 1;
alter table hotspot.catchment_pipe{suffix} add primary key (uid);
"""

#: 每个点到最近地块的距离，**不设上限** —— 用来区分「这里真没有地块」
#: 和「这一片我们根本没有地籍数据」，与 `qcap_batch.NEAREST_SQL` 同一套路。
def _nearest_plot_sql(points: str) -> str:
    return f"""
select h.uid,
       (select st_distance(h.geom, b.geom)
          from {_REF}.udm_plot b
         order by h.geom <-> b.geom
         limit 1) as nearest_plot_m
from {points} h
"""

#: 本模块会重建的工作表 —— 写入范围就这四张，`build_tables()` 执行前会逐条核对
#: DDL 只落在它们身上（外加 `hotspot.clean()` 这个几何清洗函数）。
def _work_tables(suffix: str = "") -> tuple[str, ...]:
    return (
        f"hotspot.catchment_cell{suffix}",
        f"hotspot.catchment_surface{suffix}",
        f"hotspot.catchment_plotclass{suffix}",
        f"hotspot.catchment_pipe{suffix}",
    )

def _result_sql(suffix: str = "") -> str:
    return f"""
select s.uid, c.share_n, c.flow_path_m,
       s.cell_m2, s.bldg_m2, s.parking_m2, s.pedestrian_m2,
       s.landscape_m2, s.plot_m2, s.road_m2, s.bare_m2,
       p.pipe_len_m, p.dia_med_mm, p.slope_med
from hotspot.catchment_surface{suffix} s
join hotspot.catchment_cell{suffix} c using (uid)
left join hotspot.catchment_pipe{suffix} p using (uid)
order by s.uid
"""


def _plotclass_result_sql(suffix: str = "") -> str:
    return f"select uid, landuse_class, m2 from hotspot.catchment_plotclass{suffix}"


@dataclass(frozen=True)
class HotspotCatchment:
    """一个积水点反算出来的汇水参数与它的出处。"""

    uid: str
    #: 到最近地块的距离（米），不设上限；判「这一片有没有地籍数据」用
    nearest_plot_m: float | None

    # —— 面积 ——
    #: **本列是给 registry 用的结果**：已开发部分的汇水面积（公顷）
    area_ha: float
    #: 整个汇水单元（Voronoi ∩ 250 m 圆）的面积
    area_cell_ha: float
    #: 单元内未开发沙地的面积 —— 不计入 `area_ha`，敏感性对照用
    area_bare_ha: float
    #: 对照口径：连沙地一起算的面积（= area_ha + area_bare_ha）
    area_incl_bare_ha: float

    # —— 下垫面分项（平方米，已按扣减顺序去重）——
    bldg_m2: float
    road_m2: float
    parking_m2: float
    pedestrian_m2: float
    landscape_m2: float
    plot_m2: float
    bare_m2: float
    #: 地块剩余部分的加权 C（按用地性质），以及主导用地性质
    plot_c: float | None
    plot_class_top: str | None
    #: 不透水率（建筑 + 道路 + 停车 + 人行）/ 已开发面积
    impervious_share: float | None

    # —— 径流系数 ——
    #: **本列是给 registry 用的结果**：已开发部分的面积加权 C
    runoff_c: float
    #: 对照口径：把沙地按 Table 3-9 的 0.44 一起加权
    runoff_c_incl_bare: float

    # —— 集流时间 ——
    #: **本列是给 registry 用的结果**：入网时间 + 管内流行时间（分钟）
    tc_min: float
    tc_entry_min: float
    tc_pipe_min: float
    #: tc > 30 min 时推理公式法已超适用范围（ADQCC §3.3），须在报告里标出
    tc_exceeds_rational: bool
    #: 定 tc 用到的中间量
    flow_path_m: float
    overland_m: float
    pipe_len_m: float | None
    pipe_velocity_ms: float | None
    slope_used: float
    slope_basis: str            #: pipe / dem / fallback

    #: ADQCC Table 3-3 的优先级**建议值**（按不透水率与主导用地判）。
    #: ⚠ 仅供参考，未接进计算 —— 接上会同时改掉设计历时，须先与 DMT 对口径。
    priority_suggested: str

    #: measured / measured_undeveloped / assumed_no_landuse
    basis: str


# ---------------------------------------------------------------------------
# 逐点归并
# ---------------------------------------------------------------------------


def _weighted_c(parts: dict[str, float], plot_c: float) -> tuple[float, float]:
    """分项面积 → (已开发部分加权 C, 含沙地加权 C)。面积为 0 时返回 (0, 0)。"""
    developed = sum(v for k, v in parts.items() if k != "bare")
    num = sum(parts[k] * SURFACE_C[k] for k in SURFACE_C if k in parts)
    num += parts.get("plot", 0.0) * plot_c
    c_dev = num / developed if developed > 0 else 0.0
    total = developed + parts.get("bare", 0.0)
    c_all = (num + parts.get("bare", 0.0) * BARE_C) / total if total > 0 else 0.0
    return c_dev, c_all


def _overland_velocity(impervious_share: float, slope: float) -> float:
    """坡面流速（m/s）—— 铺装与非铺装两条线按不透水率插值。"""
    coeff = (
        OVERLAND_V_PAVED * impervious_share
        + OVERLAND_V_UNPAVED * (1.0 - impervious_share)
    )
    return coeff * math.sqrt(slope)


def _pipe_velocity(diameter_mm: float | None, slope: float) -> float | None:
    """曼宁满流流速（m/s），n 固定 0.015（ADQCC §3.2.3 指定）。"""
    if not diameter_mm or diameter_mm <= 0:
        return None
    r_h = (diameter_mm / 1000.0) / 4.0     # 圆管满流水力半径 = D/4
    return (1.0 / PIPE_MANNING_N) * r_h ** (2 / 3) * math.sqrt(slope)


def _priority(impervious_share: float, top_class: str | None) -> str:
    """ADQCC Table 3-3 的优先级建议 —— 只按不透水率与主导用地粗分。"""
    if top_class == "industrial":
        return "INDUSTRIAL"
    if top_class in ("openspace", "agricultural"):
        return "OPEN_AREA"
    return "HIGH_DENSITY" if impervious_share >= 0.50 else "LOW_DENSITY"


def summarise(
    row: dict,
    plot_classes: dict[str, float],
    nearest_plot_m: float | None,
    dem_slope: float | None,
    fallback_area_ha: float,
    fallback_c: float,
    fallback_tc_min: float,
) -> HotspotCatchment:
    """把一个点的单元统计归并成一条结论。"""
    share = max(int(row.get("share_n") or 1), 1)   # 重合点均分同一个单元
    cell_m2 = float(row["cell_m2"] or 0.0) / share
    parts = {
        "bldg": float(row["bldg_m2"] or 0.0) / share,
        "road": float(row["road_m2"] or 0.0) / share,
        "parking": float(row["parking_m2"] or 0.0) / share,
        "pedestrian": float(row["pedestrian_m2"] or 0.0) / share,
        "landscape": float(row["landscape_m2"] or 0.0) / share,
        "plot": float(row["plot_m2"] or 0.0) / share,
        "bare": float(row["bare_m2"] or 0.0) / share,
    }
    developed_m2 = sum(v for k, v in parts.items() if k != "bare")

    total_plot = sum(plot_classes.values())
    if total_plot > 0:
        plot_c = sum(
            m2 * PLOT_CLASS_C.get(k, DEFAULT_PLOT_C) for k, m2 in plot_classes.items()
        ) / total_plot
        top_class = max(plot_classes.items(), key=lambda kv: kv[1])[0]
    else:
        plot_c, top_class = DEFAULT_PLOT_C, None

    c_dev, c_all = _weighted_c(parts, plot_c)
    impervious = (
        sum(parts[k] for k in IMPERVIOUS_KEYS) / developed_m2
        if developed_m2 > 0
        else 0.0
    )

    # —— 出处与最终面积 ——
    no_landuse = nearest_plot_m is None or nearest_plot_m > COVERAGE_RADIUS_M
    if no_landuse:
        basis = "assumed_no_landuse"
        area_m2, runoff_c = fallback_area_ha * 1e4, fallback_c
    elif developed_m2 < MIN_DEVELOPED_HA * 1e4:
        # 周边确实没有城市下垫面 —— 整个单元按沙地口径算，这是实测结论
        basis = "measured_undeveloped"
        area_m2, runoff_c = cell_m2, (c_all or BARE_C)
    else:
        basis = "measured"
        area_m2, runoff_c = developed_m2, c_dev

    # —— 坡度：实测管底坡度优先，其次 DEM，再兜底 ——
    if row.get("slope_med") is not None:
        slope, slope_basis = float(row["slope_med"]), "pipe"
    elif dem_slope is not None:
        slope, slope_basis = dem_slope, "dem"
    else:
        slope, slope_basis = SLOPE_FALLBACK, "fallback"
    slope = min(max(slope, SLOPE_MIN), SLOPE_MAX)

    # —— tc：入网时间 + 管内流行时间 ——
    flow_path_m = float(row.get("flow_path_m") or CELL_RADIUS_M)
    pipe_len_m = float(row["pipe_len_m"]) if row.get("pipe_len_m") else None
    if pipe_len_m and pipe_len_m > 0:
        # 管网把汇水区切成宽 A/L 的条带，条带内到中心线的平均距离是 1/4 宽
        overland_m = min(area_m2 / (4.0 * pipe_len_m), flow_path_m)
    else:
        overland_m = flow_path_m          # 没有管，全程坡面流

    v_overland = _overland_velocity(impervious, slope)
    entry_min = max(MIN_ENTRY_MIN, overland_m / v_overland / 60.0)
    v_pipe = _pipe_velocity(row.get("dia_med_mm"), slope) if pipe_len_m else None
    pipe_min = (
        max(0.0, flow_path_m - overland_m) / v_pipe / 60.0 if v_pipe else 0.0
    )
    tc = min(max(entry_min + pipe_min, TC_MIN_CLAMP), TC_MAX_CLAMP)
    if basis == "assumed_no_landuse":
        tc, entry_min, pipe_min = fallback_tc_min, fallback_tc_min, 0.0

    return HotspotCatchment(
        uid=row["uid"],
        nearest_plot_m=round(nearest_plot_m, 1) if nearest_plot_m is not None else None,
        area_ha=round(area_m2 / 1e4, 3),
        area_cell_ha=round(cell_m2 / 1e4, 3),
        area_bare_ha=round(parts["bare"] / 1e4, 3),
        area_incl_bare_ha=round((developed_m2 + parts["bare"]) / 1e4, 3),
        bldg_m2=round(parts["bldg"]),
        road_m2=round(parts["road"]),
        parking_m2=round(parts["parking"]),
        pedestrian_m2=round(parts["pedestrian"]),
        landscape_m2=round(parts["landscape"]),
        plot_m2=round(parts["plot"]),
        bare_m2=round(parts["bare"]),
        plot_c=round(plot_c, 3) if total_plot > 0 else None,
        plot_class_top=top_class,
        impervious_share=round(impervious, 3) if developed_m2 > 0 else None,
        runoff_c=round(runoff_c, 3),
        runoff_c_incl_bare=round(c_all or BARE_C, 3),
        tc_min=round(tc, 1),
        tc_entry_min=round(entry_min, 1),
        tc_pipe_min=round(pipe_min, 1),
        tc_exceeds_rational=tc > 30.0,
        flow_path_m=round(flow_path_m, 1),
        overland_m=round(overland_m, 1),
        pipe_len_m=round(pipe_len_m, 1) if pipe_len_m else None,
        pipe_velocity_ms=round(v_pipe, 3) if v_pipe else None,
        slope_used=round(slope, 5),
        slope_basis=slope_basis,
        priority_suggested=_priority(impervious, top_class),
        basis=basis,
    )


# ---------------------------------------------------------------------------
# DEM 兜底坡度
# ---------------------------------------------------------------------------


def dem_slopes(uids: list[str], points: dict[str, tuple[float, float]]) -> dict[str, float]:
    """DEM 兜底坡度：单元内高程的 p95 − p5 除以流程长。

    ⚠ DEM 是 30 m 格网的全国图，在阿布扎比这种平原城区**只够当兜底**——
      管底高程反算出来的坡度（`slope_basis = 'pipe'`）永远优先。
    """
    if not DEM_TIF.exists():
        return {}
    try:
        import numpy as np
        import rasterio
        from rasterio.windows import from_bounds
    except ImportError:
        return {}

    out: dict[str, float] = {}
    try:
        with rasterio.open(DEM_TIF) as dem:
            for uid in uids:
                xy = points.get(uid)
                if xy is None:
                    continue
                x, y = xy
                r = CELL_RADIUS_M
                try:
                    win = from_bounds(x - r, y - r, x + r, y + r, dem.transform)
                    band = dem.read(1, window=win).astype("float64")
                except Exception:  # noqa: BLE001 — 越界的点直接跳过
                    continue
                band = band[(band < 1e6) & (band > -500)]
                if band.size < 4:
                    continue
                drop = float(np.percentile(band, 95) - np.percentile(band, 5))
                out[uid] = max(drop / (2 * r), 0.0)
    except Exception:  # noqa: BLE001 — DEM 只是兜底，读不了就退回常数
        return {}
    return out


# ---------------------------------------------------------------------------
# 批算入口
# ---------------------------------------------------------------------------


def build_tables(
    points_table: str = DEFAULT_POINTS_TABLE,
    suffix: str = "",
    *,
    build_cells: bool = True,
) -> None:
    """在库里重建四张工作表。几何运算重，845 个点整批约 4 分钟。

    ⚠ 这是全项目**唯一一处可写连接**。`db.connect()` 强制只读是对的（那些是
      Esri 导出的来源图层），但本模块的几何运算量放在 Python 里跑不动，只能落库。
      写入范围锁死在 `hotspot` schema 的四张工作表，来源图层一律只读取。

    Args:
        points_table: 点表，Voronoi 与「最近地块」都基于它。
        suffix: 工作表后缀。台账那一路是空串；模型片区那一路带 `_model` /
            `_model_d8`，四张表各成一套，两边互不覆盖。
        build_cells: 是否重建汇水单元表。**D8 那一路要关掉** —— 它的单元是
            `model_cluster_batch.py` 用 D8 汇流实算出来后自己灌进去的，
            不是这里的 Voronoi 代理；关掉之后下游三张表照常按那份单元算。
    """
    import psycopg

    from .config import db_settings

    work = _work_tables(suffix)
    statements = [CLEAN_FN_SQL]
    if build_cells:
        statements.append(_cell_sql(points_table, suffix))
    statements += [_surface_sql(suffix), _plotclass_sql(suffix), _pipe_sql(suffix)]
    for sql in statements:
        for verb in ("drop table", "create table", "alter table"):
            for line in sql.lower().split(";"):
                if verb in line and not any(t in line for t in work):
                    raise RuntimeError(f"本模块只能动 {work}，拦下：{line.strip()[:80]}")

    with psycopg.connect(db_settings().conninfo) as conn, conn.cursor() as cur:
        for sql in statements:
            cur.execute(sql)
        conn.commit()


def compute_all(
    *,
    rebuild: bool = True,
    fallback_area_ha: float = 12.0,
    fallback_c: float = 0.75,
    fallback_tc_min: float = 20.0,
    points_table: str = DEFAULT_POINTS_TABLE,
    suffix: str = "",
    build_cells: bool = True,
) -> list[HotspotCatchment]:
    """连库取数 + 逐点归并。需要 `points_table` 已落库。

    Args:
        rebuild: 重建库内的四张工作表。已经建好、只想改归并口径时可以关掉。
        points_table / suffix / build_cells: 见 `build_tables()`。
    """
    from .db import query  # 延迟导入：没有数据库也能 import 本模块

    if rebuild:
        build_tables(points_table, suffix, build_cells=build_cells)

    nearest = {r["uid"]: r["nearest_plot_m"] for r in query(_nearest_plot_sql(points_table))}
    rows = query(_result_sql(suffix))
    classes: dict[str, dict[str, float]] = {}
    for r in query(_plotclass_result_sql(suffix)):
        classes.setdefault(r["uid"], {})[r["landuse_class"]] = float(r["m2"] or 0.0)

    pts = {
        r["uid"]: (float(r["x"]), float(r["y"]))
        for r in query(f"select uid, st_x(geom) as x, st_y(geom) as y from {points_table}")
    }
    slopes = dem_slopes([r["uid"] for r in rows], pts)

    return [
        summarise(
            row,
            classes.get(row["uid"], {}),
            nearest.get(row["uid"]),
            slopes.get(row["uid"]),
            fallback_area_ha,
            fallback_c,
            fallback_tc_min,
        )
        for row in rows
    ]


def write_csv(results: list[HotspotCatchment], path: Path = OUTPUT_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [f.name for f in fields(HotspotCatchment)]
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
    areas = sorted(r.area_ha for r in results)
    cs = sorted(r.runoff_c for r in results)
    tcs = sorted(r.tc_min for r in results)

    def med(xs: list[float]) -> float:
        return xs[len(xs) // 2]

    print(f"{len(results)} 个积水点 → {path}")
    for basis, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"   {basis:<22} {n:>4}")
    print(f"   面积 ha   中位 {med(areas):>6.2f}   区间 {areas[0]:.2f}–{areas[-1]:.2f}")
    print(f"   径流系数  中位 {med(cs):>6.2f}   区间 {cs[0]:.2f}–{cs[-1]:.2f}")
    print(f"   tc  min   中位 {med(tcs):>6.1f}   区间 {tcs[0]:.1f}–{tcs[-1]:.1f}")
    print(f"   tc > 30 min（超推理公式法适用范围）：{sum(r.tc_exceeds_rational for r in results)} 个点")


if __name__ == "__main__":
    main()
