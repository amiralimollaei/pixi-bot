FROM python:3.13-slim-trixie

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Disable development dependencies and install only from pyproject.toml
ENV UV_NO_DEV=1

WORKDIR /app

# Copy only dependency files first for better caching
COPY pyproject.toml ./pyproject.toml

# Create minimal package structure so `uv sync` can find the local package
RUN mkdir -p src/pixi && touch src/pixi/__init__.py

# Sync the project into a new environment, asserting the lockfile is up to date
RUN uv sync --all-extras

# Copy the full project (including src/) into the image
COPY . .

# run the server
CMD ["/bin/bash", "./start.sh"]