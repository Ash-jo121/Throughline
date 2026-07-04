from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COGNEE_ROOT = PROJECT_ROOT / ".cognee"
COGNEE_SYSTEM_ROOT = COGNEE_ROOT / "system"
COGNEE_DATA_ROOT = COGNEE_ROOT / "data"
COGNEE_CACHE_ROOT = COGNEE_ROOT / "cache"
COGNEE_LOGS_ROOT = COGNEE_ROOT / "logs"
COGNEE_HOME_ROOT = COGNEE_ROOT / "home"
DATASET_NAME = "throughline_day1"
APP_STATE_ROOT = PROJECT_ROOT / ".throughline"
BRIEF_DB_PATH = APP_STATE_ROOT / "throughline.db"


def configure_environment() -> None:
    """Load local settings before importing Cognee-heavy modules."""

    load_dotenv(PROJECT_ROOT / ".env", encoding="utf-8-sig")
    os.environ.setdefault("SYSTEM_ROOT_DIRECTORY", str(COGNEE_SYSTEM_ROOT))
    os.environ.setdefault("DATA_ROOT_DIRECTORY", str(COGNEE_DATA_ROOT))
    os.environ.setdefault("CACHE_ROOT_DIRECTORY", str(COGNEE_CACHE_ROOT))
    os.environ.setdefault("COGNEE_LOGS_DIR", str(COGNEE_LOGS_ROOT))
    os.environ.setdefault("COGNEE_LOG_FILE", "false")
    os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
    os.environ.setdefault("REQUIRE_AUTHENTICATION", "false")
    os.environ["HOME"] = str(COGNEE_HOME_ROOT)
    os.environ["USERPROFILE"] = str(COGNEE_HOME_ROOT)
