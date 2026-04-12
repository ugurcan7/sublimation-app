"""
Grading accuracy tests — size_dimensions hesaplama doğruluğu
"""
import numpy as np
import pytest

from backend.grading import GradingEngine, _grade_piece_linear
from backend.models import PatternPiece


def _rect(size: str, ptype: str, w: float, h: float) -> PatternPiece:
    pts = np.array([[0, 0], [0, h], [w, h], [w, 0], [0, 0]], dtype=float)
    return PatternPiece(label=f"{size}_{ptype}", size=size, piece_type=ptype, points=pts)


def _dims(piece: PatternPiece) -> dict:
    """Replicate the size_dimensions logic from main.py."""
    pts = piece.points
    w = float(pts[:, 0].max() - pts[:, 0].min())
    h = float(pts[:, 1].max() - pts[:, 1].min())
    n = len(pts)
    area_mm2 = 0.0
    for i in range(n):
        j = (i + 1) % n
        area_mm2 += pts[i, 0] * pts[j, 1]
        area_mm2 -= pts[j, 0] * pts[i, 1]
    area_cm2 = abs(area_mm2) / 2.0 / 100.0
    return {
        "width_mm":  round(w, 1),
        "height_mm": round(h, 1),
        "area_cm2":  round(area_cm2, 1),
    }


# ─── Boyut hesaplama doğruluğu ────────────────────────────────────────────────

def test_dims_base_rect():
    """200×300 mm dikdörtgen → beklenen boyutlar."""
    piece = _rect("BASE", "front", 200.0, 300.0)
    d = _dims(piece)
    assert d["width_mm"]  == pytest.approx(200.0, abs=0.1)
    assert d["height_mm"] == pytest.approx(300.0, abs=0.1)
    assert d["area_cm2"]  == pytest.approx(600.0, abs=0.1)  # 200*300/100


def test_dims_area_shoelace():
    """Shoelace formülü: 100×50 mm → 50 cm²."""
    piece = _rect("M", "back", 100.0, 50.0)
    d = _dims(piece)
    assert d["area_cm2"] == pytest.approx(50.0, abs=0.1)


def test_step_width_accuracy():
    """Her beden adımında genişlik tam olarak width_step_mm artmalı."""
    base = _rect("BASE", "front", 500.0, 700.0)
    grouped = {"BASE": {"front": base}}
    engine = GradingEngine(grouped, reference_size="BASE")
    result = engine.grade_all_flat(["S", "M", "L", "XL"], ref_size_key="M",
                                   width_step_mm=4.0, height_step_mm=2.0)
    sizes = ["S", "M", "L", "XL"]
    widths = [_dims(result[s]["front"])["width_mm"] for s in sizes]
    for i in range(1, len(widths)):
        assert widths[i] - widths[i-1] == pytest.approx(4.0, abs=0.15)


def test_step_height_accuracy():
    """Her beden adımında yükseklik tam olarak height_step_mm artmalı."""
    base = _rect("BASE", "front", 500.0, 700.0)
    grouped = {"BASE": {"front": base}}
    engine = GradingEngine(grouped, reference_size="BASE")
    result = engine.grade_all_flat(["S", "M", "L"], ref_size_key="M",
                                   width_step_mm=4.0, height_step_mm=2.0)
    h_s  = _dims(result["S"]["front"])["height_mm"]
    h_m  = _dims(result["M"]["front"])["height_mm"]
    h_l  = _dims(result["L"]["front"])["height_mm"]
    assert h_m - h_s == pytest.approx(2.0, abs=0.15)
    assert h_l - h_m == pytest.approx(2.0, abs=0.15)


def test_area_increases_with_size():
    """Büyük bedenin alanı küçük bedenden fazla olmalı."""
    base = _rect("BASE", "front", 500.0, 700.0)
    grouped = {"BASE": {"front": base}}
    engine = GradingEngine(grouped, reference_size="BASE")
    result = engine.grade_all_flat(["S", "L"], ref_size_key="M",
                                   width_step_mm=4.0, height_step_mm=2.0)
    area_s = _dims(result["S"]["front"])["area_cm2"]
    area_l = _dims(result["L"]["front"])["area_cm2"]
    assert area_l > area_s


def test_numeric_sizes_step_accuracy():
    """Numerik beden isimleriyle adım doğruluğu: 36→38→40."""
    base = _rect("BASE", "front", 480.0, 680.0)
    grouped = {"BASE": {"front": base}}
    engine = GradingEngine(grouped, reference_size="BASE")
    result = engine.grade_all_flat(["36", "38", "40"], ref_size_key="38",
                                   width_step_mm=4.0, height_step_mm=2.0)
    w36 = _dims(result["36"]["front"])["width_mm"]
    w38 = _dims(result["38"]["front"])["width_mm"]
    w40 = _dims(result["40"]["front"])["width_mm"]
    assert w38 - w36 == pytest.approx(4.0, abs=0.15)
    assert w40 - w38 == pytest.approx(4.0, abs=0.15)


def test_reference_size_unchanged():
    """Referans beden (M) boyutları değişmemeli."""
    base = _rect("BASE", "front", 500.0, 700.0)
    grouped = {"BASE": {"front": base}}
    engine = GradingEngine(grouped, reference_size="BASE")
    result = engine.grade_all_flat(["S", "M", "L"], ref_size_key="M",
                                   width_step_mm=4.0, height_step_mm=2.0)
    d = _dims(result["M"]["front"])
    assert d["width_mm"]  == pytest.approx(500.0, abs=0.1)
    assert d["height_mm"] == pytest.approx(700.0, abs=0.1)
