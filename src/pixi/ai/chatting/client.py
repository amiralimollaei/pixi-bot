from __future__ import annotations

import json
import logging
from collections.abc import Generator, Sequence
from contextlib import aclosing, closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import AsyncGenerator

from ...interfaces.messages import MessagesStorage
from ...interfaces.models import ChatEvent, ChatFinished, ChatModel, ContentDelta, ReasoningDelta
from ...model.chat import ChatMessageMeta
from ...model.config import LlamaLanguageModelConfig, OpenAILanguageModelConfig
from ...model.enums import ChatRole
from .callbacks import AsyncTool, Predicate, ToolContext
from .tools import AsyncToolManager


def get_rearranged_messages(messages: list[ChatMessageMeta], predicate: Predicate, n: int = 5) -> list[ChatMessageMeta]:
    selected: list[ChatMessageMeta] = []
    unselected: list[ChatMessageMeta] = []
    for message in reversed(messages):
        if predicate(message) and len(selected) < n:
            selected.append(message)
        else:
            unselected.append(message)
    return list(reversed(unselected)) + list(reversed(selected))


@dataclass
class _HistoryBranch:
    stop: int
    parent: _HistoryBranch | None = None
    messages: list[ChatMessageMeta] = field(default_factory=list)
    active: bool = True


