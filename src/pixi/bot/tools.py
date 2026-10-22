from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from ..ai.agents import RetrievalAgent
from ..ai.chatting.callbacks import AsyncTool, ToolContext

if TYPE_CHECKING:
    from ..ai.chatting import AsyncChatbotInstance
    from ..apis.wikimedia import AsyncWikimediaAPI
    from ..storage.database import DirectoryDatabase
    from .client import PixiClient


def create_database_tools(
    client: PixiClient,
    database_name: str,
    database_api: DirectoryDatabase,
) -> tuple[AsyncTool, AsyncTool]:
    class SearchDatabaseTool:
        name = f"search_{database_name}_database"
        description = (
            f"Searches the {database_name} database based on a keyword and returns the entry metadata. "
            "you may use this function multiple times to find the specific information you're looking for."
        )
        parameters = dict(
            type="object",
            properties=dict(
                keyword=dict(
                    type="string",
                    description=f"The search keyword to find matches in the database text from the {database_name} database",
                ),
            ),
            required=["keyword"],
            additionalProperties=False,
        )

        @classmethod
        def should_register(cls, instance: AsyncChatbotInstance) -> bool:
            return True

        @classmethod
        async def call(cls, context: ToolContext, *, keyword: str):
            return [asdict(match) for match in await database_api.search(keyword)]

    class QueryDatabaseTool:
        name = f"query_{database_name}_database"
        description = f"fetch and retrieve relevent information from the content of the {database_name} database based on a query."
        parameters = dict(
            type="object",
            properties=dict(
                query=dict(
                    type="string",
                    description="A question or a statement that you want to find information about.",
                ),
                ids=dict(
                    type="string",
                    description=f"Comma-seperated numerical entry ids to fetch and query information from, use `search_{database_name}_database` to optain entry ids based a search term.",
                ),
            ),
            required=["query", "ids"],
            additionalProperties=False,
        )

        @classmethod
        def should_register(cls, instance: AsyncChatbotInstance) -> bool:
            return True

        @classmethod
        async def get_entry_as_str(cls, entry_id: int) -> str:
            dataset_entry = await database_api.get_entry(entry_id)
            return json.dumps(asdict(dataset_entry), ensure_ascii=False, indent=3)

        @classmethod
        async def call(cls, context: ToolContext, *, query: str, ids: str | None):
            if ids is None:
                return "no result: no id specified"

            if client.embedding_model:
                from ..ai.rag.client import AsyncRAGClient

                rag = AsyncRAGClient(client.auth, client.embedding_model)
                entries = await asyncio.gather(*[
                    database_api.get_entry(int(entry_id.strip())) for entry_id in ids.split(",")
                ])
                for entry in entries:
                    await rag.add_document(entry.content, entry.title, entry.id)
                query_embed = await rag.embed(query)
                matches = [
                    asdict(doc_match)
                    for doc_match in rag.search(query_embed)  # pyright: ignore[reportArgumentType]
                ]
                return matches
            else:
                agent = client.create_agent_instance(
                    agent_cls=RetrievalAgent,
                    context=await asyncio.gather(*[
                        cls.get_entry_as_str(int(entry_id.strip())) for entry_id in ids.split(",")
                    ]),
                )
                return await agent.execute_query(query)

    return SearchDatabaseTool(), QueryDatabaseTool()


def create_mediawiki_tools(
    client: PixiClient,
    wiki_name: str,
    wiki_api: AsyncWikimediaAPI,
) -> tuple[AsyncTool, AsyncTool]:
    class SearchWikiTool:
        name = f"search_wiki_{wiki_name}"
        description = (
            f"Searches the {wiki_name} wiki based on a keyword. returns the page URL and Title, "
            "and optionally the description of the page. you may use this function multiple times to find the specific page you're looking for."
        )
        parameters = dict(
            type="object",
            properties=dict(
                keyword=dict(
                    type="string",
                    description=f"The search keyword to find matches in the wiki text from the {wiki_name} wiki",
                ),
            ),
            required=["keyword"],
            additionalProperties=False,
        )

        @classmethod
        def should_register(cls, instance: AsyncChatbotInstance) -> bool:
            return True

        @classmethod
        async def call(cls, context: ToolContext, *, keyword: str):
            return [asdict(search_result) for search_result in await wiki_api.search(keyword)]

    class QueryWikiContentTool:
        name = f"query_wiki_content_{wiki_name}"
        description = "fetch wiki content and retrieve relevent information from them based on a query."
        parameters = dict(
            type="object",
            properties=dict(
                query=dict(
                    type="string",
                    description='A statement that is searched inside the content of the wiki, it should clearly name what you\'re looking for, example: "how to craft an arrow?" not "how to craft it" and not "craft"',
                ),
                titles=dict(
                    type="string",
                    description=f"Page titles to fetch and query information from, seperated by a delimiter character: `|`. use `search_wiki_{wiki_name}` to optain page titles based a search term.",
                ),
            ),
            required=["query", "titles"],
            additionalProperties=False,
        )

        @classmethod
        def should_register(cls, instance: AsyncChatbotInstance) -> bool:
            return True

        @classmethod
        async def fetch_wiki_page(cls, title: str) -> tuple[str, str]:
            page_content, title = await wiki_api.get_plaintext(title.strip())
            return page_content, title

        @classmethod
        async def call(cls, context: ToolContext, *, titles: str, query: str):
            if not titles:
                return "no result: no page specified"

            _titles = [t for t in titles.split("|") if t]
            if not _titles:
                return "no result: no page specified"

            page_context = await asyncio.gather(*[
                cls.fetch_wiki_page(title) for title in _titles
            ])

            if client.embedding_model:
                from ..ai.rag.client import AsyncRAGClient

                rag = AsyncRAGClient(client.auth, client.embedding_model)
                for i, (page, title) in enumerate(page_context):
                    await rag.add_document(page, title, i)
                query_embed = await rag.embed(query)
                matches = [
                    asdict(doc_match)
                    for doc_match in rag.search(query_embed)  # pyright: ignore[reportArgumentType]
                ]
                return matches
            else:
                agent = client.create_agent_instance(
                    agent_cls=RetrievalAgent,
                    context=[page for page, title in page_context],
                )
                return await agent.execute_query(query)

    return SearchWikiTool(), QueryWikiContentTool()


class FetchChannelHistoryTool:
    name = "fetch_channel_history"
    description = "Fetches the last `n` message from a text channel"
    parameters = dict(
        type="object",
        properties=dict(
            channel_id=dict(
                type="string",
                description="The numerical channel id, which is used to identify the channel.",
            ),
            n=dict(
                type="integer",
                description="the number of messages to fetch from the channel",
            ),
        ),
        required=["channel_id"],
        additionalProperties=False,
    )

    @classmethod
    def should_register(cls, instance: AsyncChatbotInstance) -> bool:
        return True

    @classmethod
    async def call(cls, context: ToolContext, *, channel_id: str, n: int):
        assert context.parent_instance is not None
        reflection_api = context.parent_instance.bot.platform_provider
        return await reflection_api.fetch_channel_history(int(channel_id), n=n)
