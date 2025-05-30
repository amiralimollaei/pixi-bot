import os
from typing import Optional

import aiohttp


class APIBase:
    """
    Base class for asynchronous API clients using aiohttp.
    This class provides a method to make GET requests to an API endpoint with optional parameters and an API key.
    It requires a base URL for the API and optionally an API key that can be provided either directly or through an environment variable.
    
    Attributes:
        base (str): The base URL of the API.
        api_key_env_var (str): The name of the environment variable containing the API key.
        api_key (Optional[str]): The API key to use for requests, if not provided through the environment variable.
        
    Raises:
        KeyError: If the base URL is None or if the API key is not provided and the environment variable is not set.
    """

    def __init__(self, base, api_key_env_var: str = None, api_key: Optional[str] = None, ):
        self.base = base
        if self.base is None:
            raise KeyError("base must not be None.")
        
        if api_key_env_var:
            api_key = api_key or os.getenv(api_key_env_var)
            if api_key is None:
                raise KeyError(f"{api_key_env_var} must be set in environment variables or passed as an argument.")

        self.api_key = api_key

    async def request(self, url: str, data: Optional[dict] = None):
        data = data | dict(api_key=self.api_key)
        params = {k: v for k, v in data.items() if v is not None}
        async with aiohttp.ClientSession(self.base) as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()