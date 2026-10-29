"""全市应对设备配置（sim_results.equipment）：文件读法、缺文件 404、数字自洽。

数据文件在 backend/data/261029-2（不进代码库），缺失时依赖真文件的用例 skip。
"""
import shutil
from pathlib import Path

import pytest

from stormwater import sim_results
from stormwater import simulation as sim

SRC = Path(sim_results.DATA_ROOT) / "261029-2"
FILES = {
    "equipment_fixed.json": "ADM_100m_after_L2_tier1_fixed.json",
    "equipment_mobile.json": "ADM_100m_after_L2_tier2_mobile.json",
}


class _Conn:
    def __init__(self, out):
        self.out = out

    def execute(self, *_a):
        return self

    def fetchone(self):
        return {"output_dir": self.out} if self.out is not None else None


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(sim_results, "DATA_ROOT", tmp_path)
    d = tmp_path / "d1"
    d.mkdir()
    return d


def test_missing_files_404(root):
    with pytest.raises(sim.SimulationError) as e:
        sim_results.equipment(_Conn("d1"), 1)
    assert e.value.status == 404 and e.value.message == sim_results.NO_EQUIPMENT


def test_one_file_only_404(root):
    (root / "equipment_fixed.json").write_text("{}", encoding="utf-8")
    with pytest.raises(sim.SimulationError):
        sim_results.equipment(_Conn("d1"), 1)


def test_unknown_run_404(root):
    with pytest.raises(sim.SimulationError):
        sim_results.equipment(_Conn(None), 1)


@pytest.mark.skipif(not all((SRC / f).is_file() for f in FILES.values()), reason="没有 261029-2 设备配置数据")
def test_real_files_pass_through_numbers_only(root):
    for dst, src in FILES.items():
        shutil.copy(SRC / src, root / dst)
    out = sim_results.equipment(_Conn("d1"), 1)
    assert set(out) == {"fixed", "mobile"}
    # 英文标题 / 范围 / 备注不透传
    for k in out:
        assert set(out[k]) == {"generated", "inputs", "assumptions", "scenarios"}
        assert "title" not in out[k] and "scope" not in out[k]
        assert "notes" in out[k]["assumptions"]   # 假设里自带的 notes 随 assumptions 过来，页面不显示它
    assert len(out["fixed"]["scenarios"]) == 16 and len(out["mobile"]["scenarios"]) == 12
    i = out["fixed"]["inputs"]
    # 两档水量 = L2 后剩余积水 × 45/65、20/65，合起来就是剩余积水（差 1 m³ 内是取整）
    rem = i["remaining_ponding_after_L2_m3"]
    assert abs(i["volume_fixed_m3"] - rem * 45 / 65) <= 1
    assert abs(i["volume_mobile_m3"] - rem * 20 / 65) <= 1
    assert abs(i["volume_fixed_m3"] + i["volume_mobile_m3"] - rem) <= 1
    assert out["mobile"]["inputs"]["remaining_ponding_after_L2_m3"] == rem
    # 固定设施：站流量合计 ≥ 总需流量（向上取整到整站）
    for s in out["fixed"]["scenarios"]:
        p = s["pump_stations"]
        assert p["count"] * p["station_flow_m3s"] >= s["total_flow_required_m3s"] - 0.5
        assert p["duty_pumps_total"] == p["count"] * p["duty_pumps_per_station"]
        assert p["pumps_total"] == p["duty_pumps_total"] + p["standby_pumps_total"]
