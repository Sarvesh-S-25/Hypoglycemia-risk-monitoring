"""GET /api/diagnostics (the engineering view's data) and the no-score state
of GET /api/risk/current, against the real app with no data source running."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "gs_source", "none")  # no windows at all
    monkeypatch.setattr(settings, "gs_aux_source", "simulator")
    monkeypatch.setattr(settings, "gs_db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "gs_model_selection_path", str(tmp_path / "selection.txt"))
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_risk_current_is_null_before_any_score(client):
    body = client.get("/api/risk/current").json()
    assert body["score"] is None
    assert body["timestamp"] is None


def test_status_has_no_ready_estimate_without_signal(client):
    assert client.get("/api/status").json()["risk_ready_in_s"] is None


def test_diagnostics_shape(client):
    d = client.get("/api/diagnostics").json()
    assert set(d) >= {"timestamp", "link", "pipeline", "model", "controller", "foot"}
    assert d["pipeline"]["windows_total"] == 0
    assert d["controller"]["risk_alert"] == settings.risk_alert
    assert d["controller"]["confirm_windows"] == settings.confirm_windows
    assert d["foot"]["elevated_threshold_c"] == settings.foot_check_elevated_threshold_c
    assert d["model"]["needed_s"] >= 0
