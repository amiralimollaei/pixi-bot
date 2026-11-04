# Railway Deployment

Pixi is a bot process that connects to Discord or Telegram and requests responses
from a language model. This guide deploys it on [Railway](https://railway.com/)
using an OpenAI-compatible model API. You need a Railway account, a copy of this
repository, a platform bot token, and your model provider's API credentials.
See the [README](README.md#getting-started) for creating a bot account and choosing
a model.

## Deploy a bot service

Create a Railway service from this repository. Railway detects the root
`Dockerfile` and builds the bot image. In the service's **Variables** tab,
`PIXI_EXTRAS` selects the optional Python dependencies installed during the build;
`PIXI_PLATFORM` selects the platform when the container starts:

| Bot image | `PIXI_EXTRAS` | `PIXI_PLATFORM` |
| --- | --- | --- |
| Both platform SDKs and all optional integrations | Unset (installs all extras) | `telegram` or `discord` |
| Telegram only | `telegram kiwix sql redis` | `telegram` |
| Discord only | `discord kiwix sql redis` | `discord` |

For a Redis-only image, use `telegram redis` or `discord redis` as described in
[Redis-only deployment](#redis-only-deployment).

Keep the service's root directory at the repository root and leave its custom
start command unset to use the Dockerfile's `CMD`. Add `PIXI_MODEL`,
`OPENAI_API_KEY`, and the matching `TELEGRAM_BOT_TOKEN` or `DISCORD_BOT_TOKEN`
as Railway variables. `PIXI_EMBEDDING_MODEL` and `PIXI_EXTRA_ARGS` are optional;
no `.env` file is required inside the image.

To run both platforms, create **two Railway services pointing at the same
repository and branch**, each with its own extras, platform setting, variables,
and bot token. These are outbound bot workers; they do not need a public domain
or HTTP port.

The Dockerfile builds one bot container; databases are separate services. Railway
can import a Compose file through the project canvas, but it maps entries to
Railway services rather than running `docker compose` on deployments. The
repository's Compose profiles are for local use; configure each Railway service
with its own `PIXI_EXTRAS` and `PIXI_PLATFORM`.
See Railway's [Dockerfile selection](https://docs.railway.com/builds/dockerfiles)
and [Compose deployment guide](https://docs.railway.com/guides/docker-compose).

## Logs

Railway timestamps log entries. To omit Pixi's own timestamp, add
`--no-log-timestamps` to `PIXI_EXTRA_ARGS`, alongside any other CLI arguments.
Severity, logger name, and message are included regardless of this setting.
Pixi timestamps are enabled by default; `--log-timestamps` enables them explicitly.

## Redis-only deployment

1. Create your own project with one bot service from this repository and a Redis
   service. Let Railway build the root `Dockerfile` directly; do not import all
   Compose services or add a personal Dockerfile to the repository.
2. Set these variables on the **bot service** (values below are unquoted Railway
   variable values):

   | Variable | Value |
   | --- | --- |
   | `PIXI_EXTRAS` | `telegram redis` |
   | `PIXI_PLATFORM` | `telegram` |
   | `PIXI_MODEL` | Your API model ID |
   | `OPENAI_API_KEY` | Your API key |
   | `TELEGRAM_BOT_TOKEN` | Your own bot token |
   | `REDIS_URL` | `${{Redis.REDIS_URL}}` (replace `Redis` with your service name) |
   | `PIXI_EXTRA_ARGS` | `--messages-storage redis --cache-storage redis --knowledge-storage redis` |

   For Discord, change both platform values and use `DISCORD_BOT_TOKEN` instead.
   Set `OPENAI_BASE_URL` too if your API provider uses a custom endpoint.
   Railway passes `PIXI_EXTRAS` to the Dockerfile as a build argument, selecting
   the dependencies installed in the image.
3. Leave the start command unset to use the image's `start.sh`. Run one bot
   replica as a worker; it does not serve an HTTP health endpoint. Rebuild and
   redeploy after changing `PIXI_EXTRAS`.

Use a separate bot token and preferably a dedicated Redis instance so this
deployment cannot compete with an existing bot or write its data. If sharing a
Redis database, set distinct `--redis-key-prefix`, `--cache-redis-key-prefix`,
and `--knowledge-redis-key-prefix` values in `PIXI_EXTRA_ARGS`.

Redis stores message history, caches, and knowledge bases when you select it for
those backends. Persona files, prompts, and addons live under `~/.pixi/` by
default, or the path selected by `--pixi-directory`. Mount a persistent volume
at that directory to keep customized files across deployments. Schedules and
other in-memory conversation settings are not persisted.
Keep secrets in Railway variables, not build arguments or committed configuration.

## SQL and Redis

Add a PostgreSQL or Redis service to your Railway project if you want external
storage. Pixi connects to the service; it does not provision a database.
In the bot service's variables, reference the database service's connection URL
as `DATABASE_URL` or `REDIS_URL`.
Use the private URL containing its `*.railway.internal` hostname and internal
port, not the public TCP proxy. Connection URLs carry authentication and any
SSL options; no application-specific DNS configuration is needed.

The default Docker image includes the `sql` and `redis` extras; custom images
must select the extras they use. For a non-Docker installation, install them
alongside your platform extra, for example `pip install 'pixi-bot[telegram,sql,redis]'`.

For SQL histories and Redis caches, set both URL variables and use:

```sh
pixi-cli -p telegram --model YOUR_MODEL --messages-storage sql --cache-storage redis
```

With the Docker launcher, set
`PIXI_EXTRA_ARGS=--messages-storage sql --cache-storage redis` in Railway instead
of replacing the start command.

SQL storage accepts SQLAlchemy URLs. SQLite uses `sqlite:////absolute/path.db`;
plain `postgresql://` and `postgres://` URLs use psycopg 3, included in the `sql`
extra. Explicit driver URLs are preserved; other databases need their driver
installed separately, for example `pymysql` for `mysql+pymysql://...`.
The database must already exist and the account must be able to create tables.
Redis accepts `redis://`, `rediss://`, and `unix://` URLs.
