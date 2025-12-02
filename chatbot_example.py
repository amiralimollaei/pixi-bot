import json
import asyncio

from pixi.chatbot import AsyncChatbotInstance
from pixi.chatbot import AssistantPersona
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

    async def psudo_send_command(text):
        print("LLM: " + text)

    async def psudo_note_command(text):
        print("Thoughts: " + text)

    async def psudo_yeet_command(text):
        print("Yeet: " + text)

    instance.add_command(
        name="send",
        field_name="message",
        func=psudo_send_command,
        description="sends a message"
    )
    instance.add_command(
        name="note",
        field_name="thoughts",
        func=psudo_note_command,
        description="annotates your thoughts, you must do this before each message e.g., [NOTE: I should be offended and will respond with an offended tone]"
    )
    instance.add_command(
        name="yeet",
        field_name="object",
        func=psudo_yeet_command,
        description="yeets the object"
    )

    print(instance.command_manager.get_prompt())

    asyncio.run(main())
