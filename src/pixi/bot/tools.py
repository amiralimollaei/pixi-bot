from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from pixi.ai.agents import RetrievalAgent
from pixi.ai.chatting.callbacks import AsyncTool, ToolContext

if TYPE_CHECKING:
    from pixi.apis.wikimedia import AsyncWikimediaAPI
    from pixi.bot.client import PixiClient
    from pixi.bot.conversations import AsyncChatbotInstance
    from pixi.storage.knowledge import KnowledgeBase


def create_knowledge_tools(
    client: PixiClient,
    knowledge_name: str,
    knowledge_base: KnowledgeBase,
) -> tuple[AsyncTool, AsyncTool]:
    class SearchKnowledgeTool:
        name = f"search_{knowledge_name}_knowledge"
        description = (
            f"Searches the {knowledge_name} knowledge base by keyword and returns document metadata. "
            "you may use this function multiple times to find the specific information you're looking for."
        )
        parameters = dict(
            type="object",
            properties=dict(
                keyword=dict(
                    type="string",
                    description=f"The keyword to find in documents from the {knowledge_name} knowledge base",
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
            return [asdict(match) for match in await knowledge_base.search(keyword)]

    class QueryKnowledgeTool:
        name = f"query_{knowledge_name}_knowledge"
        description = f"Retrieve information from the {knowledge_name} knowledge base based on a query."
        parameters = dict(
            type="object",
            properties=dict(
                query=dict(
                    type="string",
                    description="A question or a statement that you want to find information about.",
                ),
                ids=dict(
                    type="string",
                    description=f"Comma-separated document IDs to query; use `search_{knowledge_name}_knowledge` to find IDs.",
                ),
            ),
            required=["query", "ids"],
            additionalProperties=False,
        )

        @classmethod
        def should_register(cls, instance: AsyncChatbotInstance) -> bool:
            return True

        @classmethod
        async def get_document_as_str(cls, entry_id: int) -> str:
            document = await knowledge_base.get_document(entry_id)
            return json.dumps(asdict(document), ensure_ascii=False, indent=3)

        @classmethod
        async def call(cls, context: ToolContext, *, query: str, ids: str | None):
            if ids is None:
                return "no result: no id specified"

            if client.embedding_model:
                rag = client.create_rag_client()
                entries = await asyncio.gather(
                    *[
                        knowledge_base.get_document(int(entry_id.strip()))
                        for entry_id in ids.split(",")
                    ]
                )
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
                    context=await asyncio.gather(
                        *[
                            cls.get_document_as_str(int(entry_id.strip()))
                            for entry_id in ids.split(",")
                        ]
                    ),
                )
                return await agent.execute_query(query)

    return SearchKnowledgeTool(), QueryKnowledgeTool()


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
            return [
                asdict(search_result)
                for search_result in await wiki_api.search(keyword)
            ]

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

            page_context = await asyncio.gather(
                *[cls.fetch_wiki_page(title) for title in _titles]
            )

            if client.embedding_model:
                rag = client.create_rag_client()
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
        assert context.parent_instance.bot is not None
        return (
            await context.parent_instance.bot.platform_provider.fetch_channel_history(
                int(channel_id), n=n
            )
        )
