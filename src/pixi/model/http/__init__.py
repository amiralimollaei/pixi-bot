
from types import TracebackType
from typing import AsyncIterator, Optional, Protocol


class HTTPClient(Protocol):
    """Context-managed transport whose get/post methods return request contexts.

    Callers own returned responses and must use them as async context managers.
    Request and body-read network/timeout failures raise ConnectionError with
    the backend exception chained; HTTP error statuses remain on the response.

    Empty or slash-only endpoints preserve the base URL unchanged. Request
    parameters preserve existing URL query parameters, replacing matching keys.
    """

    def __init__(self, base_url: str): ...

    async def __aenter__(self) -> "HTTPClient": ...

    async def __aexit__(self, exc_type: type[BaseException] | None,
                        exc: BaseException | None, tb: TracebackType | None): ...

    def get(self, endpoint: str, json: Optional[dict] = None, headers: Optional[dict]
            = None, params: Optional[dict] = None) -> "ClientResponse": ...

    def post(self, endpoint: str, json: Optional[dict] = None, headers: Optional[dict]
             = None, params: Optional[dict] = None) -> "ClientResponse": ...


class ClientResponse(Protocol):
    """Caller-owned response, closed when its async context exits.

    json() and text() read the body on demand. content streams bytes without
    buffering the entire response; chunk boundaries are backend-dependent.
    """

    async def __aenter__(self) -> "ClientResponse": ...

    async def __aexit__(self, exc_type: type[BaseException] | None,
                        exc: BaseException | None, tb: TracebackType | None): ...

    @property
    def status(self) -> int: ...

    async def json(self) -> dict: ...

    async def text(self) -> str: ...

    @property
    def content(self) -> AsyncIterator[bytes]: ...


def build_url(base_url: str, endpoint: str) -> str:
    """Append an endpoint, preserving the exact base URL when it is empty."""
    segment = endpoint.lstrip("/")
    return f"{base_url.rstrip('/')}/{segment}" if segment else base_url


def get_http_client_provider() -> type[HTTPClient]:
    try:
        import httpx
        provider_name = "httpx"
    except ImportError:
        try:
            import aiohttp
            provider_name = "aiohttp"
        except ImportError:
            raise ImportError("Neither httpx nor aiohttp is installed. Please install one of them.")

    if provider_name == "httpx":
        from .httpxprovider import HTTPXProvider
        return HTTPXProvider
    elif provider_name == "aiohttp":
        from .aiohttpprovider import AIOHTTPProvider
        return AIOHTTPProvider
    else:
        raise ValueError(f"Unknown provider name: {provider_name}")
