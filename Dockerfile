FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests
COPY scripts ./scripts

EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=3s --start-period=3s --retries=12 \
    CMD python -c "import json,urllib.request,sys; info=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)); sys.exit(0 if info.get('status')=='ok' else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
