"""Pruebas de la API HTTP (requieren fastapi; se omiten si no está instalado)."""
import json
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings, parse_origins  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.conftest import helisa_rows, make_xlsx  # noqa: E402

GITHUB_ORIGIN = "https://usuario.github.io"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        allowed_origins=(GITHUB_ORIGIN, "http://localhost:5500"),
        job_ttl_minutes=30, max_upload_mb=1, work_dir=tmp_path / "work",
        log_level="WARNING", enable_docs=False,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def upload(client, data, name="ventas.xlsx", portal_error=None, headers=None):
    return client.post(
        "/api/process",
        files={"file": (name, data, "application/octet-stream")},
        data={"portal_error": portal_error} if portal_error is not None else {},
        headers=headers or {},
    )


def good_file():
    return make_xlsx(helisa_rows(4), "Consulta")


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_docs_are_disabled_by_default(client):
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_process_then_download_deletes_the_file(client):
    response = upload(client, good_file(), portal_error="la columna G debe ser fecha corta")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] and body["recordsFound"] == 4 and body["outputFilename"].endswith("JULIO 2026.xlsx")
    assert any(h["code"] == "dates" for h in body["portalErrorHints"])
    job_dir = client.app.state.settings.work_dir / body["jobId"]
    assert (job_dir / "output.xlsx").is_file()

    download = client.get(f"/api/download/{body['jobId']}")
    assert download.status_code == 200
    assert download.headers["content-type"] == XLSX
    assert "PlantillaDeclaracionVentas JULIO 2026.xlsx" in download.headers["content-disposition"]
    assert download.content[:2] == b"PK"
    assert not job_dir.exists()                                  # eliminado tras completar la respuesta

    again = client.get(f"/api/download/{body['jobId']}")
    assert again.status_code == 404 and again.json()["ok"] is False


@pytest.mark.parametrize("name", ["informe.pdf", "ventas.xlsm", "ventas.exe", "ventas", "ventas.xlsx.txt"])
def test_disallowed_extensions_are_rejected(client, name):
    response = upload(client, b"contenido", name=name)
    assert response.status_code == 415 and response.json()["errors"][0]["code"] == "bad_extension"


def test_oversized_upload_is_rejected(client):
    response = upload(client, b"a,b\n" + b"1,2\n" * 400_000, name="grande.csv")
    assert response.status_code == 413


def test_invalid_file_content_returns_json_error(client):
    response = upload(client, b"esto no es un excel", name="ventas.xlsx")
    assert response.status_code in (200, 422)
    body = response.json()
    assert body["ok"] is False and body["errors"] and "Traceback" not in json.dumps(body)


def test_missing_file_field_is_422(client):
    assert client.post("/api/process", data={"portal_error": "x"}).status_code == 422


def test_validation_errors_are_returned_with_rows(client):
    rows = helisa_rows(3)
    rows[1][4] = None
    body = upload(client, make_xlsx(rows, "Consulta")).json()
    assert body["ok"] is False and body["errors"][0]["row"] == 2
    assert "jobId" not in body


@pytest.mark.parametrize("job_id", ["../../etc/passwd", "..", "123", "00000000-0000-0000-0000-000000000000"])
def test_download_rejects_invalid_ids(client, job_id):
    assert client.get(f"/api/download/{job_id}").status_code == 404


def test_expired_job_cannot_be_downloaded(client):
    body = upload(client, good_file()).json()
    meta = client.app.state.settings.work_dir / body["jobId"] / "meta.json"
    meta.write_text(json.dumps({"filename": "x.xlsx", "created": time.time() - 3600}))
    assert client.get(f"/api/download/{body['jobId']}").status_code == 404
    assert not meta.parent.exists()


def test_uploaded_filename_never_becomes_a_path(client):
    response = upload(client, good_file(), name="../../../tmp/evil.xlsx")
    assert response.status_code == 200
    job_id = response.json()["jobId"]
    assert [p.name for p in client.app.state.settings.work_dir.iterdir()] == [job_id]


def test_cors_allows_only_configured_origins(client):
    ok = client.get("/api/health", headers={"Origin": GITHUB_ORIGIN})
    assert ok.headers["access-control-allow-origin"] == GITHUB_ORIGIN
    assert "content-disposition" in ok.headers.get("access-control-expose-headers", "").lower()
    bad = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    preflight = client.options("/api/process", headers={
        "Origin": GITHUB_ORIGIN, "Access-Control-Request-Method": "POST"})
    assert preflight.status_code == 200 and preflight.headers["access-control-allow-origin"] == GITHUB_ORIGIN
    denied = client.options("/api/process", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert denied.status_code == 400


def test_origins_parsing_never_allows_wildcard():
    assert "*" not in parse_origins("*, https://a.github.io/ ,")
    assert parse_origins("https://a.github.io/, https://b.example") == ("https://a.github.io", "https://b.example")
    assert "http://localhost:5500" in parse_origins(None)
