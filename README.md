# Pixi AI Chatbot

[![CodeFactor](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot/badge)](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot)

A small, hackable and powerful AI chatbot implementation with tool calling and image support that blends in perfectly with the users.

## Features

- **Multi-Platform Support:** Works with Discord and Telegram out of the box.
- **Configurable:** Easily modify the bot's persona and behavior.
- **Change Data Directory:** Run multiple instances with completely different configurations/storage in parallel.
- **Tool Calling:** Supports calling external tools and APIs from chat.
- **Advanced Logging:** Colored logging, Supports logging tool calls and extra information for debugging.
- **Image Support:** Can recieve, compress and cache all image formats.
- **Audio Support:** Can recieve, compress and cache all audio formats.
- **Addon Support:** Easily add new actions, tools, or other integrations (WIP, API is unstable and documentation is pending).
- **Dotenv Support:** Securely manage API keys and tokens with environment variables.

## Requirements

- Python>=3.12
- dotenv
- openai
- zstandard
- discord-py (optional, for discord platform)
- python-telegram-bot (optional, for telegram platform)
- ffmpeg (on `PATH`, for default media caching)
- av (legacy fallback for when ffmpeg is not available)
- llama-server with native Hugging Face/HTTPS download support (optional, for `--llama-hf`, `--llama-helper-hf`, or `--llama-embedding-hf`)
- uv (recommended, for setting up all the requirements easily in a python virtual environemnt)

## Getting Started

There are many extra optional dependecy groups that you may need to install based on your own needs, for simplicity, this guide shows you how to install all modules at once.

| extra dependecy group | packages            | description                                                                                         |   status   |
| --------------------- | ------------------- | --------------------------------------------------------------------------------------------------- | :--------: |
| media                 | av                  | installs the optional PyAV compatibility backend; default caching uses the system FFmpeg executable |  optional  |
| discord               | discord-py          | installs discord.py and enables discord bot functionality                                           | optional\* |
| telegram              | python-telegram-bot | installs python-telegram-bot and enables telegram bot functionality                                 | optional\* |

> \[\*\] you have to install at least one of these dependecy groups for the bot to function

Choose either an OpenAI-compatible API model with `--model`, or a local GGUF
language model with `--llama-hf`. API models use the configured API URL and
`OPENAI_API_KEY` (or `--no-auth` for unauthenticated backends). An entirely local
configuration does not require an API key or contact the remote API for model
verification. Helper models for agentic tools can independently use either backend;
without an explicit helper selection, they share the main model adapter and process.
Optionally choose API embeddings with `--embedding-model`, or explicitly select a local GGUF model with `--llama-embedding-hf CompendiumLabs/bge-small-en-v1.5-gguf:Q4_K_M`. The local `llama-server` starts on the first cache miss, downloads weights using its own Hugging Face support, and stops after 60 idle seconds by default. `--llama-embedding-idle-timeout` changes that interval; the next miss restarts the server. Local inference is never selected as an API fallback.

### Installation using UV (Recommended)

```sh
git clone https://github.com/amiralimollaei/pixi-bot.git
cd pixi-bot
uv sync --all-extras
# enter the venv
source .venv/bin/activate
# run using pixi-cli -p [platform] [options]
```

### CLI Usage with UVX (Recommended)

You can combine the process of installing and/or updating requirements and pixi, and running it into a single command:

```sh
# for telegram
# installs pixi-bot from pypi, updates it, and runs pixi-cli
uvx --env-file .env pixi-bot[telegram,media]@latest -p telegram [options]
```

```sh
# for discord
# installs pixi-bot from pypi, updates it, and runs pixi-cli
uvx --env-file .env pixi-bot[discord,media]@latest -p discord [options]
```

### Installation using PIP

```sh
pip install pixi-bot[media,discord,telegram]
pixi-cli -p [platform] [options]
```

### Setup Environment Variables

- Create a `.env` file and set `OPENAI_API_KEY` to your API provider's API Key
- Set `DISCORD_BOT_TOKEN` and/or `TELEGRAM_BOT_TOKEN` environment variables
- Set `DEEPINFRA_API_KEY` environment variable and `DISCORD_BOT_TOKEN`
- Optionally set `KLIPY_API_KEY` or `GIPHY_API_KEY` for GIF search (see below).

