import time
import hashlib

from .client import ChatClient

class MemoryItem:
    def __init__(self, content: str, timestamp: float = None):
        self.content = content
        self.time = timestamp if timestamp is not None else time.time()

    def to_dict(self) -> dict:
        return dict(
            content = self.content,
            time = self.time
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'MemoryItem':
        return cls(
            content = data.get("content"),
            timestamp = data.get("time")
        )

    def hash(self) -> str:
        # Hash based on content and time for uniqueness
        return hashlib.sha256(f"{self.content}|{self.time}".encode("utf-8")).hexdigest()

class MemoryAgent:
    def __init__(self, model: str = "meta-llama/Llama-4-Scout-17B-16E-Instruct", memories: list[MemoryItem] = None):
        self.memories: list[MemoryItem] = memories or []
        self.model = model
        self.client = ChatClient(model=model)

    def to_dict(self) -> dict:
        return dict(
            memories = [m.to_dict() for m in self.memories]
        )
    
    @classmethod
    def from_dict(cls, data: dict) -> 'MemoryAgent':
        memories = [MemoryItem.from_dict(m) for m in data.get("memories", [])]
        return cls(memories = memories)
    
    def add_memory(self, memory: str):
        print(f"Adding memory: {memory}")
        self.memories.append(MemoryItem(memory))

    def remove_memory(self, memory_hash: str):
        print(f"Removing memory with hash: {memory_hash}")
        self.memories = [m for m in self.memories if m.hash() != memory_hash]

    def retrieve_memories(self, query: str, agent_system_prompt: str = None) -> list:
        """
        Retrieves relevant memories by sending all memory hashes (or indices) and a query to another agent.
        return_type: 'hash' or 'index'
        """
        print(f"Retrieving memories for query: {query}")
        # Use indices for memory retrieval
        memory_list = [f"{i}: {m.content}" for i, m in enumerate(self.memories)]
        
        prompt = (
            "You are a memory retrieval agent. Given the following list of memories and a query, "
            f"return ONLY the index of the most relevant memory (or seperated with commas if multiple).\n"
            "Memories:\n" + "\n".join(memory_list) +
            f"\nQuery: {query}\n\nJust output the index(es) as plain text."
        )
        if agent_system_prompt:
            self.client.set_system(agent_system_prompt)
        else:
            self.client.set_system("You are a helpful memory retrieval agent.")
        response = self.client.ask(prompt, temporal=True)
        memories = [self.memories[int(m.strip())] for m in response.split(",")]
        print(memories)
        return memories

if __name__ == "__main__":
    # Example usage
    memory = MemoryAgent()
    memory.add_memory("This is a test memory for testing the memory retrieval system.")
    memory.add_memory("Another memory for testing.")
    memory.add_memory("Happy ghast is added to minecraft in 2025.")
    retrieved_memories = memory.retrieve_memories("minecraft")
    for m in retrieved_memories:
        print(m.content)