FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock .python-version /app/
RUN uv sync --locked --no-dev --no-install-project --no-editable

COPY src /app/src
RUN uv sync --locked --no-dev --no-editable

EXPOSE 8000
CMD ["uvicorn", "software_developer_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
