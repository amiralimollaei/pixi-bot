import asyncio
import json

from pixi.ai.chatting import AssistantPersona, AsyncChatbotInstance
from pixi.utils import load_dotenv


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
    while True:
        reference_message = instance.add_message(input("You: "))
        noncall_result = await instance.stream_call(reference_message=reference_message)
        print(f"{noncall_result=}")

if __name__ == "__main__":
    load_dotenv()

    persona = AssistantPersona.from_dict(json.load(open("persona.json", "rb")))
    instance = AsyncChatbotInstance(0, "test")

    instance.add_action(ConsoleSendAction())
    instance.add_action(ConsoleNoteAction())
    instance.add_action(ConsoleYeetAction())

    print(instance.action_manager.get_prompt())

    asyncio.run(main())
