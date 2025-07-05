import json
import os
import time
import hashlib
from typing import Optional

from ..chatting import AsyncChatClient
from ..utils import exists


class MemoryItem:
    def __init__(self, content: str, timestamp: Optional[float] = None):
        assert exists(content) and isinstance(content, str)

        self.content = content
        self.time = timestamp if timestamp is not None else time.time()

    def to_dict(self) -> dict:
        return dict(
            content=self.content,
            time=self.time
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'MemoryItem':
        return cls(
            content=data["content"],
            timestamp=data.get("time")
        )

    def hash(self) -> str:
        # Hash based on content and time for uniqueness
        return hashlib.sha256(f"{self.content}|{self.time}".encode("utf-8")).hexdigest()


class MemoryAgent:
    def __init__(self, model: str = "google/gemma-3-27b-it", memories: Optional[list[MemoryItem]] = None):
        self.memories: list[MemoryItem] = memories or []
        self.model = model
        self.client = AsyncChatClient(model=model)
        self.system_prompt = "\n".join([
            "*You are a memory retrieval agent**",
            ""
            "Given a list of memories and a query, you MUST ONLY return the *summary* of the most relevant memories.",
            "Write the response in first person (these are YOUR memories) as if you are recalling information, for example:",
            " - I remember that ...",
            " - I don't recall anything about ...",
            " - I recall that ...",
            " - I can't remember ...",
            " - The only thing I remember is ..."
            ""
            "**NOTE**: do not just list the relevent memories"
        ])
        self.client.set_system(self.system_prompt)

    def to_dict(self) -> dict:
        return dict(
            memories=[m.to_dict() for m in self.memories]
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'MemoryAgent':
        memories = [MemoryItem.from_dict(m) for m in data.get("memories", [])]
        return cls(memories=memories)

    def save_as(self, file: str):
        with open(file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False)

    @classmethod
    def from_file(cls, file: str) -> 'MemoryAgent':
        if os.path.isfile(file):
            with open(file, "rb") as f:
                data = json.load(f)
            return cls.from_dict(data)
        else:
            inst = cls()
            inst.save_as(file)
            return inst

    def add_memory(self, memory: str):
        print(f"Adding memory: {memory}")
        self.memories.append(MemoryItem(memory))

    def remove_memory(self, memory_hash: str):
        print(f"Removing memory with hash: {memory_hash}")
        self.memories = [m for m in self.memories if m.hash() != memory_hash]

    async def retrieve_memories(self, query: str) -> str:
        """
        Retrieves relevant memories by sending all memory hashes (or indices) and a query to another agent.
        return_type: 'hash' or 'index'
        """
        print(f"Retrieving memories for query: {query}")

        prompt = "\n".join([
            f"Query: {query}",
            "",
            "Memories:",
            "\n".join([f"- {m.content}" for m in self.memories]),
        ])
        response = await self.client.ask(prompt, temporal=True, enable_timestamps=False)
        assert response
        return response.strip()
