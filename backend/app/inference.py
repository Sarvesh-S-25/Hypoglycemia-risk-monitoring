"""
inference.py -- CNN+BiLSTM risk inference (SRD 4.1), behind a fixed interface
so the real model drops in without touching any other file (docs/PLAN.md
section 1 decision 3).

RiskModel.predict(window) -> float in [0, 1] is the entire contract.
StubRiskModel is a heuristic standing in until the ONNX file from the (separate)
ML training pipeline exists. OnnxRiskModel wraps it once GS_MODEL_PATH is set.

onnxruntime is imported lazily inside OnnxRiskModel so that running with the
stub -- the common case during frontend/backend integration work -- never
requires the ML dependency to even be importable.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Protocol

import numpy as np

logger = logging.getLogger("glucosentry.inference")


class RiskModel(Protocol):
    #: Human-readable label surfaced to the frontend via GET /api/status and
    #: the WebSocket's status/hello frames ("model" field), so it's always
    #: visible -- not just logged server-side -- which model is actually
    #: scoring the data. This is what lets a silent ONNX-load failure (see
    #: load_risk_model's except branch) show up as "Stub (ONNX load failed)"
    #: in the UI instead of quietly, invisibly serving stub scores while
    #: someone believes their trained model is running.
    name: str

    def predict(self, window: np.ndarray) -> float:
        """window: (1, 1, N) float32, normalized by signal_pipeline. Returns
        a risk score in [0.0, 1.0]."""
        ...


class StubRiskModel:
    """Heuristic placeholder: maps signal energy and variability to a risk-
    like score so the controller, alerting, and dashboard can be built and
    tested end to end before the trained model exists (SRD build step 6).

    This is intentionally *not* clinically meaningful. It exists to produce a
    plausible, varying [0, 1] signal -- drifting baseline plus reactions to
    amplitude spikes -- so mode transitions and the sustained-risk alert path
    have something realistic to respond to during development.
    """

    name = "Stub (heuristic)"

    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = np.random.default_rng(seed)
        self._baseline = 0.25  # slow-drifting component, mimics a trending risk score

    def predict(self, window: np.ndarray) -> float:
        flat = window.reshape(-1)
        if flat.size == 0:
            return self._baseline

        # Windows are baseline-removed and scaled by a FIXED reference divisor
        # in signal_pipeline (not per-window normalized -- see that module's
        # docstring for why), so a real amplitude excursion, e.g. simulator's
        # spike(), is still visible here as elevated peak-to-peak amplitude.
        # A normal simulated window has ptp roughly 1.0-1.5 at this scale;
        # spike() roughly triples the raw amplitude, mapping to ~1.0 here.
        peak_to_peak = float(np.ptp(flat))
        amplitude_component = np.clip((peak_to_peak - 1.2) / 1.8, 0.0, 1.0)

        # Slow random walk keeps the baseline from looking static in a demo.
        self._baseline = float(np.clip(self._baseline + self._rng.normal(0, 0.01), 0.05, 0.45))

        # Weighted so a sustained induced spike (amplitude_component ~= 1.0)
        # clears risk_alert (0.75) even at the lowest point of the baseline's
        # drift range: 0.5*0.05 + 0.85*1.0 = 0.875. The original 0.6/0.4
        # weighting capped at 0.6*0.45 + 0.4*1.0 = 0.67, which is *always*
        # below risk_alert -- meaning SRD acceptance criterion 8 ("alert fires
        # ... demonstrable via induced test signal") could never actually be
        # demonstrated against the simulator. Caught by
        # test_alert_fires_on_sustained_simulated_spike in
        # tests/test_phase2_integration.py.
        score = 0.5 * self._baseline + 0.85 * amplitude_component
        return float(np.clip(score, 0.0, 1.0))


class OnnxRiskModel:
    """Wraps a trained CNN+BiLSTM exported to ONNX and served via ONNX
    Runtime (SRD 2, "ML" row). Model training and export happen in the
    separate ML pipeline; this class only loads and runs the artifact."""

    def __init__(self, model_path: str) -> None:
        import onnxruntime as ort  # lazy import, see module docstring

        self._session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name
        self.name = f"ONNX: {Path(model_path).name}"
        logger.info("loaded ONNX risk model from %s", model_path)

    def predict(self, window: np.ndarray) -> float:
        outputs = self._session.run(None, {self._input_name: window.astype(np.float32)})
        score = float(np.asarray(outputs[0]).reshape(-1)[0])
        return float(np.clip(score, 0.0, 1.0))


def load_risk_model(model_path: str) -> RiskModel:
    """Factory used by app/main.py at startup. Empty path -> stub.

    To use your own trained model: export it to ONNX and set GS_MODEL_PATH in
    backend/.env to its path (see README.md). No other file needs to change --
    that's the entire point of RiskModel being an interface (docs/PLAN.md
    section 1 decision 3).
    """
    if not model_path:
        logger.info("GS_MODEL_PATH not set; using StubRiskModel")
        return StubRiskModel()
    try:
        return OnnxRiskModel(model_path)
    except Exception as exc:
        logger.exception("failed to load ONNX model at %s; falling back to StubRiskModel", model_path)
        fallback = StubRiskModel()
        # Named distinctly from the plain stub case so this failure is
        # visible in the UI (GET /api/status "model" field), not just in a
        # server log nobody may be watching.
        fallback.name = f"Stub (failed to load {Path(model_path).name}: {exc})"
        return fallback
