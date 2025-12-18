FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt requirements-pptx.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt && \
    python -m pip install --no-cache-dir -r requirements-pptx.txt

COPY app ./app
COPY templates ./templates
COPY static ./static
COPY data ./data
COPY scripts ./scripts

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
