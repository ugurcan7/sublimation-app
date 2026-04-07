"""
Parça Eşleştirme Modülü
=======================
PLT'de etiket olmayan veya belirsiz parçaları,
geometrik özellikler + konumsal analiz ile eşleştirir.

Kullanılan özellikler:
  - Normalize edilmiş alan (aynı tipteki parça farklı bedende farklı alan)
  - Aspect ratio (en/boy oranı) — parça tipi tespiti için güçlü
  - Kompaktlık: alan / çevre² (daire benzeri mi değil mi)
  - Konvekslik: alanın konveks gövde alanına oranı
  - Pozisyon: PLT'deki x,y konumu (aynı tip = benzer konum)

Bu özellikler bir "parça imzası" oluşturur.
Bedenler arası eşleştirme için minimum Öklid mesafesi kullanılır.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple, Optional

import numpy as np

try:
    from shapely.geometry import Polygon
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False

from .models import PatternPiece, PIECE_TYPES, SIZE_INDEX

logger = logging.getLogger(__name__)


# ─── Parça imzası ─────────────────────────────────────────────────────────────

def compute_signature(piece: PatternPiece) -> np.ndarray:
    """
    Parça için 5 boyutlu imza vektörü:
      [aspect_ratio, compactness, convexity, norm_width, norm_height]

    Bu değerler beden bağımsızdır (oransal).
    """
    bb = piece.bounding_box()
    if bb.width < 1e-6 or bb.height < 1e-6:
        return np.zeros(5)

    area = piece.area()
    perim = piece.perimeter()

    # Aspect ratio
    ar = bb.width / bb.height

    # Kompaktlık (daire = 1, uzun şekiller < 1)
    compactness = (4 * np.pi * area) / (perim ** 2) if perim > 0 else 0.0

    # Konvekslik
    convexity = _convexity(piece)

    # Normalize width/height (birbirine oranı)
    # Gerçek boyut değil, oransal bilgi
    norm_w = bb.width / (bb.width + bb.height)
    norm_h = bb.height / (bb.width + bb.height)

    return np.array([ar, compactness, convexity, norm_w, norm_h])


def _convexity(piece: PatternPiece) -> float:
    """Konveks gövde alanı / gerçek alan — shapely varsa kullan."""
    if HAS_SHAPELY:
        try:
            poly = Polygon(piece.points)
            if not poly.is_valid:
                poly = poly.buffer(0)
            convex_area = poly.convex_hull.area
            actual_area = poly.area
            if convex_area < 1e-6:
                return 1.0
            return min(1.0, actual_area / convex_area)
        except Exception:
            pass

    # Fallback: kabaca tahmin
    pts = piece.points
    centroid = pts.mean(axis=0)
    # Merkeze uzaklıkların varyans katsayısı
    dists = np.linalg.norm(pts - centroid, axis=1)
    cv = dists.std() / (dists.mean() + 1e-9)
    # Yüksek varyans = az konveks
    return max(0.0, min(1.0, 1.0 - cv / 2.0))


# ─── Parça tipi sınıflandırıcı ────────────────────────────────────────────────

PIECE_TYPE_SIGNATURES: Dict[str, np.ndarray] = {
    # [ar,  compact, convex, norm_w, norm_h]
    "front":        np.array([0.60, 0.70, 0.85, 0.37, 0.63]),
    "back":         np.array([0.62, 0.70, 0.86, 0.38, 0.62]),
    "left_sleeve":  np.array([0.45, 0.55, 0.75, 0.31, 0.69]),
    "right_sleeve": np.array([0.45, 0.55, 0.75, 0.31, 0.69]),
}

# Sınıflandırma için özellik ağırlıkları
FEATURE_WEIGHTS = np.array([3.0, 1.0, 1.0, 2.0, 2.0])


def classify_piece_type(piece: PatternPiece) -> str:
    """
    Parçanın geometrik imzasına bakarak en olası tipi tahmin et.
    """
    sig = compute_signature(piece)
    best_type = "unknown"
    best_dist = np.inf

    for ptype, ref_sig in PIECE_TYPE_SIGNATURES.items():
        diff = (sig - ref_sig) * FEATURE_WEIGHTS
        dist = float(np.linalg.norm(diff))
        if dist < best_dist:
            best_dist = dist
            best_type = ptype

    return best_type


# ─── Bedenler arası parça eşleştirme ─────────────────────────────────────────

def match_pieces_across_sizes(
    grouped: Dict[str, Dict[str, PatternPiece]],
) -> Dict[str, Dict[str, PatternPiece]]:
    """
    Tüm bedenlerdeki parçaları karşılıklı eşleştir.

    Eğer parça tipleri zaten belirlenmiş ise (from PLT labels) doğrudan kullan.
    Belirsiz ise imza bazlı eşleştir.

    Returns: Aynı yapıda ama piece_type'ları doldurulmuş dict.
    """
    sizes = sorted(grouped.keys(), key=lambda s: SIZE_INDEX.get(s, 99))
    if not sizes:
        return grouped

    # Her bedendeki "unknown" parçaları sınıflandır
    for size in sizes:
        pieces = grouped[size]
        for key in list(pieces.keys()):
            p = pieces[key]
            if p.piece_type in ("", "unknown"):
                p.piece_type = classify_piece_type(p)
                logger.info(
                    f"  {size}/{p.label}: imza ile '{p.piece_type}' olarak sınıflandırıldı"
                )

    # Aynı parça tipi birden fazla kez varsa (örn 2 "front") → disambiguate
    for size in sizes:
        pieces = grouped[size]
        _disambiguate_duplicates(pieces)

    return grouped


def _disambiguate_duplicates(
    pieces: Dict[str, PatternPiece],
) -> None:
    """
    Aynı tipten birden fazla parça varsa konuma göre ayrıştır.
    Sol/sağ ayrımı: x koordinatına göre.
    """
    from collections import defaultdict
    type_groups: Dict[str, List[Tuple[str, PatternPiece]]] = defaultdict(list)

    for key, piece in pieces.items():
        type_groups[piece.piece_type].append((key, piece))

    for ptype, group in type_groups.items():
        if len(group) <= 1:
            continue

        if "sleeve" in ptype and len(group) == 2:
            # İkisi de sleeve: x konumuna göre sol/sağ ata
            sorted_group = sorted(group, key=lambda kp: kp[1].centroid()[0])
            sorted_group[0][1].piece_type = "left_sleeve"
            sorted_group[1][1].piece_type = "right_sleeve"
            logger.info(f"  Duplicate sleeve: x'e göre sol/sağ ayrımı yapıldı")


# ─── Kullanıcının yüklediği parçaları eşleştir ───────────────────────────────

def match_user_designs_to_pieces(
    user_piece_types: List[str],
    pattern_piece_types: List[str],
) -> Dict[str, Optional[str]]:
    """
    Kullanıcının yüklediği tasarım tiplerini pattern piecelerle eşleştir.
    Returns: {pattern_type: user_type_or_None}
    """
    result: Dict[str, Optional[str]] = {}

    for pattern_type in pattern_piece_types:
        # Direkt eşleşme
        if pattern_type in user_piece_types:
            result[pattern_type] = pattern_type
            continue

        # Kısmi eşleşme
        found = None
        for user_type in user_piece_types:
            if pattern_type in user_type or user_type in pattern_type:
                found = user_type
                break

        result[pattern_type] = found

    return result
