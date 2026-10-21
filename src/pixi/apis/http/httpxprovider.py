from types import CoroutineType, TracebackType
from typing import Any, AsyncIterator, Optional

import httpx

from . import HTTPClient, ClientResponse, build_url


class HTTPXClientResponse(ClientResponse):
    def __init__(self, context: CoroutineType[Any, Any, httpx.Response]):
        self._context = context
        self._response = None

    async def __aenter__(self) -> "ClientResponse":
        try:
            self._response = await self._context
        except httpx.RequestError as e:
            raise ConnectionError(str(e)) from e
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None):
        if self._response:
            await self._response.aclose()

    @property
    def status(self) -> int:
        assert self._response is not None, "Response is not initialized. Use 'async with' to initialize it."
        return self._response.status_code

    async def json(self) -> dict:
        assert self._response is not None, "Response is not initialized. Use 'async with' to initialize it."
        try:
            await self._response.aread()
        except httpx.RequestError as e:
            raise ConnectionError(str(e)) from e
        return self._response.json()

    async def text(self) -> str:
        assert self._response is not None, "Response is not initialized. Use 'async with' to initialize it."
        try:
            await self._response.aread()
        except httpx.RequestError as e:
            raise ConnectionError(str(e)) from e
        return self._response.text

    @property
    def content(self) -> AsyncIterator[bytes]:
        return self._iter_content()

    async def _iter_content(self) -> AsyncIterator[bytes]:
        assert self._response is not None, "Response is not initialized. Use 'async with' to initialize it."
        try:
            async for chunk in self._response.aiter_bytes():
                yield chunk
        except httpx.RequestError as e:
            raise ConnectionError(str(e)) from e


class HTTPXProvider(HTTPClient):
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = None

    async def __aenter__(self):
        if self.client is None:
            self.client = httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(5.0, read=300.0),
            )
        return self

    def get(self, endpoint: str, json: Optional[dict] = None, headers: Optional[dict] = None, params: Optional[dict] = None) -> ClientResponse:
        return self._request("GET", endpoint, json, headers, params)

    def post(self, endpoint: str, json: Optional[dict] = None, headers: Optional[dict] = None, params: Optional[dict] = None) -> ClientResponse:
        return self._request("POST", endpoint, json, headers, params)

    def _request(self, method: str, endpoint: str, json: Optional[dict], headers: Optional[dict], params: Optional[dict]) -> ClientResponse:
        assert self.client is not None, "HTTPXProvider client is not initialized. Use 'async with' to initialize it."
        url = httpx.URL(build_url(self.base_url, endpoint))
        if params:
            url = url.copy_merge_params(params)
        request = self.client.build_request(method, url, json=json, headers=headers)
        context = self.client.send(request, stream=True)
        return HTTPXClientResponse(context)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client is not None:
            await self.client.aclose()
            self.client = None
