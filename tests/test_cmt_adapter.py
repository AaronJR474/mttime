"""Unit checks for translating MTtime tensors to the helper CMT figure."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np


def load_helpers_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "src" / "mttime" / "workflows" / "mttime_helpers.py"
    spec = importlib.util.spec_from_file_location("_mttime_helpers_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeTensor:
    depth = 12.5
    mo = 3.2e24
    mw = 5.61
    pdc = 72.0
    pclvd = 18.0
    piso = 10.0
    total_VR = 64.0
    fps = [(123.0, 45.0, -90.0), (303.0, 45.0, -90.0)]

    def get_tensor_elements(self, basis="XYZ"):
        assert basis == "RTP"
        return {
            "MRR": 1.0e24,
            "MTT": -2.0e24,
            "MPP": 1.0e24,
            "MRT": 2.0e23,
            "MRP": -3.0e23,
            "MTP": 4.0e23,
        }


class FakeInversion:
    config = SimpleNamespace(degree=6)

    def get_preferred_tensor(self):
        return FakeTensor()


def test_mttime_cmt_adapter_converts_units_and_percent_vr():
    helpers = load_helpers_module()
    summary, centroid, mode = helpers._mttime_cmt_inputs(FakeInversion())

    assert mode == "full"
    assert centroid == {"centroid_depth_km": 12.5}
    assert np.isclose(summary["Mrr"], 1.0e17)
    assert np.isclose(summary["M0_Nm"], 3.2e17)
    assert np.isclose(summary["variance_reduction"], 0.64)
    assert summary["NP1_strike_deg"] == 123.0
    assert summary["NP2_strike_deg"] == 303.0
