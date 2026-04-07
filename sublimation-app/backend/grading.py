"""
Grading Motoru
==============
PLT'den elde edilen parçalar arasındaki farkları ölçer
ve bu farklara dayanarak yeni bedenler üretir.

Algoritma:
  1. Referans beden (M) ve karşılaştırma bedeni (L veya XL) parçalarını al
  2. Her parçayı N nokta ile yeniden örnekle (eşit yay uzunluğu)
  3. Başlangıç noktasını en iyi döngüsel hizalamayla bul
  4. Noktadan noktaya fark vektörlerini hesapla → GradingVectors
  5. Hedef beden için farkı çoğalt: (hedef_adım / kaynak_adım) * vektörler

Not:
  - Grading sadece "kaba" bir tahmindir; gerçek üretimde kalıpçı
    onayı gerekir.
  - Sadece PLT'de bulunan referans çiftlerinden hesaplar;
    eksik çiftler için extrapolasyon yapılır.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.interpolate import interp1d

from .models import (
    PatternPiece, GradingVectors, GradedPiece,
    SIZE_ORDER, SIZE_INDEX, PIECE_TYPES
)

logger = logging.getLogger(__name__)

N_SAMPLES = 300          # Yeniden örnekleme noktası sayısı
MIN_ALIGNMENT_RATIO = 0.7  # Hizalama kalitesi eşiği


# ─── Ana grading motoru ───────────────────────────────────────────────────────

class GradingEngine:
    """
    PLT'den gelen parça grubundan grading vektörleri hesaplar
    ve istenen bedenler için yeni parçalar üretir.
    """

    def __init__(
        self,
        grouped_pieces: Dict[str, Dict[str, PatternPiece]],
        reference_size: str = "M",
    ):
        self.grouped = grouped_pieces
        self.ref_size = reference_size
        self.available_sizes = sorted(
            grouped_pieces.keys(),
            key=lambda s: SIZE_INDEX.get(s, 99)
        )
        self._grading_cache: Dict[str, GradingVectors] = {}

    # ── Kamuya açık API ───────────────────────────────────────────────────────

    def compute_grading(self) -> Dict[str, GradingVectors]:
        """
        Her parça tipi için grading vektörlerini hesapla.
        Referans beden ile en yakın büyük bedeni karşılaştır.
        Returns: {piece_type: GradingVectors}
        """
        ref_pieces = self.grouped.get(self.ref_size, {})
        if not ref_pieces:
            raise ValueError(f"Referans beden '{self.ref_size}' PLT'de bulunamadı.")

        # En iyi karşılaştırma bedi bul (referanstan bir sonraki büyük)
        comparison_size = self._find_best_comparison_size()
        if not comparison_size:
            raise ValueError(
                f"'{self.ref_size}' bedeninden büyük başka beden PLT'de yok. "
                "Grading yapılamaz."
            )

        logger.info(
            f"Grading referansı: {self.ref_size} → {comparison_size} karşılaştırması"
        )

        comp_pieces = self.grouped[comparison_size]
        result: Dict[str, GradingVectors] = {}

        for piece_type in PIECE_TYPES:
            ref_p = ref_pieces.get(piece_type)
            comp_p = comp_pieces.get(piece_type)

            if ref_p is None or comp_p is None:
                logger.warning(
                    f"Parça tipi '{piece_type}' için "
                    f"{self.ref_size} veya {comparison_size} bulunamadı, atlandı."
                )
                continue

            gv = self._compute_piece_grading(
                ref_p, comp_p,
                from_size=self.ref_size,
                to_size=comparison_size,
                piece_type=piece_type,
            )
            result[piece_type] = gv
            self._grading_cache[piece_type] = gv
            logger.info(
                f"  {piece_type}: ortalama offset "
                f"Δx={gv.vectors[:, 0].mean():.2f}mm "
                f"Δy={gv.vectors[:, 1].mean():.2f}mm"
            )

        return result

    def grade_piece(
        self,
        piece_type: str,
        target_size: str,
        grading_vectors: Optional[GradingVectors] = None,
    ) -> Optional[GradedPiece]:
        """
        Belirtilen parça tipini ve bedeni üret.
        Referans beden parçasını alır, grading vektörlerini uygular.
        """
        gv = grading_vectors or self._grading_cache.get(piece_type)
        ref_p = self.grouped.get(self.ref_size, {}).get(piece_type)

        if gv is None or ref_p is None:
            return None

        # Hedef bedene kaç adım var?
        ref_idx = SIZE_INDEX.get(self.ref_size, 3)
        target_idx = SIZE_INDEX.get(target_size, 3)
        step_size_diff = SIZE_INDEX.get(gv.to_size, 4) - SIZE_INDEX.get(gv.from_size, 3)

        if step_size_diff == 0:
            scale = 0.0
        else:
            scale = (target_idx - ref_idx) / step_size_diff

        # Referans parçayı yeniden örnekle
        ref_resampled = resample_polyline(ref_p.points, N_SAMPLES)

        # Grading uygula
        graded_pts = ref_resampled + gv.vectors * scale

        return GradedPiece(
            piece_type=piece_type,
            size=target_size,
            points=graded_pts,
            source_label=ref_p.label,
        )

    def passthrough_all(
        self,
        target_sizes: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, GradedPiece]]:
        """
        PLT'de mevcut tüm bedenleri grading yapmadan GradedPiece'e çevir.
        Tüm parça tipleri (front, back, panel_front, strip...) dahil edilir.
        Dosyada zaten tüm bedenler varsa bu yöntemi kullan.
        """
        sizes = target_sizes or self.available_sizes
        result: Dict[str, Dict[str, GradedPiece]] = {}
        for size in sizes:
            size_pieces = self.grouped.get(size, {})
            if not size_pieces:
                logger.warning(f"Beden {size} PLT'de yok, atlandı.")
                continue
            result[size] = {}
            for ptype, piece in size_pieces.items():
                result[size][ptype] = GradedPiece(
                    piece_type=ptype,
                    size=size,
                    points=piece.points.copy(),
                    source_label=piece.label,
                )
            logger.info(f"  {size}: {len(result[size])} parça PLT'den alındı")
        return result

    def grade_all(
        self,
        target_sizes: List[str],
        grading_vectors: Dict[str, GradingVectors],
    ) -> Dict[str, Dict[str, GradedPiece]]:
        """
        Tüm hedef bedenler için tüm parça tiplerini üret.
        - PLT'de mevcut beden/parça → direkt al (grading yok)
        - PLT'de yoksa → grading ile üret
        Returns: {size: {piece_type: GradedPiece}}
        """
        result: Dict[str, Dict[str, GradedPiece]] = {}

        # Tüm bilinen parça tiplerini topla (grading vektörü olsun ya da olmasın)
        all_piece_types: set = set(grading_vectors.keys())
        for size_pieces in self.grouped.values():
            all_piece_types.update(size_pieces.keys())

        for size in target_sizes:
            result[size] = {}
            for piece_type in all_piece_types:
                # PLT'de bu beden+parça varsa direkt al
                existing = self.grouped.get(size, {}).get(piece_type)
                if existing is not None:
                    result[size][piece_type] = GradedPiece(
                        piece_type=piece_type,
                        size=size,
                        points=existing.points.copy(),
                        source_label=existing.label,
                    )
                    continue

                # Grading vektörü varsa hesapla
                gv = grading_vectors.get(piece_type)
                if gv:
                    graded = self.grade_piece(piece_type, size, gv)
                    if graded:
                        result[size][piece_type] = graded
                        logger.info(f"  {size}/{piece_type}: grading ile üretildi")
                    else:
                        logger.warning(f"  {size}/{piece_type}: üretilemedi")

        return result

    # ── Özel yardımcılar ──────────────────────────────────────────────────────

    def _find_best_comparison_size(self) -> Optional[str]:
        """Referans bedenden bir sonraki büyük bedeni bul."""
        ref_idx = SIZE_INDEX.get(self.ref_size, 99)
        candidates = [
            s for s in self.available_sizes
            if SIZE_INDEX.get(s, 0) > ref_idx
        ]
        if not candidates:
            return None
        # En yakın büyük bedeni seç
        return min(candidates, key=lambda s: SIZE_INDEX.get(s, 0))

    @staticmethod
    def _compute_piece_grading(
        ref_piece: PatternPiece,
        comp_piece: PatternPiece,
        from_size: str,
        to_size: str,
        piece_type: str,
    ) -> GradingVectors:
        """
        İki parça arasındaki fark vektörlerini hesapla.
        """
        ref_pts = resample_polyline(ref_piece.points, N_SAMPLES)
        comp_pts = resample_polyline(comp_piece.points, N_SAMPLES)

        # Hizala (döngüsel)
        comp_pts = align_polylines(ref_pts, comp_pts)

        # Fark vektörleri
        vectors = comp_pts - ref_pts

        # Gürültü azalt: hareketli ortalama
        vectors = smooth_vectors(vectors, window=7)

        return GradingVectors(
            from_size=from_size,
            to_size=to_size,
            piece_type=piece_type,
            vectors=vectors,
            n_samples=N_SAMPLES,
        )


# ─── Geometri yardımcıları ────────────────────────────────────────────────────

def resample_polyline(points: np.ndarray, n: int) -> np.ndarray:
    """
    Poligonu eşit yay uzunluğu ile n noktaya yeniden örnekle.
    """
    pts = np.asarray(points, dtype=float)
    if len(pts) < 2:
        return np.zeros((n, 2))

    # Kapalı poligon — ilk noktayı sona ekle
    if not np.allclose(pts[0], pts[-1]):
        pts = np.vstack([pts, pts[:1]])

    # Kümülatif yay uzunluğu
    diffs = np.diff(pts, axis=0)
    seg_len = np.linalg.norm(diffs, axis=1)
    cum_len = np.concatenate([[0.0], np.cumsum(seg_len)])
    total = cum_len[-1]

    if total < 1e-9:
        return np.tile(pts[0], (n, 1))

    # Hedef parametreler
    t_new = np.linspace(0, total, n, endpoint=False)

    x_interp = interp1d(cum_len, pts[:, 0], kind='linear', fill_value='extrapolate')
    y_interp = interp1d(cum_len, pts[:, 1], kind='linear', fill_value='extrapolate')

    return np.column_stack([x_interp(t_new), y_interp(t_new)])


def align_polylines(ref: np.ndarray, target: np.ndarray) -> np.ndarray:
    """
    Döngüsel öteleme ile target'ı ref'e hizala.
    En düşük ortalama mesafe veren başlangıç noktasını seç.

    Optimizasyon: tüm N² yerine her 10 noktada bir dene.
    """
    n = len(ref)
    best_offset = 0
    best_dist = np.inf

    step = max(1, n // 50)  # Her step noktada bir dene
    for offset in range(0, n, step):
        rolled = np.roll(target, -offset, axis=0)
        dist = np.mean(np.linalg.norm(rolled - ref, axis=1))
        if dist < best_dist:
            best_dist = dist
            best_offset = offset

    # Bulunan en iyi offset çevresinde ince arama
    fine_start = max(0, best_offset - step)
    fine_end = min(n, best_offset + step)
    for offset in range(fine_start, fine_end):
        rolled = np.roll(target, -offset, axis=0)
        dist = np.mean(np.linalg.norm(rolled - ref, axis=1))
        if dist < best_dist:
            best_dist = dist
            best_offset = offset

    # Ayna kontrolü (yönlendirme farklı olabilir)
    flipped = target[::-1]
    flipped_rolled = np.roll(flipped, -best_offset, axis=0)
    flip_dist = np.mean(np.linalg.norm(flipped_rolled - ref, axis=1))

    if flip_dist < best_dist * 0.9:
        aligned = flipped_rolled
        logger.debug("Poligon ayna çevrimi ile hizalandı")
    else:
        aligned = np.roll(target, -best_offset, axis=0)

    # Global ortalama ofseti kaldır — sadece şekil farkını tut
    centroid_diff = ref.mean(axis=0) - aligned.mean(axis=0)
    aligned = aligned + centroid_diff

    return aligned


def smooth_vectors(vectors: np.ndarray, window: int = 5) -> np.ndarray:
    """
    Vektör dizisine döngüsel hareketli ortalama uygula.
    """
    n = len(vectors)
    smoothed = np.zeros_like(vectors)
    half = window // 2
    for i in range(n):
        indices = [(i + j - half) % n for j in range(window)]
        smoothed[i] = vectors[indices].mean(axis=0)
    return smoothed


def compute_global_scale_grading(
    ref_piece: PatternPiece,
    target_piece: PatternPiece,
) -> Tuple[float, float, float, float]:
    """
    Basit bounding box tabanlı scale faktörü hesapla.
    Returns: (scale_x, scale_y, offset_x, offset_y)
    Bu, gelişmiş nokta tabanlı grading'in başarısız olduğu durumlarda kullanılır.
    """
    ref_bb = ref_piece.bounding_box()
    tgt_bb = target_piece.bounding_box()

    sx = tgt_bb.width / ref_bb.width if ref_bb.width > 0 else 1.0
    sy = tgt_bb.height / ref_bb.height if ref_bb.height > 0 else 1.0

    # Merkez farkı
    ref_c = ref_bb.center
    tgt_c = tgt_bb.center
    dx = tgt_c.x - ref_c.x
    dy = tgt_c.y - ref_c.y

    return sx, sy, dx, dy
