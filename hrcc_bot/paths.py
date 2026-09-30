"""Filesystem locations, anchored to the repository root (not the working directory)."""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
KNOWLEDGE_FILE = KNOWLEDGE_DIR / "knowledge_data.yaml"
REFERENCES_DIR = KNOWLEDGE_DIR / "references"
ENV_FILE = PROJECT_ROOT / ".env"
