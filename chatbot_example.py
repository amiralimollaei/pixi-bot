import json
from pixi.chatbot import AssistantPersona, ChatbotInstance
from pixi.utils import load_dotenv


if __name__ == "__main__":
    load_dotenv()
    
    persona = AssistantPersona.from_dict(json.load(open("persona.json", "rb")))
    instance = ChatbotInstance(0, persona, "test")
    
    def psudo_send_command(text):
        print("LLM: " + text)

    def psudo_note_command(text):
        print("Thoughts: " + text)
    
    instance.add_command(
        name="send",
        field_name="message",
        function=psudo_send_command,
        descriptioon="sends a message"
    )
    instance.add_command(
        name="note",
        field_name="thoughts",
        function=psudo_note_command,
        descriptioon="annotates your thoughts, you must do this before each message e.g., [NOTE: I should be offended and will respond with an offended tone]"
    )
    
    print(instance.command_manager.get_prompt())
    
    import asyncio
    
    async def main():
        while True:
            query = input("You: ")
            noncall_result = await instance.stream_call(query)
            print(f"{noncall_result=}")
    
    asyncio.run(main())
    