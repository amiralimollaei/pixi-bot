from typing import Optional

from .api import APIBase


BASE_URL = "https://g.tenor.com/v1/"


class AsyncTenorAPI(APIBase):

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(base=BASE_URL, api_key=api_key, api_key_env_var="TENOR_API_KEY", api_key_key="key")

    async def search(
        self,
        q: str,
        limit: Optional[int] = None,
        locale: Optional[str] = None,
        media_filter: Optional[str] = "minimal",
    ):
        return await self.request("search", data=dict(
            q=q,
            limit=limit,
            locale=locale,
            media_filter=media_filter,
        ))
