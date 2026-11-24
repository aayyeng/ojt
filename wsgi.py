"""WSGI entry point for PythonAnywhere (and other WSGI hosts)."""
import os
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

os.environ.setdefault("OJT_CLOUD", "1")

from app import app as application  # noqa: E402, F401
