from typing import Optional
import asyncio
import os

import aiohttp


BASE_URL = "https://api.giphy.com/v1/"


class AsyncGiphyAPI:
    def __init__(self, API_KEY: Optional[str] = None):
        self.connector = aiohttp.TCPConnector(limit=32)
        self.api_key = API_KEY or os.getenv("GIPHY_API_KEY")
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(BASE_URL, connector=self.connector)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.session.close()

    async def request(self, url: str, data: Optional[dict] = None):
        params = dict(api_key=self.api_key)
        if data:
            for key, value in data.items():
                if value is None:
                    continue
                params.update({key: value})
        print(params)
        resp = await self.session.get(url, params=params)
        result = await resp.json()
        await resp.release()
        return result

    async def search(self,
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

if __name__ == "__main__":
    from dotenv import load_dotenv; load_dotenv()
    async def main():
        async with AsyncGiphyAPI() as api:
            resp = await api.search("panda")
            data = resp.get("data")
            for gif in data:
                print(gif.get("url"))
                print(gif.get("slug"))
                print(gif.get("title"))
                if id:=gif.get("id"):
                    print(f"https://i.giphy.com/{id}.webp")
    asyncio.run(main())