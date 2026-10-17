"""Almacenamiento temporal de archivos generados (sin base de datos).

Cada procesamiento crea ``<work_dir>/<uuid4>/output.xlsx`` + ``meta.json``. El
directorio se elimina (a) tras completar la descarga, o (b) al vencer el TTL
(30 min por defecto). El nombre del archivo del usuario NUNCA forma parte de la ruta.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("ingeslingas.jobs")

_JOB_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
OUTPUT_NAME = "output.xlsx"
META_NAME = "meta.json"


@dataclass(frozen=True)
class Job:
    job_id: str
    directory: Path

    @property
    def output_path(self) -> Path:
        return self.directory / OUTPUT_NAME

    @property
    def meta_path(self) -> Path:
        return self.directory / META_NAME


class JobStore:
    def __init__(self, root: Path, ttl_seconds: int) -> None:
        self.root = root
        self.ttl_seconds = ttl_seconds
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except OSError:  # pragma: no cover - sistemas de archivos sin permisos POSIX
            pass
        self._root_resolved = self.root.resolve()

    # -- creación ---------------------------------------------------------- #
    def create(self) -> Job:
        self.cleanup_expired()
        job_id = str(uuid.uuid4())
        directory = self.root / job_id
        directory.mkdir(mode=0o700)
        return Job(job_id, directory)

    def commit(self, job: Job, download_name: str) -> None:
        """Marca el trabajo como descargable. Solo guarda el nombre y la hora."""
        meta = {"filename": download_name, "created": time.time()}
        job.meta_path.write_text(json.dumps(meta), encoding="utf-8")

    # -- consulta ---------------------------------------------------------- #
    def get(self, job_id: str) -> tuple[Job, str] | None:
        """Devuelve (job, nombre de descarga) si el trabajo existe y no venció."""
        job = self._resolve(job_id)
        if job is None or not job.output_path.is_file() or not job.meta_path.is_file():
            return None
        try:
            meta = json.loads(job.meta_path.read_text(encoding="utf-8"))
            created = float(meta["created"])
            filename = str(meta["filename"])
        except (OSError, ValueError, KeyError):
            return None
        if time.time() - created > self.ttl_seconds:
            self.delete(job_id)
            return None
        return job, filename

    # -- eliminación ------------------------------------------------------- #
    def delete(self, job_id: str) -> bool:
        job = self._resolve(job_id)
        if job is None:
            return False
        shutil.rmtree(job.directory, ignore_errors=True)
        return True

    def cleanup_expired(self) -> int:
        """Elimina trabajos vencidos (o sin metadatos y antiguos). Devuelve cuántos."""
        removed = 0
        now = time.time()
        try:
            entries = list(self.root.iterdir())
        except OSError:
            return 0
        for entry in entries:
            if not entry.is_dir() or not _JOB_ID_RE.fullmatch(entry.name):
                continue
            created = self._created_at(entry)
            if now - created > self.ttl_seconds:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        if removed:
            logger.info("Se eliminaron %d trabajo(s) temporal(es) vencido(s)", removed)
        return removed

    def purge_all(self) -> None:
        for entry in self.root.iterdir():
            if entry.is_dir() and _JOB_ID_RE.fullmatch(entry.name):
                shutil.rmtree(entry, ignore_errors=True)

    # -- internos ---------------------------------------------------------- #
    def _resolve(self, job_id: str) -> Job | None:
        if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
            return None
        directory = (self.root / job_id).resolve()
        if directory.parent != self._root_resolved or not directory.is_dir():
            return None
        return Job(job_id, directory)

    @staticmethod
    def _created_at(directory: Path) -> float:
        meta = directory / META_NAME
        try:
            return float(json.loads(meta.read_text(encoding="utf-8"))["created"])
        except (OSError, ValueError, KeyError):
            try:
                return directory.stat().st_mtime
            except OSError:
                return 0.0
