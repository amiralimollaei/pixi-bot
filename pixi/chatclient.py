import logging
import re
import os
import json
from types import CoroutineType
from typing import Any, Awaitable, Callable, Optional

from openai import AsyncOpenAI

from .chatting import FunctionCall, ChatRole, ChatMessage
from .utils import exists


AsyncFunction = Callable[..., CoroutineType]

DEFAULT_BASE_URL = "https://api.deepinfra.com/v1/openai"
DEFAULT_MODEL = "google/gemini-2.5-flash"

MAX_LENGTH = 32000
THINK_PATTERN = re.compile(r"[`\s]*[\[\<]*think[\>\]]*([\s\S]*?)[\[\<]*\/think[\>\]]*[`\s]*")


class AsyncChatClient:
    def __init__(self, messages: Optional[list[ChatMessage]] = None, model: Optional[str] = None, base_url: Optional[str] = None, log_tool_calls: bool = False):
        if messages is not None:
            assert isinstance(
                messages, list), f"expected messages to be of type `list[RoleMessage]` or be None, but got `{messages}`"
            for m in messages:
                assert isinstance(
                    m, ChatMessage), f"expected messages to be of type `list[RoleMessage]` or be None, but at least one element in the list is not of type `RoleMessage`, got `{messages}`"
        self.base_url = base_url or DEFAULT_BASE_URL
        assert exists(self.base_url), f"base_url must be set, but got {self.base_url}"
        assert isinstance(self.base_url, str), f"base_url must be a string, but got {self.base_url}"
        self.model = model or DEFAULT_MODEL
        assert exists(self.model), f"model must be set, but got {self.model}"
        assert isinstance(self.model, str), f"model must be a string, but got {self.model}"
        self.messages = messages or []
        self.log_tool_calls = log_tool_calls
        self.session = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY")
                                   or os.getenv("DEEPINFRA_API_KEY"), base_url=self.base_url)
        self.system_prompt = None
        self.tools: dict = {}
        self.tool_schema: list[dict] = []

    def add_tool(self, name: str, func: AsyncFunction, parameters: dict | None = None, description: str | None = None):
        """
        Register a tool (function) for tool calling.
        name: tool name (string)
        func: (str) -> Awaitable[None]
        parameters: OpenAI tool/function parameters schema (dict)
        description: description of the tool (string)
        """
        self.tools[name] = func
        self.tool_schema.append(dict(
            type="function",
            function=dict(
                name=name,
                description=description or name,
                parameters=parameters or dict(),
            )
        ))

    def set_system(self, prompt: str):
        assert prompt is not None and prompt != ""
        self.system_prompt = prompt

    def add_message(self, message: ChatMessage | str):
        assert message is not None
        if isinstance(message, ChatMessage):
            self.messages.append(message)
        elif isinstance(message, str):
            role = None
            match self.messages[-1].role:
                case ChatRole.SYSTEM:
                    role = ChatRole.ASSISTANT
                case ChatRole.ASSISTANT:
                    role = ChatRole.USER
                case ChatRole.USER:
                    role = ChatRole.ASSISTANT
                case _:
                    role = ChatRole.ASSISTANT
            self.messages.append(ChatMessage(role, message))
        else:
            raise ValueError(f"expected message to be a RoleMessage or a string, but got {message}.")

    async def create_chat_completion(self, stream: bool = False, enable_timestamps: bool = True):
        # If tools are registered, add them to the request
        openai_messages = self.get_openai_messages_dict(enable_timestamps=enable_timestamps)
        kwargs = dict(
            model=self.model,
            messages=openai_messages,
            temperature=0.7,
            # max_tokens=MAX_LENGTH,
            top_p=0.9,
            stream=stream,
        )
        if self.tool_schema:
            kwargs["tools"] = self.tool_schema

        return await self.session.chat.completions.create(**kwargs)  # type: ignore

    async def get_tool_results(self, tool_calls: list):
        """
        Execute tool calls and return results
        """

        function_calls: list[FunctionCall] = []
        for tool_call in tool_calls:
            function = tool_call.function
            function_name = function.name
            function_arguments = json.loads(function.arguments)
            index = tool_call.index
            id = tool_call.id
            function_calls.append(FunctionCall(
                name=function_name,
                arguments=function_arguments,
                index=index,
                id=id
            ))

        results = [ChatMessage(
            ChatRole.ASSISTANT,
            content=None,
            tool_calls=function_calls
        )]
        for fn in function_calls:
            func = self.tools.get(fn.name)
            if func:
                func_args_str = ", ".join([(f"{k}=\"{v}\"" if isinstance(v, str) else f"{k}={v}")
                                          for k, v in fn.arguments.items()])
                try:
                    if self.log_tool_calls:
                        logging.info(f"Calling {fn.name}({func_args_str})...")
                    else:
                        logging.debug(f"Calling {fn.name}({func_args_str})...")
                    result = await func(**fn.arguments)
                    result = json.dumps(result, ensure_ascii=False)
                except Exception as e:
                    logging.exception(f"Error calling tool '{fn.name}({func_args_str})'")
                    result = f"Tool error: {e}"

                if self.log_tool_calls:
                    logging.info(f"Call {fn.name}({func_args_str}): {result}")
                else:
                    logging.debug(f"Call {fn.name}({func_args_str}): {result}")
            else:
                result = f"Tool '{fn.name}' was not found."
                logging.warning(f"Tool '{fn.name}' was not found.")

            results.append(ChatMessage(
                ChatRole.TOOL,
                content=result,
                tool_call_id=fn.id,
            ))
        return results

    async def stream_request(self, verbose: bool = False):
        response = ""
        finish_reason = None
        async for event in await self.create_chat_completion(stream=True):
            if event.choices is None or len(event.choices) == 0:
                continue
            choice = event.choices[0]

            if exists(_tool_calls := choice.delta.tool_calls):
                self.messages += await self.get_tool_results(_tool_calls)

            if choice.finish_reason:
                finish_reason = choice.finish_reason

            if content := choice.delta.content:
                if verbose:
                    print(content, end="", flush=True)
                response += content
                # now yields the response character by character for easier parsing
                for char in content:
                    yield char
        if verbose:
            print()

        if response:
            self.messages.append(ChatMessage(
                role=ChatRole.ASSISTANT,
                content=response
            ))

        if finish_reason == "tool_calls":
            # Recursively call stream_request and yield its results
            async for chunk in self.stream_request():
                yield chunk

    async def request(self, enable_timestamps: bool = True) -> str | None:
        choice = (await self.create_chat_completion(
            stream=False,
            enable_timestamps=enable_timestamps
        )).choices[0]
        if choice.message.content:
            return choice.message.content

        # if tools are called, reslove them and repeat the request recursively
        if tool_calls := choice.message.tool_calls:
            self.messages += await self.get_tool_results(tool_calls)
            return await self.request(enable_timestamps=enable_timestamps)

    def get_openai_messages_dict(self, enable_timestamps: bool = True) -> list[dict]:
        if len(self.messages) == 0:
            return list()

        messages = self.messages.copy()

        final_len = 0
        for cutoff_index, message in enumerate(messages):
            role = message.role
            context = message.content or ""
            final_len += len(role) + len(context) + 3
            if final_len > MAX_LENGTH * 4:
                break
        else:
            cutoff_index = None

        if cutoff_index:
            logging.warning("unable to fit all messages in one request.")
            messages = messages[-cutoff_index:]

        openai_messages = [msg.to_openai_dict(timestamps=enable_timestamps) for msg in messages]
        # add system as the last message to ensure it is in the model's context
        if exists(self.system_prompt):
            openai_messages.append(
                ChatMessage(ChatRole.SYSTEM, self.system_prompt).to_openai_dict(timestamps=enable_timestamps)
            )
        return openai_messages

    async def stream_ask(self, message: str | ChatMessage, temporal: bool = False):
        if temporal:
            orig_messages = self.messages.copy()

        if isinstance(message, str):
            message = ChatMessage(ChatRole.USER, message)
        else:
            assert isinstance(message, ChatMessage), "Message must be a string or a RoleMessage."
        assert message.role == ChatRole.USER, "Message must be from the user."
        self.messages.append(message)

        # TODO: fix the check for think tags opening
        
        start_think = "<think>"
        end_think = "</think>"

        response: str = ""
        is_thinking = False
        async for chunk in self.stream_request():
            response += chunk

            if response.endswith(start_think):
                is_thinking = True
            elif response.endswith(end_think):
                is_thinking = False
                response = THINK_PATTERN.sub("", response)

            if not is_thinking and response.strip() != "":
                yield chunk

        if temporal:
            self.messages = orig_messages # type: ignore

    async def ask(self, message: str | ChatMessage, temporal: bool = False, enable_timestamps: bool = True):
        if temporal:
            orig_messages = self.messages.copy()

        if isinstance(message, str):
            message = ChatMessage(ChatRole.USER, message)
        else:
            assert isinstance(message, ChatMessage), "Message must be a string or a RoleMessage."
        assert message.role == ChatRole.USER, "Message must be from the user."
        self.messages.append(message)

        response = await self.request(enable_timestamps=enable_timestamps)
        if response is not None:
            response = THINK_PATTERN.sub("", response)

        if temporal:
            self.messages = orig_messages # type: ignore
        return response

    def to_dict(self):
        return dict(
            messages=[msg.to_dict() for msg in self.messages]
        )

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            messages=[ChatMessage.from_dict(msg) for msg in data.get("messages") or []],
        )


async def main():
    # Example dummy function hard coded to return the same weather
    # In production, this could be your backend API or an external API
    async def get_current_weather(location):
        """Get the current weather in a given location"""
        print("Calling get_current_weather client side.")
        return 75

    chat = AsyncChatClient()
    chat.add_tool(
        name="get_current_weather",
        func=get_current_weather,
        parameters=dict(
            type="object",
            properties={
                "location": {
                    "type": "string",
                    "description": "The location to get the weather for. (Required)",
                }
            },
            required=[
                "location"
            ],
            additionalProperties=False
        ),
        description="Get the current weather in a given location."
    )

    while True:
        query = input("You: ")
        print("LLM: ", end="")
        response = ""
        async for resp in chat.stream_ask(query):
            response += resp
            print(resp, end="", flush=True)
        print()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
