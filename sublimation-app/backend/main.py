"""
FastAPI Uygulaması — Sublimasyon Forma Üretim Sistemi
=====================================================

Endpoint'ler:
  POST /session                    — Yeni oturum oluştur
  POST /session/{id}/plt           — PLT dosyası yükle + analiz et
  GET  /session/{id}/status        — Oturum durumu
  POST /session/{id}/design/{type} — Tasarım görseli yükle
  POST /session/{id}/grade         — Grading başlat ve SVG üret
  GET  /session/{id}/pdf/{size}    — PDF indir
  GET  /session/{id}/svg/{size}/{type} — SVG önizleme
  GET  /session/{id}/preview       — Tüm parça önizlemesi (JSON)
  GET  /session/{id}/preview-svg/{type} — Adım 3 anlık SVG önizlemesi
  DELETE /session/{id}             — Oturumu temizle
"""
from __future__ import annotations

import logging
import os
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

import numpy as np
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import aiofiles

from .models import UploadSession, GradedPiece, SIZE_ORDER, PIECE_TYPES
from .plt_parser import PLTParser, group_pieces
from .grading import GradingEngine
from .pattern_matcher import match_pieces_across_sizes
from .design_placer import SVGDesignPlacer
from .pdf_generator import generate_size_pdf, svg_to_pdf
from . import db as session_db

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)

# ─── FastAPI init ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="Sublimasyon Forma Üretim Sistemi",
    description="PLT tabanlı grading + desen yerleştirme + PDF çıktı",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Dizinler ─────────────────────────────────────────────────────────────────
# Vercel serverless: sadece /tmp yazılabilir; yerel çalışmada proje kökü kullanılır
_IS_VERCEL = os.environ.get("VERCEL") == "1"
BASE_DIR = Path("/tmp/sublimation") if _IS_VERCEL else Path(__file__).parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_FILE = BASE_DIR / "sessions.pkl"   # migration için
DB_PATH = BASE_DIR / "sessions.db"

# ─── Frontend statik dosyaları ───────────────────────────────────────────────
if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

# ─── Session kalıcılığı (SQLite) ──────────────────────────────────────────────

# Pickle'dan SQLite'a tek seferlik migration
session_db.migrate_from_pickle(SESSIONS_FILE, DB_PATH)
session_db.init_db(DB_PATH)


def _save_sessions() -> None:
    for session in sessions.values():
        session_db.save_session(DB_PATH, session)


def _save_session(session: UploadSession) -> None:
    """Tek oturumu kaydet (toplu kayıt yerine)."""
    session_db.save_session(DB_PATH, session)


def _load_sessions() -> Dict[str, UploadSession]:
    return session_db.load_all_sessions(DB_PATH)


def _cleanup_old_sessions() -> None:
    """24 saatten eski veya dosyaları kayıp oturumları temizle."""
    cutoff = datetime.now() - timedelta(hours=24)
    to_del = []
    for sid, s in sessions.items():
        age_ok  = getattr(s, "created_at", datetime.now()) < cutoff
        file_ok = s.plt_path and Path(s.plt_path).exists()
        if age_ok or (s.plt_path and not file_ok):
            to_del.append(sid)
    for sid in to_del:
        sessions.pop(sid, None)
        for d in [UPLOAD_DIR / sid, OUTPUT_DIR / sid]:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
    if to_del:
        logger.info(f"{len(to_del)} eski/geçersiz oturum temizlendi")


# ─── Oturum deposu ────────────────────────────────────────────────────────────
sessions: Dict[str, UploadSession] = _load_sessions()
_cleanup_old_sessions()

# ─── Progress deposu ──────────────────────────────────────────────────────────
# { session_id: {"pct": int, "msg": str, "done": bool, "error": str|None} }
progress_store: Dict[str, Dict] = {}


def _get_session(session_id: str) -> UploadSession:
    s = sessions.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail=f"Oturum bulunamadı: {session_id}")
    return s


def _session_dir(session_id: str, subdir: str = "") -> Path:
    p = UPLOAD_DIR / session_id
    if subdir:
        p = p / subdir
    p.mkdir(parents=True, exist_ok=True)
    return p


def _output_dir(session_id: str) -> Path:
    p = OUTPUT_DIR / session_id
    p.mkdir(parents=True, exist_ok=True)
    return p


# ─── Root ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/app")


# ─── Oturum endpoint'leri ─────────────────────────────────────────────────────

@app.post("/session", response_model=dict, status_code=201)
async def create_session(reference_size: str = Form(default="M")):
    """Yeni üretim oturumu oluştur."""
    session_id = str(uuid.uuid4())[:8]
    sessions[session_id] = UploadSession(
        session_id=session_id,
        reference_size=reference_size.upper(),
    )
    logger.info(f"Yeni oturum: {session_id} (ref={reference_size})")
    _save_session(sessions[session_id])
    return {"session_id": session_id, "reference_size": reference_size.upper()}


