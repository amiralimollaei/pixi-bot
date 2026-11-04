# Pixi AI Chatbot

[![CodeFactor](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot/badge)](https://www.codefactor.io/repository/github/amiralimollaei/pixi-bot)

Pixi is a self-hosted AI chatbot for Discord and Telegram. You run the bot process,
connect it to your platform's bot account, and choose the language model that
generates its responses. The model can run through an OpenAI-compatible API or
locally through [llama.cpp](https://github.com/ggml-org/llama.cpp).

Pixi handles conversations, message history, and model-requested actions such as
sending messages, reacting, or scheduling a response. Optional tools let the model
search wikis and documentation that you import.

## Features

- **Discord and Telegram:** Run a bot on either platform, or use separate processes for both.
- **Customizable persona:** Edit files that describe the bot's personality, instructions, and examples.
- **Tool calling:** Let compatible models search external APIs and imported documentation.
- **Media support:** Process images and audio using FFmpeg or PyAV; the selected model must support the media you send.
- **Storage choices:** Store message history, cached media and embeddings, and documentation on disk, in SQL, or in Redis.
- **Python extensions:** Add actions, tools, and integrations through the addon interface.
- **Logging:** Control log verbosity, timestamps, and tool-call logging.

## Requirements

- Python 3.12 or later.
- A Discord or Telegram bot account and its token. Create a Telegram bot through
  [BotFather](https://t.me/BotFather), or a Discord application through the
  [Discord Developer Portal](https://discord.com/developers/applications).
- Access to an OpenAI-compatible language-model API, or a local `llama-server`
  executable with Hugging Face model-download support.
- [uv](https://docs.astral.sh/uv/) or pip to install the Python package and dependencies.
- FFmpeg on `PATH` if you enable image or audio processing. The optional `media`
  package extra provides PyAV as an alternative media backend.

## Getting Started

The following steps run a Telegram bot using an API-backed model. For Discord,
install the `discord` extra, set `DISCORD_BOT_TOKEN`, and select `-p discord`.
Values such as `YOUR_MODEL` and `your-api-key` are placeholders for your own
provider's model ID and credentials.

### 1. Install Pixi

Choose one installation method.

**From source with uv:**

```sh
git clone https://github.com/amiralimollaei/pixi-bot.git
cd pixi-bot
uv sync --extra telegram
source .venv/bin/activate
```

**From PyPI with pip:**

```sh
python -m venv .venv
source .venv/bin/activate
pip install 'pixi-bot[telegram]'
```

Package extras install optional dependencies. Select the ones needed for your
deployment, for example `pip install 'pixi-bot[discord,media,redis]'`.
For a source checkout, `uv sync --all-extras` installs every extra.

| Extra | Purpose |
| --- | --- |
| `telegram` | Telegram platform integration; install this or `discord` to run a bot |
| `discord` | Discord platform integration |
| `media` | PyAV image/audio processing when the FFmpeg executable is unavailable |
| `sql` | SQL message, cache, and knowledge storage |
| `redis` | Redis message, cache, and knowledge storage |
| `kiwix` | Importing documentation from Kiwix/OpenZIM archives |

### 2. Configure credentials

Create a `.env` file in the directory from which you will run Pixi:

```dotenv
OPENAI_API_KEY=your-api-key
TELEGRAM_BOT_TOKEN=your-telegram-token
# For Discord, set DISCORD_BOT_TOKEN instead.
# For an OpenAI-compatible provider other than OpenAI:
# OPENAI_BASE_URL=https://your-provider.example/v1
```

The CLI reads `.env` as well as environment variables supplied by your shell or
hosting service. Keep credentials out of version control. The default API URL is
`https://api.openai.com/v1`. Set `OPENAI_BASE_URL` or pass `--api-url URL` to use
another endpoint; `OPENAI_BASE_URL` takes precedence if both are supplied.
For a backend that does not require authentication, pass `--no-auth`.

### 3. Start the bot

```sh
pixi-cli -p telegram --model YOUR_MODEL
```

Open a chat with your Telegram bot, or add your Discord bot to a server. Pixi
responds to direct messages, mentions, and messages containing `pixi`.
The process must keep running for the bot to respond.

To run a PyPI release in an isolated environment without cloning the repository
or installing into your current environment, use uvx:

```sh
uvx --env-file .env 'pixi-bot[telegram]@latest' -p telegram --model YOUR_MODEL
# Or:
uvx --env-file .env 'pixi-bot[discord]@latest' -p discord --model YOUR_MODEL
```

For local models and optional helper or embedding models, see [CLI Usage](#cli-usage).
For containers, use [Docker and Compose](#docker-and-compose). For Railway hosting,
see [DEPLOYMENT.md](DEPLOYMENT.md).

### Optional GIF search

GIF search lets the model send a GIF chosen from a description. Configure a
provider key in `.env`:

```dotenv
# KLIPY: https://partner.klipy.com/
KLIPY_API_KEY=your-klipy-api-key
# Or GIPHY: https://developers.giphy.com/dashboard/
# GIPHY_API_KEY=your-giphy-api-key
```

Pixi uses KLIPY when both keys are nonblank, otherwise whichever provider has a
key. With neither key, the send-GIF action is unavailable. `--no-gif-search`
disables it even when a key is configured. Provider errors do not trigger a
fallback to the other service. GIF messages contain the media URL.

Both providers document a 100-call/hour test or beta limit; production access
requires approval. Review [KLIPY's integration guidelines](https://docs.klipy.com/attribution)
or [GIPHY's requirements](https://developers.giphy.com/docs/api/) when planning a deployment.
GIPHY's standard guidelines require client-side search requests; obtain approval
for this server-side bot integration rather than assuming a key grants permission.

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

`docker compose up --build` starts the `pixi` service. Set
`PIXI_PLATFORM=telegram` or `discord` in `.env` to choose its platform.
The platform-specific services set `PIXI_PLATFORM` automatically.
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
platform extras if you need to select either at runtime. Every image includes FFmpeg.
`PIXI_EXTRAS` controls installed packages at **build time**; changing it requires
rebuilding. It does not select storage backends at runtime.

For Compose, put `PIXI_EXTRAS="telegram redis"` and `PIXI_PLATFORM=telegram` in
your local `.env`, along with credentials and storage flags, then run:

```sh
docker compose up --build pixi
```

Only the `pixi` service accepts configurable extras from `.env`. The `telegram`
and `discord` services use fixed extras: their platform SDK plus `kiwix`, `sql`,
and `redis`. Profiles are additive, not exclusive: use
explicit service names rather than `docker compose --profile telegram up` if you
want only one bot.

## CLI Usage

Run `pixi-cli --help` for all platform, feature, storage, and model options.

Logs include timestamps by default. Use `--no-log-timestamps` to omit them when
your log collector adds its own, or `--log-timestamps` to explicitly enable them.

### Data directory and customization

Pixi stores its files under `~/.pixi/` by default. Set `--pixi-directory PATH`
to choose another root; use separate directories for independent bot instances.
On startup, Pixi creates missing default files under `resources/`:

- `persona.json`: personality and background information.
- `system.md`: instructions sent to the model.
- `examples.txt`: example interactions included in those instructions.

Edit these files and restart the bot to apply your changes. Message history,
caches, and imported knowledge use subdirectories of the same root when disk
storage is selected. The storage sections below explain how to use SQL or Redis.

### Model selection

The **main model** generates chat responses. An optional **helper model** extracts
relevant information for retrieval tools; it uses the main model when not specified.
An optional **embedding model** converts text into vectors for similarity-based
document retrieval. A basic chat bot needs only the main model.

| Role                   | API selection             | Native llama.cpp selection          |
| ---------------------- | ------------------------- | ----------------------------------- |
| Main chat (required)   | `--model MODEL`           | `--llama-hf REPO[:QUANT]`           |
| Helper chat (optional) | `--helper-model MODEL`    | `--llama-helper-hf REPO[:QUANT]`    |
| Embeddings (optional)  | `--embedding-model MODEL` | `--llama-embedding-hf REPO[:QUANT]` |

Choose one backend per model role. API models use the configured API URL and
credentials. Native models are GGUF files run by `llama-server`; `REPO[:QUANT]`
identifies a Hugging Face repository and an optional quantization.
Pixi starts each local server on its first request, lets llama.cpp download the
weights, and stops it after 60 idle seconds by default. The timeout does not run
during a request. Local inference is selected explicitly, not as an API fallback.
An entirely local configuration needs no model API key and does not contact a
remote API for model verification. It does need a platform bot token.

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

Set `DISCORD_BOT_TOKEN` for this example. Response quality and tool-calling ability
depend on the model; this small model is suitable for trying local inference.
Native chat enables llama.cpp's Jinja chat templates for supported tool calls.
This adapter does not configure multimodal projector files.

To mix an API main model with a local helper, combine `--model API_MODEL` with
`--llama-helper-hf REPO[:QUANT]` and, if needed, `--llama-helper-file FILE`.
Provide API credentials whenever a selected model uses an authenticated API.

### Message storage

Message storage holds the conversation history used to give the model context
from earlier messages. It is separate from cache and documentation storage.

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

The cache stores processed media and text embeddings so they can be reused
without repeating conversion or model requests.

Select media and embedding cache persistence independently with
`--cache-storage {disk,sql,redis}` (default: `disk`).
`--cache-storage-url URL` overrides the connection URL; otherwise SQL uses
`DATABASE_URL` and Redis uses `REDIS_URL`, just like message storage.
The `sql` and `redis` package extras support both messages and caches.
`--cache-redis-key-prefix PREFIX` changes the cache prefix (default:
`pixi:cache:`), independently of the message-history prefix.

Message histories and caches can use the same service URL without mixing data.
Cache entries do not expire automatically. Configure Redis durability and eviction
in your Redis service. Storage selection does not enable media processing or
choose an embedding model: use `--image-support`, `--audio-support`, and an
embedding-model option for those features.

### Knowledge-base storage

A knowledge base is a named collection of documentation that the model can
search through tools. Import documents with `pixi-cli import-knowledge`, then
select their names when starting the bot.

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

Switching storage backends does not transfer documentation between them.
Restart the bot to apply knowledge-base changes.
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
entity references are rejected. Normal XML character references are supported.

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
`--replace` saves a complete snapshot rather than merging documents. Malformed
or empty input fails without modifying stored knowledge. Stop concurrent writers
during imports. **Imported documents must fit in memory**: storage saves whole
snapshots, even though XML parsing releases completed pages. Full Wikipedia
dumps can exceed available memory.

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

## License

MIT
