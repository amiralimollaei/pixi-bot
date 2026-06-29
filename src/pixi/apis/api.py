import json
import os
from typing import Optional

import httpx


class APIBase:
    """
    Base class for asynchronous API clients using httpx.
    This class provides a method to make GET requests to an API endpoint with optional parameters and an API key.
    It requires a base URL for the API and optionally an API key that can be provided either directly or through an environment variable.

    Attributes:
        base (str): The base URL of the API.
        api_key_env_var (str): The name of the environment variable containing the API key.
        api_key (Optional[str]): The API key to use for requests, if not provided through the environment variable.

    Raises:
        KeyError: If the base URL is None or if the API key is not provided and the environment variable is not set.
    """

    def __init__(self, base: str | None , api_key_env_var: Optional[str] = None, api_key: Optional[str] = None, api_key_key: str = "api_key"):
        assert base, f"base url is not valid, got \"{base}\""
        self.base = base

        if api_key_env_var:
            api_key = api_key or os.getenv(api_key_env_var)
            if api_key is None:
                raise KeyError(f"{api_key_env_var} must be set in environment variables or passed as an argument.")

        self.api_key = api_key
        self.api_key_key = api_key_key

        self.client = httpx.AsyncClient(trust_env=False)

    async def request(self, url: str, data: Optional[dict] = None) -> str | dict | list:
        api_key_data = {self.api_key_key: self.api_key} if self.api_key else dict()
        if data is None:
            data = api_key_data
        else:
            data = data | api_key_data
        params = {k: v for k, v in data.items() if v is not None}

        resp = await self.client.get(os.path.join(self.base, url), params=params)
        content = resp.read().strip(b"\n").strip(b" ")
        if content.startswith(b"{") and content.endswith(b"}"):
            return json.loads(content)
        elif content.startswith(b"[") and content.endswith(b"]"):
            return json.loads(content)
        else:
            return content.decode("utf-8")
