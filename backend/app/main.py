"""API FastAPI del portal de archivos de INGESLINGAS S.A.S."""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from .config import ALLOWED_EXTENSIONS, Settings, load_settings
from .profile import get_profile
from .services.jobs import JobStore
from .services.pipeline import process_upload
from .utils.text import safe_display_name

logger = logging.getLogger("ingeslingas.api")

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CLEANUP_INTERVAL_SECONDS = 60
READ_CHUNK = 1024 * 1024


def _error_body(message: str, code: str, **extra: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "recordsFound": 0,
        "validRecords": 0,
        "errors": [{"severity": "error", "code": code, "message": message, "row": None, "column": None}],
        "errorCount": 1,
        "warnings": [],
        "warningCount": 0,
        "mapping": [],
        "portalErrorHints": [],
        **extra,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    profile = get_profile()
    store = JobStore(settings.work_dir, settings.job_ttl_seconds)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async def sweeper() -> None:
            while True:
                await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
                try:
                    await run_in_threadpool(store.cleanup_expired)
                except Exception:  # la limpieza nunca debe tumbar el servicio
                    logger.exception("Fallo en la limpieza periódica de trabajos")

        store.cleanup_expired()
        task = asyncio.create_task(sweeper())
        try:
            yield
        finally:
            task.cancel()

    docs = settings.enable_docs
    app = FastAPI(
        title="Portal de archivos INGESLINGAS",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.profile = profile

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        reference = uuid.uuid4().hex[:8]
        logger.error("Error no controlado [%s]", reference, exc_info=exc)
        return JSONResponse(
            _error_body(f"Error interno del servidor. Referencia: {reference}.", "server_error"),
            status_code=500,
        )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/process")
    async def process(
        request: Request,
        file: UploadFile = File(...),
        portal_error: str | None = Form(default=None),
    ) -> JSONResponse:
        display_name = safe_display_name(file.filename)
        extension = PurePosixPath(display_name.lower()).suffix
        if extension not in ALLOWED_EXTENSIONS:
            return JSONResponse(
                _error_body("Formato no permitido. Solo se aceptan archivos .xls, .xlsx y .csv.", "bad_extension"),
                status_code=415,
            )

        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes + 64 * 1024:
            return JSONResponse(_too_large(settings), status_code=413)

        data = bytearray()
        while True:
            chunk = await file.read(READ_CHUNK)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > settings.max_upload_bytes:
                return JSONResponse(_too_large(settings), status_code=413)
        await file.close()

        logger.info("Solicitud de procesamiento: extensión=%s tamaño=%d bytes", extension, len(data))
        try:
            result = await run_in_threadpool(process_upload, bytes(data), extension, portal_error, profile, store)
        except Exception:
            reference = uuid.uuid4().hex[:8]
            logger.exception("Fallo no controlado al procesar el archivo [%s]", reference)
            return JSONResponse(
                _error_body(f"Error interno al procesar el archivo. Referencia: {reference}.", "server_error"),
                status_code=500,
            )
        return JSONResponse(result.payload, status_code=result.http_status)

    @app.get("/api/download/{job_id}")
    async def download(job_id: str) -> Any:
        found = await run_in_threadpool(store.get, job_id)
        if found is None:
            return JSONResponse(
                _error_body("El archivo ya fue descargado o expiró. Procésalo nuevamente.", "not_found"),
                status_code=404,
            )
        job, filename = found
        return FileResponse(
            job.output_path,
            media_type=XLSX_MEDIA_TYPE,
            filename=filename,
            background=BackgroundTask(store.delete, job_id),   # se elimina al terminar la respuesta
        )

    return app


def _too_large(settings: Settings) -> dict[str, Any]:
    return _error_body(f"El archivo supera el tamaño máximo permitido de {settings.max_upload_mb} MB.", "too_large")


app = create_app()
