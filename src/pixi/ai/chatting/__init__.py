from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import (TYPE_CHECKING, Any, AsyncGenerator, AsyncIterator,
                    Awaitable, Callable, Generator, Iterator, Optional)

from pixi.caching import get_caching_provider

if TYPE_CHECKING:
    from pixi.bot.client import PixiClient

from ...apis.openai import AsyncOpenAI, AsyncStream, ChatCompletionChunk
from ...model.config import OpenAIAuthConfig, OpenAILanguageModelConfig
from ...model.enums import ChatRole
from ...model.storage.message import ChatMessageMeta
from ...storage.paths import PixiPaths, open_resource
from ...utils import (AsyncScheduler, CoroutineQueueExecutor, clean_dict,
                      exists, format_time_ago)
from .callbacks import (ActionContext, AsyncAction, AsyncTool,
                        PartialToolCallMeta, Predicate, ToolCallMeta,
                        ToolContext)
from .persona import AssistantPersona


# takes the last N messages in the message list that match a predicate, and moves them to the
# end of the message list, this is to ensure the LLMs immmediate context is accurate
def get_rearranged_messages(messages: list[ChatMessageMeta], predicate: Predicate, n: int = 5) -> list[ChatMessageMeta]:
    selected_messages: list[ChatMessageMeta] = []
    unselected_predicate: list[ChatMessageMeta] = []
    for msg in messages[::-1]:
        if predicate(msg) and len(selected_messages) < n:
            selected_messages.append(msg)
        else:
            unselected_predicate.append(msg)

    return unselected_predicate[::-1] + selected_messages[::-1]


