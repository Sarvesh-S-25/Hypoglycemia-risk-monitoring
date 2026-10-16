"""Fixed-length ONNX model buffering (app/inference.py) and the foot module's
result packet (app/aux_gateway.py)."""
from __future__ import annotations

import struct

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper

from app.aux_gateway import RESULT_FORMAT, parse_foot_result
from app.config import settings
from app.inference import OnnxRiskModel

FIXED_LEN = 7500  # same input length as the D1NAMO CNN+BiLSTM


@pytest.fixture
def logit_model(tmp_path):
    """A stand-in with the trained model's I/O: ecg_window (batch, 1, 7500)
    -> risk_logit, here just the mean of the input (0 after z-scoring)."""
    inp = helper.make_tensor_value_info("ecg_window", TensorProto.FLOAT, ["batch", 1, FIXED_LEN])
    out = helper.make_tensor_value_info("risk_logit", TensorProto.FLOAT, ["batch"])
    axes = helper.make_tensor("axes", TensorProto.INT64, [2], [1, 2])
    node = helper.make_node("ReduceMean", ["ecg_window", "axes"], ["risk_logit"], keepdims=0)
    graph = helper.make_graph([node], "g", [inp], [out], initializer=[axes])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 9
    path = tmp_path / "logit.onnx"
    onnx.save(model, path)
    return OnnxRiskModel(str(path))


def one_second(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(size=(1, 1, settings.ecg_sample_rate_hz)).astype(np.float32)


def test_fixed_length_model_waits_for_a_full_window(logit_model):
    windows_needed = int(settings.model_window_s)
    scores = [logit_model.predict(one_second(i)) for i in range(windows_needed)]
    assert all(s is None for s in scores[:-1])
    # z-scored input has mean 0 -> logit 0 -> sigmoid 0.5
    assert scores[-1] == pytest.approx(0.5, abs=1e-4)
    # Rolling: every further window is scored.
    assert logit_model.predict(one_second(99)) == pytest.approx(0.5, abs=1e-4)


def test_reset_restarts_the_buffer(logit_model):
    for i in range(int(settings.model_window_s)):
        logit_model.predict(one_second(i))
    logit_model.reset()
    assert logit_model.predict(one_second(1)) is None


def test_parse_foot_result():
    reading = parse_foot_result(struct.pack(RESULT_FORMAT, 30.123, 32.456, -2.333, 1))
    assert reading.t_left == pytest.approx(30.12)
    assert reading.t_right == pytest.approx(32.46)
    assert reading.delta == pytest.approx(-2.33)
    assert reading.valid is True


def test_parse_foot_result_rejects_short_packets():
    with pytest.raises(ValueError):
        parse_foot_result(b"\x00" * 5)


def test_ecg_filter_matches_the_notebook_design():
    from app.ecg_filter import frequency_response

    h = frequency_response(np.array([0.5, 10.0, 50.0, 100.0]), 250)
    assert h[0] == pytest.approx(1 / np.sqrt(2), abs=1e-3)  # Butterworth -3 dB at the band edge
    assert h[1] == pytest.approx(1.0, abs=1e-3)              # passband
    assert h[2] < 1e-3                                       # mains notch
    assert h[3] < 1e-2                                       # above 40 Hz


def test_clean_ecg_keeps_ecg_band_and_drops_mains_and_drift():
    from app.ecg_filter import clean_ecg

    t = np.arange(7500) / 250
    x = np.sin(2 * np.pi * 10 * t) + np.sin(2 * np.pi * 50 * t) + 3.0 + np.sin(2 * np.pi * 0.05 * t)
    y = clean_ecg(x, 250)[500:-500]
    expected = np.sin(2 * np.pi * 10 * t)[500:-500]
    assert np.max(np.abs(y - expected)) < 0.05
