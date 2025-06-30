from dataclasses import dataclass
from types import CoroutineType
from typing import  Any, Callable, Iterator, AsyncGenerator, Optional, overload

AsyncCallback = Callable[..., CoroutineType]


@dataclass
class AsyncCommand:
    name: str
    field_name: str
    function: AsyncCallback
    description: Optional[str] = None

    # TODO: implement callbacks for when we enter the command (after the command name) and when
    # we leave the command (before executing the command but right after the command is completed)
    enter_callback: Optional[AsyncCallback] = None
    leave_callback: Optional[AsyncCallback] = None

    def get_syntax(self):
        desc = self.description or "no description"
        return f"[{self.name}:<{self.field_name}>]: {desc}"

    async def __call__(self, *args, **kwds):
        return await self.function(*args, **kwds)

    def __str__(self):
        return f"<async-function {self.name}>"


class AsyncCommandManager:
    def __init__(self):
        self.commands: dict[str, AsyncCommand] = dict()

    def _add_command(self, command: AsyncCommand):
        assert command is not None
        self.commands.update({command.name.lower(): command})

    def add_command(self, name: str, field_name: str, function: AsyncCallback, description: str | None = None):
        assert name is not None
        assert function is not None
        assert field_name is not None
        self._add_command(AsyncCommand(
            name=name,
            field_name=field_name,
            function=function,
            description=description,
        ))

    def get_prompt(self):
        return "\n".join(["- "+func.get_syntax() for name, func in self.commands.items()])

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
                    _command_str = command_str[1:-1]
                    seperator_idx = None
                    if ":" in command_str:
                        seperator_idx = _command_str.index(":")

                    command_data = None
                    if seperator_idx:
                        command_name = _command_str[:seperator_idx].strip()
                        command_data = _command_str[seperator_idx+1:].strip()
                    else:
                        command_name = _command_str

                    command = self.commands.get(command_name.lower())
                    if command is not None:
                        await command(command_data)
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
        "Markdown inside command test [SEND: This is a (link)[https://example.com]!]",
        "The following command does not exist and will result in an error: [NONE]"
    ])

    print(test_text)
    print("\n---------\n")

    import asyncio

    async def main():
        async for char in command_maneger.stream_commands(iter(test_text)):
            print(char, end="")

    asyncio.run(main())