class ChatMessageUtils:
    def __init__(self, meta: ChatMessageMeta):
        self.meta = meta
        self.logger = logging.getLogger(self.__class__.__name__)

        self.validate_params(meta)

    @classmethod
    def from_meta(cls, meta: ChatMessageMeta):
        return cls(meta)

    @staticmethod
    def validate_params(meta: ChatMessageMeta):
        # validating each role's requirements

        if meta.role != ChatRole.USER:
            assert not exists(
                meta.metadata), f"Metadata can only be attached to USER messages (e.g. the metadata should be None) but got `{meta.metadata}`"
            assert not exists(
                meta.image_hashes), f"Image attachements to non-USER messages are not allowed, but got {meta.image_hashes} for role ASSISTANT"
            assert not exists(
                meta.audio_hashes), f"Audio attachements to non-USER messages are not allowed, but got {meta.image_hashes} for role ASSISTANT"

        if meta.role != ChatRole.TOOL:
            assert not exists(
                meta.tool_call_id), f"`tool_call_id` can only be attached to TOOL messages (e.g. the tool_call_id should be None) but got `{meta.tool_call_id}`"

        match meta.role:
            case ChatRole.SYSTEM:
                assert exists(
                    meta.content, True), f"expected SYSTEM to have a `content` of type `str` but got `{meta.content}`"
                assert not exists(
                    meta.tool_calls), f"expected SYSTEM to not have `tool_calls` (e.g. the tool_calls should be None) but got `{meta}`"

            case ChatRole.ASSISTANT:
                if exists(meta.tool_calls):
                    assert meta.content is None, f"expected ASSISTANT to not have `content` (e.g. the content should be None) while `tool_calls` is not None but got `{meta.content}`"
                    for tool_call in meta.tool_calls:
                        assert isinstance(
                            tool_call, ToolCallMeta), f"expected TOOL to have `tool_calls` of type `list[FunctionCall]` but at least one of the list elements is not of type FunctionCall, got `{meta.tool_calls}`"
                else:
                    assert exists(
                        meta.content, True), f"expected ASSISTANT to have a `content` of type `str` but got `{meta.content}`"
            case ChatRole.USER:
                assert exists(
                    meta.content, True), f"expected USER to have a `content` of type `str` but got `{meta.content}`"
                assert not exists(
                    meta.tool_calls), f"expected USER to not have `tool_calls` (e.g. the tool_calls should be None) but got `{meta.tool_calls}`"

            case ChatRole.TOOL:
                assert exists(
                    meta.content, True), f"expected TOOL to have a `content` of type `str` but got `{meta.content}`"

            case _:
                raise ValueError(f"Invalid role \"{meta.role}\".")

    def to_openai_dict(self, timestamps: bool = True) -> dict:
        openai_dict = dict(role=self.meta.role.lower())  # ensure role is in lower case
        match self.meta.role:
            case ChatRole.USER:
                content = [f"User: {self.meta.content}"]
                if timestamps:
                    fmt_time = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(self.meta.time))
                    fmt_diff_time = format_time_ago(time.time()-self.meta.time)
                    content.append(f"Sent At: {fmt_time} ({fmt_diff_time})")
                if self.meta.metadata is not None:
                    content += [
                        "Metadata:",
                        ""
                        "```json",
                        json.dumps(self.meta.metadata, ensure_ascii=False, indent=3),
                        "```"
                    ]
                content_dict: list[dict] = [dict(type="text", text="\n".join(content))]
                for hash in self.meta.image_hashes:
                    image = get_caching_provider().load_media(hash)
                    if image is None:
                        self.logger.warning("Failed to load image from cache.")
                        continue
                    content_dict.append(dict(
                        type="image_url",
                        image_url=dict(url=image.to_data_url())
                    ))
                for hash in self.meta.audio_hashes:
                    audio = get_caching_provider().load_media(hash)
                    if audio is None:
                        self.logger.warning("Failed to load audio from cache.")
                        continue
                    content_dict.append(dict(
                        input_audio=dict(
                            data=audio.to_base64(),
                            # for some reason this value is required to be mp3 or wav, but is
                            # not used for decoding the audio, the API may support more formats;
                            # so we can hardcode it to wav as the universally supported format.
                            format="wav"
                        ),
                        type="input_audio",
                    ))
                openai_dict.update(dict(content=content_dict))  # type: ignore
            case ChatRole.ASSISTANT:
                if exists(self.meta.content, True):
                    openai_dict.update(dict(content=self.meta.content))  # type: ignore
                else:
                    openai_dict.update(dict(
                        tool_calls=[
                            dict(
                                type="function",
                                id=tool.id,
                                function=dict(
                                    name=tool.name,
                                    arguments=json.dumps(tool.arguments, ensure_ascii=False)
                                )
                            ) for tool in self.meta.tool_calls
                        ]
                    ))  # type: ignore
            case ChatRole.TOOL:
                openai_dict.update(dict(
                    content=self.meta.content,
                    tool_call_id=self.meta.tool_call_id
                ))  # type: ignore
            case _:
                openai_dict.update(dict(content=self.meta.content))  # type: ignore
        return clean_dict(openai_dict)


class AsyncActionManager:
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.actions: dict[str, AsyncAction] = dict()
        self.on_action: Callable[[str, str | None]] | None = None
        self.visible_actions_taken = 0

    def add_action(self, action: AsyncAction):
        assert action.name
        assert action.field_name
        self.actions[action.name.lower()] = action

    def get_prompt(self):
        return "\n".join(
            f"- [{action.name}:<{action.field_name}>]: {action.description or 'no description'}"
            for action in self.actions.values()
        )

    async def execute_action(self, action_str: str, action_context: ActionContext):
        action_content = action_str[1:-1]  # removed brakets

        separator_idx = action_content.index(":") if ":" in action_content else None
        if separator_idx:
            name = action_content[:separator_idx].strip()
            value = action_content[separator_idx+1:].strip()
        else:
            name = action_content
            value = None

        if self.on_action:
            self.on_action(name, value)

        action = self.actions.get(name.lower())
        if action is None:
            self.logger.error(f"Model tried to use the action \"{name}\", which is not implemented.")
            return

        await self._invoke_action(action, action_context, value)

    async def _invoke_action(self, action: AsyncAction, action_context: ActionContext, value: str | None):

        try:
            await action.call(action_context, value)
            if action.is_visible:
                self.visible_actions_taken += 1
        except Exception:
            logging.exception("an error accured during action")

    async def consume(self, stream: Iterator | Generator | AsyncIterator | AsyncGenerator, action_context: ActionContext):
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
                            action_str=action,
                            action_context=action_context
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