class AsyncChatClient:
    def __init__(
        self,
        *,
        storage: MessagesStorage,
        history_key: str,
        chat_model: ChatModel,
        model: OpenAILanguageModelConfig | LlamaLanguageModelConfig,
        log_tool_calls: bool = False,
        enforce_system_header: bool = False,
    ):
        self.logger = logging.getLogger(type(self).__name__)
        self.storage = storage
        self.history_key = history_key
        self.chat_model = chat_model
        self.model = model
        self.log_tool_calls = log_tool_calls
        self.enforce_system_header = enforce_system_header
        self.system_prompt: str | None = None
        self.rearrange_predicate: Predicate | None = None
        self._history_branch: ContextVar[_HistoryBranch | None] = ContextVar("history_branch", default=None)
        self.tool_manager = AsyncToolManager(log_tool_calls=log_tool_calls)
        self.tool_manager.tool_results_consumer = self._append_messages

    def _active_branch(self) -> _HistoryBranch | None:
        branch = self._history_branch.get()
        return branch if branch is not None and branch.active else None

    @contextmanager
    def detached_history(self):
        """Start background work without inheriting the current request delta."""
        token = self._history_branch.set(None)
        try:
            yield
        finally:
            self._history_branch.reset(token)

    @contextmanager
    def history_scope(self, *, temporal: bool = False):
        """Keep only this request's new messages; commit once on successful completion."""
        parent = self._active_branch()
        branch = _HistoryBranch(parent.stop if parent is not None else self.storage.count(self.history_key), parent)
        token = self._history_branch.set(branch)
        try:
            yield
            if not temporal and branch.messages:
                if parent is not None and parent.active:
                    parent.messages.extend(branch.messages)
                else:
                    self.storage.append(self.history_key, branch.messages)
        finally:
            branch.active = False
            branch.messages.clear()
            branch.parent = None
            self._history_branch.reset(token)

    def _append_messages(self, messages: Sequence[ChatMessageMeta]) -> None:
        branch = self._active_branch()
        if branch is None:
            self.storage.append(self.history_key, messages)
        else:
            branch.messages.extend(messages)

    @property
    def message_count(self) -> int:
        branch = self._active_branch()
        if branch is None:
            return self.storage.count(self.history_key)
        count = branch.stop
        while branch is not None:
            count += len(branch.messages)
            branch = branch.parent
        return count

    def iter_messages(
        self, *, start: int = 0, stop: int | None = None, reverse: bool = False,
    ) -> Generator[ChatMessageMeta, None, None]:
        if start < 0 or (stop is not None and stop < 0):
            raise ValueError("History bounds must be nonnegative.")
        branches = []
        branch = self._active_branch()
        while branch is not None:
            branches.append(branch)
            branch = branch.parent
        branches.reverse()
        base_stop = branches[0].stop if branches else self.storage.count(self.history_key)
        total = base_stop + sum(len(item.messages) for item in branches)
        end = total if stop is None else min(stop, total)
        if start >= end:
            return

        def pending_messages():
            offset = total if reverse else base_stop
            for item in reversed(branches) if reverse else branches:
                if reverse:
                    offset -= len(item.messages)
                first = max(0, start - offset)
                last = min(len(item.messages), end - offset)
                indexes = range(last - 1, first - 1, -1) if reverse else range(first, last)
                for index in indexes:
                    yield item.messages[index]
                if not reverse:
                    offset += len(item.messages)

        if reverse:
            yield from pending_messages()
        if start < base_stop:
            source = self.storage.iter_messages(
                self.history_key, start=start, stop=min(end, base_stop), reverse=reverse,
            )
            try:
                yield from source
            finally:
                close = getattr(source, "close", None)
                if close is not None:
                    close()
        if not reverse:
            yield from pending_messages()

    @property
    def last_message(self) -> ChatMessageMeta | None:
        count = self.message_count
        if count == 0:
            return None
        with closing(self.iter_messages(start=count - 1, stop=count)) as messages:
            return next(messages, None)

    def add_tool(self, tool: AsyncTool):
        self.tool_manager.add_tool(tool)

    def set_rearrange_predicate(self, predicate):
        self.rearrange_predicate = predicate

    def set_system(self, prompt):
        assert prompt is not None and prompt != ""
        self.system_prompt = prompt

    def get_system_prompt(self):
        return self.system_prompt or ""

    def add_message(self, message: ChatMessageMeta | str) -> ChatMessageMeta:
        assert message is not None
        if isinstance(message, str):
            previous = self.last_message
            if previous is None or previous.role == ChatRole.ASSISTANT:
                role = ChatRole.USER
            else:
                role = ChatRole.ASSISTANT
            message = ChatMessageMeta(role, message)
        elif not isinstance(message, ChatMessageMeta):
            raise ValueError(f"expected a ChatMessageMeta or string, got {message!r}")
        self._append_messages((message,))
        return message

    @staticmethod
    def _message_size(message: ChatMessageMeta) -> int:
        size = 96 + len(str(message.role)) + len(message.content or "")
        size += 1024 * (len(message.audio_hashes) + len(message.image_hashes))
        if message.metadata is not None:
            size += len(json.dumps(message.metadata, ensure_ascii=False))
        for call in message.tool_calls:
            size += len(call.name) + len(call.id) + len(json.dumps(call.arguments, ensure_ascii=False)) + 64
        return size

    def get_portable_messages(self, system_prompt: str | ChatMessageMeta | None = None) -> list[ChatMessageMeta]:
        """Materialize only the recent context needed by this model request."""
        prompt = system_prompt or self.get_system_prompt()
        prompt_text = prompt.content if isinstance(prompt, ChatMessageMeta) else (prompt or "")
        budget = self.model.max_context * 4 - len(prompt_text or "") - 96
        if budget <= 0:
            raise ValueError("System prompt exceeds the approximate model context budget.")
        messages: list[ChatMessageMeta] = []
        with closing(self.iter_messages(reverse=True)) as history:
            for message in history:
                size = self._message_size(message)
                if size > budget:
                    if not messages:
                        raise ValueError("Latest message exceeds the approximate model context budget.")
                    break
                budget -= size
                messages.append(message)
        messages.reverse()
        # A context boundary must not leave a tool result without its call.
        first = 0
        while first < len(messages) and messages[first].role == ChatRole.TOOL:
            first += 1
        if first:
            del messages[:first]
        if self.rearrange_predicate is not None:
            messages = get_rearranged_messages(messages, self.rearrange_predicate)
        if prompt:
            system_message = prompt if isinstance(prompt, ChatMessageMeta) else ChatMessageMeta(ChatRole.SYSTEM, prompt)
            insert_index = 0
            if not self.enforce_system_header:
                for index, message in enumerate(messages):
                    if message.role == ChatRole.USER:
                        insert_index = index
            messages.insert(insert_index, system_message)
        return messages

    async def stream_chat_completion(
        self,
        enable_timestamps: bool = True,
        system_prompt: str | ChatMessageMeta | None = None,
    ) -> AsyncGenerator[ChatEvent, None]:
        return self.chat_model.stream(
            self.get_portable_messages(system_prompt),
            tools=self.tool_manager.get_tools_schema(),
            timestamps=enable_timestamps,
        )

    def create_tool_context(self, reference_message: ChatMessageMeta) -> ToolContext:
        return ToolContext(reference_message=reference_message)

    async def stream_request(
        self,
        verbose: bool = logging.getLevelName(logging.root.level).lower() == "debug",
        reference_message: ChatMessageMeta | None = None,
        system_prompt: str | ChatMessageMeta | None = None,
        tool_context: ToolContext | None = None,
    ) -> AsyncGenerator[str, None]:
        reference_message = reference_message or self.last_message
        assert reference_message is not None and reference_message.role in (ChatRole.USER, ChatRole.SYSTEM), "reference_message must be USER or SYSTEM"
        context = tool_context or self.create_tool_context(reference_message)
        source = await self.stream_chat_completion(system_prompt=system_prompt)
        response = ""
        finish_reason = None
        tool_source = self.tool_manager.stream_tool_calls(source, context)
        async with aclosing(source), aclosing(tool_source):
            async for event in tool_source:
                if isinstance(event, ContentDelta):
                    if verbose:
                        print(event.content, end="", flush=True)
                    response += event.content
                    for char in event.content:
                        yield char
                elif isinstance(event, ReasoningDelta) and verbose:
                    print(event.content, end="", flush=True)
                elif isinstance(event, ChatFinished):
                    finish_reason = event.reason
        if verbose:
            print()
        if response:
            self._append_messages((ChatMessageMeta(ChatRole.ASSISTANT, response),))
        if finish_reason == "tool_calls":
            continuation = self.stream_request(
                verbose=verbose,
                reference_message=reference_message,
                system_prompt=system_prompt,
                tool_context=context,
            )
            async with aclosing(continuation):
                async for char in continuation:
                    yield char

    async def stream_completion(
        self,
        start_think_tag: str = "<think>",
        end_think_tag: str = "</think>",
        temporal: bool = False,
        system_prompt: str | ChatMessageMeta | None = None,
        tool_context: ToolContext | None = None,
    ) -> AsyncGenerator[str, None]:
        with self.history_scope(temporal=temporal):
            buffer = ""
            thinking = False
            width = max(len(start_think_tag), len(end_think_tag))
            source = self.stream_request(system_prompt=system_prompt, tool_context=tool_context)
            async with aclosing(source):
                async for char in source:
                    buffer += char
                    if len(buffer) > width:
                        out, buffer = buffer[0], buffer[1:]
                        if not thinking:
                            yield out
                    if buffer.endswith(start_think_tag) and not thinking:
                        thinking = True
                        buffer = ""
                    elif buffer.endswith(end_think_tag) and thinking:
                        thinking = False
                        buffer = ""
            if not thinking:
                for char in buffer:
                    yield char

    async def stream_ask(self, message: ChatMessageMeta | str, temporal=False, system_prompt=None):
        if isinstance(message, str):
            message = ChatMessageMeta(ChatRole.USER, message)
        assert isinstance(message, ChatMessageMeta), "Message must be a string or a ChatMessageMeta."
        assert message.role == ChatRole.USER, "Message must be from the user."
        with self.history_scope(temporal=temporal):
            self.add_message(message)
            source = self.stream_completion(system_prompt=system_prompt)
            async with aclosing(source):
                async for part in source:
                    yield part
