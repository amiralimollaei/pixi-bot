import re
from typing import Iterator, AsyncGenerator

from pixi.client import Callback


# constants

COMMAND_PATTERN = re.compile(r"\[(\w+)(?::\s?(.*))?]")


class AsyncCommandManager:
    def __init__(self):
        self.commands: dict = dict()

    def add_command(self, name: str, field_name: str, function: Callback, description: str = None):
        assert name is not None
        assert function is not None
        assert field_name is not None
        self.commands.update({name.lower(): dict(
            function=function,
            field_name=field_name,
            description=description,
        )})

    def get_prompt(self):
        return "\n".join([f"- [{name}:<{func.get('field_name')}>]: {desc}" for name, func in self.commands.items() if (desc := func.get("description"))])

    # consumes commands and runs them automatically
    async def stream_commands(self, stream: Iterator | AsyncGenerator):
        inside_command = 0
        command_str = ""
        
        async def process(char):
            nonlocal inside_command
            nonlocal command_str
            
            result = None

            if char == "[":
                inside_command += 1

            if inside_command != 0:
                command_str += char
            else:
                result = char
            
            if char == "]":
                inside_command -= 1
                
                if inside_command == 0:
                    matches = COMMAND_PATTERN.match(command_str)
                    if not matches:
                        raise SyntaxError(f"Invalid Command: `{command_str}`")
                    groups = matches.groups()

                    command_name = groups[0]
                    command_data = matches.groups()[1] if len(groups) >= 2 else None

                    command = self.commands.get(command_name.lower())
                    if command is not None:
                        await command["function"](command_data)
                    else:
                        raise NotImplementedError(f"The command `{command_name}` is not implemented.")

                    command_str = ""
 
            return result
        
        if isinstance(stream, Iterator):
            for char in stream:
                result = await process(char)
                if result:
                    yield result
        elif isinstance(stream, AsyncGenerator):
            async for char in stream:
                result = await process(char)
                if result:
                    yield result
        else:
            raise TypeError(f"expected `stream` to be an Iterator or an AsyncGenerator but got `{type(stream)}`!")


if __name__ == "__main__":
    command_maneger = AsyncCommandManager()
    async def send(x):
        print(f"SEND: {x}")
    
    command_maneger.add_command(
        name="send",
        field_name="message",
        function=send, description="sends a message"
    )

    print(command_maneger.get_prompt())

    test_text = "\n".join([
        "[SEND: This is a test!]",
        "Nested command test [SEND: This is a [test]!]",
        "The following command does not exist and will result in an error: [NONE]"
    ])
    
    print(test_text)

    import asyncio

    async def main():
        async for char in command_maneger.stream_commands(iter(test_text)):
            print(char, end="")

    asyncio.run(main())