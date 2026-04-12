"""
PLT Parser testleri
"""
import textwrap
import tempfile
from pathlib import Path

import numpy as np
import pytest

from backend.plt_parser import PLTParser, group_pieces, _normalize_size
from backend.models import PatternPiece


# ─── _normalize_size ──────────────────────────────────────────────────────────

def test_normalize_letter_sizes():
    assert _normalize_size("xs") == "XS"
    assert _normalize_size("m")  == "M"
    assert _normalize_size("XL") == "XL"
    assert _normalize_size("xxxl") == "XXXL"

def test_normalize_multixl():
    assert _normalize_size("2XL") == "XXL"
    assert _normalize_size("3XL") == "XXXL"
    assert _normalize_size("4XL") == "XXXL"

def test_normalize_numeric_kept_as_is():
    """Numerik bedenler normalize edilmemeli — PLT adı korunmalı."""
    assert _normalize_size("36") == "36"
    assert _normalize_size("40") == "40"
    assert _normalize_size("44") == "44"

def test_normalize_empty():
    assert _normalize_size("") == ""


# ─── PLTParser ────────────────────────────────────────────────────────────────

def _write_plt(content: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".plt", delete=False, mode="w", encoding="latin-1")
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


def test_parse_simple_square():
    """4 köşeli bir kare → en az 1 parça döner."""
    # 200×200 mm → 200*40=8000 HPGL birim
    plt_content = textwrap.dedent("""\
        IN;SP1;
        PU0,0;PD0,8000,8000,8000,8000,0,0,0;PU;
    """)
    path = _write_plt(plt_content)
    try:
        pieces = PLTParser(path).parse()
        assert len(pieces) >= 1
        p = pieces[0]
        assert p.area() > 100  # mm² cinsinden > 100
    finally:
        path.unlink(missing_ok=True)


def test_parse_labeled_pieces():
    """Etiketli PLT → beden ve parça tipi doğru atanmalı."""
    plt_content = textwrap.dedent("""\
        IN;SP1;
        LB M_FRONT\x03
        PU0,0;PD0,16000,12000,16000,12000,0,0,0;PU;
    """)
    path = _write_plt(plt_content)
    try:
        pieces = PLTParser(path).parse()
        assert len(pieces) >= 1
        fronts = [p for p in pieces if p.piece_type == "front"]
        assert len(fronts) >= 1
        assert fronts[0].size == "M"
    finally:
        path.unlink(missing_ok=True)


def test_parse_numeric_size_label():
    """Numerik beden etiketi (36) olduğu gibi korunmalı."""
    plt_content = textwrap.dedent("""\
        IN;SP1;
        LB 36_FRONT\x03
        PU0,0;PD0,16000,12000,16000,12000,0,0,0;PU;
    """)
    path = _write_plt(plt_content)
    try:
        pieces = PLTParser(path).parse()
        sized = [p for p in pieces if p.size == "36"]
        assert len(sized) >= 1, f"Beklenen '36', bulunan: {[p.size for p in pieces]}"
    finally:
        path.unlink(missing_ok=True)


def test_group_pieces_deduplicates():
    """Aynı size+type için en büyük alan alınmalı."""
    small = PatternPiece(label="", size="M", piece_type="front",
                         points=np.array([[0,0],[0,100],[100,100],[100,0],[0,0]], dtype=float))
    large = PatternPiece(label="", size="M", piece_type="front",
                         points=np.array([[0,0],[0,200],[200,200],[200,0],[0,0]], dtype=float))
    grouped = group_pieces([small, large])
    assert grouped["M"]["front"].area() == large.area()


def test_too_small_pieces_filtered():
    """Alan < 500 mm² olan parçalar atılmalı."""
    plt_content = textwrap.dedent("""\
        IN;SP1;
        PU0,0;PD0,400,400,400,400,0,0,0;PU;
    """)
    path = _write_plt(plt_content)
    try:
        pieces = PLTParser(path).parse()
        assert all(p.area() >= 500 for p in pieces)
    finally:
        path.unlink(missing_ok=True)