@app.get("/session/{session_id}/status")
async def get_status(session_id: str):
    """Oturum durumunu döndür."""
    s = _get_session(session_id)
    return {
        "session_id": session_id,
        "reference_size": s.reference_size,
        "has_plt": s.plt_path is not None,
        "detected_sizes": s.detected_sizes(),
        "detected_piece_types": s.detected_piece_types(),
        "uploaded_designs": list(s.design_files.keys()),
        "grading_done": bool(s.grading_vectors),
        "output_pdfs": list(s.output_pdfs.keys()),
        "errors": s.errors,
    }


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Oturumu ve dosyalarını temizle."""
    import shutil
    _get_session(session_id)
    sessions.pop(session_id, None)
    session_db.delete_session(DB_PATH, session_id)
    for d in [UPLOAD_DIR / session_id, OUTPUT_DIR / session_id]:
        if d.exists():
            shutil.rmtree(d)
    return {"deleted": session_id}


# ─── PLT yükleme ──────────────────────────────────────────────────────────────

@app.post("/session/{session_id}/plt")
async def upload_plt(
    session_id: str,
    file: UploadFile = File(...),
):
    """
    PLT dosyasını yükle ve analiz et.
    Beden + parça tipi tespiti burada yapılır.
    """
    s = _get_session(session_id)

    if not file.filename.lower().endswith((".plt", ".hpgl", ".hgl")):
        raise HTTPException(400, "Desteklenen format: .plt, .hpgl, .hgl")

    # Kaydet
    save_dir = _session_dir(session_id, "plt")
    save_path = save_dir / "pastal.plt"

    content = await file.read()
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(content)

    # Parse et
    try:
        parser = PLTParser(save_path)
        raw_pieces = parser.parse()
    except Exception as e:
        raise HTTPException(422, f"PLT parse hatası: {e}")

    if not raw_pieces:
        raise HTTPException(422, "PLT dosyasında kalıp parçası bulunamadı")

    has_labels = any(p.label.strip() for p in raw_pieces)

    if has_labels:
        # Etiketli PLT: beden + parça tipi otomatik grupla
        grouped = group_pieces(raw_pieces)
        grouped = match_pieces_across_sizes(grouped)
        mode = "labeled"
    else:
        # Etiketsiz PLT: şekil + alan analizi ile tüm bedenleri otomatik tespit et
        grouped = _detect_all_sizes(raw_pieces)
        mode = "graded" if len(grouped) > 1 else "flat"

    s.plt_path = str(save_path)
    s.parsed_pieces = grouped
    sizes_found = list(grouped.keys())
    if sizes_found:
        s.reference_size = sizes_found[0]  # varsayılan: en büyük beden

    warnings = []
    if mode == "graded":
        warnings.append(
            f"PLT'de {len(grouped)} beden tespit edildi (S1=en büyük). "
            "Referans beden seçip tasarımı yükleyin."
        )
    elif mode == "flat":
        warnings.append(
            "Tek beden tespit edildi. Parça tiplerini kontrol edip onaylayın."
        )

    logger.info(
        f"PLT yüklendi: {file.filename} → {len(raw_pieces)} ham parça, "
        f"mod={mode}, {len(grouped.get('BASE', grouped.get(sizes_found[0] if sizes_found else '', {})))} parça gösteriliyor"
    )

    _save_session(s)

    return {
        "total_pieces": len(raw_pieces),
        "detected_sizes": sizes_found,
        "size_names_from_plt": has_labels,   # True → adlar PLT'den geldi, doğrudan kullan
        "piece_types_found": s.detected_piece_types(),
        "labeled": has_labels,
        "mode": mode,
        "warnings": warnings,
    }


def _detect_all_sizes(raw_pieces) -> "Dict[str, Dict[str, Any]]":
    """
    Etiketsiz PLT'den tüm bedenleri otomatik tespit et.

    Algoritma:
      1. Border/çerçeve parçasını çıkar (medyan alanın 50x'inden büyük)
      2. Çok küçük parçaları (notch) çıkar
      3. Parçaları ŞEKLE göre ayır:
         - Geniş/kare-ish (oran < 1.55) → gövde parçası (ön/arka)
         - Uzun/dar (oran ≥ 1.55) → kol parçası (sol/sağ kol)
      4. Her grubu alana göre sırala; ikişerli eşleştir → beden
      5. Gövde çifti + kol çifti = bir beden
      6. "S1" (en büyük) … "SN" (en küçük) olarak adlandır
    """
    if not raw_pieces:
        return {}

    areas = sorted(p.area() for p in raw_pieces)
    median_area = areas[len(areas) // 2]

    # Border ve notch'ları çıkar
    filtered = [
        p for p in raw_pieces
        if 0.05 * median_area < p.area() < 50 * median_area
    ]
    if not filtered:
        filtered = raw_pieces[:]

    # Şekle göre ayır
    body_pieces: list = []
    sleeve_pieces: list = []
    for p in filtered:
        bb = p.bounding_box()
        ratio = max(bb.width, bb.height) / (min(bb.width, bb.height) or 1)
        if ratio >= 1.55:
            sleeve_pieces.append(p)
        else:
            body_pieces.append(p)

    # Kol yoksa gövdedeki en büyük çifti kol kabul et (şekil ayırt edemezse)
    if not sleeve_pieces and len(body_pieces) >= 4:
        body_pieces.sort(key=lambda p: p.area())
        sleeve_pieces = body_pieces[-2:]
        body_pieces   = body_pieces[:-2]

    # Her grubu alana göre sırala (küçükten büyüğe → S1 en küçük beden)
    body_pieces.sort(key=lambda p: p.area())
    sleeve_pieces.sort(key=lambda p: p.area())

    # Gövde çiftleri → her 2 parça = 1 bedenin ön+arka
    n_body_sizes   = len(body_pieces) // 2
    # Kol çiftleri → her 2 parça = 1 bedenin sol+sağ kol
    n_sleeve_sizes = len(sleeve_pieces) // 2

    n_sizes = max(n_body_sizes, n_sleeve_sizes)
    if n_sizes == 0:
        # Fallback: tek BASE grubu
        return _build_flat_group_fallback(filtered)

    result: Dict[str, Any] = {}
    for si in range(n_sizes):
        size_name = f"S{si + 1}"
        group: Dict[str, Any] = {}

        bi = si * 2  # gövde index
        sl = si * 2  # kol index

        # Çift içinde: bi = küçük (ön), bi+1 = büyük (arka)
        if bi < len(body_pieces):
            p = body_pieces[bi]
            p.piece_type = "front"
            p.size = size_name
            group["front"] = p
        if bi + 1 < len(body_pieces):
            p = body_pieces[bi + 1]
            p.piece_type = "back"
            p.size = size_name
            group["back"] = p
        if sl < len(sleeve_pieces):
            p = sleeve_pieces[sl]
            p.piece_type = "left_sleeve"
            p.size = size_name
            group["left_sleeve"] = p
        if sl + 1 < len(sleeve_pieces):
            p = sleeve_pieces[sl + 1]
            p.piece_type = "right_sleeve"
            p.size = size_name
            group["right_sleeve"] = p

        if group:
            result[size_name] = group

    return result


def _build_flat_group_fallback(filtered_pieces) -> "Dict[str, Dict[str, Any]]":
    """Beden tespiti başarısız olursa tek BASE grubu döner (eski davranış)."""
    filtered_pieces.sort(key=lambda p: p.area(), reverse=True)
    type_hints = ["front", "back", "left_sleeve", "right_sleeve",
                  "front_2", "back_2", "sleeve_3", "sleeve_4",
                  "piece_5", "piece_6", "piece_7", "piece_8"]
    group: Dict[str, Any] = {}
    for i, p in enumerate(filtered_pieces[:12]):
        key = type_hints[i] if i < len(type_hints) else f"piece_{i+1}"
        p.piece_type = key
        p.size = "BASE"
        group[key] = p
    return {"BASE": group}


def _classify_unlabeled_plt(
    plt_path: Path,
    raw_pieces,
) -> "Dict[str, Dict[str, Any]]":
    """
    Etiket içermeyen PLT dosyasını geometrik sınıflandırma ile grupla.
    hpgl_pipeline + hpgl_classifier kullanır.
    Sonucu PatternPiece benzeri GradedPiece olarak döner.
    """
    import sys, json, tempfile
    sys.path.insert(0, str(BASE_DIR))

    from hpgl_pipeline import run_pipeline
    from hpgl_classifier import classify_pieces, estimate_n_sizes
    from .models import PatternPiece

    # Geçici çıktı dosyaları
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        json_tmp = tf.name
    svg_tmp = json_tmp.replace(".json", ".svg")

    # Pipeline
    pieces_raw = run_pipeline(
        str(plt_path),
        json_out=json_tmp,
        svg_out=svg_tmp,
    )
    if not pieces_raw:
        return {}

    # Beden sayısını tahmin et
    n_sizes = estimate_n_sizes(pieces_raw)
    logger.info(f"Geometrik sınıflandırma: {len(pieces_raw)} parça → {n_sizes} beden")

    classified = classify_pieces(
        json_in=json_tmp,
        json_out=json_tmp,
        svg_out=svg_tmp,
        n_sizes=n_sizes,
    )

    # PatternPiece yapısına dönüştür
    grouped: Dict[str, Dict[str, PatternPiece]] = {}
    for pc in classified:
        size_lbl = pc["size_label"]
        ptype = pc["piece_type"]
        pts = np.array(pc["points"], dtype=float)
        piece = PatternPiece(
            label=pc.get("label", ""),
            size=size_lbl,
            piece_type=ptype,
            points=pts,
        )
        if size_lbl not in grouped:
            grouped[size_lbl] = {}
        # Aynı tipten birden fazla varsa suffix ekle
        key = ptype
        suffix = 0
        while key in grouped[size_lbl]:
            suffix += 1
            key = f"{ptype}_{suffix}"
        grouped[size_lbl][key] = piece

    # Debug SVG'yi oturum klasörüne taşı
    import shutil
    debug_out = plt_path.parent / "classified_debug.svg"
    if Path(svg_tmp).exists():
        shutil.copy(svg_tmp, debug_out)
        logger.info(f"Sınıflandırma SVG kaydedildi: {debug_out}")

    return grouped


# ─── Tasarım yükleme ──────────────────────────────────────────────────────────

@app.post("/session/{session_id}/design/{piece_type}")
async def upload_design(
    session_id: str,
    piece_type: str,
    file: UploadFile = File(...),
):
    """
    Belirtilen parça tipi için tasarım görselini yükle.
    piece_type: PLT'den gelen herhangi bir parça adı veya 'all' (tümü).
    """
    s = _get_session(session_id)

    # 'all' → tüm tespit edilen parça tiplerine aynı deseni ata
    if piece_type == "all":
        target_types = s.detected_piece_types() or ["front", "back", "left_sleeve", "right_sleeve"]
    else:
        target_types = [piece_type]

    ext = Path(file.filename).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".svg", ".webp", ".tif", ".tiff"):
        raise HTTPException(400, "Desteklenen format: PNG, JPG, SVG, WEBP, TIFF")

    content = await file.read()

    # TIFF → JPEG dönüşümü: boyutu küçült, sistem yükünü azalt
    if ext in (".tif", ".tiff"):
        try:
            from PIL import Image as PILImage
            import io
            img = PILImage.open(io.BytesIO(content))
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=95, optimize=True)
            content = buf.getvalue()
            ext = ".jpg"
            logger.info(f"TIFF → JPEG dönüştürüldü: {len(content)//1024}KB")
        except Exception as e:
            raise HTTPException(422, f"TIFF dönüştürme hatası: {e}")

    save_dir = _session_dir(session_id, "designs")

    saved = []
    for ptype in target_types:
        save_path = save_dir / f"{ptype}{ext}"
        async with aiofiles.open(save_path, "wb") as f:
            await f.write(content)
        s.design_files[ptype] = str(save_path)
        saved.append(ptype)

    logger.info(f"Tasarım yüklendi: {session_id}/{piece_type} → {len(saved)} parça tipine atandı")

    return {
        "piece_type": piece_type,
        "assigned_to": saved,
        "filename": file.filename,
        "uploaded_designs": list(s.design_files.keys()),
    }


# ─── Grading + SVG üretimi ────────────────────────────────────────────────────

@app.get("/session/{session_id}/progress")
async def get_progress(session_id: str):
    """Grade işleminin anlık ilerlemesini döndür."""
    _get_session(session_id)
    prog = progress_store.get(session_id, {"pct": 0, "msg": "Bekliyor", "done": False, "error": None})
    return prog


def _set_progress(session_id: str, pct: int, msg: str, done: bool = False, error: str = None):
    progress_store[session_id] = {"pct": pct, "msg": msg, "done": done, "error": error}


@app.post("/session/{session_id}/grade")
async def run_grading(
    session_id: str,
    target_sizes: str = Form(default="S,M,L,XL,XXL"),
    bleed_mm: float = Form(default=3.0),
    dpi: int = Form(default=300),
    design_rotations: str = Form(default=""),
    size_label: str = Form(default=""),       # flat modda çıktı için beden etiketi (M, L, 42 vs.)
    width_step_mm: float = Form(default=4.0), # flat grading adım genişliği
    height_step_mm: float = Form(default=2.0),# flat grading adım yüksekliği
):
    """
    Grading çalıştır + tüm bedenlere desen yerleştir + SVG üret.

    target_sizes: virgülle ayrılmış beden listesi (örn: "S,M,L,XL,XXL")
    bleed_mm: kesim payı mm cinsinden
    dpi: çıktı çözünürlüğü
    """
    s = _get_session(session_id)

    if not s.plt_path or not s.parsed_pieces:
        raise HTTPException(400, "Önce PLT dosyası yükleyin")

    requested_sizes = [sz.strip().upper() for sz in target_sizes.split(",") if sz.strip()]
    if not requested_sizes:
        raise HTTPException(400, "En az bir beden belirtilmeli")

    _set_progress(session_id, 5, "Başlatılıyor...")

    # Dönme açılarını parse et: "front:90,back:0" → {"front": 90, "back": 0}
    rotations: Dict[str, int] = {}
    for item in design_rotations.split(","):
        item = item.strip()
        if ":" in item:
            ptype, deg_str = item.split(":", 1)
            try:
                rotations[ptype.strip()] = int(deg_str.strip())
            except ValueError:
                pass

    # Beden tespiti: çoklu beden varsa passthrough, tek BASE ise flat mod
    has_base = "BASE" in s.parsed_pieces
    is_multi = len(s.parsed_pieces) > 1

    if has_base and not is_multi:
        # Tek BASE: kullanıcı beden etiketi veya grading serisi girdiyse işle
        label = size_label.strip().upper() if size_label.strip() else "BASE"
        if label != "BASE":
            s.parsed_pieces[label] = s.parsed_pieces.pop("BASE")
            s.reference_size = label
        else:
            s.reference_size = "BASE"
            label = "BASE"

        if len(requested_sizes) > 1:
            # Flat grading modu: doğrusal ölçekleme ile birden fazla beden üret
            ref_key = label  # PLT'deki anahtar
            pass  # graded_all aşağıda üretilecek
        else:
            requested_sizes = [label]
    elif is_multi:
        # Çoklu beden (S1…SN veya labeled): tüm bedenleri işle
        # requested_sizes zaten kullanıcıdan geliyor; yoksa tüm bedenler
        if not requested_sizes or requested_sizes == ["BASE"]:
            requested_sizes = list(s.parsed_pieces.keys())
        # Referans beden: requested_sizes içindeki ilk
        if requested_sizes[0] in s.parsed_pieces:
            s.reference_size = requested_sizes[0]

    # Grading motoru
    engine = GradingEngine(
        grouped_pieces=s.parsed_pieces,
        reference_size=s.reference_size,
    )

    # PLT'de tüm istenen bedenler zaten varsa → passthrough (grading gerekmez)
    plt_sizes = set(s.parsed_pieces.keys())
    all_present = all(sz in plt_sizes for sz in requested_sizes)

    # Flat PLT + birden fazla hedef beden → doğrusal grading
    flat_multi = (
        has_base and not is_multi and len(requested_sizes) > 1
        and not all_present
    )

    if all_present:
        logger.info("Tüm bedenler PLT'de mevcut — grading atlandı (passthrough)")
        _set_progress(session_id, 15, "Parçalar hazırlanıyor...")
        graded_all = engine.passthrough_all(target_sizes=requested_sizes)
        s.grading_vectors = {}
    elif flat_multi:
        # Tek beden PLT'den doğrusal ölçekleme
        ref_key = s.reference_size
        _set_progress(session_id, 15, f"Doğrusal grading ({len(requested_sizes)} beden)...")
        try:
            graded_all = engine.grade_all_flat(
                target_sizes=requested_sizes,
                ref_size_key=ref_key,
                width_step_mm=width_step_mm,
                height_step_mm=height_step_mm,
            )
        except ValueError as e:
            _set_progress(session_id, 0, str(e), done=True, error=str(e))
            raise HTTPException(422, f"Flat grading hatası: {e}")
        s.grading_vectors = {}
    else:
        _set_progress(session_id, 10, "Grading hesaplanıyor...")
        try:
            grading_vectors = engine.compute_grading()
        except ValueError as e:
            _set_progress(session_id, 0, str(e), done=True, error=str(e))
            raise HTTPException(422, f"Grading hatası: {e}")
        s.grading_vectors = grading_vectors
        _set_progress(session_id, 20, "Bedenler üretiliyor...")
        graded_all = engine.grade_all(
            target_sizes=requested_sizes,
            grading_vectors=grading_vectors,
        )

    # SVG ve PDF üret
    placer = SVGDesignPlacer(bleed_mm=bleed_mm, dpi=dpi)
    out_dir = _output_dir(session_id)

    s.output_svgs = {}
    s.output_pdfs = {}
    failed_sizes = []
    n = len(requested_sizes)

    for idx, size in enumerate(requested_sizes):
        pct_start = 20 + int(idx / n * 75)
        _set_progress(session_id, pct_start, f"Beden {size} işleniyor... ({idx+1}/{n})")

        size_pieces = graded_all.get(size)
        if not size_pieces:
            s.errors.append(f"Beden {size} için parça üretilemedi")
            failed_sizes.append(size)
            continue

        size_out_dir = out_dir / size
        size_out_dir.mkdir(exist_ok=True)

        # Kombine SVG (tüm parçalar tek dosyada)
        combined_svg_path = str(size_out_dir / f"{size}_combined.svg")
        try:
            placer.generate_combined_svg(
                pieces=size_pieces,
                design_files=s.design_files,
                output_path=combined_svg_path,
                size=size,
                rotations=rotations,
            )
        except Exception as e:
            logger.error(f"Beden {size} SVG hatası: {e}")
            s.errors.append(f"Beden {size} SVG üretim hatası: {e}")
            failed_sizes.append(size)
            continue

        # Parça parça SVG'ler
        piece_svgs = placer.generate_all_pieces_svg(
            pieces=size_pieces,
            design_files=s.design_files,
            output_dir=str(size_out_dir / "pieces"),
            size=size,
            rotations=rotations,
        )

        s.output_svgs[size] = {
            "combined": combined_svg_path,
            **piece_svgs,
        }

        # PDF (Pillow tabanlı — Cairo gerekmez)
        pdf_path = str(out_dir / f"{size}_forma.pdf")
        pdf_ok = generate_size_pdf(
            svg_paths_by_piece=piece_svgs,
            output_pdf_path=pdf_path,
            size=size,
            dpi=dpi,
            combined_svg_path=combined_svg_path,
            graded_pieces=size_pieces,
            design_files=s.design_files,
            bleed_mm=bleed_mm,
            rotations=rotations,
        )

        if pdf_ok:
            s.output_pdfs[size] = pdf_path
            logger.info(f"Beden {size} PDF hazır: {pdf_path}")
        else:
            s.errors.append(f"Beden {size} PDF üretilemedi")

    logger.info(
        f"Grading tamamlandı: {len(s.output_pdfs)}/{len(requested_sizes)} beden"
    )

    if failed_sizes and not s.output_pdfs:
        _set_progress(session_id, 100, "Hata: Hiç beden üretilemedi", done=True, error="Tüm bedenler başarısız")
    else:
        _set_progress(session_id, 100, f"Tamamlandı! {len(s.output_pdfs)} beden hazır.", done=True)

    _save_session(s)

    return {
        "completed_sizes": list(s.output_pdfs.keys()),
        "failed_sizes": failed_sizes,
        "total_requested": len(requested_sizes),
        "grading_vectors_computed": list(s.grading_vectors.keys()),
        "errors": s.errors,
        "download_urls": {
            size: f"/session/{session_id}/pdf/{size}"
            for size in s.output_pdfs.keys()
        },
    }


# ─── PDF indirme ──────────────────────────────────────────────────────────────

@app.get("/session/{session_id}/pdf/{size}")
async def download_pdf(session_id: str, size: str):
    """Üretilen PDF'i indir."""
    s = _get_session(session_id)
    size = size.upper()

    pdf_path = s.output_pdfs.get(size)
    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(404, f"Beden {size} için PDF bulunamadı. Önce /grade çalıştırın.")

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"forma_{size}.pdf",
    )


