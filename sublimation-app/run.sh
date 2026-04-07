#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# Sublimasyon Forma Üretim Sistemi — Başlatma Scripti
# ────────────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo " Sublimasyon Forma Üretim Sistemi"
echo "=========================================="

# Python sürüm kontrolü
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
  echo "HATA: Python bulunamadı. Python 3.9+ gerekli."
  exit 1
fi

PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python: $PY_VERSION"

# Sanal ortam
if [ ! -d "venv" ]; then
  echo ""
  echo "→ Sanal ortam oluşturuluyor..."
  $PYTHON -m venv venv
fi

# Sanal ortamı etkinleştir
if [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
elif [ -f "venv/Scripts/activate" ]; then
  source venv/Scripts/activate
fi

echo "→ Bağımlılıklar yükleniyor..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# Cairo kontrolü (macOS)
if command -v brew &>/dev/null; then
  if ! brew list cairo &>/dev/null 2>&1; then
    echo ""
    echo "⚠  cairosvg için Cairo kütüphanesi önerilen. Kurmak için:"
    echo "   brew install cairo"
    echo "   (Şimdi atlanıyor — PDF çıktısı sınırlı olabilir)"
    echo ""
  fi
fi

# Dizinleri oluştur
mkdir -p uploads outputs

echo ""
echo "→ Sunucu başlatılıyor..."
echo ""
echo "  API:      http://localhost:8000"
echo "  Arayüz:   http://localhost:8000/app"
echo "  API Docs: http://localhost:8000/docs"
echo ""
echo "Durdurmak için: Ctrl+C"
echo "=========================================="
echo ""

uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload \
  --log-level info
