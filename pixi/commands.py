import logging

from dataclasses import dataclass

from .utils import CoroutineQueueExecutor
from .typing import AsyncFunction, Optional, Iterator, Generator, AsyncIterator, AsyncGenerator
from .chatting import ChatMessage


@dataclass
class AsyncCommand:
    name: str
    field_name: str
    function: AsyncFunction
    description: Optional[str] = None

    # TODO: implement callbacks for when we enter the command (after the command name) and when
    # we leave the command (right after the command is completed btu before executing the command)
    enter_callback: Optional[AsyncFunction] = None
    leave_callback: Optional[AsyncFunction] = None

    def get_syntax(self):
        desc = self.description or "no description"
        return f"[{self.name}:<{self.field_name}>]: {desc}"

    async def __call__(self, *args, **kwds):
        return await self.function(*args, **kwds)

    def __str__(self):
        return f"<async-function {self.name}>"


class AsyncCommandManager:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self.commands: dict[str, AsyncCommand] = dict()

    def _add_command(self, command: AsyncCommand):
        assert command is not None
        self.commands.update({command.name.lower(): command})

    def add_command(self, name: str, field_name: str, function: AsyncFunction, description: Optional[str] = None):
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

    async def execute_command(self, command_str: str, reference_message: Optional[ChatMessage] = None):
        command_content = command_str[1:-1]
        seperator_idx = None
        if ":" in command_str:
            seperator_idx = command_content.index(":")

        if seperator_idx:
            command_name = command_content[:seperator_idx].strip()
            command_data = command_content[seperator_idx+1:].strip()
        else:
            command_name = command_content
            command_data = None

        maybe_command_fn = self.commands.get(command_name.lower())
        if maybe_command_fn is None:
            self.logger.error(f"The command `{command_name}` is not implemented.")
            return

        return await maybe_command_fn(reference_message, command_data)

    async def stream_commands(self, stream: Iterator | Generator | AsyncGenerator | AsyncGenerator, reference_message: ChatMessage):
        """
        Consumes commands and runs them automatically
        """
        inside_command = 0  # counts the number of "[" characters minus the number of "]" characters
        command_str = ""
        
        async with CoroutineQueueExecutor() as queue:
            async def process(char):
                nonlocal inside_command
                nonlocal command_str

                result = None

                # the opening of the command
                if char == "[":
                    inside_command += 1

                if inside_command != 0:
                    command_str += char
                else:
                    result = char

                # the closing of the command
                if char == "]":
                    inside_command -= 1

                    # if the command is fully captured
                    if inside_command == 0:
                        # run command without blocking the stream
                        await queue.add_to_queue(self.execute_command(
                            command_str=command_str,
                            reference_message=reference_message
                        ))
                        command_str = ""

                return result

            if isinstance(stream, (Iterator, Generator)):
                for char in stream:
                    result = await process(char)
                    if result:
                        yield result
            elif isinstance(stream, (AsyncIterator, AsyncGenerator)):
                async for char in stream:
                    result = await process(char)
                    if result:
                        yield result
            else:
                raise TypeError(
                    f"expected `stream` to be an Iterator, Generator, AsyncIterator or AsyncGenerator but got `{type(stream)}`!")