# ─── ZIP indirme ──────────────────────────────────────────────────────────────

@app.get("/session/{session_id}/download-all")
async def download_all_pdfs(session_id: str):
    """Tüm üretilmiş PDF'leri ZIP olarak indir."""
    import io, zipfile
    from fastapi.responses import StreamingResponse

    s = _get_session(session_id)
    if not s.output_pdfs:
        raise HTTPException(404, "Henüz PDF üretilmedi. Önce /grade çalıştırın.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for size, pdf_path in s.output_pdfs.items():
            if os.path.exists(pdf_path):
                zf.write(pdf_path, arcname=f"forma_{size}.pdf")

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="formalar_{session_id}.zip"'},
    )


# ─── SVG önizleme ─────────────────────────────────────────────────────────────

@app.get("/session/{session_id}/svg/{size}")
async def get_combined_svg(session_id: str, size: str):
    """Bir bedenin kombine SVG önizlemesini döndür."""
    s = _get_session(session_id)
    size = size.upper()

    svg_info = s.output_svgs.get(size, {})
    combined_path = svg_info.get("combined")

    if not combined_path or not os.path.exists(combined_path):
        raise HTTPException(404, f"Beden {size} için SVG bulunamadı. Önce /grade çalıştırın.")

    return FileResponse(
        path=combined_path,
        media_type="image/svg+xml",
        filename=f"forma_{size}.svg",
    )


