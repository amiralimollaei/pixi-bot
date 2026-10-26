# Contributing to Pixi

Architecture, Python integration contracts, extension points, and regression checks
are documented here. For installation, CLI usage, storage configuration, and
deployment, see the [README](README.md).

- [Development](#development)
- [Architecture](#architecture)
- [Custom Actions and Tools](#custom-actions-and-tools)
- [Knowledge Importers](#knowledge-importers)

## Development

Install the development environment (including Ruff, Pyright, and pre-commit) and
enable the Git hooks:

```sh
uv sync --all-extras
uv run pre-commit install
```

Format Python files and organize imports:

```sh
uv run ruff check --fix
uv run ruff format
```

Check formatting without changing files:

```sh
uv run ruff check
uv run ruff format --check
```

Ruff sorts imports into standard-library, third-party, and local groups and
requires absolute imports rooted at `pixi`. Preserve optional dependency imports
at their existing execution boundaries.

The pre-commit hooks run Ruff's import checks, Ruff's formatter, and Pyright.
Pyright checks the entire `src` and `examples` trees, with all optional
dependencies installed. Run all hooks manually with:

```sh
uv run pre-commit run --all-files
```

Run the scheduler and knowledge-import regression tests:

```sh
uv run python -m unittest discover -s tests -v
```

## Architecture

Pixi keeps feature-oriented packages with explicit ports between application
behavior and external systems:

| Module                                                       | Responsibility                                                                                                |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `pixi.cli`                                                   | Arguments, dotenv settings, and logging                                                                       |
| `pixi.bootstrap`                                             | Production composition: selects adapters, loads resources, registers built-ins and addons                     |
| `pixi.bot`                                                   | Message handling, conversation lifecycle, and scheduled actions                                               |
| `pixi.ai.chatting`                                           | Provider-independent completion, tool execution, and inline action processing                                 |
| `pixi.ai.rag`                                                | Chunking and retrieval using injected embedding and cache services                                            |
| `pixi.model`                                                 | Portable message, platform metadata, and embedding values                                                     |
| `pixi.interfaces`                                            | Platform, model-stream, embedding-cache, message-storage, knowledge-storage, and knowledge-importer contracts |
| `pixi.platform`, `pixi.apis`, `pixi.storage`, `pixi.caching` | Concrete external-system adapters                                                                             |

Application code consumes ports; adapters implement them. Concrete adapter
selection belongs in `bootstrap.py`, not in conversation or retrieval logic.
`create_bot(...)` builds the production application. Construct `PixiClient`
directly when supplying your own platform, model, message storage, and prompt
resources. Neither the chat client nor the RAG client constructs an API client.

GIF search uses the `pixi.interfaces.gifs.GifSearchAPI` port: `search(query)`
always returns an immutable `pixi.model.gifs.GifSearchResult` with a `results`
tuple of `Gif` objects and provider `attribution`. Each GIF has a non-null media
`url`, optional `id`, `title`, `description`, and `page_url`, plus a `tags` tuple.
No usable GIF means an empty tuple, never `None`. The send-GIF action sends the
first GIF's URL only and sends nothing for empty results.
`bootstrap.create_gif_api()` selects KLIPY before GIPHY
from nonblank environment keys. The KLIPY adapter uses its Tenor-compatible v2
search endpoint; the GIPHY adapter uses its native v1 GIF search endpoint.
Provider-specific response parsing stays in the adapters.

KLIPY maps `content_description` to `description`, preserves `tags`, and uses
`itemurl` (or its short `url`) as `page_url`. GIPHY maps `alt_text` to `description`
and its top-level `url` to `page_url`; its media URL remains
`images.original.url`. GIPHY alt-text access can depend on API-key capabilities,
and tags are not guaranteed by its standard GIF schema. Missing text metadata
stays `None`, and missing tags become `()`; titles are not substituted for missing
descriptions. Provider attribution remains available in the search result metadata.

Telegram commands are excluded from the ordinary chat handler, so slash commands
registered by bootstrap or addons work regardless of registration order. Unknown
commands and commands addressed to other bots do not trigger chat inference.

Discord command authorization accepts direct messages and guild administrators,
for both message and interaction events. Video captions are sent as message text
alongside the attachment.

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

| Operation                                               | Behavior                                                                              |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `exists(key)` / `count(key)`                            | Inspect a history without reading its messages; missing histories have count zero     |
| `append(key, messages)`                                 | Atomically append only new messages; an empty batch creates an existing empty history |
| `iter_messages(key, start=0, stop=None, reverse=False)` | Lazily read the absolute half-open range `[start, stop)` using bounded pages          |
| `truncate(key, length)`                                 | Remove a tail without rewriting the retained messages or growing the history          |
| `delete(key)`                                           | Remove a history; deleting an absent key is a no-op                                   |

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

`pixi.storage.paths.PixiPaths` owns the default root (`DEFAULT_ROOT`) and all
application paths. Both CLIs and `create_bot` use that root by default.
`set_root(...)` changes the root used by subsequent accessor calls; paths are not
cached at import time. Use `messages()` for message history rather than appending
to `userdata()`, and `knowledge()` for the existing `datasets/` directory.
Use `persona()`, `system_prompt()`, and `examples()` for default resource files.
Accessors return `pathlib.Path`; open resources with `.open(encoding="utf-8")`
instead of the removed `get_resource_path` and `open_resource` helpers.

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
`AsyncScheduler.aclose()` also waits for cleanup of previously cancelled tasks,
even after their IDs have been freed or reused.

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

## Knowledge Importers

The Python importer contract is
`pixi.interfaces.knowledge.KnowledgeImporter`:

```python
from pathlib import Path

from pixi.interfaces.knowledge import KnowledgeImporter
from pixi.knowledge_import.devdocs import DevDocsImporter

importer: KnowledgeImporter = DevDocsImporter()
documents = list(importer.read_documents(Path("./devdocs/python")))
```

`MediaWikiImporter`, `DevDocsImporter`, and `KiwixImporter` implement this protocol
in their respective `pixi.knowledge_import` modules. Importers yield `DocumentMeta`
values and have no storage or bot dependencies. Instances are stateless; document
IDs must be unique and deterministic for a given source. Exhaust the iterator
before saving, since malformed input can fail during iteration.

To add a format, implement the protocol and register an instance in
`pixi.knowledge_import.IMPORTERS`. That typed registry supplies both CLI format
choices and importer selection; no CLI format-switch branch is required.
