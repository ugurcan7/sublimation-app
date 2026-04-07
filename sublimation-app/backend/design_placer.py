"""
Desen Yerleştirici
==================
Kullanıcının yüklediği tasarım görselini (PNG/JPG/SVG)
graded kalıp parçası üzerine yerleştirir.

Yöntem:
  1. Her parça için SVG dosyası oluştur
  2. SVG <clipPath> ile parça kenarını kes
  3. Tasarım görselini parçanın bounding box'ına sığdır
  4. Opsiyonel: kesim payı (bleed) ekle

Koordinat sistemi:
  - mm cinsinden (HPGL'den dönüştürülmüş)
  - SVG viewBox mm cinsinden
  - 300 DPI için: 1mm = 300/25.4 ≈ 11.811 px
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from .models import GradedPiece, PatternPiece, BoundingBox

logger = logging.getLogger(__name__)

DPI = 300
MM_PER_INCH = 25.4
PX_PER_MM = DPI / MM_PER_INCH   # ~11.811


# ─── SVG oluşturucu ───────────────────────────────────────────────────────────

class SVGDesignPlacer:
    """
    Tek bir kalıp parçası + tasarım görseli → SVG dosyası üretir.
    """

    def __init__(self, bleed_mm: float = 3.0, dpi: int = 300):
        self.bleed = bleed_mm
        self.dpi = dpi

    def generate_svg(
        self,
        piece: GradedPiece,
        design_image_path: Optional[str],
        output_path: str,
        cut_line: bool = True,
        rotation: int = 0,
    ) -> str:
        """
        SVG dosyasını üret ve output_path'e kaydet.
        Returns: SVG içeriği (string)
        """
        pts = piece.points
        if len(pts) < 3:
            raise ValueError(f"Parça çok az nokta içeriyor: {len(pts)}")

        # Bounding box
        bb = _pts_bounding_box(pts)

        # Bleed dahil padding
        pad = self.bleed
        vb_x = bb.x_min - pad
        vb_y = bb.y_min - pad
        vb_w = bb.width + 2 * pad
        vb_h = bb.height + 2 * pad

        # SVG boyutları (pixel cinsinden)
        svg_w_px = vb_w * PX_PER_MM
        svg_h_px = vb_h * PX_PER_MM

        # Parça noktaları → SVG poligon string
        poly_points = " ".join(f"{x:.4f},{y:.4f}" for x, y in pts)

        # Clip path ID
        clip_id = f"clip_{piece.piece_type}_{piece.size}"

        lines = [
            f'<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="{vb_x:.4f} {vb_y:.4f} {vb_w:.4f} {vb_h:.4f}" '
            f'width="{svg_w_px:.1f}px" height="{svg_h_px:.1f}px">',
            f'  <title>{piece.size} - {piece.piece_type}</title>',
            "",
            "  <defs>",
            f'    <clipPath id="{clip_id}">',
            f'      <polygon points="{poly_points}" />',
            "    </clipPath>",
        ]

        # Bleed mask (isteğe bağlı: biraz genişletilmiş clip)
        if self.bleed > 0:
            bleed_pts = _expand_polygon(pts, self.bleed)
            bleed_poly = " ".join(f"{x:.4f},{y:.4f}" for x, y in bleed_pts)
            lines += [
                f'    <clipPath id="{clip_id}_bleed">',
                f'      <polygon points="{bleed_poly}" />',
                "    </clipPath>",
            ]

        lines.append("  </defs>")
        lines.append("")

        # Arka plan (beyaz)
        lines.append(
            f'  <rect x="{vb_x:.4f}" y="{vb_y:.4f}" '
            f'width="{vb_w:.4f}" height="{vb_h:.4f}" fill="white" />'
        )

        # Tasarım görseli
        if design_image_path and os.path.exists(design_image_path):
            img_data = _image_to_base64(design_image_path)
            if img_data:
                mime = _get_mime_type(design_image_path)
                use_clip = f'{clip_id}_bleed' if self.bleed > 0 else clip_id
                img_x = bb.x_min - self.bleed
                img_y = bb.y_min - self.bleed
                img_w = bb.width + 2 * self.bleed
                img_h = bb.height + 2 * self.bleed
                lines += _image_lines(img_data, mime, img_x, img_y, img_w, img_h, use_clip, rotation)
            else:
                # Görsel yüklenemedi — renk dolgusu
                lines.append(
                    f'  <polygon points="{poly_points}" '
                    f'fill="#cccccc" clip-path="url(#{clip_id})" />'
                )
        else:
            # Tasarım yok — açık gri dolgu
            lines.append(
                f'  <polygon points="{poly_points}" '
                f'fill="#e8e8e8" clip-path="url(#{clip_id})" />'
            )

        # Kesim çizgisi
        if cut_line:
            lines.append(
                f'  <polygon points="{poly_points}" '
                f'fill="none" stroke="#000000" stroke-width="0.3" />'
            )

        # Beden / parça tipi etiketi (debugging)
        cx = float(np.mean(pts[:, 0]))
        cy = float(np.mean(pts[:, 1]))
        label = f"{piece.size} {piece.piece_type.replace('_', ' ').upper()}"
        lines.append(
            f'  <text x="{cx:.2f}" y="{cy:.2f}" '
            f'font-size="8" text-anchor="middle" fill="rgba(0,0,0,0.3)" '
            f'font-family="sans-serif">{label}</text>'
        )

        lines.append("</svg>")
        svg_content = "\n".join(lines)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(svg_content, encoding="utf-8")
        logger.info(f"SVG üretildi: {output_path}")

        return svg_content

    def generate_all_pieces_svg(
        self,
        pieces: dict,          # {piece_type: GradedPiece}
        design_files: dict,    # {piece_type: image_path}
        output_dir: str,
        size: str,
        rotations: Optional[dict] = None,  # {piece_type: int degrees}
    ) -> dict:
        """
        Bir bedendeki tüm parçalar için ayrı SVG dosyaları üret.
        Tasarım yüklenmemiş parçalar atlanır.
        Returns: {piece_type: svg_path}
        """
        os.makedirs(output_dir, exist_ok=True)
        result = {}
        rotations = rotations or {}

        for piece_type, graded_piece in pieces.items():
            design_path = design_files.get(piece_type)
            # Tasarım yoksa bu parçayı atla
            if not design_path or not os.path.exists(design_path):
                logger.info(f"Tasarım yok, atlanıyor: {size}/{piece_type}")
                continue
            out_path = os.path.join(output_dir, f"{size}_{piece_type}.svg")
            try:
                self.generate_svg(
                    piece=graded_piece,
                    design_image_path=design_path,
                    output_path=out_path,
                    rotation=rotations.get(piece_type, 0),
                )
                result[piece_type] = out_path
            except Exception as e:
                logger.error(f"SVG üretim hatası {size}/{piece_type}: {e}")

        return result

    def generate_combined_svg(
        self,
        pieces: dict,          # {piece_type: GradedPiece}
        design_files: dict,    # {piece_type: image_path}
        output_path: str,
        size: str,
        pieces_per_row: int = 2,
        rotations: Optional[dict] = None,  # {piece_type: int degrees}
    ) -> str:
        """
        Tüm parçaları tek bir SVG'de yan yana yerleştir.
        Sublimasyon yazıcılar için tek çıktı dosyası.
        """
        rotations = rotations or {}

        # Tasarım yüklenmemiş parçaları filtrele
        piece_list = [
            (ptype, gp) for ptype, gp in pieces.items()
            if design_files.get(ptype) and os.path.exists(design_files[ptype])
        ]

        if not piece_list:
            raise ValueError("Tasarım yüklü parça bulunamadı")

        MARGIN = 20.0  # mm
        n = len(piece_list)
        n_cols = min(pieces_per_row, n)
        n_rows = (n + n_cols - 1) // n_cols

        # Her parçanın boyutunu hesapla
        piece_dims = []
        for ptype, gp in piece_list:
            bb = _pts_bounding_box(gp.points)
            piece_dims.append((bb.width + 2 * self.bleed, bb.height + 2 * self.bleed))

        # Grid düzeni
        col_widths = []
        row_heights = []
        for row in range(n_rows):
            max_h = 0.0
            for col in range(n_cols):
                idx = row * n_cols + col
                if idx < len(piece_dims):
                    max_h = max(max_h, piece_dims[idx][1])
            row_heights.append(max_h + MARGIN)

        for col in range(n_cols):
            max_w = 0.0
            for row in range(n_rows):
                idx = row * n_cols + col
                if idx < len(piece_dims):
                    max_w = max(max_w, piece_dims[idx][0])
            col_widths.append(max_w + MARGIN)

        total_w = sum(col_widths) + MARGIN
        total_h = sum(row_heights) + MARGIN
        svg_w_px = total_w * PX_PER_MM
        svg_h_px = total_h * PX_PER_MM

        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {total_w:.4f} {total_h:.4f}" '
            f'width="{svg_w_px:.1f}px" height="{svg_h_px:.1f}px">',
            f'  <title>Sublimasyon Pastal - Beden {size}</title>',
            "  <defs>",
        ]

        # Tüm clip path'leri tanımla
        for idx, (ptype, gp) in enumerate(piece_list):
            row = idx // n_cols
            col = idx % n_cols

            # Bu parçanın offset'ini hesapla
            ox = MARGIN + sum(col_widths[:col])
            oy = MARGIN + sum(row_heights[:row])

            bb = _pts_bounding_box(gp.points)
            shifted_pts = gp.points - np.array([bb.x_min, bb.y_min]) + np.array([ox + self.bleed, oy + self.bleed])

            clip_id = f"clip_{size}_{ptype}"
            poly_str = " ".join(f"{x:.4f},{y:.4f}" for x, y in shifted_pts)
            lines += [
                f'    <clipPath id="{clip_id}">',
                f'      <polygon points="{poly_str}" />',
                "    </clipPath>",
            ]

            if self.bleed > 0:
                bleed_pts = _expand_polygon(shifted_pts, self.bleed)
                bleed_str = " ".join(f"{x:.4f},{y:.4f}" for x, y in bleed_pts)
                lines += [
                    f'    <clipPath id="{clip_id}_bleed">',
                    f'      <polygon points="{bleed_str}" />',
                    "    </clipPath>",
                ]

        lines += [
            "  </defs>",
            "",
            f'  <rect width="{total_w:.4f}" height="{total_h:.4f}" fill="white"/>',
            "",
        ]

        # Her parçayı çiz
        for idx, (ptype, gp) in enumerate(piece_list):
            row = idx // n_cols
            col = idx % n_cols

            ox = MARGIN + sum(col_widths[:col])
            oy = MARGIN + sum(row_heights[:row])

            bb = _pts_bounding_box(gp.points)
            shifted_pts = gp.points - np.array([bb.x_min, bb.y_min]) + np.array([ox + self.bleed, oy + self.bleed])
            poly_str = " ".join(f"{x:.4f},{y:.4f}" for x, y in shifted_pts)

            clip_id = f"clip_{size}_{ptype}"
            use_clip = f"{clip_id}_bleed" if self.bleed > 0 else clip_id

            design_path = design_files.get(ptype)

            if design_path and os.path.exists(design_path):
                img_data = _image_to_base64(design_path)
                mime = _get_mime_type(design_path)
                img_x = ox
                img_y = oy
                img_w = piece_dims[idx][0]
                img_h = piece_dims[idx][1]
                rot = rotations.get(ptype, 0)
                lines.append(f'  <!-- {size} {ptype} -->')
                lines += _image_lines(img_data, mime, img_x, img_y, img_w, img_h, use_clip, rot)
            else:
                lines.append(f'  <polygon points="{poly_str}" fill="#e0e0e0" />')

            # Kesim çizgisi
            lines.append(
                f'  <polygon points="{poly_str}" fill="none" '
                f'stroke="#000000" stroke-width="0.5" />'
            )

            # Etiket
            cx = float(shifted_pts[:, 0].mean())
            cy = float(shifted_pts[:, 1].mean())
            label = f"{size} / {ptype.replace('_', ' ').upper()}"
            lines.append(
                f'  <text x="{cx:.2f}" y="{cy:.2f}" font-size="6" '
                f'text-anchor="middle" fill="rgba(0,0,0,0.4)" '
                f'font-family="sans-serif">{label}</text>'
            )

        lines.append("</svg>")
        svg_content = "\n".join(lines)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(svg_content, encoding="utf-8")
        logger.info(f"Kombine SVG üretildi: {output_path}")

        return svg_content


# ─── Yardımcı fonksiyonlar ────────────────────────────────────────────────────

def _image_lines(
    img_data: str,
    mime: str,
    x: float, y: float, w: float, h: float,
    clip_id: str,
    rotation: int = 0,
) -> List[str]:
    """
    SVG <image> elementini döndürme destekli üretir.
    clip_id'yi <g> üzerinde uygular, böylece parça dışı kesilir.
    rotation 90/270 iken genişlik/yükseklik yer değiştirir (yatay→dikey).
    """
    cx = x + w / 2
    cy = y + h / 2

    if rotation in (90, 270):
        rw, rh = h, w
    else:
        rw, rh = w, h

    rx = cx - rw / 2
    ry = cy - rh / 2

    transform_attr = f' transform="rotate({rotation}, {cx:.4f}, {cy:.4f})"' if rotation else ''

    return [
        f'  <g clip-path="url(#{clip_id})">',
        f'    <image xlink:href="data:{mime};base64,{img_data}"',
        f'      x="{rx:.4f}" y="{ry:.4f}"',
        f'      width="{rw:.4f}" height="{rh:.4f}"',
        f'      preserveAspectRatio="xMidYMid slice"{transform_attr} />',
        f'  </g>',
    ]


def _pts_bounding_box(pts: np.ndarray) -> BoundingBox:
    from .models import BoundingBox
    return BoundingBox(
        x_min=float(pts[:, 0].min()),
        y_min=float(pts[:, 1].min()),
        x_max=float(pts[:, 0].max()),
        y_max=float(pts[:, 1].max()),
    )


def _image_to_base64(image_path: str) -> Optional[str]:
    """Görseli base64 string'e dönüştür."""
    try:
        with open(image_path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode("ascii")
    except Exception as e:
        logger.error(f"Görsel yüklenemedi {image_path}: {e}")
        return None


def _get_mime_type(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }.get(ext, "image/png")


def _expand_polygon(pts: np.ndarray, amount: float) -> np.ndarray:
    """
    Poligonu belirtilen miktarda (mm) dışa doğru genişlet.
    Basit merkez tabanlı öteleme yöntemi.
    """
    centroid = pts.mean(axis=0)
    vectors = pts - centroid
    lengths = np.linalg.norm(vectors, axis=1, keepdims=True)
    lengths = np.where(lengths < 1e-9, 1e-9, lengths)
    unit_vecs = vectors / lengths
    return pts + unit_vecs * amount


def scale_design_for_graded_piece(
    ref_pts: np.ndarray,
    graded_pts: np.ndarray,
    image_path: str,
    output_path: str,
) -> Optional[str]:
    """
    Referans parçadan graded parçaya orantılı görsel yeniden ölçekleme.
    PIL ile gerçek görsel dönüşümü yapar ve kaydeder.
    """
    try:
        img = Image.open(image_path).convert("RGBA")

        ref_bb = _pts_bounding_box(ref_pts)
        grad_bb = _pts_bounding_box(graded_pts)

        sx = grad_bb.width / ref_bb.width if ref_bb.width > 0 else 1.0
        sy = grad_bb.height / ref_bb.height if ref_bb.height > 0 else 1.0

        new_w = max(1, int(img.width * sx))
        new_h = max(1, int(img.height * sy))

        resized = img.resize((new_w, new_h), Image.LANCZOS)
        resized.save(output_path)
        return output_path
    except Exception as e:
        logger.error(f"Görsel ölçekleme hatası: {e}")
        return None