@app.get("/session/{session_id}/svg/{size}/{piece_type}")
async def get_piece_svg(session_id: str, size: str, piece_type: str):
    """Tek parça SVG önizlemesi."""
    s = _get_session(session_id)
    size = size.upper()

    svg_info = s.output_svgs.get(size, {})
    piece_path = svg_info.get(piece_type)

    if not piece_path or not os.path.exists(piece_path):
        raise HTTPException(404, f"{size}/{piece_type} için SVG bulunamadı")

    return FileResponse(path=piece_path, media_type="image/svg+xml")


# ─── Önizleme JSON ────────────────────────────────────────────────────────────

@app.get("/session/{session_id}/preview")
async def get_preview_data(session_id: str):
    """
    Frontend önizlemesi için parça koordinatlarını JSON olarak döndür.
    Her parça için: bounding box, nokta sayısı, beden, tip.
    """
    s = _get_session(session_id)

    if not s.parsed_pieces:
        raise HTTPException(400, "PLT henüz yüklenmedi")

    result: Dict[str, Any] = {}

    for size, piece_dict in s.parsed_pieces.items():
        result[size] = {}
        for ptype, piece in piece_dict.items():
            bb = piece.bounding_box()
            # SVG önizleme için basitleştirilmiş nokta listesi (maks 100 nokta)
            pts = piece.points
            if len(pts) > 100:
                step = len(pts) // 100
                pts = pts[::step]

            result[size][ptype] = {
                "label": piece.label,
                "n_points": len(piece.points),
                "area_cm2": round(piece.area() / 100, 1),
                "bbox": {
                    "x": round(bb.x_min, 1),
                    "y": round(bb.y_min, 1),
                    "w": round(bb.width, 1),
                    "h": round(bb.height, 1),
                },
                "points_preview": [[round(x, 1), round(y, 1)] for x, y in pts],
            }

    return result


