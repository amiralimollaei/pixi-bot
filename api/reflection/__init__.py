from api.utils import ImageCache
from enums import Platform

# helper functions:

def strip_message(message: str):
    remove_starts = ["!pixi", "!pix", "!p", "@pixiaibot", "@pixiai", "@pixi", "@pixibot"]
    for rs in remove_starts:
        if message.lower().startswith(rs):
            message = message[len(rs):]
    return message

class ReflectionAPI:
    class Forbidden(Exception):
        def __init__(self, msg: str, platform: Platform, *args):
            super().__init__(*args)
            self.platform = platform
            self.msg = msg
    
    def __init__(self, platform: Platform):
        assert type(platform) == Platform
        self.platform = platform
        
        match platform:
            case Platform.DISCORD:
                from .discord import ReflectionAPI
                self._ref = ReflectionAPI()
            case Platform.TELEGRAM:
                from .telegram import ReflectionAPI
                self._ref = ReflectionAPI()

    def get_identifier_from_message(self, message) -> str:
        return self._ref.get_identifier_from_message(message)
    
    def get_realtime_data(self, message) -> dict:
        return self._ref.get_realtime_data(message)

    async def send_status_typing(self, message):
        return await self._ref.send_status_typing(message)
    
    async def send_reply(self, message, text: str, delay: int = None) -> bool:
        return await self._ref.send_reply(message, text, delay)
    
    def get_sender_id(self, message) -> int:
        return self._ref.get_sender_id(message)
    
    def get_sender_name(self, message) -> str:
        return self._ref.get_sender_name(message)
        
    def is_message_from_the_bot(self, message) -> bool:
        return self._ref.is_message_from_the_bot(message)
    
    def is_message_from_the_bot(self, message) -> bool:
        return self._ref.is_message_from_the_bot(message)
    
    async def fetch_attachment_images(self, message) -> list[ImageCache]:
        return await self._ref.fetch_attachment_images(message)
    
    def get_message_text(self, message) -> str:
        return self._ref.get_message_text(message)
    
    async def fetch_message_reply(self, message):
        return await self._ref.fetch_message_reply(message)
    
    def is_bot_mentioned(self, message) -> bool:
        return self._ref.is_bot_mentioned(message)
    
    def is_inside_dm(self, message) -> bool:
        return self._ref.is_inside_dm(message)
    
    async def is_dm_or_admin(self, interaction) -> bool:
        return self._ref.is_dm_or_admin(interaction)

if __name__ == "__main__":
    ReflectionAPI(Platform.DISCORD)