class AsyncToolManager:
    def __init__(self, log_tool_calls: bool = True, verbose: bool = False):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.log_tool_calls = log_tool_calls
        self.verbose = verbose

        self.tools: dict[str, AsyncTool] = dict()
        self.on_tool: Callable[[ToolCallMeta]] | None = None
        self.tool_results_consumer: Callable[[list[ChatMessageMeta]]] | None = None

    def add_tool(self, tool: AsyncTool):
        assert tool.name
        self.tools[tool.name.lower()] = tool

    def get_tools_schema(self):
        return [
            dict(
                type="function",
                function=dict(
                    name=tool.name,
                    description=tool.description or tool.name,
                    parameters=tool.parameters or dict(),
                )
            ) for tool in self.tools.values()
        ]

    async def get_tool_results(self, function_calls: list[ToolCallMeta], tool_context: ToolContext) -> list[ChatMessageMeta]:
        """
        Execute tool calls and return results
        """

        if not function_calls:
            return []

        results = [ChatMessageMeta(
            ChatRole.ASSISTANT,
            content=None,
            tool_calls=function_calls
        )]
        for fn in function_calls:
            tool = self.tools.get(fn.name)
            if tool:
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
                    result = await tool.call(tool_context, **(fn.arguments or {}))
                    result = json.dumps(result, ensure_ascii=False, indent=3)
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

            results.append(ChatMessageMeta(
                ChatRole.TOOL,
                content=result,
                tool_call_id=fn.id,
            ))
        return results

    async def execute_tool(self, tool_call: ToolCallMeta, tool_context: ToolContext):
        if self.on_tool:
            self.on_tool(tool_call)

        tool = self.tools.get(tool_call.name.lower())
        if tool is None:
            self.logger.error(f"Model tried to use the tool \"{tool}\", which is not implemented.")
            return

        try:
            tool_kwargs = tool_call.arguments or dict()
            await tool.call(tool_context, **tool_kwargs)
        except Exception:
            logging.exception("an error accured during action")

    async def stream_tool_calls(self, stream: AsyncStream[ChatCompletionChunk], tool_context: ToolContext):
        async def execute_and_consume_tool_results(tool_call: ToolCallMeta, tool_context: ToolContext):
            retults = await self.get_tool_results(
                [tool_call],
                tool_context=tool_context
            )
            if self.tool_results_consumer is None:
                self.logger.warning("tool results are being ignored")
                return
            maybe_coro = self.tool_results_consumer(retults)
            if asyncio.iscoroutine(maybe_coro):
                await maybe_coro

        async with CoroutineQueueExecutor() as tool_call_queue:
            partial_tool_calls: dict[int, PartialToolCallMeta] = dict()
            last_tool_call_index = None
            async for chunk in stream:
                if chunk.choices is None or len(chunk.choices) == 0:
                    continue
                choice = chunk.choices[0]

                for tool_call in choice.delta.tool_calls or []:
                    function = tool_call.function
                    function_index = tool_call.index
                    assert function_index is not None, f"Tool call index is None for tool call {tool_call}"
                    function_id = tool_call.id
                    function_name = function.name if function else None
                    function_arguments = function.arguments if function else None
                    if prev_function_call := partial_tool_calls.get(function_index):
                        if function_arguments:
                            new_function_arguments = (prev_function_call.arguments or "") + function_arguments
                        else:
                            new_function_arguments = prev_function_call.arguments
                        partial_tool_calls[function_index] = PartialToolCallMeta(
                            name=prev_function_call.name,
                            arguments=new_function_arguments,
                            index=function_index,
                            id=prev_function_call.id
                        )
                    else:
                        if self.verbose:
                            print(f"Tool Call: {function_name}", end="")
                        assert function_name is not None, f"Tool call name is None for tool call {tool_call}"
                        assert function_id is not None, f"Tool call id is None for tool call {tool_call}"
                        partial_tool_calls[function_index] = PartialToolCallMeta(
                            name=function_name,
                            arguments=function_arguments,
                            index=function_index,
                            id=function_id
                        )
                    # if the model is producing a new tool call, we can assume the current partial tool call is finished generating
                    if last_tool_call_index is not None and function_index != last_tool_call_index:
                        tool_call = partial_tool_calls.pop(function_index).to_tool_call()
                        # runs the tool call without blocking and in correct order
                        await tool_call_queue.add_to_queue(execute_and_consume_tool_results(tool_call, tool_context))
                    last_tool_call_index = function_index
                    if self.verbose:
                        print(function_arguments, end="")

                # yield chunk
                yield chunk

            # if the generation is finished, we can assume the current partial tool calls are finished generating
            tool_calls = [f.to_tool_call() for f in partial_tool_calls.values()]
            for tool_call in tool_calls:
                # runs the tool call without blocking and in correct order
                await tool_call_queue.add_to_queue(execute_and_consume_tool_results(tool_call, tool_context))


