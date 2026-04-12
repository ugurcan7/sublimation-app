"""
SQLite Session Kalıcılığı
=========================
Pickle yerine SQLite kullanır — worker restart'larında oturumlar kaybolmaz.
PatternPiece.points numpy dizileri JSON listesine dönüştürülür.
"""
from __future__ import annotations

import json
import logging
import pickle
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict

import numpy as np

from .models import GradedPiece, PatternPiece, UploadSession

logger = logging.getLogger(__name__)

DB_VERSION = 1


# ─── Init ─────────────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    """Veritabanı ve tabloları oluştur."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id          TEXT PRIMARY KEY,
                data_json   TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("INSERT OR IGNORE INTO meta VALUES ('version', ?)", (str(DB_VERSION),))


# ─── CRUD ─────────────────────────────────────────────────────────────────────

def save_session(db_path: Path, session: UploadSession) -> None:
    try:
        data = _serialize_session(session)
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions (id, data_json, created_at) VALUES (?, ?, ?)",
                (session.session_id, data, session.created_at.isoformat()),
            )
    except Exception as e:
        logger.warning(f"SQLite kayıt hatası: {e}")


def load_all_sessions(db_path: Path) -> Dict[str, UploadSession]:
    if not db_path.exists():
        return {}
    loaded: Dict[str, UploadSession] = {}
    try:
        with sqlite3.connect(str(db_path)) as conn:
            rows = conn.execute("SELECT id, data_json FROM sessions").fetchall()
        for sid, data_json in rows:
            try:
                loaded[sid] = _deserialize_session(data_json)
            except Exception as e:
                logger.warning(f"Oturum {sid} yüklenemedi: {e}")
        logger.info(f"SQLite'dan {len(loaded)} oturum yüklendi")
    except Exception as e:
        logger.warning(f"SQLite yükleme hatası: {e}")
    return loaded


def delete_session(db_path: Path, session_id: str) -> None:
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    except Exception as e:
        logger.warning(f"SQLite silme hatası: {e}")


def delete_sessions_batch(db_path: Path, session_ids: list) -> None:
    """Birden fazla oturumu tek sorguda sil."""
    if not session_ids:
        return
    try:
        placeholders = ",".join("?" * len(session_ids))
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                f"DELETE FROM sessions WHERE id IN ({placeholders})", session_ids
            )
        logger.info(f"SQLite: {len(session_ids)} oturum toplu silindi")
    except Exception as e:
        logger.warning(f"SQLite toplu silme hatası: {e}")


# ─── Pickle → SQLite migration ────────────────────────────────────────────────

def migrate_from_pickle(pkl_path: Path, db_path: Path) -> None:
    """Eski pickle dosyasını SQLite'a aktar (bir kez çalışır)."""
    if not pkl_path.exists():
        return
    try:
        with open(pkl_path, "rb") as f:
            old: Dict[str, UploadSession] = pickle.load(f)
        init_db(db_path)
        for session in old.values():
            save_session(db_path, session)
        pkl_path.rename(pkl_path.with_suffix(".pkl.migrated"))
        logger.info(f"Pickle → SQLite: {len(old)} oturum aktarıldı")
    except Exception as e:
        logger.warning(f"Migration hatası (önemsiz): {e}")


# ─── Serialize ────────────────────────────────────────────────────────────────

def _serialize_session(session: UploadSession) -> str:
    d = {
        "session_id": session.session_id,
        "reference_size": session.reference_size,
        "plt_path": session.plt_path,
        "created_at": session.created_at.isoformat(),
        "design_files": session.design_files,
        "output_pdfs": session.output_pdfs,
        "output_svgs": session.output_svgs,
        "errors": session.errors,
        "parsed_pieces": _serialize_pieces(session.parsed_pieces),
    }
    return json.dumps(d, ensure_ascii=False)


def _serialize_pieces(grouped: dict) -> dict:
    result = {}
    for size, piece_dict in grouped.items():
        result[size] = {}
        for ptype, piece in piece_dict.items():
            pts = piece.points
            result[size][ptype] = {
                "label": getattr(piece, "label", ""),
                "size": getattr(piece, "size", size),
                "piece_type": getattr(piece, "piece_type", ptype),
                "points": pts.tolist() if isinstance(pts, np.ndarray) else list(pts),
            }
    return result


# ─── Deserialize ──────────────────────────────────────────────────────────────

def _deserialize_session(data_json: str) -> UploadSession:
    d = json.loads(data_json)
    session = UploadSession(
        session_id=d["session_id"],
        reference_size=d.get("reference_size", "M"),
        plt_path=d.get("plt_path"),
        created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else datetime.now(),
    )
    session.design_files = d.get("design_files", {})
    session.output_pdfs  = d.get("output_pdfs", {})
    session.output_svgs  = d.get("output_svgs", {})
    session.errors       = d.get("errors", [])
    session.parsed_pieces = _deserialize_pieces(d.get("parsed_pieces", {}))
    session.grading_vectors = {}  # vektörler yeniden hesaplanabilir
    return session


def _deserialize_pieces(raw: dict) -> dict:
    result = {}
    for size, piece_dict in raw.items():
        result[size] = {}
        for ptype, pdata in piece_dict.items():
            pts = np.array(pdata["points"], dtype=float)
            result[size][ptype] = PatternPiece(
                label=pdata.get("label", ""),
                size=pdata.get("size", size),
                piece_type=pdata.get("piece_type", ptype),
                points=pts,
            )
    return result
