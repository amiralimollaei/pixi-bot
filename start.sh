#!/bin/bash

source .env

# Run the main entry point
uv sync --all-extras
uv run pixi-cli \
    --platform $PIXI_PLATFORM \
    --model $PIXI_MODEL \
    --embedding-model $PIXI_EMBEDDING_MODEL \
    --tool-logging \
    --wiki-search \
    --gif-search \
    --mediawiki-wikis minecraft=https://minecraft.wiki/ wikipedia=https://www.wikipedia.org/w/ \
    $PIXI_EXTRA_ARGS