# ─── Grading vektörleri (debug) ───────────────────────────────────────────────

@app.get("/session/{session_id}/preview-svg/{piece_type}")
async def preview_piece_svg(session_id: str, piece_type: str):
    """
    Adım 3'te desen yüklendikten sonra anlık SVG önizlemesi döndür.
    Tasarım yüklenmediyse parça konturunu gösterir.
    Dosyaya yazmaz — bellekte üretir.
    """
    import tempfile

    s = _get_session(session_id)
    if not s.parsed_pieces:
        raise HTTPException(400, "PLT henüz yüklenmedi")

    # Parçayı bul (referans beden veya BASE)
    piece = None
    for candidate_size in [s.reference_size, "BASE"] + list(s.parsed_pieces.keys()):
        piece = s.parsed_pieces.get(candidate_size, {}).get(piece_type)
        if piece is not None:
            break

    if piece is None:
        raise HTTPException(404, f"Parça '{piece_type}' bulunamadı")

    gp = GradedPiece(
        piece_type=getattr(piece, "piece_type", piece_type),
        size=getattr(piece, "size", s.reference_size),
        points=piece.points.copy(),
        source_label=getattr(piece, "label", ""),
    )

    design_path = s.design_files.get(piece_type)
    if design_path and not os.path.exists(design_path):
        design_path = None

    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tf:
        tmp_path = tf.name

    try:
        placer = SVGDesignPlacer(bleed_mm=3.0, dpi=150)
        placer.generate_svg(
            piece=gp,
            design_image_path=design_path,
            output_path=tmp_path,
        )
        content = Path(tmp_path).read_text(encoding="utf-8")
    finally:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass

    return Response(content=content, media_type="image/svg+xml")


