from pixi.apis import HTTPAPI
from pixi.model.gifs import Gif, GifSearchResult


class AsyncGiphyAPI(HTTPAPI):
    def __init__(self, api_key: str | None = None):
        super().__init__(
            base="https://api.giphy.com/v1/gifs/",
            api_key=api_key,
            api_key_env_var="GIPHY_API_KEY",
        )

    async def search(self, query: str) -> GifSearchResult:
        response = await self.request(
            "search",
            data={"q": query, "lang": "en", "limit": 1},
        )
        if not isinstance(response, dict):
            raise ValueError("GIPHY search returned an invalid response")
        results = response.get("data", [])
        gifs: tuple[Gif, ...] = ()
        if results:
            item = results[0]
            url = item.get("images", {}).get("original", {}).get("url")
            if url:
                gifs = (
                    Gif(
                        url=url,
                        id=item.get("id") or None,
                        title=item.get("title") or None,
                        description=item.get("alt_text") or None,
                        tags=tuple(item.get("tags") or ()),
                        page_url=item.get("url") or None,
                    ),
                )
        return GifSearchResult(results=gifs, attribution="Powered by GIPHY")
