from types import TracebackType
from typing import AsyncIterator, Optional

import aiohttp
from aiohttp.client import _RequestContextManager
from yarl import URL

from . import HTTPClient, ClientResponse, build_url


class AIOHTTPClientResponse(ClientResponse):
    def __init__(self, context: _RequestContextManager):
        self._context = context
        self._response = None

    async def __aenter__(self) -> "ClientResponse":
        try:
            self._response = await self._context
        except (aiohttp.ClientError, TimeoutError) as e:
            raise ConnectionError(str(e)) from e
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None):
        if self._response is not None:
            await self._response.__aexit__(exc_type, exc, tb)

    @property
    def status(self) -> int:
        assert self._response is not None, "Response is not initialized. Use 'async with' to initialize it."
        return self._response.status

    async def json(self) -> dict:
        assert self._response is not None, "Response is not initialized. Use 'async with' to initialize it."
        try:
            return await self._response.json()
        except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError, TimeoutError) as e:
            raise ConnectionError(str(e)) from e

    async def text(self) -> str:
        assert self._response is not None, "Response is not initialized. Use 'async with' to initialize it."
        try:
            return await self._response.text()
        except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError, TimeoutError) as e:
            raise ConnectionError(str(e)) from e

    @property
    def content(self) -> AsyncIterator[bytes]:
        return self._iter_content()

    async def _iter_content(self) -> AsyncIterator[bytes]:
        assert self._response is not None, "Response is not initialized. Use 'async with' to initialize it."
        try:
            async for chunk in self._response.content:
                yield chunk
        except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError, TimeoutError) as e:
            raise ConnectionError(str(e)) from e


class AIOHTTPProvider(HTTPClient):
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = None

    async def __aenter__(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self

    def get(self, endpoint: str, json: Optional[dict] = None, headers: Optional[dict] = None, params: Optional[dict] = None) -> ClientResponse:
        return self._request("GET", endpoint, json, headers, params)

    def post(self, endpoint: str, json: Optional[dict] = None, headers: Optional[dict] = None, params: Optional[dict] = None) -> ClientResponse:
        return self._request("POST", endpoint, json, headers, params)

    def _request(self, method: str, endpoint: str, json: Optional[dict], headers: Optional[dict], params: Optional[dict]) -> ClientResponse:
        assert self.session is not None, "AIOHTTPProvider session is not initialized. Use 'async with' to initialize it."
        url = URL(build_url(self.base_url, endpoint))
        if params:
            url = url.update_query(params)
        context = self.session.request(method, url, json=json, headers=headers)
        return AIOHTTPClientResponse(context)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session is not None:
            await self.session.close()
            self.session = None