@app.get("/session/{session_id}/grading-info")
async def get_grading_info(session_id: str):
    """Hesaplanan grading vektörlerinin özetini döndür."""
    s = _get_session(session_id)

    if not s.grading_vectors:
        raise HTTPException(400, "Grading henüz çalıştırılmadı")

    info = {}
    for ptype, gv in s.grading_vectors.items():
        avg_dx = float(gv.vectors[:, 0].mean())
        avg_dy = float(gv.vectors[:, 1].mean())
        max_dx = float(abs(gv.vectors[:, 0]).max())
        max_dy = float(abs(gv.vectors[:, 1]).max())
        info[ptype] = {
            "from_size": gv.from_size,
            "to_size": gv.to_size,
            "n_samples": gv.n_samples,
            "avg_dx_mm": round(avg_dx, 3),
            "avg_dy_mm": round(avg_dy, 3),
            "max_dx_mm": round(max_dx, 3),
            "max_dy_mm": round(max_dy, 3),
        }

    return info


# ─── Ham PLT debug SVG ───────────────────────────────────────────────────────

@app.get("/session/{session_id}/debug-classified")
async def debug_classified_svg(session_id: str):
    """Geometrik sınıflandırma SVG'sini döndür (etiketsiz PLT)."""
    s = _get_session(session_id)
    if not s.plt_path:
        raise HTTPException(400, "PLT henüz yüklenmedi")
    svg_path = Path(s.plt_path).parent / "classified_debug.svg"
    if not svg_path.exists():
        raise HTTPException(404, "Sınıflandırma SVG'si bulunamadı (etiketli PLT olabilir)")
    return FileResponse(path=str(svg_path), media_type="image/svg+xml")