#### GIF search

Configure either provider in `.env`:

```dotenv
# KLIPY: https://partner.klipy.com/
KLIPY_API_KEY=your-klipy-api-key
# Or GIPHY: https://developers.giphy.com/dashboard/
# GIPHY_API_KEY=your-giphy-api-key
```

Pixi uses KLIPY when both keys are nonblank, otherwise whichever provider has a
key. With neither key, the send-GIF action is unavailable. `--no-gif-search`
disables it even when a key is configured. Provider errors do not trigger a
fallback to the other service.

GIF messages include only the media URL. Tenor is no longer supported; replace
its old key with a key from one of these providers.

Both providers document a 100-call/hour test or beta limit; production access
requires approval. Review [KLIPY's integration guidelines](https://docs.klipy.com/attribution)
or [GIPHY's requirements](https://developers.giphy.com/docs/api/) before deployment.
GIPHY's standard guidelines require client-side search requests; obtain approval
for this server-side bot integration rather than assuming a key grants permission.

### Runninig The Bot

- Discord: `pixi-cli -p discord [options]`
- Telegram: `pixi-cli -p telegram [options]`

### Docker and Compose

The root `Dockerfile` installs all extras by default and uses `PIXI_PLATFORM` to
choose a platform at runtime. Set the `PIXI_EXTRAS` build argument to a
space-separated list of extras to install only what your deployment needs.
The `telegram` and `discord` Compose services use this same Dockerfile with
their platform's SDK plus the `kiwix`, `sql`, and `redis` extras. Every image
includes FFmpeg; the default generic image also includes the `media` extra (PyAV).

For an API-backed bot, put these runtime settings in `.env`:

```dotenv
PIXI_MODEL=your-api-model
OPENAI_API_KEY=your-api-key
TELEGRAM_BOT_TOKEN=your-telegram-token
# For Discord, use DISCORD_BOT_TOKEN instead.
# Optional:
# PIXI_EMBEDDING_MODEL=your-embedding-model
# PIXI_EXTRA_ARGS=--messages-storage sql --cache-storage redis
```

Do not surround `PIXI_EXTRA_ARGS` with quotes in a Docker `--env-file`: Docker
passes those quotes literally. For a direct local launch that sources `.env`,
quote the value instead: `PIXI_EXTRA_ARGS="--messages-storage sql --cache-storage redis"`.

Build and run one platform directly:

```sh
docker build --build-arg "PIXI_EXTRAS=telegram kiwix sql redis" -t pixi-bot:telegram .
docker run --rm --env-file .env -e PIXI_PLATFORM=telegram pixi-bot:telegram
# For Discord, replace telegram with discord in the build argument, tag, and platform.
```

Or select the platform-specific Compose services:

```sh
docker compose up --build telegram
docker compose up --build discord
# Run both as separate containers:
docker compose up --build telegram discord
```

The original `docker compose up --build` still starts only the generic `pixi`
service; set `PIXI_PLATFORM=telegram` or `discord` in `.env` for that service.
Platform-specific services override that variable with their own platform.
`.env` and local virtual environments are excluded from image builds; inject
secrets at runtime. `PIXI_EXTRA_ARGS` accepts whitespace-separated CLI arguments,
not shell expressions or embedded quoting. Explicit command arguments can also
be passed to `bash ./start.sh`.

#### Custom images

Build a Telegram image without Kiwix, SQL, Discord, or PyAV:

```sh
docker build --build-arg "PIXI_EXTRAS=telegram redis" -t pixi-bot:personal .
docker run --rm --env-file .env -e PIXI_PLATFORM=telegram pixi-bot:personal
```

Use `discord redis` and `PIXI_PLATFORM=discord` for Discord, or include both
platform extras if you need to select either at runtime. FFmpeg remains installed.
`PIXI_EXTRAS` controls installed packages at **build time**; changing it requires
rebuilding. It does not select storage backends at runtime.

For Compose, put `PIXI_EXTRAS="telegram redis"` and `PIXI_PLATFORM=telegram` in
your local `.env`, along with credentials and storage flags, then run:

```sh
docker compose up --build pixi
```

Only the `pixi` service accepts configurable extras from `.env`. The `telegram`
and `discord` services build the shared Dockerfile with fixed platform-specific
extras to preserve existing behavior. Profiles are additive, not exclusive: use
explicit service names rather than `docker compose --profile telegram up` if you
want only one bot.

## CLI Usage

Run `pixi-cli --help` for all platform, feature, storage, and model options.

Logs include timestamps by default. Use `--no-log-timestamps` to omit them when
your log collector adds its own, or `--log-timestamps` to explicitly enable them.

| Role                   | API selection             | Native llama.cpp selection          |
| ---------------------- | ------------------------- | ----------------------------------- |
| Main chat (required)   | `--model MODEL`           | `--llama-hf REPO[:QUANT]`           |
| Helper chat (optional) | `--helper-model MODEL`    | `--llama-helper-hf REPO[:QUANT]`    |
| Embeddings (optional)  | `--embedding-model MODEL` | `--llama-embedding-hf REPO[:QUANT]` |

Selections within each role are mutually exclusive. Native inference never acts
as an API fallback. Main, helper, and embedding servers are loaded lazily and
unloaded after 60 idle seconds by default; the timeout does not run during a request.

On shutdown, active conversation and scheduled tasks (including tool workers)
are cancelled and awaited before platform shutdown and native-model cleanup.
No new chat generations start during shutdown.

Native main options are `--llama-file FILE`, `--llama-binary PATH`, and
`--llama-idle-timeout SECONDS`. Helper options use the `--llama-helper-` prefix;
embedding options use `--llama-embedding-`. These options require the corresponding
native model selection. The binary defaults to `llama-server` on `PATH`.

`--model-max-context` and `--helper-model-max-context` set chat context sizes
(default: 16192 tokens; positive values required for local chat). Embedding context
uses `--embedding-model-max-context`; local embeddings default to the model's native
context. `--embedding-model-dimension` is API-only.

For a small local text-only chat model:

```sh
pixi-cli -p discord \
  --llama-hf LiquidAI/LFM2.5-350M-GGUF \
  --llama-file LFM2.5-350M-Q4_0.gguf \
  --model-max-context 4096 \
  --no-image-support --no-audio-support
```

The selected platform's bot token is still required. This model is suitable for
small smoke checks; response quality and tool-calling ability depend on the model.
Native chat enables llama.cpp's Jinja chat templates for supported tool calls.
This adapter does not configure multimodal projector files.

To mix an API main model with a local helper, combine `--model API_MODEL` with
`--llama-helper-hf REPO[:QUANT]` and, if needed, `--llama-helper-file FILE`.
API authentication is still required when any selected model uses the API.

### Message storage

Select a backend with `--messages-storage`:

| Backend          | Connection configuration                               | Optional install extra |
| ---------------- | ------------------------------------------------------ | ---------------------- |
| `disk` (default) | `userdata/messages/` under `--pixi-directory`          | None                   |
| `sql`            | `--messages-storage-url URL`, otherwise `DATABASE_URL` | `sql`                  |
| `redis`          | `--messages-storage-url URL`, otherwise `REDIS_URL`    | `redis`                |

An explicit URL takes precedence over the selected backend's environment
variable. Disk storage ignores database environment variables and rejects a URL.
`--redis-key-prefix PREFIX` changes the Redis namespace (default:
`pixi:messages:`); use distinct prefixes for deployments sharing one Redis DB.

### Cache storage

Select media and embedding cache persistence independently with
`--cache-storage {disk,sql,redis}` (default: `disk`).
`--cache-storage-url URL` overrides the connection URL; otherwise SQL uses
`DATABASE_URL` and Redis uses `REDIS_URL`, just like message storage.
The existing `sql` and `redis` install extras cover both uses.
`--cache-redis-key-prefix PREFIX` changes the cache prefix (default:
`pixi:cache:`), independently of the message-history prefix.

Message histories and caches can use the same service URL without mixing data.
No cache TTL is applied. Redis durability and eviction remain service settings.
Backend selection does not enable media or configure an embedding model;
the existing `--image-support`, `--audio-support`, and `--embedding-model`
options still apply.

### Knowledge-base storage

Select knowledge persistence independently with
`--knowledge-storage {disk,sql,redis}` and select the knowledge bases to use with
`--knowledge-bases NAME [NAME ...]`. Knowledge tools require tool calling to be enabled.

| Backend          | Connection configuration                                | Optional install extra |
| ---------------- | ------------------------------------------------------- | ---------------------- |
| `disk` (default) | `datasets/<name>/*.zst` under `--pixi-directory`        | None                   |
| `sql`            | `--knowledge-storage-url URL`, otherwise `DATABASE_URL` | `sql`                  |
| `redis`          | `--knowledge-storage-url URL`, otherwise `REDIS_URL`    | `redis`                |

Explicit URLs take precedence over environment variables. Disk ignores database
environment variables and rejects an explicit URL. `--knowledge-redis-key-prefix`
sets the Redis namespace (default: `pixi:datasets:`) and requires Redis storage.
Message histories, caches, and knowledge bases can share a server URL without mixing data.

For example, with `DATABASE_URL` configured:

```sh
pixi-cli -p telegram --model YOUR_MODEL \
  --knowledge-bases minecraft --knowledge-storage sql
```

Existing stored knowledge remains readable without migration. Switching backends
does not automatically transfer it. Restart the bot to apply knowledge-base changes.
Use SQL or Redis when multiple processes need to update knowledge.

#### Importing knowledge bases

Import local documentation without starting the bot or configuring a model,
platform token, or API key:

```sh
pixi-cli import-knowledge wikipedia ./pages-articles.xml.bz2 --format mediawiki
pixi-cli import-knowledge python ./devdocs/python --format devdocs

# Kiwix support is an optional dependency.
pip install 'pixi-bot[kiwix]'
pixi-cli import-knowledge offline-wiki ./wikipedia.zim --format kiwix
```

| Format      | Accepted local source                                                                  | Imported content                                                                                     |
| ----------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `mediawiki` | MediaWiki XML export, plain or compressed with gzip, bzip2, or xz                      | Latest revision of nonredirect main-namespace pages; original page IDs and raw wikitext are retained |
| `devdocs`   | `db.json`, or a directory containing it; optional sibling `index.json` and `meta.json` | One document per page, with titles from the index when available; HTML converted to text             |
| `kiwix`     | Kiwix/OpenZIM `.zim` archive                                                           | HTML and plain-text articles; redirects, metadata, and binary assets excluded                        |

Download sources first; URLs are not fetched by this command. Extract DevDocs
download bundles before importing. HTML extraction excludes scripts, styles, and
navigation while preserving code-block indentation. Documents retain source
links where available, otherwise local file references.
DevDocs sources use local `db.json` references: `meta.json` project homepages
are not documentation bases. MediaWiki sources preserve explicit `?title=...`
article URLs. Path-based main-page URLs and unrecognized query layouts use local
page references: exports do not identify the article route reliably, especially
when the main-page title contains slashes or the route has a suffix. MediaWiki log
entries are skipped without affecting article imports.
MediaWiki XML is parsed with `defusedxml`; DTDs, entity declarations, and external
entity references are rejected. Normal XML character references remain supported.

Disk imports use `datasets/<name>/` under `--pixi-directory` (default `~/.pixi/`).
The same storage flags as bot startup select SQL or Redis:

```sh
pixi-cli import-knowledge python ./devdocs/python --format devdocs \
  --knowledge-storage sql --knowledge-storage-url sqlite:///knowledge.db
```

SQL uses `DATABASE_URL` and Redis uses `REDIS_URL` when no explicit URL is given;
install the corresponding `sql` or `redis` extra. Redis also accepts
`--knowledge-redis-key-prefix`.

An existing nonempty knowledge base is rejected unless `--replace` is supplied.
Replacement removes stale documents; this is not a merge. Malformed or empty
input is rejected before saving, leaving existing knowledge unchanged. Stop
concurrent writers during imports. **Imported documents must fit in memory**:
the existing storage API saves whole snapshots, even though XML parsing itself
releases completed pages. Full Wikipedia dumps can exceed available memory.

Start or restart the bot with the same data directory/backend and
`--knowledge-bases wikipedia python offline-wiki` to enable the imported bases.
Run `pixi-cli import-knowledge --help` for all import options.

For the Python importer contract and instructions on adding a format, see
[Knowledge Importers](CONTRIBUTING.md#knowledge-importers).

## Railway Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for deployment setup, Redis-only configuration,
platform selection, and SQL/Redis connections.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture, codebase contracts,
custom actions and tools, knowledge importers, and regression checks.

## Lisence

MIT
