import asyncio
import json
import unittest

from pixi.openai import _stream_chat_completions


class ChatStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def read_completion(self, fragments: list[tuple[float, bytes]]) -> str:
        handlers = set()

        async def handle(reader, writer):
            task = asyncio.current_task()
            handlers.add(task)
            try:
                headers = await reader.readuntil(b"\r\n\r\n")
                for header in headers.split(b"\r\n")[1:]:
                    if header.lower().startswith(b"content-length:"):
                        await reader.readexactly(int(header.split(b":", 1)[1]))
                size = sum(len(fragment) for _, fragment in fragments)
                writer.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/event-stream\r\n"
                    b"Connection: close\r\n"
                    + f"Content-Length: {size}\r\n\r\n".encode()
                )
                await writer.drain()
                for delay, fragment in fragments:
                    await asyncio.sleep(delay)
                    writer.write(fragment)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
                handlers.discard(task)

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            async def consume():
                return "".join([
                    chunk.choices[0].delta.content or ""
                    async for chunk in _stream_chat_completions(
                        f"http://127.0.0.1:{port}/v1", "test-key", {}
                    )
                ])

            return await asyncio.wait_for(consume(), timeout=10)
        finally:
            server.close()
            await server.wait_closed()
            if handlers:
                await asyncio.gather(*handlers)

    @staticmethod
    def event(content: str) -> bytes:
        data = {"choices": [{"delta": {"content": content}}]}
        return ("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode()

    async def test_utf8_characters_can_span_network_chunks(self):
        expected = "café فارسی 👋"
        body = self.event(expected) + b"data: [DONE]\n\n"
        fragments = [(0.005, bytes([byte])) for byte in body]
        self.assertEqual(await self.read_completion(fragments), expected)

    async def test_stream_can_pause_longer_than_five_seconds(self):
        fragments = [
            (0, self.event("first")),
            (5.5, self.event(" second") + b"data: [DONE]\n\n"),
        ]
        self.assertEqual(await self.read_completion(fragments), "first second")


if __name__ == "__main__":
    unittest.main()
