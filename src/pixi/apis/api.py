import json
import os
from abc import ABC, abstractmethod
from typing import Optional


def _build_url(base: str, url: str) -> str:
    base = base.rstrip("/")
    seg = url.lstrip("/")
    return f"{base}/{seg}" if seg else base


class AbstractAPI(ABC):
    @abstractmethod
    async def get(self, url: str, params: Optional[dict]) -> "AbstractResponse":
        ...


class AbstractResponse(ABC):
    @abstractmethod
    async def read(self) -> bytes:
        ...

    async def _read(self) -> bytes:
        return await self.read()

    async def text(self) -> str:
        return (await self._read()).decode("utf-8", errors="replace")


class _AiohttpAPI(AbstractAPI):
    def __init__(self):
        import aiohttp  # pyright: ignore[reportMissingImports]
        self._session = aiohttp.ClientSession()

    async def get(self, url: str, params: Optional[dict]) -> AbstractResponse:
        resp = await self._session.get(url, params=params)
        return _AiohttpResponse(resp)


class _AiohttpResponse(AbstractResponse):
    def __init__(self, response: "aiohttp.ClientResponse"):  # pyright: ignore[reportUndefinedVariable]
        self._response = response

    async def read(self) -> bytes:
        return await self._response.read()


class _HttpxAPI(AbstractAPI):
    def __init__(self):
        import httpx  # pyright: ignore[reportMissingImports]
        self._client = httpx.AsyncClient(trust_env=False)

    async def get(self, url: str, params: Optional[dict]) -> AbstractResponse:
        return _HttpxResponse(await self._client.get(url, params=params))


class _HttpxResponse(AbstractResponse):
    def __init__(self, response: "httpx.Response"):  # pyright: ignore[reportUndefinedVariable]
        self._response = response
        self._response = response

    async def read(self) -> bytes:
        return self._response.content


class APIBase:
    def __init__(self, base: str | None, api_key_env_var: Optional[str] = None, api_key: Optional[str] = None, api_key_key: str = "api_key"):
        assert base, f"base url is not valid, got \"{base}\""
        self.base = base

        if api_key_env_var:
            api_key = api_key or os.getenv(api_key_env_var)
            if api_key is None:
                raise KeyError(f"{api_key_env_var} must be set in environment variables or passed as an argument.")

        self.api_key = api_key
        self.api_key_key = api_key_key

        self.api = None

    def _select_api(self) -> AbstractAPI:
        try:
            return _AiohttpAPI()
        except ImportError:
            return _HttpxAPI()  # type: ignore[return-value]

    async def request_raw(self, url: str, data: Optional[dict] = None) -> bytes:
        if self.api is None:
            self.api = self._select_api()

        full_url = _build_url(self.base, url)
        api_key_data = {self.api_key_key: self.api_key} if self.api_key else {}
        if data is None:
            data = api_key_data
        else:
            data = {**data, **api_key_data}
        params = {k: v for k, v in data.items() if v is not None}

        response = await self.api.get(full_url, params=params)
        content = await response.read()
        return content.strip(b"\n").strip(b" ")

    async def request(self, url: str, data: Optional[dict] = None) -> str | dict | list:
        text = await self.request_raw(url=url, data=data)
        if text.startswith(b"{") and text.endswith(b"}"):
            return json.loads(text)
        elif text.startswith(b"[") and text.endswith(b"]"):
            return json.loads(text)
        else:
            return text.decode("utf-8")
