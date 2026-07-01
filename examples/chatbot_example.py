import json
import asyncio

from pixi.chatting import AsyncChatbotInstance, AssistantPersona
from pixi.utils import load_dotenv


async def main():
    while True:
        reference_message = instance.add_message(input("You: "))
        noncall_result = await instance.stream_call(reference_message=reference_message)
        print(f"{noncall_result=}")

if __name__ == "__main__":
    load_dotenv()

    persona = AssistantPersona.from_dict(json.load(open("persona.json", "rb")))
    instance = AsyncChatbotInstance(0, "test")

    async def psudo_send_action(ctx, text):
        print("LLM: " + text)

    async def psudo_note_action(ctx, text):
        print("Thoughts: " + text)

    async def psudo_yeet_action(ctx, text):
        print("Yeet: " + text)

    instance.add_action(
        name="send",
        field_name="message",
        func=psudo_send_action,
        description="sends a message"
    )
    instance.add_action(
        name="note",
        field_name="thoughts",
        func=psudo_note_action,
        description="annotates your thoughts, you must do this before each message e.g., [NOTE: I should be offended and will respond with an offended tone]"
    )
    instance.add_action(
        name="yeet",
        field_name="object",
        func=psudo_yeet_action,
        description="yeets the object"
    )

    print(instance.action_manager.get_prompt())

    asyncio.run(main())
