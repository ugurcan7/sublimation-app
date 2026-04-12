"""
Grading engine testleri
"""
import numpy as np
import pytest

from backend.grading import GradingEngine, _grade_piece_linear
from backend.models import PatternPiece, GradedPiece


def _make_rect(size: str, ptype: str, w: float, h: float) -> PatternPiece:
    """w×h mm dikdörtgen parça oluştur."""
    pts = np.array([
        [0, 0], [0, h], [w, h], [w, 0], [0, 0]
    ], dtype=float)
    return PatternPiece(label=f"{size}_{ptype}", size=size, piece_type=ptype, points=pts)


# ─── _grade_piece_linear ──────────────────────────────────────────────────────

def test_linear_grade_zero_steps():
    """steps=0 → parça değişmemeli."""
    piece = _make_rect("M", "front", 500, 700)
    graded = _grade_piece_linear(piece, "M", steps=0, width_step_mm=4.0, height_step_mm=2.0)
    np.testing.assert_allclose(graded.points, piece.points, atol=1e-6)


def _bb(pts: np.ndarray):
    return pts[:, 0].max() - pts[:, 0].min(), pts[:, 1].max() - pts[:, 1].min()


def test_linear_grade_positive_step():
    """steps=+1 → beden 4mm genişlemeli."""
    piece = _make_rect("M", "front", 500, 700)
    graded = _grade_piece_linear(piece, "L", steps=1, width_step_mm=4.0, height_step_mm=2.0)
    w_orig, h_orig   = _bb(piece.points)
    w_graded, h_graded = _bb(graded.points)
    assert w_graded == pytest.approx(w_orig + 4.0, abs=0.1)
    assert h_graded == pytest.approx(h_orig + 2.0, abs=0.1)


def test_linear_grade_negative_step():
    """steps=-1 → beden 4mm daralmalı."""
    piece = _make_rect("M", "front", 500, 700)
    graded = _grade_piece_linear(piece, "S", steps=-1, width_step_mm=4.0, height_step_mm=2.0)
    w_orig, h_orig   = _bb(piece.points)
    w_graded, h_graded = _bb(graded.points)
    assert w_graded == pytest.approx(w_orig - 4.0, abs=0.1)
    assert h_graded == pytest.approx(h_orig - 2.0, abs=0.1)


def test_linear_grade_centroid_preserved():
    """Grading merkezden yapılmalı → centroid aynı kalmalı."""
    piece = _make_rect("M", "front", 500, 700)
    graded = _grade_piece_linear(piece, "L", steps=2, width_step_mm=4.0, height_step_mm=2.0)
    np.testing.assert_allclose(graded.points.mean(axis=0), piece.points.mean(axis=0), atol=1e-6)


# ─── GradingEngine.grade_all_flat ────────────────────────────────────────────

def test_grade_all_flat_produces_all_sizes():
    """grade_all_flat → istenen tüm bedenler üretilmeli."""
    base_pieces = {
        "front": _make_rect("BASE", "front", 500, 700),
        "back":  _make_rect("BASE", "back",  500, 680),
    }
    grouped = {"BASE": base_pieces}
    engine = GradingEngine(grouped, reference_size="BASE")
    result = engine.grade_all_flat(["S", "M", "L"])
    assert set(result.keys()) == {"S", "M", "L"}


def test_grade_all_flat_step_counts():
    """Referans beden = M → S bir adım küçük, L bir adım büyük."""
    piece = _make_rect("BASE", "front", 500, 700)
    grouped = {"BASE": {"front": piece}}
    engine = GradingEngine(grouped, reference_size="BASE")
    result = engine.grade_all_flat(["S", "M", "L"], ref_size_key="M",
                                   width_step_mm=4.0, height_step_mm=2.0)
    w_s, _ = _bb(result["S"]["front"].points)
    w_m, _ = _bb(result["M"]["front"].points)
    w_l, _ = _bb(result["L"]["front"].points)

    assert w_s < w_m < w_l
    assert w_l - w_m == pytest.approx(4.0, abs=0.1)
    assert w_m - w_s == pytest.approx(4.0, abs=0.1)


def test_grade_all_flat_numeric_sizes():
    """Numerik beden isimleri (36, 38, 40) ile grade_all_flat çalışmalı."""
    piece = _make_rect("BASE", "front", 500, 700)
    grouped = {"BASE": {"front": piece}}
    engine = GradingEngine(grouped, reference_size="BASE")
    result = engine.grade_all_flat(["36", "38", "40"], ref_size_key="38",
                                   width_step_mm=4.0, height_step_mm=2.0)
    assert set(result.keys()) == {"36", "38", "40"}
    w_36, _ = _bb(result["36"]["front"].points)
    w_38, _ = _bb(result["38"]["front"].points)
    w_40, _ = _bb(result["40"]["front"].points)
    assert w_36 < w_38 < w_40
