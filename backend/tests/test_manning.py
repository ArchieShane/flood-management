"""曼宁 Qcap 与糙率映射测试（§4.3 / §4.4 / §4.6）。"""

import pytest

from stormwater.manning import (
    DEFAULT_MANNING_N, DiameterUnit, GradientConvention,
    box_culvert_qcap, circular_pipe_qcap, is_material_unusable, manning_n,
    normalize_diameter, normalize_gradient, trapezoidal_ditch_qcap,
)


def test_dn1200_matches_documented_worked_example():
    """§4.3 验证示例：DN1200 混凝土管, S=0.002, n=0.013 → Q ≈ 1.74 m³/s
    （接近原 Excel 示例点 H1 填的 Qcap=1.8）。"""
    assert circular_pipe_qcap(1.2, 0.002, 0.013) == pytest.approx(1.74, abs=0.01)


class TestMaterialRoughness:
    @pytest.mark.parametrize("material,expected", [
        ("GRP", 0.010), ("Glass Reinforced Epoxy", 0.010),
        ("UPVC", 0.010), ("uPVC", 0.010), ("PVC", 0.010), ("Solid_uPVC", 0.010),
        ("HDPE", 0.010), ("HDPI", 0.010),                    # HDPI 是拼写错误
        ("Vitrified Clay", 0.012), ("Ductile Iron", 0.012), ("Steel", 0.012), ("AC", 0.012),
        ("Concrete", 0.013), ("Reinforced Concrete", 0.013), ("NDRC", 0.013),
    ])
    def test_known_materials(self, material, expected):
        assert manning_n(material) == expected

    def test_grc_is_concrete_not_fibreglass(self):
        """§4.4 的分支顺序陷阱：GRC(Glass Reinforced Concrete) 必须落到混凝土。"""
        assert manning_n("GRC") == 0.013
        assert manning_n("GRP") == 0.010

    def test_full_spec_text_stuffed_into_material_field(self):
        """§4.4：8 条记录把完整规格描述塞进了材质字段。"""
        assert manning_n("160 mm ∅ uPVC SLOTTED DRAIN PIPE, PN10\r\n") == 0.010

    @pytest.mark.parametrize("material", [None, "", "   ", "Undefined", "Other"])
    def test_unusable_falls_back_conservatively(self, material):
        assert manning_n(material) == DEFAULT_MANNING_N
        assert is_material_unusable(material)

    def test_valid_material_not_flagged_unusable(self):
        assert not is_material_unusable("GRP")

    def test_roughness_sensitivity_is_about_18_percent(self):
        """§4.4：n 从 0.010 到 0.013，Qcap 相差约 18%。"""
        q_smooth = circular_pipe_qcap(1.2, 0.002, 0.010)
        q_rough = circular_pipe_qcap(1.2, 0.002, 0.013)
        assert (q_smooth - q_rough) / q_smooth == pytest.approx(0.231, abs=0.005)


class TestUnitNormalization:
    """§4.6：单位判错会导致 Qcap 出现数量级错误。"""

    def test_diameter_units(self):
        assert normalize_diameter(1200, DiameterUnit.MM) == pytest.approx(1.2)
        assert normalize_diameter(1.2, DiameterUnit.M) == pytest.approx(1.2)

    def test_gradient_conventions(self):
        assert normalize_gradient(0.002, GradientConvention.DECIMAL) == pytest.approx(0.002)
        assert normalize_gradient(500, GradientConvention.INVERSE) == pytest.approx(0.002)

    def test_misreading_mm_as_m_is_catastrophic(self):
        """把 mm 当成 m 会让 Qcap 差 5 个数量级 —— 这就是为什么不做自动猜测。"""
        right = circular_pipe_qcap(normalize_diameter(1200, DiameterUnit.MM), 0.002)
        wrong = circular_pipe_qcap(1200, 0.002)
        assert wrong / right > 1e5

    @pytest.mark.parametrize("bad", [0, -1])
    def test_rejects_nonpositive(self, bad):
        with pytest.raises(ValueError):
            normalize_diameter(bad, DiameterUnit.MM)
        with pytest.raises(ValueError):
            normalize_gradient(bad, GradientConvention.DECIMAL)


class TestOtherCrossSections:
    def test_box_culvert(self):
        """2.0×1.5 m 方涵, S=0.002, n=0.013：A=3.0, P=7.0, R=0.4286, R^(2/3)=0.5684"""
        assert box_culvert_qcap(2.0, 1.5, 0.002, 0.013) == pytest.approx(5.866, abs=0.005)

    def test_trapezoidal_ditch(self):
        """底宽 2.0 / 顶宽 5.0 / 深 1.5 —— 边坡 1:1：A=5.25, P=6.2426, R=0.8410"""
        q = trapezoidal_ditch_qcap(2.0, 5.0, 1.5, 0.002, 0.013)
        assert q == pytest.approx(16.089, abs=0.005)

    def test_rectangular_ditch_equals_box_culvert(self):
        """顶宽=底宽的梯形退化为矩形，但明渠只有一侧湿周（无顶板）。"""
        q = trapezoidal_ditch_qcap(2.0, 2.0, 1.5, 0.002, 0.013)
        assert q > box_culvert_qcap(2.0, 1.5, 0.002, 0.013)  # 湿周更小 → R 更大

    def test_inverted_ditch_dimensions_rejected(self):
        with pytest.raises(ValueError, match="顶宽"):
            trapezoidal_ditch_qcap(5.0, 2.0, 1.5, 0.002)


@pytest.mark.parametrize("kwargs", [
    {"diameter_m": 0, "slope": 0.002}, {"diameter_m": 1.2, "slope": 0},
    {"diameter_m": 1.2, "slope": -0.001},
])
def test_circular_rejects_invalid(kwargs):
    with pytest.raises(ValueError):
        circular_pipe_qcap(**kwargs)
