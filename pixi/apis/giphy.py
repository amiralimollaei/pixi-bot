from typing import Optional

from .api import APIBase


BASE_URL = "https://api.giphy.com/v1/"


class AsyncGiphyAPI(APIBase):

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(base=BASE_URL, api_key=api_key, api_key_env_var="GIPHY_API_KEY")

    async def search(
        self,
        q: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        rating: Optional[str] = None,
        lang: Optional[str] = None,
        random_id: Optional[str] = None,
        bundle: Optional[str] = None,
        country_code: Optional[str] = None,
        region: Optional[str] = None,
    ):
        return await self.request("gifs/search", data=dict(
            q=q,
            limit=limit,
            offset=offset,
            rating=rating,
            lang=lang,
            random_id=random_id,
            bundle=bundle,
            country_code=country_code,
            region=region,
        ))
