# syntax=docker/dockerfile:1
# Runtime image for the Financial Document Intelligence API.
# Defaults to local/mock mode; point DOCINTEL_* env vars at Bedrock / Azure OpenAI for real providers.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    DOCINTEL_DATA_DIR=/data \
    DOCINTEL_LOG_JSON=true

# tesseract-ocr enables the local OCR path for scanned PDFs (ocr_provider=auto picks it up).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first (pinned, platform-universal lock) for layer caching.
COPY requirements.lock ./
RUN pip install -r requirements.lock

# Application code and the assets it reads at runtime.
COPY app ./app
COPY prompts ./prompts
COPY config ./config
COPY evals ./evals
COPY sample_data ./sample_data
COPY scripts ./scripts

RUN useradd --create-home --uid 10001 docintel \
    && mkdir -p /data \
    && chown docintel:docintel /data
USER docintel
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
