FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src src
RUN uv sync --frozen --no-dev --no-editable && rm /usr/local/bin/uv

ENV PATH=/app/.venv/bin:$PATH HOME=/tmp
USER 1000:1000
ENTRYPOINT ["github-archive"]
CMD ["run"]
