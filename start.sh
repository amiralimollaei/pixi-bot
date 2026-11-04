#!/bin/bash

set -ef

# Optional for direct local runs; containers receive variables at runtime.
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

args=(
    --platform "${PIXI_PLATFORM:?Set PIXI_PLATFORM to telegram or discord}"
    --tool-logging
    --wiki-search
    --gif-search
    --mediawiki-wikis minecraft=https://minecraft.wiki/ wikipedia=https://www.wikipedia.org/w/
)

if [[ -n "${PIXI_MODEL:-}" ]]; then
    args+=(--model "$PIXI_MODEL")
fi
if [[ -n "${PIXI_EMBEDDING_MODEL:-}" ]]; then
    args+=(--embedding-model "$PIXI_EMBEDDING_MODEL")
fi

# Preserve whitespace-separated extra flags without globbing or shell evaluation.
extra_args=(${PIXI_EXTRA_ARGS:-})
exec uv run --no-sync pixi-cli "${args[@]}" "${extra_args[@]}" "$@"
