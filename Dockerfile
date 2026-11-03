FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/Parabolum/coc-clan-tracker"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN groupadd --gid 10001 tracker \
    && useradd --uid 10001 --gid tracker --create-home --shell /usr/sbin/nologin tracker \
    && mkdir -p /app/data \
    && chown -R tracker:tracker /app

USER tracker

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
