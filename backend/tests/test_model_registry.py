"""
Tests for the model upload/select/reset feature (docs/API_CONTRACT.md
section 3.1). Uses FastAPI's TestClient against the real app, with
model_registry's directories monkeypatched to a tmp_path so tests never
touch the project's real backend/models/ or backend/data/.

The corrupt-upload test guards a real bug found by hand-testing: the first
version of _apply_model swapped state.model to the failed stub fallback
*before* checking whether the load actually succeeded, so uploading a bad
file silently replaced a working, already-active model. See routes.py's
_apply_model docstring for the full story.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import model_registry
from app.config import settings


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Point model_registry (via settings) at a throwaway directory tree so
    tests never touch the real backend/models/ or backend/data/."""
    monkeypatch.setattr(settings, "gs_models_dir", str(tmp_path / "models"))
    monkeypatch.setattr(settings, "gs_model_selection_path", str(tmp_path / "data" / "model_selection.txt"))
    monkeypatch.setattr(settings, "gs_db_path", str(tmp_path / "data" / "test.db"))
    yield tmp_path


@pytest.fixture
def client(isolated_dirs):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _tiny_valid_onnx_bytes() -> bytes:
    """A minimal, genuinely loadable ONNX model: identity-like graph with the
    (1, 1, N) float32 input shape inference.py expects, built directly with
    onnx.helper rather than depending on torch being installed for tests."""
    import numpy as np
    import onnx
    from onnx import TensorProto, helper

    node = helper.make_node("ReduceMean", inputs=["input"], outputs=["risk"], axes=[2], keepdims=0)
    graph = helper.make_graph(
        [node],
        "tiny",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 1, None])],
        [helper.make_tensor_value_info("risk", TensorProto.FLOAT, [1, 1])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    # The installed `onnx` package (1.23.0) defaults new models to IR version
    # 14, but the installed `onnxruntime` (1.20.1) only supports up to IR
    # version 10 -- a version-skew issue between the two packages, not
    # anything about this graph. Pin it down explicitly so the test fixture
    # actually loads; found by a real ort.InferenceSession failure:
    # "Unsupported model IR version: 14, max supported IR version: 10".
    model.ir_version = 9
    return model.SerializeToString()


def test_list_models_empty_initially(client):
    r = client.get("/api/model/list")
    assert r.status_code == 200
    assert r.json() == {"models": [], "active": "stub"}


def test_status_reports_stub_by_default(client):
    r = client.get("/api/status")
    assert r.json()["model"] == "Stub (heuristic)"


def test_upload_rejects_non_onnx_extension(client):
    r = client.post("/api/model/upload", files={"file": ("model.txt", b"not a model", "text/plain")})
    assert r.status_code == 400
    assert "onnx" in r.json()["detail"].lower()


def test_upload_valid_model_activates_it_immediately(client):
    r = client.post(
        "/api/model/upload", files={"file": ("risk_model.onnx", _tiny_valid_onnx_bytes(), "application/octet-stream")}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["active_model"] == "ONNX: risk_model.onnx"

    status = client.get("/api/status").json()
    assert status["model"] == "ONNX: risk_model.onnx"

    listing = client.get("/api/model/list").json()
    assert listing["active"] == "risk_model.onnx"
    assert listing["models"][0]["active"] is True


def test_corrupt_upload_does_not_disturb_a_working_active_model(client):
    """The core regression guard for the bug described in this file's
    docstring: uploading a bad file after a good one is active must leave the
    good one running, not silently fall back to the stub."""
    good = client.post(
        "/api/model/upload", files={"file": ("good.onnx", _tiny_valid_onnx_bytes(), "application/octet-stream")}
    )
    assert good.json()["ok"] is True

    bad = client.post(
        "/api/model/upload", files={"file": ("bad.onnx", b"not a real onnx file", "application/octet-stream")}
    )
    assert bad.status_code == 200
    assert bad.json()["ok"] is False
    assert "good.onnx" not in bad.json()["message"]  # error is about bad.onnx, not the working one

    # The critical assertion: status must STILL report the good model.
    status = client.get("/api/status").json()
    assert status["model"] == "ONNX: good.onnx", (
        "a failed upload must never replace a working active model with the stub"
    )

    # The corrupt file must not linger in the list.
    listing = client.get("/api/model/list").json()
    filenames = [m["filename"] for m in listing["models"]]
    assert "bad.onnx" not in filenames
    assert "good.onnx" in filenames


def test_reset_reverts_to_stub(client):
    client.post("/api/model/upload", files={"file": ("m.onnx", _tiny_valid_onnx_bytes(), "application/octet-stream")})
    r = client.post("/api/model/reset")
    assert r.status_code == 200
    assert r.json()["active_model"] == "Stub (heuristic)"
    assert client.get("/api/status").json()["model"] == "Stub (heuristic)"


def test_select_switches_to_a_previously_uploaded_model_without_reupload(client):
    client.post("/api/model/upload", files={"file": ("m.onnx", _tiny_valid_onnx_bytes(), "application/octet-stream")})
    client.post("/api/model/reset")
    assert client.get("/api/status").json()["model"] == "Stub (heuristic)"

    r = client.post("/api/model/select", json={"filename": "m.onnx"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert client.get("/api/status").json()["model"] == "ONNX: m.onnx"


def test_select_unknown_filename_returns_404(client):
    r = client.post("/api/model/select", json={"filename": "does_not_exist.onnx"})
    assert r.status_code == 404


def test_select_path_traversal_is_rejected(client):
    """model_registry.model_path must reject a filename that would escape
    models_dir, e.g. via '../'."""
    r = client.post("/api/model/select", json={"filename": "../../etc/passwd"})
    assert r.status_code in (400, 404)


def test_selection_persists_across_a_simulated_restart(client, isolated_dirs):
    client.post(
        "/api/model/upload", files={"file": ("persisted.onnx", _tiny_valid_onnx_bytes(), "application/octet-stream")}
    )
    assert model_registry.read_selection() == "persisted.onnx"

    # Simulate what main.py's lifespan does on startup: read the persisted
    # selection and resolve it to a path, without going through the running
    # app at all.
    selection = model_registry.read_selection()
    assert selection == "persisted.onnx"
    assert model_registry.model_path(selection).exists()


def test_upload_oversized_file_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "gs_max_model_upload_mb", 0)  # anything nonzero content exceeds "0 MB"
    r = client.post(
        "/api/model/upload", files={"file": ("m.onnx", _tiny_valid_onnx_bytes(), "application/octet-stream")}
    )
    assert r.status_code == 400
    assert "exceeds" in r.json()["detail"]