@app.get("/session/{session_id}/debug-plt")
async def debug_plt_svg(session_id: str):
    """
    PLT'den okunan ham parçaları SVG olarak döndür.
    Her parça farklı renkte, etiketi ve alanı gösterilir.
    Tarayıcıda açarak parse doğruluğunu kontrol edin.
    """
    s = _get_session(session_id)
    if not s.parsed_pieces:
        raise HTTPException(400, "PLT henüz yüklenmedi")

    COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706",
              "#7c3aed", "#0891b2", "#be185d", "#65a30d"]

    all_pieces = [
        (size, ptype, piece)
        for size, pd in s.parsed_pieces.items()
        for ptype, piece in pd.items()
    ]
    if not all_pieces:
        raise HTTPException(404, "Parça bulunamadı")

    # Genel bounding box
    all_pts = np.vstack([p.points for _, _, p in all_pieces])
    gx_min, gy_min = all_pts[:, 0].min(), all_pts[:, 1].min()
    gx_max, gy_max = all_pts[:, 0].max(), all_pts[:, 1].max()
    W = gx_max - gx_min + 40
    H = gy_max - gy_min + 40
    PAD = 20

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.1f} {H:.1f}" '
        f'width="{min(1200, W*0.8):.0f}" style="background:#f8fafc">',
        '<style>text{font-family:sans-serif;pointer-events:none}</style>',
    ]

    for i, (size, ptype, piece) in enumerate(all_pieces):
        color = COLORS[i % len(COLORS)]
        pts_shifted = piece.points - np.array([gx_min - PAD, gy_min - PAD])
        poly = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts_shifted)
        cx = float(pts_shifted[:, 0].mean())
        cy = float(pts_shifted[:, 1].mean())
        area = piece.area()
        lines += [
            f'<polygon points="{poly}" fill="{color}33" stroke="{color}" stroke-width="1"/>',
            f'<text x="{cx:.1f}" y="{cy-8:.1f}" text-anchor="middle" '
            f'font-size="8" font-weight="bold" fill="{color}">{size}/{ptype}</text>',
            f'<text x="{cx:.1f}" y="{cy+6:.1f}" text-anchor="middle" '
            f'font-size="6" fill="{color}99">{area/100:.0f}cm² · {piece.label[:20]}</text>',
        ]

    lines.append("</svg>")
    from fastapi.responses import HTMLResponse
    svg_content = "\n".join(lines)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>PLT Debug — {session_id}</title>
