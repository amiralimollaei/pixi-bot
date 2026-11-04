FROM python:3.13-slim-trixie

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install uv for dependency setup and the shared launcher.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ARG PIXI_EXTRAS="telegram discord media kiwix sql redis"
ENV UV_NO_DEV=1

WORKDIR /app

# Cache third-party dependencies independently of the source.
COPY pyproject.toml ./pyproject.toml

RUN set -f; \
    for extra in $PIXI_EXTRAS; do set -- "$@" --extra "$extra"; done; \
    uv sync "$@" --no-install-project

# Install the actual package after copying its source.
COPY . .
RUN set -f; \
    for extra in $PIXI_EXTRAS; do set -- "$@" --extra "$extra"; done; \
    uv sync "$@"

# Start using runtime-injected environment variables.
CMD ["/bin/bash", "./start.sh"]
