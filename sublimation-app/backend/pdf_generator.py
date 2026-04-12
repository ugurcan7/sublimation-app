"""
PDF Üretici
===========
Cairo gerektirmez — Pillow + reportlab ile çalışır.

Strateji:
  1. Her beden için tüm parçaları tek bir büyük Pillow canvas'ına yerleştir
  2. Her parça için tasarım görselini polygon mask ile kes (Pillow ImageDraw)
  3. Parça üzerine kesim çizgisi çiz
  4. Canvas'ı PDF olarak kaydet (Pillow native PDF export)

Opsiyonel: reportlab ile çok sayfalı PDF desteği
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .models import GradedPiece

logger = logging.getLogger(__name__)

DPI = 300
MM_PER_INCH = 25.4
PX_PER_MM = DPI / MM_PER_INCH   # ~11.811

# Parça arası boşluk (mm)
MARGIN_MM = 20.0

# Parça tipi renkleri (kesim çizgisi rengi)
CUT_COLORS: Dict[str, Tuple[int, int, int]] = {
    "front":        (37,  99, 235),   # mavi
    "back":         (124, 58, 237),   # mor
    "left_sleeve":  (5,  150, 105),   # yeşil
    "right_sleeve": (217, 119,  6),   # turuncu
    "unknown":      (100, 116, 139),  # gri
}


# ─── Ana PDF üretim fonksiyonu ────────────────────────────────────────────────

def generate_size_pdf(
    svg_paths_by_piece: Dict[str, str],    # artık kullanılmıyor (uyumluluk için)
    output_pdf_path: str,
    size: str,
    dpi: int = DPI,
    combined_svg_path: Optional[str] = None,   # artık kullanılmıyor
    graded_pieces: Optional[Dict[str, GradedPiece]] = None,
    design_files: Optional[Dict[str, str]] = None,
    bleed_mm: float = 3.0,
    rotations: Optional[Dict[str, int]] = None,
) -> bool:
    """
    Bir beden için PDF üret.
    graded_pieces ve design_files verilirse Pillow ile render eder.
    Verilmezse SVG dizininden PNG dönüşümü dener.
    """
    if graded_pieces is not None:
        return _render_pdf_with_pillow(
            graded_pieces=graded_pieces,
            design_files=design_files or {},
            output_pdf_path=output_pdf_path,
            size=size,
            dpi=dpi,
            bleed_mm=bleed_mm,
            rotations=rotations or {},
        )

    # Eski yol: SVG yollarından türet (SVG → PNG → PDF)
    # SVG render edemiyorsak basit placeholder PDF üret
    return _placeholder_pdf(output_pdf_path, size, list(svg_paths_by_piece.keys()))


def svg_to_pdf(svg_path: str, pdf_path: str, dpi: int = DPI) -> bool:
    """Tek SVG → PDF (uyumluluk stub — placeholder üretir)."""
    return _placeholder_pdf(pdf_path, Path(svg_path).stem, [])


def svg_files_to_pdf(svg_paths: List[str], pdf_path: str, dpi: int = DPI) -> bool:
    return _placeholder_pdf(pdf_path, "output", [Path(p).stem for p in svg_paths])


# ─── Pillow tabanlı render ────────────────────────────────────────────────────

PIECE_NAMES_TR: Dict[str, str] = {
    "front":        "Ön",
    "back":         "Arka",
    "left_sleeve":  "Sol Kol",
    "right_sleeve": "Sağ Kol",
    "sleeve":       "Kol",
    "strip":        "Şerit",
    "panel_front":  "Ön Panel",
    "panel_back":   "Arka Panel",
}

def _piece_name_tr(ptype: str) -> str:
    base = ptype.rstrip("_0123456789")
    suffix = ptype[len(base):]
    name = PIECE_NAMES_TR.get(base, ptype.replace("_", " ").title())
    return f"{name} {suffix.strip('_')}" if suffix.strip("_") else name


def _load_font(size: int) -> "ImageFont.FreeTypeFont":
    """Platform-bağımsız font yükle."""
    paths = [
        "/System/Library/Fonts/Helvetica.ttc",   # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
        "C:/Windows/Fonts/arial.ttf",            # Windows
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _render_pdf_with_pillow(
    graded_pieces: Dict[str, GradedPiece],
    design_files: Dict[str, str],
    output_pdf_path: str,
    size: str,
    dpi: int,
    bleed_mm: float,
    rotations: Optional[Dict[str, int]] = None,
) -> bool:
    """
    Pillow ile render et:
    1. Her parça için tasarım görselini polygon mask ile kes
    2. Tüm parçaları grid düzeninde büyük canvas'a yerleştir
    3. PDF olarak kaydet
    """
    px_per_mm = dpi / MM_PER_INCH
    margin_px = int(MARGIN_MM * px_per_mm)
    bleed_px  = int(bleed_mm * px_per_mm)
    rotations = rotations or {}

    # Tasarım olmayan parçaları atla
    piece_list = [
        (ptype, gp) for ptype, gp in graded_pieces.items()
        if design_files.get(ptype) and os.path.exists(design_files[ptype])
    ]
    if not piece_list:
        logger.warning(f"Beden {size}: tasarım yüklü parça yok, PDF üretilmedi")
        return False

    n_cols = min(2, len(piece_list))
    n_rows = math.ceil(len(piece_list) / n_cols)

    # Her parçanın pixel boyutlarını hesapla
    piece_images: Dict[str, Image.Image] = {}
    piece_sizes: List[Tuple[int, int]] = []

    for idx, (ptype, gp) in enumerate(piece_list):
        design_path = design_files.get(ptype)
        rot = rotations.get(ptype, 0)
        img = _render_piece(gp, design_path, px_per_mm, bleed_px, rotation=rot)
        piece_images[ptype] = img
        piece_sizes.append(img.size)

    # Grid boyutları
    col_widths  = []
    row_heights = []
    for col in range(n_cols):
        max_w = 0
        for row in range(n_rows):
            idx = row * n_cols + col
            if idx < len(piece_sizes):
                max_w = max(max_w, piece_sizes[idx][0])
        col_widths.append(max_w + margin_px)

    for row in range(n_rows):
        max_h = 0
        for col in range(n_cols):
            idx = row * n_cols + col
            if idx < len(piece_sizes):
                max_h = max(max_h, piece_sizes[idx][1])
        row_heights.append(max_h + margin_px)

    canvas_w = sum(col_widths) + margin_px
    canvas_h = sum(row_heights) + margin_px

    canvas = Image.new("RGB", (canvas_w, canvas_h), color=(248, 250, 252))
    draw = ImageDraw.Draw(canvas)

    # Başlık
    _draw_header(draw, canvas_w, size, dpi)

    # Parçaları yerleştir
    for idx, (ptype, gp) in enumerate(piece_list):
        row = idx // n_cols
        col = idx % n_cols

        ox = margin_px + sum(col_widths[:col])
        oy = margin_px + sum(row_heights[:row]) + int(12 * px_per_mm)  # başlık boşluğu

        piece_img = piece_images[ptype]
        canvas.paste(piece_img, (ox, oy))

    # PDF olarak kaydet (Pillow native)
    Path(output_pdf_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        canvas.save(
            output_pdf_path,
            "PDF",
            resolution=dpi,
            save_all=False,
        )
        logger.info(f"PDF üretildi (Pillow): {output_pdf_path} — {canvas_w}×{canvas_h}px @ {dpi}DPI")
        return True
    except Exception as e:
        logger.error(f"Pillow PDF kayıt hatası: {e}")
        # JPEG fallback
        try:
            jpeg_path = output_pdf_path.replace(".pdf", "_preview.jpg")
            canvas.save(jpeg_path, "JPEG", quality=95, dpi=(dpi, dpi))
            logger.info(f"JPEG önizleme kaydedildi: {jpeg_path}")
            # Minimal PDF wrapper
            _write_minimal_pdf(output_pdf_path, jpeg_path, canvas.size, dpi)
            return True
        except Exception as e2:
            logger.error(f"PDF/JPEG fallback hatası: {e2}")
            return False


def _render_piece(
    gp: GradedPiece,
    design_path: Optional[str],
    px_per_mm: float,
    bleed_px: int,
    rotation: int = 0,
) -> Image.Image:
    """
    Tek bir kalıp parçasını Pillow Image olarak render et.
    """
    pts = gp.points
    min_x, min_y = pts[:, 0].min(), pts[:, 1].min()
    max_x, max_y = pts[:, 0].max(), pts[:, 1].max()

    w_mm = max_x - min_x
    h_mm = max_y - min_y

    w_px = int((w_mm + 2 * bleed_px / px_per_mm) * px_per_mm) + 1
    h_px = int((h_mm + 2 * bleed_px / px_per_mm) * px_per_mm) + 1

    # Parça noktalarını pixel koordinatlarına çevir
    offset_x = -min_x * px_per_mm + bleed_px
    offset_y = -min_y * px_per_mm + bleed_px
    poly_px = [(int(x * px_per_mm + offset_x), int(y * px_per_mm + offset_y))
               for x, y in pts]

    # ── 1. Polygon mask ──
    mask = Image.new("L", (w_px, h_px), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.polygon(poly_px, fill=255)

    # ── 2. Tasarım görseli ──
    if design_path and os.path.exists(design_path):
        try:
            design = Image.open(design_path).convert("RGBA")
            # Rotation uygula
            if rotation:
                design = design.rotate(-rotation, expand=True)
            # Parça boyutuna sığdır (fill — kırparak)
            design_resized = _fit_cover(design, w_px, h_px)
            # Mask uygula
            result = Image.new("RGBA", (w_px, h_px), (255, 255, 255, 0))
            result.paste(design_resized, (0, 0))
            result.putalpha(mask)
            # RGB'ye dönüştür (beyaz arka plan)
            bg = Image.new("RGB", (w_px, h_px), (255, 255, 255))
            bg.paste(result, mask=result.split()[3])
            piece_img = bg
        except Exception as e:
            logger.warning(f"Tasarım görsel hatası ({gp.piece_type}): {e}")
            piece_img = _solid_fill(w_px, h_px, mask, (220, 220, 220))
    else:
        piece_img = _solid_fill(w_px, h_px, mask, (232, 232, 232))

    # ── 3. Kesim çizgisi ──
    draw = ImageDraw.Draw(piece_img)
    color = CUT_COLORS.get(gp.piece_type, CUT_COLORS["unknown"])
    cut_width = max(2, int(px_per_mm * 0.3))  # ~0.3mm kalınlık
    draw.polygon(poly_px, outline=color + (0,)[:0], width=cut_width)
    # PIL polygon outline — sadece kenarları çiz
    for i in range(len(poly_px)):
        draw.line([poly_px[i], poly_px[(i+1) % len(poly_px)]], fill=color, width=cut_width)

    return piece_img


def _fit_cover(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Görseli hedef boyutu tamamen kaplayacak şekilde ölçekle (cover)."""
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    # Ortala ve kırp
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _solid_fill(w: int, h: int, mask: Image.Image, color: tuple) -> Image.Image:
    """Tek renkli dolgu, polygon mask ile."""
    img = Image.new("RGB", (w, h), (255, 255, 255))
    fill_layer = Image.new("RGB", (w, h), color)
    img.paste(fill_layer, mask=mask)
    return img


