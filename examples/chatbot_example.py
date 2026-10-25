import asyncio
import json
import os

from pixi.ai.chatting.persona import AssistantPersona
from pixi.apis.openai.adapter import OpenAIChatModel
from pixi.bot.conversations import AsyncChatbotInstance
from pixi.cli import load_dotenv
from pixi.model.config import OpenAIAuthConfig, OpenAILanguageModelConfig
from pixi.storage.messages import MessagesDiskStorage
from pixi.storage.paths import PixiPaths, copy_default_resources


class ConsoleSendAction:
    name = "send"
    field_name = "message"
    description = "sends a message"
    label = "LLM"
    is_visible = True

    @classmethod
    def should_register(cls, instance):
        return True

    @classmethod
    async def call(cls, context, value):
        print(f"{cls.label}: {value}")


class ConsoleNoteAction(ConsoleSendAction):
    name = "note"
    field_name = "thoughts"
    description = "annotates your thoughts, you must do this before each message e.g., [NOTE: I should be offended and will respond with an offended tone]"
    label = "Thoughts"
    is_visible = False


class ConsoleYeetAction(ConsoleSendAction):
    name = "yeet"
    field_name = "object"
    description = "yeets the object"
    label = "Yeet"


async def main():
    load_dotenv()
    PixiPaths.set_root("~/.pixi-example/")
    copy_default_resources()
    model = OpenAILanguageModelConfig(id=os.environ["OPENAI_MODEL"], max_context=16192)
    auth = OpenAIAuthConfig(
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.environ["OPENAI_API_KEY"],
    )
    with PixiPaths.persona().open(encoding="utf-8") as resource:
        persona = AssistantPersona.from_dict(json.load(resource))
    with PixiPaths.system_prompt().open(encoding="utf-8") as resource:
        system_prompt_template = resource.read()
    with PixiPaths.examples().open(encoding="utf-8") as resource:
        examples = resource.read()

    instance = AsyncChatbotInstance(
        "console",
        "example",
        chat_model=OpenAIChatModel(auth, model),
        model=model,
        store=MessagesDiskStorage(PixiPaths.messages()),
        persona=persona,
        system_prompt_template=system_prompt_template,
        examples=examples,
        actions=(ConsoleSendAction(), ConsoleNoteAction(), ConsoleYeetAction()),
    )
    print(instance.action_manager.get_prompt())
    while True:
        try:
            text = input("You: ")
        except EOFError:
            break
        reference_message = instance.add_message(text)
        noncall_result = await instance.stream_call(reference_message=reference_message)
        print(f"{noncall_result=}")


if __name__ == "__main__":
    asyncio.run(main())