class AsyncChatClient:
    def __init__(
        self,
        auth: OpenAIAuthConfig,
        model: OpenAILanguageModelConfig,
        messages: Optional[list[ChatMessageMeta]] = None,
        log_tool_calls: bool = False,
        enforce_system_header: bool = False
    ):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.auth = auth
        self.model = model
        self.messages = messages or []
        self.log_tool_calls = log_tool_calls
        self.enforce_system_header = enforce_system_header

        if messages is not None:
            assert isinstance(messages, list), \
                f"expected messages to be of type `list[ChatMessageMeta]` or be None, but got `{messages}`"
            for m in messages:
                assert isinstance(m, ChatMessageMeta), \
                    f"expected messages to be of type `list[ChatMessageMeta]` or be None, but at least one element in the list is not of type `ChatMessageMeta`, got `{messages}`"

        self.system_prompt = None
        self.rearrange_predicate = None

        # tools
        self.tool_manager = AsyncToolManager()
        self.tool_manager.tool_results_consumer = self.messages.extend

        self.session = AsyncOpenAI(
            api_key=self.auth.api_key,
            base_url=self.auth.base_url,
        )

    def add_tool(self, tool: AsyncTool):
        """Register a tool instance implementing the AsyncTool protocol."""
        self.tool_manager.add_tool(tool)

    def set_rearrange_predicate(self, predicate: Predicate):
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
        return (self.system_prompt or "")

    def add_message(self, message: ChatMessageMeta | str) -> ChatMessageMeta:
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
            message = ChatMessageMeta(role, message)
        elif not isinstance(message, ChatMessageMeta):
            raise ValueError(f"expected message to be a ChatMessageMeta or a string, but got {message}.")
        self.messages.append(message)
        return message

    def set_messages(self, messages: list[ChatMessageMeta]):
        assert isinstance(messages, list), f"Invalid messages \"{messages}\"."
        self.messages = messages

    def get_messages(self):
        return self.messages

    async def stream_chat_completion(self, enable_timestamps: bool = True, system_prompt: Optional[str | ChatMessageMeta] = None) -> AsyncStream[ChatCompletionChunk]:
        openai_messages: list = await self.get_openai_messages_dict(
            enable_timestamps=enable_timestamps,
            system_prompt=system_prompt
        )
        kwargs = dict(
            model=self.model.id,
            messages=openai_messages,
            temperature=0.7,
            top_p=0.9,
            max_tokens=1024,
            parallel_tool_calls=True,
            reasoning_effort="high",
            stream=True,
        )
        # If tools are registered, add them to the request
        if self.tool_manager.tools:
            kwargs["tools"] = self.tool_manager.get_tools_schema()

        # Debugging: print the request to a file
        # with open("last-request.json", "w", encoding="utf-8") as f:
        #     json.dump(kwargs, f, ensure_ascii=False, indent=4)

        return await self.session.chat.completions.create(**kwargs)  # type: ignore

    async def get_openai_messages_dict(self, enable_timestamps: bool = True, system_prompt: Optional[str | ChatMessageMeta] = None) -> list[dict]:
        if len(self.messages) == 0:
            return list()

        system_prompt = system_prompt or self.get_system_prompt()
        messages = self.enforce_approximate_context_limit(
            system_prompt.content if isinstance(system_prompt, ChatMessageMeta) else system_prompt,  # type: ignore
            self.messages.copy()
        )

        openai_messages = [ChatMessageUtils.from_meta(msg).to_openai_dict(
            timestamps=enable_timestamps) for msg in messages]
        # add system prompt before to the last user message message to ensure it is in the
        # model's context but also don't disrupt the conversation or tool calling
        if exists(system_prompt):
            if not isinstance(system_prompt, ChatMessageMeta):
                system_prompt = ChatMessageMeta(
                    role=ChatRole.SYSTEM,
                    content=system_prompt
                )
            system_message = ChatMessageUtils.from_meta(system_prompt).to_openai_dict(timestamps=enable_timestamps)

            insert_index = 0
            # some models only support system message as the very first message
            if not self.enforce_system_header:
                for i, message in enumerate(messages):
                    if message.role == ChatRole.USER:
                        insert_index = i
            openai_messages.insert(insert_index, system_message)
        return openai_messages

    def enforce_approximate_context_limit(self, system_prompt: str, messages: list[ChatMessageMeta]):
        system_prompt_size = len(system_prompt) if system_prompt else 0
        request_size = system_prompt_size
        for cutoff_index, message in enumerate(messages):
            role = message.role
            context = message.content or ""
            # TODO: better approximate images
            # TODO: audio should be approximated with a function of it's duration
            request_size += len(role) + len(context) + 1024 * len(message.audio_hashes) + \
                1024 * len(message.image_hashes)
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

    async def stream_completion(self, start_think_tag: str = "<think>", end_think_tag: str = "</think>", temporal: bool = False, system_prompt: Optional[str | ChatMessageMeta] = None):
        if temporal:
            orig_messages = self.messages.copy()

        lookbehind_buffer: str = ""
        max_buffer_size = max(len(start_think_tag), len(end_think_tag))

        is_thinking = False

        async for char in self.stream_request(system_prompt=system_prompt):
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

        if temporal:
            self.messages = orig_messages  # pyright: ignore[reportPossiblyUnboundVariable]

    def create_tool_context(self, reference_message: ChatMessageMeta):
        return ToolContext(
            reference_message=reference_message,
        )

    async def stream_request(
        self,
        verbose: bool = logging.getLevelName(logging.root.level).lower() == "debug",
        reference_message: ChatMessageMeta | None = None,
        system_prompt: Optional[str | ChatMessageMeta] = None
    ):
        # reference_message is the last user message in which we are responding to, it contains
        # information about the current channel and holds special metadata
        reference_message = reference_message or self.messages[-1]
        assert reference_message.role in [
            ChatRole.USER, ChatRole.SYSTEM
        ], f"`reference_message` must be a USER or SYSTEM message, but got a message with the role of \"{reference_message.role}\"."

        async with await self.stream_chat_completion(system_prompt=system_prompt) as stream:
            response = ""
            finish_reason = None
            async for event in self.tool_manager.stream_tool_calls(stream, tool_context=self.create_tool_context(reference_message=reference_message)):
                if event.choices is None or len(event.choices) == 0:
                    continue
                choice = event.choices[0]

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
                    # pyright: ignore[reportAttributeAccessIssue]
                    print(choice.delta.reasoning_content, end="", flush=True)

            if verbose:
                print()

        if response:
            self.messages.append(ChatMessageMeta(
                role=ChatRole.ASSISTANT,
                content=response
            ))

        if finish_reason == "tool_calls":
            # Recursively call stream_request and yield its results
            async for chunk in self.stream_request(reference_message=reference_message):
                yield chunk

    async def stream_ask(self, message: str | ChatMessageMeta, temporal: bool = False, system_prompt: Optional[str] = None):
        if isinstance(message, str):
            message = ChatMessageMeta(ChatRole.USER, message)
        else:
            assert isinstance(message, ChatMessageMeta), "Message must be a string or a ChatMessageMeta."

        assert message.role == ChatRole.USER, "Message must be from the user."
        self.messages.append(message)

        async for chunk in self.stream_completion(temporal=temporal, system_prompt=system_prompt):
            yield chunk

    def state_dict(self):
        return dict(
            messages=[msg.to_dict() for msg in self.messages]
        )

    def load_state_dict(self, data: dict):
        self.messages = [ChatMessageMeta.from_dict(msg) for msg in data.get("messages") or []]


