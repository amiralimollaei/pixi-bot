from typing import Optional
from .aiohttpapi import APIBase

class AsyncWikimediaAPI(APIBase):
    def __init__(self, base_url: str):
        super().__init__(base=base_url, api_key=None, api_key_env_var=None)

    async def apiphp_request(self, **kwargs):
        return await self.request("api.php", data=kwargs | dict(format="json"))

    async def search(self, srsearch: str):
        return await self.apiphp_request(
            action="query",
            list="search",
            srsearch=srsearch,
        )
    
    async def get_info(self, titles: Optional[str] = None, pageids: Optional[str] = None):
        return await self.apiphp_request(
            action="query",
            titles=titles,
            pageids=pageids,
            prop="info|extracts",
            explaintext="true",
            inprop="url|talkid"
        )
    
    async def get_page(self, page: str = None, pageid: str = None):
        return await self.apiphp_request(
            action="parse",
            page=page,
            pageid=pageid,
            prop="info|extracts|wikitext",
            explaintext="true",
            inprop="url|talkid",
            contentmodel="wikitext"
        )