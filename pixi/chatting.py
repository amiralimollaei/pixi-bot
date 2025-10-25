from dataclasses import dataclass
import logging
import re
import os
import json
import time

from openai import AsyncOpenAI, APIError

from .enums import ChatRole
from .utils import CoroutineQueueExecutor, exists, format_time_ago
from .caching import AudioCache, ImageCache
from .typing import AsyncPredicate, AsyncFunction, Optional

# constants

DEFAULT_BASE_URL = "https://api.deepinfra.com/v1/openai"
DEFAULT_MODEL = "google/gemini-2.5-flash"

MAX_CONTEXT_LENGTH = 8000


@dataclass
class FunctionCall:
    name: str
    index: int
    id: str
    arguments: Optional[dict] = None

    def to_dict(self) -> dict:
        return dict(
            name=self.name,
            arguments=self.arguments,
            index=self.index,
            id=self.id
        )

    def to_openai_dict(self) -> dict:
        return dict(
            type="function",
            id=self.id,
            function=dict(
                name=self.name,
                arguments=json.dumps(self.arguments, ensure_ascii=False)
            )
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'FunctionCall':
        return cls(
            name=data["name"],
            index=data["index"],
            id=data["id"],
            arguments=data.get("arguments"),
        )


@dataclass
class PartialFunctionCall:
    name: str
    index: int
    id: str
    arguments: Optional[str] = None

    def to_function_call(self) -> FunctionCall:
        return FunctionCall(
            name=self.name,
            index=self.index,
            id=self.id,
            arguments=json.loads(self.arguments) if self.arguments else {}
        )


class ChatMessage:
    def __init__(
        self,
        role: ChatRole | str,
        content: Optional[str] = None,
        metadata: Optional[dict] = None,
        message_time: Optional[float] = None,
        images: Optional[ImageCache | list[ImageCache]] = None,
        audio: Optional[AudioCache | list[AudioCache]] = None,
        tool_calls: Optional[list[FunctionCall]] = None,
        tool_call_id: Optional[str] = None,
        *,
        # TODO: add type hints and type checks
        instance_id: Optional[str] = None,
        origin=None,
        bot=None
    ):
        self.instance_id = instance_id

        # the original message that this message is instantiated from, should be of type
        # discord.Message or telegram.Message, but the type is not specified here to avoid import
        # errors if one library is not found, is used mostly to reply to the original message
        self.origin = origin

        self.bot = bot

        assert role is not None, f"expected `role` to be of type `Role` and not be None, but got `{role}`"
        if images is not None:
            assert isinstance(images, (ImageCache, list)
                              ), f"Images must be of type ImageCache or list[ImageCache], but got {images}."
            if isinstance(images, ImageCache):
                images = [images]
            else:
                for image in images:
                    assert isinstance(image, ImageCache), f"expected image to be ImageCache, but got {image}."
        else:
            images = []

        if audio is not None:
            assert isinstance(audio, (AudioCache, list)
                              ), f"audio must be of type AudioCache or list[AudioCache], but got {audio}."
            if isinstance(audio, AudioCache):
                audio = [audio]
            else:
                for _audio in audio:
                    assert isinstance(_audio, AudioCache), f"expected audio to be of type AudioCache, but got {_audio}."
        else:
            audio = []

        # validating each role's requirements
        match role:
            case ChatRole.SYSTEM:
                assert exists(content, True) and isinstance(
                    content, str), f"expected SYSTEM to have a `content` of type `str` but got `{content}`"
                assert not exists(
                    metadata), f"expected SYSTEM to not have `metadata` (e.g. the metadata should be None) but got `{metadata}`"
                assert not exists(
                    tool_calls), f"expected SYSTEM to not have `tool_calls` (e.g. the tool_calls should be None) but got `{tool_calls}`"
                assert not exists(
                    tool_call_id), f"expected SYSTEM to not have `tool_call_id` (e.g. the tool_call_id should be None) but got `{tool_call_id}`"
                assert not exists(
                    images), f"Images can only be attached to user messages, but got {images} for role SYSTEM"

            case ChatRole.ASSISTANT:
                assert content is None or isinstance(
                    content, str), f"expected ASSISTANT to have a `content` of type `str` but got `{content}`"
                assert not exists(
                    metadata), f"expected ASSISTANT to not have `metadata` (e.g. the metadata should be None) but got `{metadata}`"
                assert not exists(
                    tool_call_id), f"expected ASSISTANT to not have `tool_call_id` (e.g. the tool_call_id should be None) but got `{tool_call_id}`"
                assert not exists(
                    images), f"Images can only be attached to user messages, but got {images} for role ASSISTANT"

                if exists(tool_calls):
                    assert not exists(
                        content, True), f"expected ASSISTANT to not have `content` (e.g. the content should be None) while `tool_calls` is not None but got `{content}`"
                    assert isinstance(
                        tool_calls, list), f"expected TOOL to have `tool_calls` of type `list[FunctionCall]` but got `{tool_calls}`"
                    for tc in tool_calls:
                        assert isinstance(
                            tc, FunctionCall), f"expected TOOL to have `tool_calls` of type `list[FunctionCall]` but at least one of the list elements is not of type FunctionCall, got `{tool_calls}`"

            case ChatRole.USER:
                assert exists(content, True) and isinstance(
                    content, str), f"expected USER to have a `content` of type `str` but got `{content}`"
                assert not exists(metadata) or isinstance(
                    metadata, dict), f"expected `metadata` to be None or `metadata` to be of type `dict` but got `{metadata}`"
                assert not exists(tool_calls) or (isinstance(tool_calls, list) and tool_calls == [
                ]), f"expected SYSTEM to not have `tool_calls` (e.g. the tool_calls should be None) but got `{tool_calls}`"
                assert not exists(
                    tool_call_id), f"expected USER to not have `tool_call_id` (e.g. the tool_call_id should be None) but got `{tool_call_id}`"

            case ChatRole.TOOL:
                assert exists(content, True) and isinstance(
                    content, str), f"expected TOOL to have a `content` of type `str` but got `{content}`"
                assert not exists(
                    metadata), f"expected TOOL to not have `metadata` (e.g. the metadata should be None) but got `{metadata}`"
                assert exists(tool_call_id) and isinstance(
                    tool_call_id, str), f"expected TOOL to have a `tool_call_id` of type `str` but got `{tool_call_id}`"
                assert not exists(
                    images), f"Images can only be attached to user messages, but got {images} for role TOOL"

            case _:
                raise ValueError(f"Invalid role \"{role}\".")

        self.role = role
        self.content = content
        self.metadata = metadata
        self.time = (message_time if message_time and message_time > 0 else time.time())

        self.images = images  # Should be an ImageCache instance or a list of ImageCache instances or None
        self.audio = audio

        # store function calls and function results
        self.tool_calls: list[FunctionCall] = tool_calls or []
        self.tool_call_id = tool_call_id

    @property
    async def instance(self):
        if not self.bot:
            return
        return await self.bot.get_conversation_instance(self.instance_id)

    def to_dict(self) -> dict:
        return dict(
            role=self.role,
            content=self.content,
            metadata=self.metadata,
            time=self.time,
            images=[x.to_dict() for x in self.images or []],
            audio=[x.to_dict() for x in self.audio or []],
            tool_calls=[x.to_dict() for x in self.tool_calls or []],
            tool_call_id=self.tool_call_id
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'ChatMessage':
        return cls(
            role=ChatRole[data["role"].upper()],
            content=data.get("content"),
            metadata=data.get("metadata"),
            message_time=data.get("time", time.time()),
            images=[ImageCache.from_dict(i) for i in data.get("images", [])],
            tool_calls=[FunctionCall.from_dict(d) for d in data.get("tool_calls", [])],
            tool_call_id=data.get("tool_call_id")
        )

    def to_openai_dict(self, timestamps: bool = True) -> dict:
        openai_dict = dict(role=self.role.lower())  # ensure role is in lower case
        match self.role:
            case ChatRole.USER:
                content = [f"User: {self.content}"]
                if timestamps:
                    fmt_time = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(self.time))
                    fmt_diff_time = format_time_ago(time.time()-self.time)
                    content.append(f"Sent At: {fmt_time} ({fmt_diff_time})")
                if self.metadata is not None:
                    content += [
                        "Metadata:",
                        ""
                        "```json",
                        json.dumps(self.metadata, ensure_ascii=False),
                        "```"
                    ]
                content_dict: list[dict] = [dict(type="text", text="\n".join(content))]
                for img in self.images:
                    content_dict.append(dict(
                        type="image_url",
                        image_url=dict(url=img.to_data_url())
                    ))
                for audio in self.audio:
                    content_dict.append(dict(
                        input_audio=dict(
                            data=audio.to_base64(),
                            format="wav"  # for some reason this value is not used by the API is required to be mp3 or wav
                        ),
                        type="input_audio",
                    ))
                openai_dict.update(dict(content=content_dict))  # type: ignore
            case ChatRole.ASSISTANT:
                if exists(self.content, True):
                    openai_dict.update(dict(content=self.content))  # type: ignore
                else:
                    openai_dict.update(dict(
                        tool_calls=[i.to_openai_dict() for i in self.tool_calls]
                    ))  # type: ignore
            case ChatRole.TOOL:
                openai_dict.update(dict(
                    content=self.content,
                    tool_call_id=self.tool_call_id
                ))  # type: ignore
            case _:
                openai_dict.update(dict(content=self.content))  # type: ignore
        return openai_dict


# takes the last N messages in the message list that match a predicate, and moves them to the
# end of the message list, this is to ensure the LLMs immmediate context is accurate
async def get_rearranged_messages(messages: list[ChatMessage], predicate: AsyncPredicate, n: int = 5) -> list[ChatMessage]:
    selected_messages: list[ChatMessage] = []
    unselected_predicate: list[ChatMessage] = []
    for msg in messages[::-1]:
        if await predicate(msg) and len(selected_messages) < n:
            selected_messages.append(msg)
        else:
            unselected_predicate.append(msg)

    return unselected_predicate[::-1] + selected_messages[::-1]


class AsyncChatClient:
    def __init__(
        self,
        messages: Optional[list[ChatMessage]] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        log_tool_calls: bool = False,
        enforce_system_header: bool = False,
    ):
        if messages is not None:
            assert isinstance(
                messages, list), f"expected messages to be of type `list[ChatMessage]` or be None, but got `{messages}`"
            for m in messages:
                assert isinstance(
                    m, ChatMessage), f"expected messages to be of type `list[ChatMessage]` or be None, but at least one element in the list is not of type `ChatMessage`, got `{messages}`"
        self.base_url = base_url or DEFAULT_BASE_URL
        self.api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPINFRA_API_KEY")
        assert exists(self.api_key), "API key must be set in the environment variable OPENAI_API_KEY or DEEPINFRA_API_KEY."
        assert exists(self.base_url), f"base_url must be set, but got {self.base_url}"
        assert isinstance(self.base_url, str), f"base_url must be a string, but got {self.base_url}"
        self.model = model or DEFAULT_MODEL
        assert exists(self.model), f"model must be set, but got {self.model}"
        assert isinstance(self.model, str), f"model must be a string, but got {self.model}"
        self.messages = messages or []
        self.log_tool_calls = log_tool_calls
        self.enforce_system_header = enforce_system_header
        self.system_prompt = None
        self.tools: dict = {}

        self.rearrange_predicate = None

    # Hotfix: create a new session every time to avoid issues with cancelling requests and connection errors
    @property
    def session(self):
        return AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def add_tool(self, name: str, func: AsyncFunction, parameters: Optional[dict] = None, description: Optional[str] = None):
        """
        Register a tool (function) for tool calling.
        name: tool name (string)
        func: (str) -> Awaitable[None]
        parameters: OpenAI tool/function parameters schema (dict)
        description: description of the tool (string)
        """
        self.tools[name] = dict(
            func=func,
            schema=dict(
                type="function",
                function=dict(
                    name=name,
                    description=description or name,
                    parameters=parameters or dict(),
                )
            )
        )

    def set_rearrange_predicate(self, predicate: AsyncPredicate):
        self.rearrange_predicate = predicate

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
            raise ValueError(f"expected message to be a ChatMessage or a string, but got {message}.")

    async def create_chat_completion(self, stream: bool = False, enable_timestamps: bool = True):
        openai_messages: list = await self.get_openai_messages_dict(enable_timestamps=enable_timestamps)
        kwargs = dict(
            model=self.model,
            messages=openai_messages,
            temperature=0.7,
            top_p=0.9,
            max_tokens=1024,
            parallel_tool_calls=True,
            # reasoning_effort="high",
            stream=stream,
        )
        # If tools are registered, add them to the request
        if self.tools:
            kwargs["tools"] = [v["schema"] for k, v in self.tools.items()]  # type: ignore

        # Debugging: print the request to a file
        # with open("last-request.json", "w", encoding="utf-8") as f:
        #     json.dump(kwargs, f, ensure_ascii=False, indent=4)

        return await self.session.chat.completions.create(**kwargs)  # type: ignore

    async def get_openai_messages_dict(self, enable_timestamps: bool = True) -> list[dict]:
        if len(self.messages) == 0:
            return list()

        messages = self.enforce_approximate_context_limit(self.messages.copy())

        openai_messages = [msg.to_openai_dict(timestamps=enable_timestamps) for msg in messages]
        # add system prompt before to the last user message message to ensure it is in the
        # model's context but also don't disrupt the conversation or tool calling
        if exists(self.system_prompt):
            system_message = ChatMessage(
                role=ChatRole.SYSTEM,
                content=self.system_prompt
            ).to_openai_dict(timestamps=enable_timestamps)

            insert_index = 0
            # some models only support system message as the very first message
            if not self.enforce_system_header:
                for i, message in enumerate(messages):
                    if message.role == ChatRole.USER:
                        insert_index = i
            openai_messages.insert(insert_index, system_message)
        return openai_messages

    def enforce_approximate_context_limit(self, messages: list[ChatMessage]):
        system_prompt_size = len(self.system_prompt) if self.system_prompt else 0
        request_size = system_prompt_size
        for cutoff_index, message in enumerate(messages):
            role = message.role
            context = message.content or ""
            # TODO: better handle images and audio
            request_size += len(role) + len(context) + 1024 * len(message.audio) + 1024 * len(message.images)
            # approximate size of the message in tokens, assuming 4 characters per token
            if request_size > MAX_CONTEXT_LENGTH * 4:
                break
        else:
            cutoff_index = None

        if cutoff_index:
            if cutoff_index == 0:
                logging.warning("No messages fit in the request, cutting off the first message.")
                message_cut = messages[0]
                assert message_cut.content, "Message content must not be empty, this is a bug."
                message_cut.content = "(This message was cut off due to length limitations)\n\n" + \
                    message_cut.content[:request_size-system_prompt_size -
                                        200]  # cut off the message to fit in the request
            logging.warning("unable to fit all messages in one request.")
            messages = messages[-(cutoff_index-1):]
        return messages

    async def stream_completion(self, start_think_tag: str = "<think>", end_think_tag: str = "</think>"):
        lookbehind_buffer: str = ""
        max_buffer_size = max(len(start_think_tag), len(end_think_tag))

        is_thinking = False

        async for char in self.stream_request():
            lookbehind_buffer += char

            # make sure buffer doesn't grow indefinitely if none of the tags are found
            if len(lookbehind_buffer) > max_buffer_size:
                char_to_yield = lookbehind_buffer[0]
                lookbehind_buffer = lookbehind_buffer[1:]
                if not is_thinking:
                    yield char_to_yield

            # check for tags
            if lookbehind_buffer.endswith(start_think_tag):
                is_thinking = True
                lookbehind_buffer = ""
            elif lookbehind_buffer.endswith(end_think_tag) and is_thinking:
                is_thinking = False
                lookbehind_buffer = ""

        if not is_thinking and lookbehind_buffer:
            for c in lookbehind_buffer:
                yield c

    async def get_tool_results(self, function_calls: list[FunctionCall], reference_message: ChatMessage):
        """
        Execute tool calls and return results
        """

        results = [ChatMessage(
            ChatRole.ASSISTANT,
            content=None,
            tool_calls=function_calls
        )]
        for fn in function_calls:
            tool = self.tools.get(fn.name)
            if tool:
                func = tool["func"]
                func_args_str = ""
                if fn.arguments:
                    func_args_str = ", ".join([
                        (f"{k}=\"{v}\"" if isinstance(v, str) else f"{k}={v}")
                        for k, v in fn.arguments.items()
                    ])
                try:
                    if self.log_tool_calls:
                        logging.info(f"Calling {fn.name}({func_args_str})...")
                    else:
                        logging.debug(f"Calling {fn.name}({func_args_str})...")
                    result = await func(reference_message, **fn.arguments)  # type: ignore
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

    async def stream_request(
        self,
        verbose: bool = logging.getLevelName(logging.root.level).lower() == "debug",
        reference_message: ChatMessage | None = None
    ):
        # reference_message is the last user message in which we are responding to, it contains
        # information about the current channel and holds special metadata
        reference_message = reference_message or self.messages[-1]
        assert reference_message.role == ChatRole.USER, f"`reference_message` must be a USER message, but got a message with the role of \"{reference_message.role}\"."

        async def execute_tool_task(function_call):
            self.messages += await self.get_tool_results(
                [function_call],
                reference_message=reference_message
            )

        async with CoroutineQueueExecutor() as tool_call_queue:
            partial_function_calls:  dict[int, PartialFunctionCall] = dict()
            last_function_call_index = None
            response = ""
            finish_reason = None
            async for event in await self.create_chat_completion(stream=True):
                if event.choices is None or len(event.choices) == 0:
                    continue
                choice = event.choices[0]

                if exists(_tool_calls := choice.delta.tool_calls):
                    for tool_call in _tool_calls:
                        function = tool_call.function
                        function_index = tool_call.index
                        function_id = tool_call.id
                        function_name = function.name
                        function_arguments = function.arguments
                        if prev_function_call := partial_function_calls.get(function_index):
                            if function_arguments:
                                new_function_arguments = (prev_function_call.arguments or "") + function_arguments
                            else:
                                new_function_arguments = prev_function_call.arguments
                            partial_function_calls[function_index] = PartialFunctionCall(
                                name=prev_function_call.name,
                                arguments=new_function_arguments,
                                index=function_index,
                                id=prev_function_call.id
                            )
                        else:
                            if verbose:
                                print(f"Function: {function_name}", end="")
                            partial_function_calls[function_index] = PartialFunctionCall(
                                name=function_name,
                                arguments=function_arguments,
                                index=function_index,
                                id=function_id
                            )
                        # if the model is producing a new function call, we can assume the function call is finished generating
                        if last_function_call_index is not None and function_index != last_function_call_index:
                            function_call = partial_function_calls.pop(function_index).to_function_call()
                            # runs the tool call without blocking and in correct order
                            await tool_call_queue.add_to_queue(execute_tool_task(function_call))
                        last_function_call_index = function_index
                        if verbose:
                            print(function_arguments, end="")

                if choice.finish_reason:
                    finish_reason = choice.finish_reason

                if content := choice.delta.content:
                    if verbose:
                        print(content, end="", flush=True)
                    response += content
                    # now yields the response character by character for easier parsing
                    for char in content:
                        yield char

                if verbose and hasattr(choice.delta, "reasoning_content") and (reasoning_content := choice.delta.reasoning_content):
                    print(reasoning_content, end="", flush=True)

            if verbose:
                print()

        function_calls = [f.to_function_call() for f in partial_function_calls.values()]
        del partial_function_calls
        if function_calls:
            self.messages += await self.get_tool_results(
                function_calls,
                reference_message=reference_message
            )

        if response:
            self.messages.append(ChatMessage(
                role=ChatRole.ASSISTANT,
                content=response
            ))

        if finish_reason == "tool_calls":
            # Recursively call stream_request and yield its results
            async for chunk in self.stream_request(reference_message=reference_message):
                yield chunk

    async def stream_ask(self, message: str | ChatMessage, temporal: bool = False):
        if temporal:
            orig_messages = self.messages.copy()

        if isinstance(message, str):
            message = ChatMessage(ChatRole.USER, message)
        else:
            assert isinstance(message, ChatMessage), "Message must be a string or a ChatMessage."

        assert message.role == ChatRole.USER, "Message must be from the user."
        self.messages.append(message)

        async for chunk in self.stream_completion():
            yield chunk

        if temporal:
            self.messages = orig_messages  # type: ignore

    def to_dict(self):
        return dict(
            messages=[msg.to_dict() for msg in self.messages]
        )

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            messages=[ChatMessage.from_dict(msg) for msg in data.get("messages") or []],
        )
