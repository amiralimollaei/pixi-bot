import json
import logging
from typing import Optional

from .base import AgentBase
from ..chatting import AsyncChatClient


class RetrievalAgent(AgentBase):
    """
    Retrieves relevant information from context and a query to the agent.
    """

    def __init__(self, context: Optional[list[str]] = None, **client_kwargs):
        super().__init__(**client_kwargs)

        self.context = context or []
        self.system_prompt = "\n".join([
            "## You are a context retrieval agent",
            ""
            "Given a list of entries and a query, you must return any context that is relevent to the query.",
            "Write the response without loosing any data, mention all the details, the less you summerize is the better.",
            ""
            "output a json object with the following keys:",
            " - `relevant`: a list of all information that could possibly be used to answer the query in any way",
            " - `source`: a list of sources where the information was found, if applicable",
            " - `confidence`: a score value between 1 and 10 indicating how confident you are in the information provided",
            ""
            "example output:",
            "```json",
            "{",
            "  \"source\": [\"page_title:Villagers\"]",
            "  \"relevant\": [\"Villagers can be cured from zombie villagers by using a splash potion of weakness and a golden apple.\"],",
            "  \"confidence\": 9",
            "}",
            "```"
        ])
        self.client.set_system(self.system_prompt)

    def to_dict(self) -> dict:
        return super().to_dict() | dict(
            context=self.context
        )

    @classmethod
    def from_dict(cls, data: dict, **client_kwargs) -> 'RetrievalAgent':
        client = AsyncChatClient(**client_kwargs)
        client.load_state_dict(data["client"])
        context = data.get("context", [])
        return cls(
            context = context,
            client = client            
        )

    def add_context(self, context: str):
        logging.debug(f"Adding context: {context}")
        self.context.append(context)

    def format_query(self, query: str) -> str:
        logging.debug(f"Retrieving information for query: {query}")
        prompt = "\n".join([
            "Context:",
            "```json",
            json.dumps(self.context),
            "```",
            ""
            f"Query: \"{query}\"",
        ])
        return prompt