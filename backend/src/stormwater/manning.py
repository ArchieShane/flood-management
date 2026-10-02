"""曼宁公式 Qcap 计算与管材糙率映射（交接文档 §4.3 / §4.4 / §4.5）。

本模块是「把 846 个积水点那列文本估值换成真实数字」的核心。

所有公式一律接收 **SI 单位**（米、十进制坡度）。数据库里 `pipe_diameter` 和
`gradient` 的单位尚未确认（§4.6），因此提供 `normalize_diameter` /
`normalize_gradient` 做显式转换 —— 单位判错会导致 Qcap 出现数量级错误，
所以这里不做任何猜测，必须由调用方显式声明。
"""

from __future__ import annotations

import re
from enum import Enum
from math import pi, sqrt

# --------------------------------------------------------------------------
# 管材 → 曼宁糙率 n（§4.4）
# --------------------------------------------------------------------------

#: 未知/脏数据管材的兜底糙率。方向保守：n 偏大 → Qcap 偏小 → 更易判定超载。
DEFAULT_MANNING_N = 0.013

#: ⚠ 顺序有意义：玻璃钢分支必须在混凝土分支之前，
#:   否则 Glass Reinforced Concrete (GRC) 与 Glass Reinforced Plastic (GRP)
#:   会被同一条规则吃掉。与 §4.4 的 SQL CASE 分支严格一一对应。
_MATERIAL_RULES: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"grp|glass reinforced|^gre$", re.I), 0.010),   # 玻璃钢 / 环氧
    (re.compile(r"pvc", re.I),                        0.010),   # UPVC/uPVC/PVC/含描述文本
    (re.compile(r"hdp[ei]|polyethylene", re.I),       0.010),   # HDPE（含 HDPI 拼写错误）
    (re.compile(r"vitrified|clay", re.I),             0.012),   # 陶土
    (re.compile(r"ductile|steel|^ac$|asbestos", re.I),0.012),   # 球墨铸铁 / 钢 / 石棉水泥
    (re.compile(r"concrete|^grc$|^ndrc$", re.I),      0.013),   # 混凝土类
)


def manning_n(pipe_material: str | None) -> float:
    """管材文本 → 曼宁糙率 n。

    与 §4.4 的 SQL CASE 表达式等价，供单点快算复用（批量计算应在 SQL 里物化，
    不要 26 万行逐行回 Python）。

    ⚠ 待确认（§4.4）：ADQCC WA726-1 是否规定统一取 n = 0.013。若是，
      本函数作废，全网改用 DEFAULT_MANNING_N。
    """
    mat = (pipe_material or "").strip()
    for pattern, n in _MATERIAL_RULES:
        if pattern.search(mat):
            return n
    return DEFAULT_MANNING_N


#: §4.4 统计：无有效材质合计 31,249 条 / 12.0%
_UNUSABLE_MATERIALS = {"", "undefined", "other"}


def is_material_unusable(pipe_material: str | None) -> bool:
    """材质字段是否属于「无有效值」（Undefined / Other / null / 纯空格）。

    这些记录的 n 是兜底值而非实测，产出 Qcap 时应标记置信度。
    """
    return (pipe_material or "").strip().lower() in _UNUSABLE_MATERIALS


# --------------------------------------------------------------------------
# 单位归一化（§4.6 —— 单位未确认前必须显式声明）
# --------------------------------------------------------------------------


class DiameterUnit(str, Enum):
    MM = "mm"
    M = "m"


class GradientConvention(str, Enum):
    #: 直接是十进制坡度，如 0.002
    DECIMAL = "decimal"
    #: 存的是 1:X 里的 X，如 500 表示 1:500 → 坡度 0.002
    INVERSE = "inverse"


def normalize_diameter(value: float, unit: DiameterUnit) -> float:
    """管径归一化为米。

    §4.6 判读规则：`pipe_diameter` 最大值约 2400 → 单位是 mm；约 2.4 → 单位是 m。
    """
    if value <= 0:
        raise ValueError(f"管径必须为正，得到 {value}")
    return value / 1000.0 if unit is DiameterUnit.MM else value


def normalize_gradient(value: float, convention: GradientConvention) -> float:
    """坡度归一化为十进制。

    §4.6 判读规则：范围 0.0005–0.05 → 十进制坡度；范围 100–2000 → 1:X 的 X。
    """
    if value <= 0:
        raise ValueError(f"坡度必须为正，得到 {value}")
    return 1.0 / value if convention is GradientConvention.INVERSE else value


# --------------------------------------------------------------------------
# 断面 Qcap 公式
# --------------------------------------------------------------------------


def _manning_q(area_m2: float, hydraulic_radius_m: float, slope: float, n: float) -> float:
    """曼宁公式：Q = (1/n) × A × R^(2/3) × S^(1/2)。"""
    if n <= 0:
        raise ValueError(f"曼宁糙率必须为正，得到 {n}")
    if slope <= 0:
        raise ValueError(f"坡度必须为正，得到 {slope}")
    return (1.0 / n) * area_m2 * hydraulic_radius_m ** (2.0 / 3.0) * sqrt(slope)


def circular_pipe_qcap(diameter_m: float, slope: float, n: float = DEFAULT_MANNING_N) -> float:
    """满流圆管 Qcap（m³/s）—— §4.3。A = π(D/2)²，R = D/4。"""
    if diameter_m <= 0:
        raise ValueError(f"管径必须为正，得到 {diameter_m}")
    area = pi * (diameter_m / 2.0) ** 2
    return _manning_q(area, diameter_m / 4.0, slope, n)


def box_culvert_qcap(
    width_m: float, height_m: float, slope: float, n: float = DEFAULT_MANNING_N
) -> float:
    """满流方涵 Qcap（m³/s）—— §4.5 `boxculvert` 表。

    高度 = culvert_top_level − culvert_bottom_level。
    """
    if width_m <= 0 or height_m <= 0:
        raise ValueError(f"方涵断面尺寸必须为正，得到 {width_m}×{height_m}")
    area = width_m * height_m
    return _manning_q(area, area / (2.0 * (width_m + height_m)), slope, n)


def trapezoidal_ditch_qcap(
    bottom_width_m: float, top_width_m: float, depth_m: float,
    slope: float, n: float = DEFAULT_MANNING_N,
) -> float:
    """满水梯形明渠 Qcap（m³/s）—— §4.5 `ditch` 表。

    depth = top_level − bottom_level；边坡由 top_width 与 bottom_width 反推。
    """
    if bottom_width_m < 0 or top_width_m <= 0 or depth_m <= 0:
        raise ValueError(
            f"明渠断面尺寸非法：bottom={bottom_width_m}, top={top_width_m}, depth={depth_m}"
        )
    if top_width_m < bottom_width_m:
        raise ValueError(f"顶宽 {top_width_m} 小于底宽 {bottom_width_m}，数据有误")
    area = (bottom_width_m + top_width_m) / 2.0 * depth_m
    side = sqrt(depth_m**2 + ((top_width_m - bottom_width_m) / 2.0) ** 2)
    return _manning_q(area, area / (bottom_width_m + 2.0 * side), slope, n)
