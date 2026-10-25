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
- python-telegram-bot  (optional, for telegram platform)
- ffmpeg (on `PATH`, for default media caching)
- av (legacy fallback for when ffmpeg is not available)
- llama-server with native Hugging Face/HTTPS download support (optional, for `--llama-hf`, `--llama-helper-hf`, or `--llama-embedding-hf`)
- uv (recommended, for setting up all the requirements easily in a python virtual environemnt)

## Getting Started

There are many extra optional dependecy groups that you may need to install based on your own needs, for simplicity, this guide shows you how to install all modules at once.

| extra dependecy group | packages | description | status |
|---|---|---|:---:|
| media | av | installs the optional PyAV compatibility backend; default caching uses the system FFmpeg executable | optional |
| discord | discord-py | installs discord.py and enables discord bot functionality | optional\* |
| telegram | python-telegram-bot | installs python-telegram-bot and enables telegram bot functionality | optional\* |

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
- Optionally set `TENOR_API_KEY` for GIF search features powered by Tenor

### Runninig The Bot

- Discord: `pixi-cli -p discord [options]`
- Telegram: `pixi-cli -p telegram [options]`

## CLI Usage

Run `pixi-cli --help` for all platform, feature, storage, and model options.

| Role | API selection | Native llama.cpp selection |
|---|---|---|
| Main chat (required) | `--model MODEL` | `--llama-hf REPO[:QUANT]` |
| Helper chat (optional) | `--helper-model MODEL` | `--llama-helper-hf REPO[:QUANT]` |
| Embeddings (optional) | `--embedding-model MODEL` | `--llama-embedding-hf REPO[:QUANT]` |

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

| Backend | Connection configuration | Optional install extra |
|---|---|---|
| `disk` (default) | `userdata/messages/` under `--pixi-directory` | None |
| `sql` | `--messages-storage-url URL`, otherwise `DATABASE_URL` | `sql` |
| `redis` | `--messages-storage-url URL`, otherwise `REDIS_URL` | `redis` |

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

| Backend | Connection configuration | Optional install extra |
|---|---|---|
| `disk` (default) | `datasets/<name>/*.zst` under `--pixi-directory` | None |
| `sql` | `--knowledge-storage-url URL`, otherwise `DATABASE_URL` | `sql` |
| `redis` | `--knowledge-storage-url URL`, otherwise `REDIS_URL` | `redis` |

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


### Railway

Use Railway's existing SQL/Redis services; Pixi does not provision containers
or require a Compose stack. In the bot service's Railway variables, reference
the database service's connection URL as `DATABASE_URL` or `REDIS_URL`.
Use the private URL containing its `*.railway.internal` hostname and internal
port, not the public TCP proxy. Connection URLs carry authentication and any
SSL options; no application-specific DNS configuration is needed.

Install the matching extra alongside your platform extra, for example:

```sh
pip install 'pixi-bot[telegram,sql,redis]'
```

For SQL histories and Redis caches, set both URL variables and use:

```sh
pixi-cli -p telegram --model YOUR_MODEL --messages-storage sql --cache-storage redis
```

SQL storage accepts SQLAlchemy URLs. SQLite uses `sqlite:////absolute/path.db`;
plain `postgresql://` and `postgres://` URLs use psycopg 3, included in the `sql`
extra. Explicit driver URLs are preserved; other databases need their driver
installed separately, for example `pymysql` for `mysql+pymysql://...`.
The database must already exist and the account must be able to create tables.
Redis accepts `redis://`, `rediss://`, and `unix://` URLs.

## Architecture

Pixi keeps feature-oriented packages with explicit ports between application
behavior and external systems:

| Module | Responsibility |
|---|---|
| `pixi.cli` | Arguments, dotenv settings, and logging |
| `pixi.bootstrap` | Production composition: selects adapters, loads resources, registers built-ins and addons |
| `pixi.bot` | Message handling, conversation lifecycle, and scheduled actions |
| `pixi.ai.chatting` | Provider-independent completion, tool execution, and inline action processing |
| `pixi.ai.rag` | Chunking and retrieval using injected embedding and cache services |
| `pixi.model` | Portable message, platform metadata, and embedding values |
| `pixi.interfaces` | Platform, model-stream, embedding-cache, message-storage, and knowledge-storage contracts |
| `pixi.platform`, `pixi.apis`, `pixi.storage`, `pixi.caching` | Concrete external-system adapters |

Application code consumes ports; adapters implement them. Concrete adapter
selection belongs in `bootstrap.py`, not in conversation or retrieval logic.
`create_bot(...)` builds the production application. Construct `PixiClient`
directly when supplying your own platform, model, message storage, and prompt
resources. Neither the chat client nor the RAG client constructs an API client.

Telegram commands are excluded from the ordinary chat handler, so slash commands
registered by bootstrap or addons work regardless of registration order. Unknown
commands and commands addressed to other bots do not trigger chat inference.