class AsyncChatbotInstance(AsyncChatClient):
    def __init__(self,
                 uuid: int | str,
                 hash_prefix: str,
                 *,
                 tools: list[AsyncTool] = [],
                 actions: list[AsyncAction] = [],
                 bot: PixiClient | None = None,
                 **client_kwargs,
                 ):

        super().__init__(**client_kwargs)

        self.logger = logging.getLogger(self.__class__.__name__)

        assert bot is not None
        self.bot: PixiClient = bot

        assert exists(uuid) and isinstance(uuid, (int, str)), f"Invalid uuid \"{uuid}\"."
        assert exists(hash_prefix) and isinstance(hash_prefix, str), f"Invalid hash_prefix \"{hash_prefix}\"."

        self.id = str(uuid)
        self.prefix = hash_prefix
        self.path = AsyncChatbotInstance.get_save_path(id=self.id, hash_prefix=self.prefix)

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
        self.last_used_at = time.monotonic()
        self._active_users = 0

        if not self.messages:
            self.add_message(ChatMessageMeta(
                role=ChatRole.ASSISTANT,
                content="[NOTE: I accept the guidelines of the system, I use the SEND to respond nicely] [SEND: OK!, Let's begin!]",
                bot=self.bot
            ))

        self.scheduler = AsyncScheduler()
        self.news_task: Any | None = None

        # actions
        self.action_manager = AsyncActionManager()

        # async states
        self.channel_active_tasks: defaultdict[str, list[asyncio.Task]] = defaultdict(list)

        # register all the tools
        for tool in tools:
            if not tool.should_register(self):
                continue
            self.add_tool(tool)

        # register all the actions
        for action in actions:
            if not action.should_register(self):
                continue
            self.add_action(action)

    @contextmanager
    def use(self):
        """Keep this instance resident until the current operation finishes."""
        self._active_users += 1
        try:
            yield self
        finally:
            self._active_users -= 1
            self.last_used_at = time.monotonic()

    @property
    def is_busy(self) -> bool:
        return (
            self._active_users > 0
            or self.scheduler.pending_count > 0
            or self.news_task is not None
            or any(
                not task.done()
                for tasks in self.channel_active_tasks.values()
                for task in tasks
            )
        )

    @staticmethod
    def get_save_path(id: str, hash_prefix: str):
        uuid_hash = hashlib.sha256(f"{hash_prefix}_{id}".encode("utf-8")).hexdigest()
        path = str(PixiPaths.userdata() / f"{hash_prefix}_{uuid_hash}.json")
        return path

    def schedule(self, id: str, delay: float, callback: Callable[[], Awaitable[None]]) -> bool:
        """Schedule a callback while protecting its execution from eviction."""
        async def run_callback():
            with self.use():
                await callback()

        return self.scheduler.schedule(id=id, delay=delay, callback=run_callback)

    def schedule_action(self, action: AsyncAction, value: str | None, action_context: ActionContext, id: str, delay: float) -> bool:
        """Schedule an action instance with its value, without parsing inline syntax."""
        async def execute_scheduled():
            if self.action_manager.on_action:
                self.action_manager.on_action(action.name, value)
            await self.action_manager._invoke_action(action, action_context, value)
        return self.schedule(id=id, delay=delay, callback=execute_scheduled)

    def cancel_schedule(self, id: str) -> bool:
        """Convenience wrapper for self.scheduler.cancel."""
        return self.scheduler.cancel(id)

    def cancel_all_schedules(self):
        """Convenience wrapper for self.scheduler.cancel_all."""
        self.scheduler.cancel_all()

    def add_action(self, action: AsyncAction):
        """Register an action instance implementing the AsyncAction protocol."""
        self.action_manager.add_action(action)

    def add_message(self, message: ChatMessageMeta | str, default_role: ChatRole = ChatRole.USER) -> ChatMessageMeta:
        """
        Add a message to the conversation, and adds a reference to the bot to the messages as well.

        if message is a string, tries to determine the role of the message based on the last message recieved.
        """
        self.actions_since_last_message = 0
        self.last_used_at = time.monotonic()
        if isinstance(message, str):
            message = ChatMessageMeta(default_role, message, bot=self.bot)

        if isinstance(message, ChatMessageMeta):
            message.bot = self.bot  # this is intended to be handled by this class
            return super().add_message(message)
        else:
            raise TypeError(f"expected message to be a string or a ChatMessageMeta, but got {type(message)}.")

    def update_realtime(self, data: dict):
        self.realtime_data.update(data)

    def get_realtime_data(self):
        return json.dumps(self.realtime_data | dict(date=time.strftime("%a %d %b %Y, %I:%M%p")), ensure_ascii=False, indent=3)

    def create_tool_context(self, reference_message: ChatMessageMeta):
        context = super().create_tool_context(
            reference_message=reference_message
        )
        context.parent_instance = self
        return context

    # override system prompt from the base class
    def get_system_prompt(self):
        return self.system_prompt_template.format(
            persona=self.persona,
            examples=self.examples,
            realtime=self.get_realtime_data(),
            actions=self.action_manager.get_prompt()
        )

    async def stream_call(self, reference_message: ChatMessageMeta, message: Optional[str] = None, temporal: bool = False, system_prompt: Optional[str] = None):
        with self.use():
            if temporal:
                prev_visible_actions_taken = self.action_manager.visible_actions_taken
                orig_messages = self.messages.copy()

            if message:
                self.add_message(message)

            non_response = "".join([char async for char in self.action_manager.consume(
                stream=self.stream_completion(temporal=temporal, system_prompt=system_prompt),
                action_context=ActionContext(
                    reference_message=reference_message,
                    parent_instance=self
                )
            )])
            if temporal:
                self.action_manager.visible_actions_taken = prev_visible_actions_taken # pyright: ignore[reportPossiblyUnboundVariable]
                self.messages = orig_messages  # pyright: ignore[reportPossiblyUnboundVariable]
            return non_response.strip() or None

    async def concurrent_channel_stream_call(self, channel_id: str, reference_message: ChatMessageMeta):
        assert channel_id, "channel_id is None"

        await self.cancel_channel_active_tasks(channel_id)

        async def stream_call_task():
            try:
                await self.stream_call(reference_message)
            except asyncio.CancelledError:
                self.logger.warning(
                    f"stream_call task was cancelled inside {self.id} in channel {channel_id}"
                )
                # propegate the cancellation
                raise

        task = asyncio.create_task(stream_call_task())
        self.channel_active_tasks[channel_id].append(task)
        task.add_done_callback(lambda t: self.channel_active_tasks[channel_id].remove(t))
        return task

    async def cancel_channel_active_tasks(self, channel_id: str):
        for task in self.channel_active_tasks[channel_id]:
            task.cancel()

    @property
    def forum_id(self) -> Optional[int]:
        """Extract the forum/guild ID from the instance identifier."""
        if self.id.startswith("forum#"):
            return int(self.id.split("#")[1])
        return None

    @property
    def chat_id(self) -> Optional[int]:
        """Extract the chat ID from the instance identifier."""
        if self.id.startswith("chat#"):
            return int(self.id.split("#")[1])
        return None

    def start_news_background_task(self, news_config, reflection_api):
        """Start the proactive news background task for this instance."""
        from ...bot.news import NewsBackgroundTask

        self.news_task = NewsBackgroundTask(
            news_config=news_config,
            reflection_api=reflection_api,
            instance=self,
        )
        self.news_task.start()

    def stop_news_background_task(self):
        """Stops the proactive news background task if running."""
        if self.news_task is not None:
            self.news_task.stop()
            self.news_task = None

    def toggle_notes(self):
        self.is_notes_visible = not self.is_notes_visible
        return self.is_notes_visible

    def to_dict(self):
        return dict(
            uuid=self.id,
            prefix=self.prefix,
            messages=[msg.to_dict() for msg in self.messages],
            is_notes_visible=self.is_notes_visible,
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
            self.messages[:] = [ChatMessageMeta.from_dict(d) for d in data.get("messages", [])]
            self.is_notes_visible = data.get("is_notes_visible", False)
        except json.decoder.JSONDecodeError:
            self.logger.warning(f"Unable to load the instance save file `{self.path}`, using default values.")
        except FileNotFoundError:
            if not not_found_ok:
                raise FileNotFoundError(f"Unable to find the instance save file {self.path}`.")
        except Exception:
            self.logger.exception(f"Unable to load the instance save file {self.path}`, using default values.")


class ChatbotInstanceRegistry:
    hash_prefix: str
    instances: dict[str, AsyncChatbotInstance] = {}
    tools: list[AsyncTool] = []
    actions: list[AsyncAction] = []
    bot: Any | None = None
    logger = logging.getLogger("ChatbotInstanceRegistry")

    @staticmethod
    def init(hash_prefix: str, bot: Any):
        ChatbotInstanceRegistry.hash_prefix = hash_prefix
        ChatbotInstanceRegistry.bot = bot

    @staticmethod
    def register_action(action: AsyncAction):
        """
        Register an action

        actions are inline tools with only one parameter that can be used by all models (even those without tool
        calling capabilities), their descriptions are dynamically added to the system prompt at runtime
        """

        ChatbotInstanceRegistry.actions.append(action)

    @staticmethod
    def register_tool(tool: AsyncTool):
        """
        Register a tool (function) for tool calling.
        """

        ChatbotInstanceRegistry.tools.append(tool)

    @staticmethod
    def new_instance(identifier: str, **kwargs) -> AsyncChatbotInstance:
        instance = AsyncChatbotInstance(
            identifier,
            ChatbotInstanceRegistry.hash_prefix,
            **kwargs,
            tools=ChatbotInstanceRegistry.tools,
            actions=ChatbotInstanceRegistry.actions,
            bot=ChatbotInstanceRegistry.bot
        )
        ChatbotInstanceRegistry.instances.update({instance.id: instance})
        return instance

    @staticmethod
    def get(identifier: str, or_create: bool = True, **kwargs) -> AsyncChatbotInstance | None:
        if instance := ChatbotInstanceRegistry.instances.get(identifier):
            instance.last_used_at = time.monotonic()
            return instance
        if or_create:
            instance = ChatbotInstanceRegistry.new_instance(identifier, **kwargs)
            instance.load(not_found_ok=True)
            ChatbotInstanceRegistry.logger.info(f"created new chatbot instance {instance.id=}.")
            return instance

    @staticmethod
    def evict_idle(idle_timeout: float) -> int:
        """Save and unload idle instances without deleting their saved history."""
        now = time.monotonic()
        evicted = 0
        for identifier in list(ChatbotInstanceRegistry.instances):
            instance = ChatbotInstanceRegistry.instances[identifier]
            if instance.is_busy or now - instance.last_used_at < idle_timeout:
                continue
            try:
                instance.save()
            except Exception:
                ChatbotInstanceRegistry.logger.exception(
                    "Failed to save idle instance %s; keeping it loaded.", identifier
                )
                continue
            del ChatbotInstanceRegistry.instances[identifier]
            evicted += 1
            ChatbotInstanceRegistry.logger.info("Unloaded idle chatbot instance %s.", identifier)
        return evicted

    @staticmethod
    def remove(identifier: str):
        save_path = AsyncChatbotInstance.get_save_path(id=identifier, hash_prefix=ChatbotInstanceRegistry.hash_prefix)
        if os.path.exists(save_path):
            os.remove(save_path)
            ChatbotInstanceRegistry.logger.info(f"removed chatbot instance {identifier=}.")
        if identifier in ChatbotInstanceRegistry.instances.keys():
            del ChatbotInstanceRegistry.instances[identifier]
