FROM ghcr.io/astral-sh/uv:0.9.5-python3.12-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends libportaudio2 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY services ./services
COPY scripts ./scripts
COPY evaluations ./evaluations
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/services/api:/app/services/agent"
EXPOSE 8000
CMD ["uvicorn", "support_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
