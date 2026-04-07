import sys
import os

# Backend paketini import edilebilir yap
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.main import app
