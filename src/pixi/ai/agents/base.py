from ..chatting.client import AsyncChatClient


class AgentBase:
    def __init__(self, *, client: AsyncChatClient | None = None, **client_kwargs):
        self.client = client or AsyncChatClient(**client_kwargs)


    def format_query(self, query: str):
        return query
    
    async def execute_query(self, query: str, temporal=True) -> str | None:
        response = ""
        async for char in self.client.stream_ask(self.format_query(query), temporal=temporal):
            response += char
        return response.strip()