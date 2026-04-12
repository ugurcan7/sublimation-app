"""SVG üretimi testleri"""
import tempfile
from pathlib import Path

import numpy as np
import pytest

from backend.design_placer import SVGDesignPlacer
from backend.models import GradedPiece


def _make_piece(w=500, h=700, size="M", ptype="front"):
    pts = np.array([
        [0, 0], [0, h], [w, h], [w, 0], [0, 0]
    ], dtype=float)
    return GradedPiece(piece_type=ptype, size=size, points=pts)


def test_generate_svg_no_design():
    """Tasarımsız SVG üretimi — hata vermemeli, polygon içermeli."""
    piece = _make_piece()
    placer = SVGDesignPlacer()
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
        out_path = f.name
    try:
        svg = placer.generate_svg(piece, design_image_path=None, output_path=out_path)
        assert "<svg" in svg
        assert "<polygon" in svg or "<path" in svg
    finally:
        Path(out_path).unlink(missing_ok=True)


def test_generate_svg_with_dimensions():
    """SVG doğru viewBox boyutlarına sahip olmalı."""
    piece = _make_piece(w=300, h=500)
    placer = SVGDesignPlacer()
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
        out_path = f.name
    try:
        svg = placer.generate_svg(piece, design_image_path=None, output_path=out_path)
        assert "viewBox" in svg
    finally:
        Path(out_path).unlink(missing_ok=True)


def test_generate_svg_offset():
    """offset_x/y ve scale parametreleri hata vermemeli."""
    piece = _make_piece()
    placer = SVGDesignPlacer()
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
        out_path = f.name
    try:
        svg = placer.generate_svg(
            piece, design_image_path=None, output_path=out_path,
            offset_x=0.1, offset_y=-0.1, scale=1.2
        )
        assert "<svg" in svg
    finally:
        Path(out_path).unlink(missing_ok=True)


def test_generate_svg_saves_file():
    """generate_svg çıktıyı dosyaya kaydetmeli."""
    piece = _make_piece()
    placer = SVGDesignPlacer()
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
        out_path = f.name
    try:
        placer.generate_svg(piece, design_image_path=None, output_path=out_path)
        assert Path(out_path).exists()
        assert Path(out_path).stat().st_size > 0
    finally:
        Path(out_path).unlink(missing_ok=True)


def test_generate_svg_cut_line():
    """Kesim çizgisi varsayılan olarak eklenmiş olmalı."""
    piece = _make_piece()
    placer = SVGDesignPlacer()
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
        out_path = f.name
    try:
        svg = placer.generate_svg(piece, design_image_path=None, output_path=out_path, cut_line=True)
        assert 'stroke="#000000"' in svg
    finally:
        Path(out_path).unlink(missing_ok=True)
