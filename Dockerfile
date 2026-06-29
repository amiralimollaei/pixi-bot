FROM python:3.13-slim-trixie

# install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy only dependency files first for better caching
COPY pyproject.toml ./pyproject.toml

# Create minimal package structure so `uv sync` can find the local package
RUN mkdir -p src/pixi && touch src/pixi/__init__.py

# Disable development dependencies and install only from pyproject.toml
ENV UV_NO_DEV=1

# Sync the project into a new environment, asserting the lockfile is up to date
RUN uv sync --all-extras

# Copy the full project (including src/) into the image
COPY . .

# run the server
CMD ["/bin/bash", "./start.sh"]