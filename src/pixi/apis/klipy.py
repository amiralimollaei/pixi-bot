from pixi.apis import HTTPAPI
from pixi.model.gifs import Gif, GifSearchResult


class AsyncKlipyAPI(HTTPAPI):
    def __init__(self, api_key: str | None = None):
        super().__init__(
            base="https://api.klipy.com/v2/",
            api_key=api_key,
            api_key_env_var="KLIPY_API_KEY",
            api_key_key="key",
        )

    async def search(self, query: str) -> GifSearchResult:
        response = await self.request(
            "search",
            data={"q": query, "locale": "en_US", "limit": 1, "media_filter": "gif"},
        )
        if not isinstance(response, dict):
            raise ValueError("KLIPY search returned an invalid response")
        results = response.get("results", [])
        gifs: tuple[Gif, ...] = ()
        if results:
            item = results[0]
            url = item.get("media_formats", {}).get("gif", {}).get("url")
            if url:
                gifs = (
                    Gif(
                        url=url,
                        id=item.get("id") or None,
                        title=item.get("title") or None,
                        description=item.get("content_description") or None,
                        tags=tuple(item.get("tags") or ()),
                        page_url=item.get("itemurl") or item.get("url") or None,
                    ),
                )
        return GifSearchResult(results=gifs, attribution="Powered by KLIPY")
