"""
model_registry.py -- file management for user-uploaded ONNX models, backing
the frontend's Model page (docs/API_CONTRACT.md section 3.1).

Kept separate from api/routes.py (which stays thin, per AGENTS.md) and from
inference.py (which only knows how to *run* a model, not manage files of
them). Three responsibilities: list what's in config.models_dir, save an
upload there, and persist/read which one is currently selected so a restart
doesn't silently forget it and fall back to the stub.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger("glucosentry.model_registry")


def ensure_models_dir() -> None:
    settings.models_dir.mkdir(parents=True, exist_ok=True)


def list_models() -> list[dict]:
    """Every .onnx file in config.models_dir, newest first."""
    ensure_models_dir()
    entries = []
    for p in settings.models_dir.glob("*.onnx"):
        stat = p.stat()
        entries.append({"filename": p.name, "size_bytes": stat.st_size, "uploaded_ts": stat.st_mtime})
    entries.sort(key=lambda e: e["uploaded_ts"], reverse=True)
    return entries


def model_path(filename: str) -> Path:
    """Resolves a filename to a path inside models_dir, rejecting anything
    that would escape it (e.g. '../../etc/passwd') -- filenames here
    ultimately come from an HTTP request, so this is not just defensive
    style, it is the one thing standing between an upload/select request and
    writing or reading outside the intended directory."""
    candidate = (settings.models_dir / Path(filename).name).resolve()
    models_dir_resolved = settings.models_dir.resolve()
    if models_dir_resolved not in candidate.parents and candidate != models_dir_resolved:
        raise ValueError(f"invalid model filename: {filename}")
    return candidate


def save_upload(filename: str, content: bytes) -> Path:
    ensure_models_dir()
    if not filename.lower().endswith(".onnx"):
        raise ValueError("only .onnx files are accepted")
    max_bytes = settings.gs_max_model_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ValueError(f"file exceeds the {settings.gs_max_model_upload_mb} MB limit")
    dest = model_path(filename)
    dest.write_bytes(content)
    logger.info("saved uploaded model to %s (%d bytes)", dest, len(content))
    return dest


def read_selection() -> Optional[str]:
    """The filename (relative to models_dir) persisted as the active
    selection, or None for "use the stub". Missing/empty file -> None,
    treated the same as "no selection yet" rather than an error, so a fresh
    checkout with no prior selection just starts on the stub."""
    p = settings.model_selection_path
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8").strip()
    return text or None


def write_selection(filename: Optional[str]) -> None:
    p = settings.model_selection_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(filename or "", encoding="utf-8")


def delete_model(filename: str) -> None:
    path = model_path(filename)
    if path.exists():
        path.unlink()
        logger.info("deleted model %s", path)
