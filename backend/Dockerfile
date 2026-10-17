FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/backend

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY templates ./templates

# Usuario sin privilegios; los archivos temporales viven en /tmp/ingeslingas-excel-portal.
RUN useradd --system --uid 10001 --no-create-home appuser
USER appuser

EXPOSE 8000

# Render define PORT; en local se usa 8000.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
