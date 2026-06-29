FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONPATH=/app

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml README.md ./

RUN python -m pip install --upgrade pip \
    && python -m pip install -e ".[dev]"

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN mkdir -p /app/storage/reports /app/storage/profile-images /app/artifacts \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