Model streams use portable `ContentDelta`, `ReasoningDelta`, `ToolCallDelta`, and
`ChatFinished` events. Streams must support `aclose()` so cancellation releases
their transport. OpenAI request serialization and stream translation live in
`pixi.apis.openai`; HTTP implementation details do not enter the chat engine.

OpenAI response values and their JSON conversion live in `pixi.model.openai`.
HTTP requests and SSE framing live in `pixi.apis.openai.transport`; client/resource
classes live in `pixi.apis.openai.client`, and API errors in
`pixi.apis.openai.exceptions`. The generic closable `AsyncStream` belongs to
`pixi.async_utils`. Import these modules explicitly: the OpenAI package initializer
has no implementation, re-exports, or third-party `openai.*` module registration.

Tool calls execute serially in first-seen order as soon as their streamed arguments
form complete JSON objects, while the model stream continues. Results are buffered
until the source stream ends and tool execution finishes, then added to history
before any continuation request. Calls with omitted arguments execute at the end
of the stream.

`AsyncChatbotInstance` and its per-bot `ChatbotInstanceRegistry` live in
`pixi.bot.conversations`. `AsyncChatClient` receives a `MessagesStorage` adapter
and a `history_key`; storage is the source of truth, not a resident history list.
Its synchronous storage contract is:

| Operation | Behavior |
|---|---|
| `exists(key)` / `count(key)` | Inspect a history without reading its messages; missing histories have count zero |
| `append(key, messages)` | Atomically append only new messages; an empty batch creates an existing empty history |
| `iter_messages(key, start=0, stop=None, reverse=False)` | Lazily read the absolute half-open range `[start, stop)` using bounded pages |
| `truncate(key, length)` | Remove a tail without rewriting the retained messages or growing the history |
| `delete(key)` | Remove a history; deleting an absent key is a no-op |

The client fetches a recent context within its approximate model-context budget
for each inference request and releases it afterward. Rearrangement operates on
that bounded context, not the entire stored history. `iter_messages()`,
`message_count`, and `last_message` expose history without loading a full snapshot.
Idle eviction releases conversation runtime state; it neither saves nor reloads
message histories.

Messages added outside a request are appended immediately. During a request,
only its new messages are held in a task-local delta, including tool calls and
results. Successful requests append that delta as one batch. Failed, cancelled,
or explicitly closed requests discard it; `temporal=True` discards it even on
success. Temporary requests do not persist their input prompt. Rollback therefore
does not copy history or truncate messages committed by another concurrent request.
Nested requests have independent deltas and merge into their parent only on
success. Scheduled callbacks start detached from the originating request and
read the current stored history rather than retaining an expired request delta.

`pixi.storage.messages.MessagesDiskStorage(directory)` uses the standard-library
SQLite implementation and stores individual indexed message rows in
`directory/messages.sqlite3`; it needs no SQL install extra. Production histories
live under `userdata/messages/` in the configured data root. `PixiClient` and
`create_bot` accept `messages_storage=...`; chatbot instances and registries accept
`store=...` and use keys of the form `{platform_or_prefix}:{identifier}`.

`pixi.storage.sql.MessagesSQLStorage(url)` stores individual JSON message rows in
`pixi_history_messages`, with atomic append positions tracked by
`pixi_history_heads`. `pixi.storage.redis.MessagesRedisStorage(url,
key_prefix="pixi:messages:")` uses Redis lists under `{key_prefix}v2:{key}`.
Neither backend rewrites the previous messages when appending. Both preserve
ordering and distinguish missing histories from existing empty histories.
Call `close()` on SQL/Redis storage when finished. CLI-created backends are closed
on exit; callers own storage injected into `create_bot` or `PixiClient`.

Only message data is persisted by the message-storage backend, including metadata,
timestamps, media hashes, tool calls/results, and channel IDs. Note visibility,
scheduler state, agent context, and other runtime settings are not persisted.
Note visibility resets after eviction. The former JSON-array snapshots, SQL
snapshot table, and unversioned Redis keys are left untouched but are not read or
automatically migrated; this is a message-storage-layout cutover.

Persona and prompts intentionally remain files under `resources/`. Edit
`persona.json`, `system.md`, or `examples.txt`, then restart the bot to apply the
changes. Startup copies only missing default resources and never overwrites
customized files; these resources are not moved into a database.

Agents receive storage and a history key when constructed:

```python
from pixi.ai.agents import RetrievalAgent
from pixi.storage.messages import MessagesDiskStorage

storage = MessagesDiskStorage("./histories")
agent = RetrievalAgent(
    storage=storage, history_key="agent:research",
    context=["Current reference material"], chat_model=chat_model, model=model,
)
await agent.execute_query("What is relevant?", temporal=False)
```

Constructing another client with the same adapter and key accesses the same
history without a load step. Agent queries default to `temporal=True`; use
`temporal=False` to persist the query and response. Agents created by the bot
share its storage and receive distinct history keys unless one is supplied.
The snapshot `save`/`load` and `get_messages`/`set_messages` APIs are removed.
Storage errors propagate from the backend.

