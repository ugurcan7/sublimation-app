"""SQLite persist/load testleri"""
import tempfile
from datetime import datetime
from pathlib import Path
import numpy as np
import pytest

from backend.db import init_db, save_session, load_all_sessions, delete_session
from backend.models import UploadSession, PatternPiece


def _make_session(sid="test-001"):
    s = UploadSession(session_id=sid, reference_size="M", created_at=datetime(2026, 1, 1))
    s.parsed_pieces = {
        "M": {
            "front": PatternPiece(
                label="M_FRONT", size="M", piece_type="front",
                points=np.array([[0,0],[0,100],[80,100],[80,0],[0,0]], dtype=float)
            )
        }
    }
    s.design_files = {"front": "/tmp/test_design.jpg"}
    s.errors = ["test hatası"]
    return s


def test_save_and_load():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Path(f.name)
    try:
        init_db(db)
        s = _make_session()
        save_session(db, s)
        loaded = load_all_sessions(db)
        assert "test-001" in loaded
        s2 = loaded["test-001"]
        assert s2.session_id == "test-001"
        assert s2.reference_size == "M"
        assert "M" in s2.parsed_pieces
        assert "front" in s2.parsed_pieces["M"]
        pts = s2.parsed_pieces["M"]["front"].points
        assert pts.shape == (5, 2)
        np.testing.assert_allclose(pts[1], [0, 100])
    finally:
        db.unlink(missing_ok=True)


def test_delete_session():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Path(f.name)
    try:
        init_db(db)
        save_session(db, _make_session("del-001"))
        save_session(db, _make_session("del-002"))
        delete_session(db, "del-001")
        loaded = load_all_sessions(db)
        assert "del-001" not in loaded
        assert "del-002" in loaded
    finally:
        db.unlink(missing_ok=True)


def test_overwrite_session():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Path(f.name)
    try:
        init_db(db)
        s = _make_session()
        save_session(db, s)
        s.reference_size = "L"
        save_session(db, s)
        loaded = load_all_sessions(db)
        assert loaded["test-001"].reference_size == "L"
    finally:
        db.unlink(missing_ok=True)


def test_empty_db_returns_empty():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Path(f.name)
    try:
        init_db(db)
        loaded = load_all_sessions(db)
        assert loaded == {}
    finally:
        db.unlink(missing_ok=True)


def test_numpy_roundtrip():
    """numpy array serialize → deserialize sonrası aynı değerler."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Path(f.name)
    try:
        init_db(db)
        orig_pts = np.array([[1.5, 2.3],[3.7, 4.1],[5.0, 6.9]], dtype=float)
        s = _make_session("np-001")
        s.parsed_pieces["M"]["front"].points = orig_pts
        save_session(db, s)
        loaded = load_all_sessions(db)
        loaded_pts = loaded["np-001"].parsed_pieces["M"]["front"].points
        np.testing.assert_allclose(loaded_pts, orig_pts)
    finally:
        db.unlink(missing_ok=True)
