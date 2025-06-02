import json
import logging
import os
from typing import Optional

from ..chatclient import AsyncChatClient

class RetrievalAgent:
    def __init__(self, model: Optional[str] = None, context: Optional[list[str]] = None):
        self.context = context or []
        self.model = model
        self.client = AsyncChatClient(model=model)
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
            "  \"relevant\": [\"Villagers can be cured from zombie villagers by using a splash potion of weakness and a golden apple.\"],",
            "  \"source\": [\"pageid:154847\"]",
            "  \"confidence\": 9",
            "}",
            ])
        self.client.set_system(self.system_prompt)

    def to_dict(self) -> dict:
        return dict(context=self.context)

    @classmethod
    def from_dict(cls, data: dict) -> 'RetrievalAgent':
        context = data.get("context", [])
        return cls(context=context)

    def save_as(self, file: str):
        with open(file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False)

    @classmethod
    def from_file(cls, file: str) -> 'RetrievalAgent':
        if os.path.isfile(file):
            with open(file, "rb") as f:
                data = json.load(f)
            return cls.from_dict(data)
        else:
            inst = cls()
            inst.save_as(file)
            return inst

    def add_context(self, context: str):
        logging.debug(f"Adding context: {context}")
        self.context.append(context)

    async def retrieve(self, query: str) -> list:
        """
        Retrieves relevant information all context and a query to the agent.
        """
        logging.debug(f"Retrieving information for query: {query}")

        prompt = "\n".join([
            "Context:",
            "```json",
            json.dumps(self.context, indent=4),
            "```",
            ""
            f"Query: \"{query}\"",
        ])
        response = ""
        async for char in self.client.stream_ask(prompt, temporal=True):
            response += char
        return response.strip()