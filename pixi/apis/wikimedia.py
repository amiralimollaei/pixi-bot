from dataclasses import dataclass
from typing import Optional

from .aiohttpapi import APIBase


@dataclass
class WikiMediaSearchResult:
    title: str
    snippet: Optional[str] = None,
    url: Optional[str] = None,
    description: Optional[str] = None,
    pageid: Optional[str] = None,


class AsyncWikimediaAPI(APIBase):
    def __init__(self, base_url: str):
        super().__init__(base=base_url, api_key=None, api_key_env_var=None)

    async def apiphp_request(self, **kwargs) -> dict | list:
        return await self.request("api.php", data=kwargs | dict(format="json", formatversion=2, redirects="resolve"))

    async def indexphp_request(self, **kwargs) -> str:
        return await self.request("index.php", data=kwargs)

    async def search(self, srsearch: str) -> list[WikiMediaSearchResult]:
        resp = await self.apiphp_request(
            action="query",
            origin="*",
            generator="search",
            gsrsearch=srsearch,
            gsrlimit=5,
            gsrinfo="",
            gsrprop="snippet",
            prop="extracts|info",
            inprop="url",
            exintro=1,
            explaintext=1,
            exchars=500,
            exlimit=3
        )

        results = []
        for page_data in resp.get("query", {}).get("pages", []):
            title = page_data.get("title")
            snippet = page_data.get("snippet")
            extract = page_data.get("extract")
            pageid = page_data.get("pageid")
            fullurl = page_data.get("fullurl")
            assert title
            results.append(WikiMediaSearchResult(
                title=title,
                snippet=snippet,
                description=extract,
                pageid=pageid,
                url=fullurl
            ))

        return results

    async def opensearch(self, search: str) -> list[WikiMediaSearchResult]:
        result = await self.apiphp_request(
            action="opensearch",
            search=search,
        )
        print(result)
        results = []
        for title, desc, url in zip(result[1], result[2], result[3]):
            results.append(WikiMediaSearchResult(title=title, url=url, description=desc or None))

        return results

    async def get_raw(self, title: str) -> str:
        return await self.indexphp_request(
            title=title,
            action="raw",
        )

    async def get_info(self, titles: Optional[str] = None, pageids: Optional[str] = None):
        return await self.apiphp_request(
            action="query",
            titles=titles,
            pageids=pageids,
            prop="extracts|description|info",
            list="",
            redirects=1,
            exsentences=10,
            exintro=1,
            explaintext=1,
            inprop="url"
        )

    async def get_page(self, page: str = None, pageid: str = None):
        return await self.apiphp_request(
            action="parse",
            page=page,
            pageid=pageid,
            prop="wikitext",
            contentmodel="wikitext"
        )
