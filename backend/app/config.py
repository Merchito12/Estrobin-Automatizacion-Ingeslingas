"""Configuración del servicio (variables de entorno) y rutas del proyecto."""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("ingeslingas.config")

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent                 # backend/
TEMPLATES_DIR = BASE_DIR / "templates"
PROFILES_DIR = APP_DIR / "profiles"

# Orígenes de desarrollo. La URL de GitHub Pages se añade con ALLOWED_ORIGINS.
DEFAULT_DEV_ORIGINS = (
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:5173",
    "http://localhost:8080",
    "http://localhost:3000",
)

ALLOWED_EXTENSIONS = frozenset({".xls", ".xlsx", ".csv"})


@dataclass(frozen=True)
class Settings:
    allowed_origins: tuple[str, ...]
    job_ttl_minutes: int
    max_upload_mb: int
    work_dir: Path
    log_level: str
    enable_docs: bool

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def job_ttl_seconds(self) -> int:
        return self.job_ttl_minutes * 60


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        logger.warning("Valor inválido para %s; se usa %s", name, default)
        return default


def parse_origins(raw: str | None) -> tuple[str, ...]:
    """Convierte ALLOWED_ORIGINS en una lista exacta de orígenes (nunca '*')."""
    if raw is None or not raw.strip():
        return DEFAULT_DEV_ORIGINS
    origins: list[str] = []
    for item in raw.split(","):
        origin = item.strip().rstrip("/")
        if not origin:
            continue
        if origin == "*":
            logger.warning("ALLOWED_ORIGINS='*' no está permitido y se ignora")
            continue
        if origin not in origins:
            origins.append(origin)
    return tuple(origins) or DEFAULT_DEV_ORIGINS


def load_settings() -> Settings:
    default_work_dir = Path(tempfile.gettempdir()) / "ingeslingas-excel-portal"
    return Settings(
        allowed_origins=parse_origins(os.getenv("ALLOWED_ORIGINS")),
        job_ttl_minutes=_int_env("JOB_TTL_MINUTES", 30),
        max_upload_mb=_int_env("MAX_UPLOAD_MB", 25),
        work_dir=Path(os.getenv("WORK_DIR") or default_work_dir),
        log_level=(os.getenv("LOG_LEVEL") or "INFO").upper(),
        enable_docs=(os.getenv("ENABLE_DOCS", "").lower() in {"1", "true", "yes"}),
    )