For Python integrations, construct `CacheDiskStorage(directory)` from
`pixi.caching.disk`, `CacheSQLStorage(url)` from `pixi.caching.sql`, or
`CacheRedisStorage(url, key_prefix=...)` from `pixi.caching.redis`.
Pass it to `create_bot(cache_storage=storage)` to use it throughout the bot.
Individual consumers can use `get_media_cache(storage=storage)` and
`get_embedding_cache(storage=storage, embedding_model=backend)`.
Call `close()` on injected SQL/Redis storage when finished; the caller owns
those connections. CLI-created connections are closed automatically.
Disk remains the default under the configured root's `cache/` directory.
Old disk cache layouts are not read or migrated.

Construct `LlamaEmbeddingModel(config)`
from `pixi.inference.embeddings` for native llama.cpp inference, and call its
`aclose()` when finished. Production bootstrap registers that method as a bot
shutdown hook, so stopping the bot reaps its local `llama-server` process.

`LlamaChatModel(LlamaLanguageModelConfig(...))` in `pixi.inference.chat` implements
the same `ChatModel` streaming protocol as the API adapter, including content,
reasoning, and tool-call events. It and `LlamaEmbeddingModel` inherit the shared
`LlamaServer` lifecycle ABC in `pixi.inference.server`: process startup, readiness,
request serialization, idle shutdown, cancellation-safe cleanup, and explicit
`aclose()`. Each adapter owns its process; the default helper reuses the main adapter.
Closing a partial chat stream releases its HTTP connection and reaps the local
server. Applications that stop consuming a stream early must call its `aclose()`
(for example, through `contextlib.aclosing`).

SQL/Redis caching still requires FFmpeg or the optional `media` install extra
for image/audio conversion.

Chat history contains portable `ChatMessageMeta` values from `pixi.model.chat`.
Live platform messages belong to action/tool contexts, not saved history.
`context.reference_message` is conversation data;
`context.platform_message` is the current reply/reaction handle. Scheduled
actions retain their original execution context. Cancelling a schedule frees
its ID immediately; cleanup of the cancelled task cannot remove a replacement
scheduled with the same ID.

Imports use their owning modules: `pixi.ai.chatting.client.AsyncChatClient`,
`pixi.bot.conversations.AsyncChatbotInstance`, and
`pixi.interfaces.platform.PlatformProvider`. Package initializers do not retain
compatibility aliases for the former locations.

Run the storage and cache regression checks (no external API calls or model downloads):

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```

SQL tests run against temporary SQLite databases when the `sql` extra is
installed. Redis integration tests require the `redis` extra and an existing
server; they use unique namespaces and delete only their own keys:

```sh
PIXI_TEST_REDIS_URL=redis://localhost:6379/15 PYTHONPATH=src python -m unittest discover -s tests -v
```


## Custom Actions and Tools

`PixiClient.register_action(action)` and `register_tool(tool)` accept instances
implementing `AsyncAction` and `AsyncTool` from
`pixi.ai.chatting.callbacks`.

Actions provide `name`, `field_name`, `description`, `is_visible`,
`should_register(instance)`, and `async call(context, value)`. The value is a
string, or `None` when the model omits it. Tools provide `name`, `description`,
`parameters` (an OpenAI-compatible JSON schema, or `None`),
`should_register(instance)`, and `async call(context, **arguments)`. Define metadata on the class.

```python
from pixi.ai.chatting.callbacks import ActionContext, ToolContext


class ShoutAction:
    name = "shout"
    field_name = "message"
    description = "Send an uppercase message in the current chat."
    is_visible = True

    @classmethod
    def should_register(cls, instance) -> bool:
        return True

    @classmethod
    async def call(cls, context: ActionContext, value: str | None) -> None:
        if value and context.platform_message is not None:
            await context.platform_message.send(value.upper())


class CounterTool:
    name = "increment_counter"
    description = "Increment a shared counter by the requested amount."
    parameters = {
        "type": "object",
        "properties": {"amount": {"type": "integer"}},
        "required": ["amount"],
        "additionalProperties": False,
    }

    total = 0

    @classmethod
    def should_register(cls, instance) -> bool:
        return True

    @classmethod
    async def call(cls, context: ToolContext, *, amount: int) -> int:
        cls.total += amount
        return cls.total


# Given an initialized PixiClient:
client.register_action(ShoutAction())
client.register_tool(CounterTool())
```

Client registrations apply to subsequently created chats. Each chat calls
`should_register(self)` when it is constructed; return `False` to exclude an
action or tool from that chat. Use instance attributes for per-bot state and
`context.parent_instance` for chat-specific state; classmethod-based actions and
tools are also supported. Both contexts expose `reference_message` and an optional
live `platform_message`. Invisible actions (`is_visible = False`) do not count as a
visible response. Tool registration is ignored when tool calling is disabled.

## Lisence

MIT