def _draw_header(draw: ImageDraw.ImageDraw, canvas_w: int, size: str, dpi: int) -> None:
    """Canvas üstüne beden başlığı yaz."""
    text = f"Sublimasyon Forma — Beden: {size}    ({dpi} DPI)"
    font = _load_font(28)
    draw.text((40, 20), text, font=font, fill=(55, 65, 81))


def _write_minimal_pdf(pdf_path: str, jpeg_path: str, size: Tuple[int, int], dpi: int) -> None:
    """
    JPEG görselini içeren minimal PDF yazar.
    reportlab varsa onu kullan, yoksa ham PDF bytes.
    """
    try:
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.lib.units import mm as rl_mm

        w_pt = size[0] / dpi * 72
        h_pt = size[1] / dpi * 72

        c = rl_canvas.Canvas(pdf_path, pagesize=(w_pt, h_pt))
        c.drawImage(jpeg_path, 0, 0, width=w_pt, height=h_pt)
        c.save()
    except Exception:
        pass


# ─── Placeholder PDF (son çare) ──────────────────────────────────────────────

def _placeholder_pdf(pdf_path: str, size: str, piece_types: List[str]) -> bool:
    """
    reportlab ile minimal bilgi PDF'i üret.
    """
    try:
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.lib.units import mm as rl_mm
        from reportlab.lib.pagesizes import A4

        Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)
        c = rl_canvas.Canvas(pdf_path, pagesize=A4)
        c.setFont("Helvetica-Bold", 20)
        c.drawString(40, 780, f"Sublimasyon Forma — Beden: {size}")
        c.setFont("Helvetica", 12)
        c.drawString(40, 750, "Parçalar: " + ", ".join(piece_types))
        c.drawString(40, 730, "SVG önizleme için: /session/{id}/svg/" + size)
        c.drawString(40, 710, "(Pillow render başarısız — SVG dosyalarını kullanın)")
        c.save()
        return True
    except Exception as e:
        logger.error(f"Placeholder PDF hatası: {e}")
        return False


# ─── Beden boyutu yardımcısı ─────────────────────────────────────────────────

def get_page_size_for_pattern(
    width_mm: float,
    height_mm: float,
    margin_mm: float = 20.0,
) -> Tuple[float, float]:
    from reportlab.lib.units import mm as rl_mm
    total_w = (width_mm + 2 * margin_mm) * rl_mm
    total_h = (height_mm + 2 * margin_mm) * rl_mm
    return (total_w, total_h)
