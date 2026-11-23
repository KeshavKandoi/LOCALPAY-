FROM python:3.13-slim-bookworm AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.12 /uv /usr/local/bin/uv
WORKDIR /srv/localpay
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN useradd --no-create-home --uid 10001 localpay
ENV PATH="/srv/localpay/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
FROM base AS test
RUN uv sync --locked --no-install-project
COPY apps/api/app ./app
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./
COPY apps/api/tests ./tests
USER localpay
CMD ["pytest"]

FROM base AS runtime
RUN uv sync --locked --no-dev --no-install-project
COPY apps/api/app ./app
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./
USER localpay
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
