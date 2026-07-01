import asyncio
import hashlib
import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from functools import partial
from typing import Any, Callable, Concatenate, Coroutine, ParamSpec, Sequence, TypeVar

import httpx
from openai import APIError, AsyncOpenAI
from openai._streaming import AsyncStream
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from .caching.base import MediaCache
from .config import OpenAIAuthConfig, OpenAILanguageModelConfig
from .enums import ChatRole
from .reflection.message import AbstractMessage
from .storage.paths import PixiPaths, open_resource
from .typing import (AsyncGenerator, AsyncIterator, AsyncPredicate, Generator,
                     Iterator, Optional)
from .utils import CoroutineQueueExecutor, clean_dict, exists, format_time_ago


@dataclass(frozen=True)
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
            arguments=data.get("arguments", {}),
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


@dataclass
class ChatMessage:
    role: ChatRole | str
    content: Optional[str] = None
    images: list[MediaCache] = field(default_factory=list)
    audio: list[MediaCache] = field(default_factory=list)
    tool_calls: Sequence[FunctionCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None

    # --- additional states---
    metadata: Optional[dict] = None
    message_time: Optional[float] = None

    # --- references ---
    instance_id: Optional[str] = None

    # the original message that this message is instantiated from, should be of type
    # discord.Message or telegram.Message, but the type is not specified here to avoid import
    # errors if one library is not found, is used mostly to reply to the original message
    origin: Optional[AbstractMessage] = None

    bot: Any = None

    def __post_init__(self):
        self.validate_params()

        self.time = (self.message_time if self.message_time and self.message_time > 0 else time.time())

    def validate_params(self):

        if self.images:
            # image cache might not be an installed feature, so we import it only when we need to use it
            from .caching import ImageCache

            for image in self.images:
                assert isinstance(
                    image, ImageCache), f"expected image to be an instance of ImageCache, but got {image}."

        if self.audio:
            # audio cache might not be an installed feature, so we import it only when we need to use it
            from .caching import AudioCache

            for audio in self.audio:
                assert isinstance(
                    audio, AudioCache), f"expected audio to be an instance of AudioCache, but got {audio}."

        # validating each role's requirements

        if self.role != ChatRole.USER:
            assert not exists(
                self.metadata), f"Metadata can only be attached to USER messages (e.g. the metadata should be None) but got `{self.metadata}`"
            assert not exists(
                self.images), f"Images can only be attached to USER messages, but got {self.images} for role ASSISTANT"

        if self.role != ChatRole.TOOL:
            assert not exists(
                self.tool_call_id), f"`tool_call_id` can only be attached to TOOL messages (e.g. the tool_call_id should be None) but got `{self.tool_call_id}`"

        match self.role:
            case ChatRole.SYSTEM:
                assert exists(
                    self.content, True), f"expected SYSTEM to have a `content` of type `str` but got `{self.content}`"
                assert not exists(
                    self.tool_calls), f"expected SYSTEM to not have `tool_calls` (e.g. the tool_calls should be None) but got `{self.tool_calls}`"

            case ChatRole.ASSISTANT:
                if exists(self.tool_calls):
                    assert self.content is None, f"expected ASSISTANT to not have `content` (e.g. the content should be None) while `tool_calls` is not None but got `{self.content}`"
                    for tool_call in self.tool_calls:
                        assert isinstance(
                            tool_call, FunctionCall), f"expected TOOL to have `tool_calls` of type `list[FunctionCall]` but at least one of the list elements is not of type FunctionCall, got `{self.tool_calls}`"
                else:
                    assert exists(
                        self.content, True), f"expected ASSISTANT to have a `content` of type `str` but got `{self.content}`"
            case ChatRole.USER:
                assert exists(
                    self.content, True), f"expected USER to have a `content` of type `str` but got `{self.content}`"
                assert not exists(
                    self.tool_calls), f"expected USER to not have `tool_calls` (e.g. the tool_calls should be None) but got `{self.tool_calls}`"

            case ChatRole.TOOL:
                assert exists(
                    self.content, True), f"expected TOOL to have a `content` of type `str` but got `{self.content}`"

            case _:
                raise ValueError(f"Invalid role \"{self.role}\".")

    def to_dict(self) -> dict:
        return clean_dict(dict(
            role=self.role,
            content=self.content,
            metadata=self.metadata,
            time=self.time,
            images=[x.to_dict() for x in self.images or []],
            audio=[x.to_dict() for x in self.audio or []],
            tool_calls=[x.to_dict() for x in self.tool_calls or []],
            tool_call_id=self.tool_call_id
        ))

    @classmethod
    def from_dict(cls, data: dict) -> 'ChatMessage':
        images = []
        if images_cache := data.get("images", []):
            from .caching import ImageCache
            images = [ImageCache.from_dict(d) for d in images_cache]
        audio = []
        if audio_cache := data.get("audio", []):
            from .caching import AudioCache
            audio = [AudioCache.from_dict(d) for d in audio_cache]
        return cls(
            role=ChatRole[data["role"].upper()],
            content=data.get("content"),
            metadata=data.get("metadata"),
            message_time=data.get("time", time.time()),
            images=images,  # pyright: ignore[reportArgumentType]
            audio=audio,  # pyright: ignore[reportArgumentType]
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
        return clean_dict(openai_dict)


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


@dataclass(frozen=True)
class ToolContext:
    reference_message: Optional[ChatMessage] = None
    parent_instance: 'Optional[AsyncChatbotInstance]' = None
    # more to be added


P = ParamSpec("P")
AsyncTool = Callable[Concatenate[ToolContext, P], Coroutine[Any, Any, Any]]


@dataclass(frozen=True)
class ActionContext:
    reference_message: Optional[ChatMessage] = None
    parent_instance: 'Optional[AsyncChatbotInstance]' = None
    # more fields to be added


ActionFunction = Callable[[ActionContext, str], Coroutine[Any, Any, None]]


@dataclass(frozen=True)
class AsyncAction:
    name: str
    field_name: str
    function: ActionFunction
    description: Optional[str] = None
    is_visible: bool = True  # whether or not the action has a visible effect from the user's perspective

    # TODO: implement callbacks for when we enter the action (after the action name) and when
    # we leave the action (right after the action is completed but before executing the action)
    enter_callback: Optional[ActionFunction] = None
    leave_callback: Optional[ActionFunction] = None

    def get_syntax(self):
        desc = self.description or "no description"
        return f"[{self.name}:<{self.field_name}>]: {desc}"

    async def call(self, *args, **kwds):
        return await self.function(*args, **kwds)

    def __str__(self):
        return f"<async-action {self.name}>"


class AsyncActionManager:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.actions: dict[str, AsyncAction] = dict()
        self.on_action: Callable[[str]] | None = None
        self.visible_actions_taken = 0

    def _add_action(self, action: AsyncAction):
        assert action is not None
        self.actions.update({action.name.lower(): action})

    def add_action(self, name: str, field_name: str, function: ActionFunction, description: Optional[str] = None, is_visible: bool = True):
        assert name
        assert field_name
        assert function is not None
        self._add_action(AsyncAction(
            name=name,
            field_name=field_name,
            function=function,
            description=description,
            is_visible=is_visible
        ))

    def get_prompt(self):
        return "\n".join(["- "+func.get_syntax() for name, func in self.actions.items()])

    async def execute_action(self, action: str, reference_message: Optional[ChatMessage] = None):
        action_content = action[1:-1]  # removed brakets

        separator_idx = action_content.index(":") if ":" in action_content else None
        if separator_idx:
            name = action_content[:separator_idx].strip()
            value = action_content[separator_idx+1:].strip()
        else:
            name = action_content
            value = None

        if self.on_action:
            self.on_action(name)

        action_meta = self.actions.get(name.lower())
        if action_meta is None:
            self.logger.error(f"Model tried to use the action \"{name}\", which is not implemented.")
            return
        ctx = ActionContext(
            reference_message=reference_message
        )
        try:
            await action_meta.call(ctx, value)
            if action_meta.is_visible:
                self.visible_actions_taken += 1
        except Exception:
            logging.exception("an error accured during action")

    async def consume(self, stream: Iterator | Generator | AsyncGenerator | AsyncGenerator, reference_message: ChatMessage):
        """
        Consumes actions and runs them automatically
        """
        i = 0  # counts the number of "[" characters minus the number of "]" characters
        action = ""
        self.visible_actions_taken = 0

        async with CoroutineQueueExecutor() as queue:
            async def process(char):
                nonlocal i
                nonlocal action

                result = None

                # the opening of the action
                if char == "[":
                    i += 1

                if i != 0:
                    action += char
                else:
                    result = char

                # the closing of the action
                if char == "]":
                    i -= 1

                    # if the action is fully captured
                    if i == 0:
                        # run action without blocking the stream
                        await queue.add_to_queue(self.execute_action(
                            action=action,
                            reference_message=reference_message
                        ))
                        action = ""

                return result

            if isinstance(stream, (Iterator, Generator)):
                for char in stream:
                    if (result := await process(char)):
                        yield result
            elif isinstance(stream, (AsyncIterator, AsyncGenerator)):
                async for char in stream:
                    if (result := await process(char)):
                        yield result
            else:
                raise TypeError(
                    f"expected `stream` to be an Iterator, Generator, AsyncIterator or AsyncGenerator but got `{type(stream)}`!")

    def is_visible_actions_taken(self) -> bool:
        return self.visible_actions_taken > 0


class AsyncChatClient:
    def __init__(
        self,
        auth: OpenAIAuthConfig,
        model: OpenAILanguageModelConfig,
        messages: Optional[list[ChatMessage]] = None,
        log_tool_calls: bool = False,
        enforce_system_header: bool = False,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.auth = auth
        self.model = model
        self.messages = messages or []
        self.log_tool_calls = log_tool_calls
        self.enforce_system_header = enforce_system_header

        if messages is not None:
            assert isinstance(messages, list), \
                f"expected messages to be of type `list[ChatMessage]` or be None, but got `{messages}`"
            for m in messages:
                assert isinstance(m, ChatMessage), \
                    f"expected messages to be of type `list[ChatMessage]` or be None, but at least one element in the list is not of type `ChatMessage`, got `{messages}`"

        self.system_prompt = None
        self.tools: dict = {}
        self.rearrange_predicate = None

        self.session = AsyncOpenAI(
            api_key=self.auth.api_key,
            base_url=self.auth.base_url,
            # don't use proxies from environment variables
            http_client=httpx.AsyncClient(trust_env=False),
        )
        self.action_manager = AsyncActionManager()

    def add_tool(self, name: str, func: AsyncTool, parameters: Optional[dict] = None, description: Optional[str] = None):
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

    def add_action(self, name: str, field_name: str, func: ActionFunction, description: Optional[str] = None):
        self.action_manager.add_action(name, field_name, func, description)

    def set_rearrange_predicate(self, predicate: AsyncPredicate):
        """
        Set a predicate function to rearrange messages based on a specific condition.
        This is useful for filtering messages by channel or other criteria and moving them
        to the front of the model context.
        """

        self.rearrange_predicate = predicate

    def set_system(self, prompt: Optional[str]):
        assert prompt is not None and prompt != ""
        self.system_prompt = prompt

    def get_system_prompt(self):
        return (self.system_prompt or "") + "\n\nActions:\n" + self.action_manager.get_prompt()

    async def stream_call(self, reference_message: ChatMessage):
        non_response = "".join([char async for char in self.action_manager.consume(
            stream=self.stream_completion(),
            reference_message=reference_message
        )])

        return non_response.strip() or None

    def add_message(self, message: ChatMessage | str) -> ChatMessage:
        assert message is not None
        if isinstance(message, str):
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
            message = ChatMessage(role, message)
        elif not isinstance(message, ChatMessage):
            raise ValueError(f"expected message to be a ChatMessage or a string, but got {message}.")
        self.messages.append(message)
        return message

    def set_messages(self, messages: list[ChatMessage]):
        assert isinstance(messages, list), f"Invalid messages \"{messages}\"."
        self.messages = messages

    def get_messages(self):
        return self.messages

    async def stream_chat_completion(self, enable_timestamps: bool = True) -> AsyncStream[ChatCompletionChunk]:
        openai_messages: list = await self.get_openai_messages_dict(enable_timestamps=enable_timestamps)
        kwargs = dict(
            model=self.model.id,
            messages=openai_messages,
            temperature=0.7,
            top_p=0.9,
            max_tokens=1024,
            parallel_tool_calls=True,
            # reasoning_effort="high",
            stream=True,
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

        system_prompt = self.get_system_prompt()
        messages = self.enforce_approximate_context_limit(system_prompt, self.messages.copy())

        openai_messages = [msg.to_openai_dict(timestamps=enable_timestamps) for msg in messages]
        # add system prompt before to the last user message message to ensure it is in the
        # model's context but also don't disrupt the conversation or tool calling
        
        if exists(system_prompt):
            system_message = ChatMessage(
                role=ChatRole.SYSTEM,
                content=system_prompt
            ).to_openai_dict(timestamps=enable_timestamps)

            insert_index = 0
            # some models only support system message as the very first message
            if not self.enforce_system_header:
                for i, message in enumerate(messages):
                    if message.role == ChatRole.USER:
                        insert_index = i
            openai_messages.insert(insert_index, system_message)
        return openai_messages

    def enforce_approximate_context_limit(self, system_prompt: str, messages: list[ChatMessage]):
        system_prompt_size = len(system_prompt) if system_prompt else 0
        request_size = system_prompt_size
        for cutoff_index, message in enumerate(messages):
            role = message.role
            context = message.content or ""
            # TODO: better approximate images
            # TODO: audio should be approximated with a function of it's duration
            request_size += len(role) + len(context) + 1024 * len(message.audio) + 1024 * len(message.images)
            # approximate size of the message in tokens, assuming 4 characters per token
            if request_size > self.model.max_context * 4:
                break
        else:
            cutoff_index = None

        if cutoff_index:
            self.logger.warning("LLM ran out of context, older context will be forgotten.")
            if cutoff_index == 0:
                self.logger.warning("First message can't fit in the model context, this is probaby a bug.")
                message_cut = messages[0]
                assert message_cut.content, "Message content must not be empty."
                message_cut.content = "(This message was cut off due to length limitations)\n\n" + \
                    message_cut.content[:request_size-system_prompt_size - 200]
            else:
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
            if lookbehind_buffer.endswith(start_think_tag) and not is_thinking:
                is_thinking = True
                lookbehind_buffer = ""
            elif lookbehind_buffer.endswith(end_think_tag) and is_thinking:
                is_thinking = False
                lookbehind_buffer = ""

        if not is_thinking and lookbehind_buffer:
            for c in lookbehind_buffer:
                yield c

    async def get_tool_results(self, function_calls: list[FunctionCall], reference_message: ChatMessage) -> list[ChatMessage]:
        """
        Execute tool calls and return results
        """

        if not function_calls:
            return []

        if isinstance(self, AsyncChatbotInstance):
            tool_context = ToolContext(
                reference_message=reference_message,
                parent_instance=self
            )
        else:
            tool_context = ToolContext(
                reference_message=reference_message,
            )

        results = [ChatMessage(
            ChatRole.ASSISTANT,
            content=None,
            tool_calls=function_calls
        )]
        for fn in function_calls:
            tool = self.tools.get(fn.name)
            if tool:
                func: AsyncTool = tool["func"]
                func_args_str = ""
                if fn.arguments:
                    func_args_str = ", ".join([
                        (f"{k}=\"{v}\"" if isinstance(v, str) else f"{k}={v}")
                        for k, v in fn.arguments.items()
                    ])
                try:
                    if self.log_tool_calls:
                        self.logger.info(f"Calling {fn.name}({func_args_str})...")
                    else:
                        self.logger.debug(f"Calling {fn.name}({func_args_str})...")
                    result = await func(tool_context, **fn.arguments)  # type: ignore
                    result = json.dumps(result, ensure_ascii=False, indent=2)
                except Exception as e:
                    self.logger.exception(f"Error calling tool '{fn.name}({func_args_str})'")
                    result = f"Tool error: {e}"

                if self.log_tool_calls:
                    self.logger.info(f"Call {fn.name}({func_args_str}): {result}")
                else:
                    self.logger.debug(f"Call {fn.name}({func_args_str}): {result}")
            else:
                result = f"Tool '{fn.name}' was not found."
                self.logger.warning(f"Tool '{fn.name}' was not found.")

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

        async with CoroutineQueueExecutor() as tool_call_queue, await self.stream_chat_completion() as stream:
            partial_function_calls: dict[int, PartialFunctionCall] = dict()
            last_function_call_index = None
            response = ""
            finish_reason = None
            async for event in stream:
                if event.choices is None or len(event.choices) == 0:
                    continue
                choice = event.choices[0]

                for tool_call in choice.delta.tool_calls or []:
                    function = tool_call.function
                    function_index = tool_call.index
                    function_id = tool_call.id
                    function_name = function.name if function else None
                    function_arguments = function.arguments if function else None
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
                        assert function_name
                        assert function_id
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

                if verbose and hasattr(choice.delta, "reasoning_content"):
                    print(choice.delta.reasoning_content, end="", flush=True) # pyright: ignore[reportAttributeAccessIssue]

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

    def state_dict(self):
        return dict(
            messages=[msg.to_dict() for msg in self.messages]
        )

    def load_state_dict(self, data: dict):
        self.messages = [ChatMessage.from_dict(msg) for msg in data.get("messages") or []]


@dataclass(frozen=True)
class AssistantPersona:
    name: str
    age: Optional[int] = None
    location: Optional[str] = None
    appearance: Optional[str] = None
    background: Optional[str] = None
    likes: Optional[str] = None
    dislikes: Optional[str] = None
    online: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'AssistantPersona':
        return cls(**data)

    @classmethod
    def from_json(cls, file: str) -> 'AssistantPersona':
        with open(file, "rb") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def __str__(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass(frozen=True)
class ToolEntry:
    name: str
    func: AsyncTool
    parameters: Optional[dict] = None
    description: Optional[str] = None
    predicate: Optional[AsyncPredicate] = None


@dataclass(frozen=True)
class ActionEntry:
    name: str
    field_name: str
    func: ActionFunction
    description: str
    is_visible: bool = True
    predicate: Optional[AsyncPredicate] = None


def get_instance_save_path(id: str, hash_prefix: str):
    uuid_hash = hashlib.sha256(f"{hash_prefix}_{id}".encode("utf-8")).hexdigest()
    path = str(PixiPaths.userdata() / f"{hash_prefix}_{uuid_hash}.json")
    return path


class AsyncChatbotInstance(AsyncChatClient):
    def __init__(self,
                 uuid: int | str,
                 hash_prefix: str,
                 *,
                 bot=None,
                 resource_folder: str | None = None,
                 **client_kwargs,
                 ):

        super().__init__(**client_kwargs)

        self.logger = logging.getLogger(self.__class__.__name__)

        self.bot = bot
        assert self.bot

        assert exists(uuid) and isinstance(uuid, (int, str)), f"Invalid uuid \"{uuid}\"."
        assert exists(hash_prefix) and isinstance(hash_prefix, str), f"Invalid hash_prefix \"{hash_prefix}\"."
        assert not exists(resource_folder) or (exists(resource_folder) and isinstance(
            resource_folder, str)), f"Invalid resource_folder \"{resource_folder}\"."

        self.id = str(uuid)
        self.prefix = hash_prefix
        self.path = get_instance_save_path(id=self.id, hash_prefix=self.prefix)

        # load resources
        with open_resource("persona.json", "r") as f:
            self.persona = AssistantPersona.from_dict(
                json.load(f)
            )
        with open_resource("system.md", "r") as f:
            self.system_prompt_template: str = f.read()
        with open_resource("examples.txt", "r") as f:
            self.examples: str = f.read()

        # runtime states
        self.realtime_data = dict()
        self.is_notes_visible = False
        self.actions_since_last_message = 0

        if not self.messages:
            self.add_message(ChatMessage(
                role=ChatRole.ASSISTANT,
                content="[NOTE: I accept the guidelines of the system, I use the SEND to respond nicely] [SEND: OK!, Let's begin!]",
                bot=self.bot
            ))

        self.channel_active_tasks: defaultdict[str, list[asyncio.Task]] = defaultdict(list)

    def add_message(self, message: ChatMessage | str, default_role: ChatRole = ChatRole.USER) -> ChatMessage:
        """
        Add a message to the conversation, and adds a reference to the bot to the messages as well.

        if message is a string, tries to determine the role of the message based on the last message recieved.
        """
        self.actions_since_last_message = 0
        if isinstance(message, str):
            message = ChatMessage(default_role, message, bot=self.bot)

        if isinstance(message, ChatMessage):
            message.bot = self.bot  # this is intended to be handled by this class
            return super().add_message(message)
        else:
            raise TypeError(f"expected message to be a string or a ChatMessage, but got {type(message)}.")

    def update_realtime(self, data: dict):
        self.realtime_data.update(data)

    def get_realtime_data(self):
        return json.dumps(self.realtime_data | dict(date=time.strftime("%a %d %b %Y, %I:%M%p")), ensure_ascii=False)

    # override system prompt from the base class
    def get_system_prompt(self):
        return self.system_prompt_template.format(
            persona=self.persona,
            examples=self.examples,
            realtime=self.get_realtime_data(),
            actions=self.action_manager.get_prompt()
        )

    async def concurrent_channel_stream_call(self, channel_id: str, reference_message: ChatMessage):
        assert channel_id, "channel_id is None"

        async def stream_call_task():
            try:
                await self.stream_call(reference_message)
            except asyncio.CancelledError:
                self.logger.warning(
                    f"stream_call task was cancelled inside {self.id} in channel {channel_id}"
                )

        task = asyncio.create_task(stream_call_task())
        self.channel_active_tasks[channel_id].append(task)
        task.add_done_callback(lambda t: self.channel_active_tasks[channel_id].remove(t))
        # cancell extra tasks
        while len(self.channel_active_tasks[channel_id]) > 1:
            cancel_task = self.channel_active_tasks[channel_id][0]
            cancel_task.cancel()
            await cancel_task
        return task

    def toggle_notes(self):
        self.is_notes_visible = not self.is_notes_visible
        return self.is_notes_visible

    def to_dict(self):
        return dict(
            uuid=self.id,
            prefix=self.prefix,
            messages=[msg.to_dict() for msg in self.messages],
        )

    def save(self):
        os.makedirs(PixiPaths.userdata(), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), ensure_ascii=False))

    def load(self, not_found_ok: bool = True):
        # load is called on every chatbot instance after they are created, in case you must load an
        # existing instance, you should set not_found_ok to false.

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.hash_prefix = data.get("prefix")
            self.messages = [ChatMessage.from_dict(d) for d in data.get("messages", [])]
        except json.decoder.JSONDecodeError:
            self.logger.warning(f"Unable to load the instance save file `{self.path}`, using default values.")
        except FileNotFoundError:
            if not not_found_ok:
                raise FileNotFoundError(f"Unable to find the instance save file {self.path}`.")
        except Exception:
            self.logger.exception(f"Unable to load the instance save file {self.path}`, using default values.")


class CachedAsyncChatbotFactory:
    def __init__(self, *, parent=None, hash_prefix: str, **kwargs):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.instances: dict[str, AsyncChatbotInstance] = {}
        self.kwargs = kwargs
        self.hash_prefix = hash_prefix
        self.tools: list[ToolEntry] = []
        self.actions: list[ActionEntry] = []
        self.bot = parent
        assert self.bot

    def register_action(self, action: ActionEntry):
        """
        Register an action

        actions are inline tools with only one parameter that can be used by all models (even those without tool
        calling capabilities), their descriptions are dynamically added to the system prompt at runtime
        """

        self.actions.append(action)

    def register_tool(self, tool: ToolEntry):
        """
        Register a tool (function) for tool calling.
        """

        self.tools.append(tool)

    async def __execute_predicate_if_present(self, predicate: AsyncPredicate | None, *args, **kwargs) -> bool:
        if predicate is None:
            return True
        return await predicate(*args, **kwargs)

    async def new_instance(self, identifier: str) -> AsyncChatbotInstance:
        instance = AsyncChatbotInstance(identifier, **self.kwargs, hash_prefix=self.hash_prefix, bot=self.bot)

        # register all the tools for the newly created instance
        for tool in self.tools:
            if not await self.__execute_predicate_if_present(tool.predicate, instance):
                continue
            instance.add_tool(
                name=tool.name,
                func=tool.func,
                parameters=tool.parameters,
                description=tool.description
            )

        # register all the actions for the newly created instance
        for action in self.actions:
            if not await self.__execute_predicate_if_present(action.predicate, instance):
                continue
            instance.add_action(
                name=action.name,
                func=action.func,
                field_name=action.field_name,
                description=action.description
            )

        return instance

    def cache_instance(self, instance: AsyncChatbotInstance):
        self.instances.update({instance.id: instance})

    async def get(self, identifier: str) -> AsyncChatbotInstance | None:
        cached_instance = self.instances.get(identifier)
        if cached_instance:
            return cached_instance
        instance = await self.new_instance(identifier)
        try:
            instance.load(not_found_ok=False)
            # cache the instance
            self.cache_instance(instance)
            return instance
        except FileNotFoundError:
            return None

    async def get_or_create(self, identifier: str) -> AsyncChatbotInstance:
        instance = self.instances.get(identifier)
        if instance is None:
            instance = await self.new_instance(identifier)
            instance.load(not_found_ok=True)
            # cache the instance
            self.cache_instance(instance)
            self.logger.info(f"initiated a conversation with {identifier=}.")
        return instance

    def remove(self, identifier: str):
        self.logger.info(f"removing {identifier}")
        save_path = get_instance_save_path(id=identifier, hash_prefix=self.hash_prefix)
        if os.path.exists(save_path):
            os.remove(save_path)
        if identifier in self.instances.keys():
            del self.instances[identifier]

    def save(self):
        for identifier, conversation in self.instances.items():
            try:
                conversation.save()
            except Exception as e:
                self.logger.exception(f"Failed to save conversation with {identifier=}: {e}")
