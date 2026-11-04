# Contributing to Pixi

Pixi is a Python application that connects a language model to Discord or Telegram.
This guide explains how its modules fit together, how to run development tools,
and how to extend the bot. For installation, credentials, and a first chat, start
with the [README](README.md). For hosting on Railway, see [DEPLOYMENT.md](DEPLOYMENT.md).

- [Development](#development)
- [Architecture](#architecture)
- [Custom Actions and Tools](#custom-actions-and-tools)
- [Knowledge Importers](#knowledge-importers)

## Development

Clone the repository and enter its directory, then install the development
environment, including Ruff, Pyright, and pre-commit, and enable the Git hooks:

```sh
git clone https://github.com/amiralimollaei/pixi-bot.git
cd pixi-bot
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
requires absolute imports rooted at `pixi`. Import optional dependencies only
when selecting or using their integration, so unrelated features can run without them.

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

The bot receives a platform message, loads the conversation's history, requests
a model response, and executes any actions or tools requested by the model.
An **action** is an inline instruction such as `[SEND: Hello]`; a **tool** is a
structured model request, such as a documentation search, whose result is sent
back to the model.

Python protocols in `pixi.interfaces` describe the behavior expected from
platforms, models, and storage. Concrete implementations, called **adapters**,
connect those protocols to external libraries and services:

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

Application code uses these protocols; adapters implement them.
`pixi.bootstrap.create_bot(...)` selects adapters, loads prompt resources, and
registers built-in actions, tools, and addons. To supply your own implementations,
construct `PixiClient` with a platform provider, model provider, message storage,
and prompt resources.

CLI startup separates parser construction, logging, configuration validation and
resolution, resource construction, and execution. `pixi.cli_storage` shares URL
resolution and lifetime management for message, cache, and knowledge backends;
offline knowledge imports run without starting the bot.

### Platform and model adapters

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
and its top-level `url` to `page_url`; its media URL comes from
`images.original.url`. GIPHY alt-text access can depend on API-key capabilities,
and tags are not guaranteed by its standard GIF schema. Missing text metadata
is `None`, and missing tags become `()`; titles are not substituted for missing
descriptions. Provider attribution is available in the search result metadata.

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

User-message text is optional, with or without media. History serialization omits
empty text, so adapters must accept `content=None` and render an empty user-text
field rather than the literal text `"None"`. The user template supplies its
label, timestamps when enabled, and any attached metadata. Raw-content requirements
apply to system, assistant-text, and tool-result messages, not templated user messages.

OpenAI HTTP requests and SSE decoding live in `pixi.apis.openai.transport`.
The transport yields portable chat events directly, returns embedding vectors,
and exposes async `list_models()` for startup verification. Model adapters build
wire payloads.
API errors live in `pixi.apis.openai.exceptions`; the package initializer has no
implementation or re-exports.

Tool calls execute serially in first-seen order as soon as their streamed arguments
form complete JSON objects, while the model stream continues. Results are buffered
until the source stream ends and tool execution finishes, then added to history
before any continuation request. Calls with omitted arguments execute at the end
of the stream.

### Conversation history

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
or explicitly closed requests discard it; `discard_history=True` discards it even on
success. Temporary requests do not persist their input prompt. Rollback therefore
does not copy history or truncate messages committed by another concurrent request.
Nested requests have independent deltas and merge into their parent only on
success. Scheduled callbacks start detached from the originating request and
read the current stored history rather than retaining an expired request delta.

Each public turn entry point (`stream_ask`, `stream_completion`, or chatbot
`stream_call`) owns one history scope and closes its private streaming helpers.
Nested turns have independent deltas. The streaming pipeline passes text one
character at a time; parsers recognize `<think>...</think>` regions and inline
action instructions.

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
Note visibility resets after an idle conversation instance is unloaded.

Persona and prompts are files under `resources/`. Edit `persona.json`,
`system.md`, or `examples.txt`, then restart the bot to apply the changes.
Startup copies missing default resources and does not overwrite customized files.

`pixi.storage.paths.PixiPaths` owns the default root (`DEFAULT_ROOT`) and all
application paths. Both CLIs and `create_bot` use that root by default.
`set_root(...)` changes the root used by subsequent accessor calls; paths are not
cached at import time. `messages()` returns the message-history directory,
`userdata()` its parent, and `knowledge()` the `datasets/` directory.
Use `persona()`, `system_prompt()`, and `examples()` for default resource files.
Accessors return `pathlib.Path`; open resources with `.open(encoding="utf-8")`.

### Agents, models, and caches

An agent uses a chat client for a specific task. `RetrievalAgent` receives
reference text and asks a helper model to extract information relevant to a query.

This example constructs an API-backed retrieval agent and saves its conversation
under `./histories`. Set `OPENAI_API_KEY` in your environment or `.env`, and
replace `YOUR_MODEL` with a model ID supplied by your API provider.

```python
import asyncio
import os

from pixi.ai.agents import RetrievalAgent
from pixi.apis.openai.adapter import OpenAIChatModel
from pixi.cli import load_dotenv
from pixi.model.config import OpenAIAuthConfig, OpenAILanguageModelConfig
from pixi.storage.messages import MessagesDiskStorage


async def main():
    load_dotenv()
    auth = OpenAIAuthConfig(
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.environ["OPENAI_API_KEY"],
    )
    model = OpenAILanguageModelConfig(id="YOUR_MODEL", max_context=8192)
    agent = RetrievalAgent(
        storage=MessagesDiskStorage("./histories"),
        history_key="agent:research",
        context=["Apples are fruit that grow on trees."],
        language_model_inference=OpenAIChatModel(auth, model),
        model=model,
    )
    answer = await agent.execute_query("Where do apples grow?", discard_history=False)
    print(answer)


asyncio.run(main())
```

Clients with the same storage adapter and history key access the same
conversation. Agent queries default to `discard_history=True`, so the input and
response are not saved; use `discard_history=False` to save them. Agents created
by the bot share its storage and receive distinct history keys unless one is
supplied. Storage errors propagate from the backend.

For Python integrations, construct `CacheDiskStorage(directory)` from
`pixi.caching.disk`, `CacheSQLStorage(url)` from `pixi.caching.sql`, or
`CacheRedisStorage(url, key_prefix=...)` from `pixi.caching.redis`.
Pass it to `create_bot(cache_storage=storage)` to use it throughout the bot.
Individual consumers can use `get_media_cache(storage=storage)` and
`get_embedding_cache(storage=storage, embedding_model_inference=backend)`.
Embedding backends implement the `EmbeddingModelInferenceProvder` protocol.
Call `close()` on injected SQL/Redis storage when finished; the caller owns
those connections. CLI-created connections are closed automatically.
Disk caching uses the configured root's `cache/` directory by default.

Media conversion is synchronous; embedding computation is asynchronous.
Both bind storage operations to a namespace, which keeps their cache entries
separate. `MediaCachePair` provides image/audio operations for the FFmpeg and
PyAV providers. Each provider loads only its own codec dependencies.

Construct `LlamaEmbeddingModel(config)`
from `pixi.inference.embeddings` for native llama.cpp inference, and call its
`aclose()` when finished. Production bootstrap registers that method as a bot
shutdown hook, so stopping the bot reaps its local `llama-server` process.

`OpenAILanguageModelConfig` and `LlamaLanguageModelConfig` inherit
`LanguageModelConfig`, which exposes the shared `id` and `max_context` attributes
used by chat clients.

`LlamaChatModel(LlamaLanguageModelConfig(...))` in `pixi.inference.chat` implements
the same `LanguageModelInferenceProvider` streaming protocol as the API adapter, including content,
reasoning, and tool-call events. It and `LlamaEmbeddingModel` inherit the shared
`LlamaServer` lifecycle ABC in `pixi.inference.server`: process startup, readiness,
request serialization, idle shutdown, cancellation-safe cleanup, and explicit
`aclose()`. Each adapter owns its process; the default helper reuses the main adapter.
Closing a partial chat stream releases its HTTP connection and reaps the local
server. Applications that stop consuming a stream early must call its `aclose()`
(for example, through `contextlib.aclosing`).

SQL and Redis store converted media; image/audio processing also needs FFmpeg or
the optional `media` install extra.

### Messages and invocation contexts

Chat history contains portable `ChatMessage` values and `ToolCall` records from
`pixi.model.chat`. A message's `timestamp` field records its creation time as
Unix seconds. Its serialized dictionary uses the key `time`.
Live platform messages belong to invocation contexts, not saved history.
`context.reference_message` is conversation data;
`context.platform_message` is the current reply/reaction handle. Scheduled
actions retain their original execution context. Cancelling a schedule frees
its ID immediately; cleanup of the cancelled task cannot remove a replacement
scheduled with the same ID.
`AsyncScheduler.aclose()` also waits for cleanup of previously cancelled tasks,
even after their IDs have been freed or reused.

Import classes from their defining modules, such as
`pixi.ai.chatting.client.AsyncChatClient`,
`pixi.bot.conversations.AsyncChatbotInstance`, and
`pixi.interfaces.platform.PlatformProvider`.

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

Register extensions on an initialized `PixiClient` to make them available to
conversations. The example below defines an action that sends uppercase text and
a tool that maintains a counter. It assumes `client` is the bot instance created
by your application.


Actions provide `name`, `field_name`, `description`, `is_visible`,
`should_register(instance)`, and `async call(context, value)`. The value is a
string, or `None` when the model omits it. Tools provide `name`, `description`,
`parameters` (an OpenAI-compatible JSON schema, or `None`),
`should_register(instance)`, and `async call(context, **arguments)`. Use ordinary
instance methods, class attributes for constant metadata, and constructor
arguments for dependencies. Built-in knowledge/wiki tools are module-level
classes constructed with their client and storage/API dependencies.

```python
from pixi.ai.chatting.callbacks import InvocationContext


class ShoutAction:
    name = "shout"
    field_name = "message"
    description = "Send an uppercase message in the current chat."
    is_visible = True

    def should_register(self, instance) -> bool:
        return True

    async def call(self, context: InvocationContext, value: str | None) -> None:
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

    def __init__(self):
        self.total = 0

    def should_register(self, instance) -> bool:
        return True

    async def call(self, context: InvocationContext, *, amount: int) -> int:
        self.total += amount
        return self.total


# Given an initialized PixiClient:
client.register_action(ShoutAction())
client.register_tool(CounterTool())
```

Client registrations apply to subsequently created chats. Each chat calls
`should_register(self)` when it is constructed; return `False` to exclude an
action or tool from that chat. Use instance attributes for per-bot state and
`context.parent_instance` for chat-specific state. Both receive the same frozen
`InvocationContext`, exposing `reference_message` and an optional live
`platform_message`. Each action consumption receives its own `ActionOutcome`;
`has_visible_actions` records whether a visible action completed, including when
a later stream failure prevents history commit. Scheduled actions use public
`invoke_action()` without mutating another turn's outcome. Invisible actions
(`is_visible = False`) do not count as a visible response. Tool registration is
ignored when tool calling is disabled.

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