<style>body{{margin:0;padding:20px;background:#1e293b;color:white;font-family:sans-serif}}
h2{{margin-bottom:10px}}svg{{max-width:100%;border-radius:8px}}</style>
</head><body>
<h2>PLT Ham Parça Görünümü — {session_id}</h2>
<p style="opacity:.6;font-size:13px">
  {len(all_pieces)} parça · Renk = parça tipi · Etiket = beden/tip/alan
</p>
{svg_content}
</body></html>"""
    return HTMLResponse(html)


# ─── Manuel parça tipi atama ─────────────────────────────────────────────────

@app.post("/session/{session_id}/assign-piece-type")
async def assign_piece_type(
    session_id: str,
    size: str = Form(...),
    old_type: str = Form(...),
    new_type: str = Form(...),
):
    """
    Kullanıcı belirli bir parçanın tipini değiştirir.
    Örn: size=M, old_type=unknown, new_type=front
    """
    s = _get_session(session_id)
    size = size.upper()

    if size not in s.parsed_pieces:
        raise HTTPException(404, f"Beden {size} bulunamadı")

    piece_dict = s.parsed_pieces[size]
    if old_type not in piece_dict:
        raise HTTPException(404, f"Parça tipi '{old_type}' bulunamadı")

    if new_type not in ["front", "back", "left_sleeve", "right_sleeve", "unknown"]:
        raise HTTPException(400, f"Geçersiz parça tipi: {new_type}")

    piece = piece_dict.pop(old_type)
    piece.piece_type = new_type

    # Aynı tipte zaten varsa eski olanı sil
    if new_type in piece_dict:
        logger.warning(f"  {size}/{new_type} zaten var, üzerine yazılıyor")

    piece_dict[new_type] = piece
    logger.info(f"Parça tipi değiştirildi: {size}/{old_type} → {new_type}")

    return {
        "size": size,
        "old_type": old_type,
        "new_type": new_type,
        "current_pieces": list(piece_dict.keys()),
    }


# ─── Tüm oturumlar (admin) ────────────────────────────────────────────────────

@app.get("/sessions")
async def list_sessions():
    return [
        {
            "session_id": s.session_id,
            "reference_size": s.reference_size,
            "has_plt": s.plt_path is not None,
            "designs_uploaded": len(s.design_files),
            "pdfs_ready": len(s.output_pdfs),
        }
        for s in sessions.values()
    ]
