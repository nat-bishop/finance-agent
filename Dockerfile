FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# System deps for scipy/numpy wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Install claude-code CLI (bundled by SDK)
RUN uv pip install --system --no-cache claude-code

# Install project deps — copy source before install so -e works
COPY pyproject.toml uv.lock /app/
COPY src/ /app/src/
RUN uv pip install --system --no-cache "/app"

# Create isolated agent workspace
RUN mkdir -p /workspace/{analysis,data,lib,backups}
COPY workspace/lib/ /workspace/lib/

WORKDIR /workspace
CMD ["python", "-m", "finance_agent.main"]
