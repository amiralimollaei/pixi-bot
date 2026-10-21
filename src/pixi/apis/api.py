import json
import os
from typing import Optional

from .http import build_url, get_http_client_provider

HTTPClient = get_http_client_provider()


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

    async def request_raw(self, url: str, data: Optional[dict] = None) -> bytes:
        full_url = build_url(self.base, url)
        api_key_data = {self.api_key_key: self.api_key} if self.api_key else {}
        if data is None:
            data = api_key_data
        else:
            data = {**data, **api_key_data}
        params = {k: v for k, v in data.items() if v is not None}

        content = b""
        async with HTTPClient(self.base) as client:
            async with client.get(url, params=params) as response:
                if response.status // 100 != 2:
                    text = await response.text()
                    # TODO: raise a more specific exception with the response content
                    raise RuntimeError(f"Request to {full_url} failed with status {response.status}: {text}")
                async for chunk in response.content:
                    content += chunk
        return content.strip(b"\n").strip(b" ")

    async def request(self, url: str, data: Optional[dict] = None) -> str | dict | list:
        text = await self.request_raw(url=url, data=data)
        if text.startswith(b"{") and text.endswith(b"}"):
            return json.loads(text)
        elif text.startswith(b"[") and text.endswith(b"]"):
            return json.loads(text)
        else:
            return text.decode("utf-8")
