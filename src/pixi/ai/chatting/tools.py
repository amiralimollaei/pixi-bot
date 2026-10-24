from __future__ import annotations

import inspect
import json
import logging
from typing import AsyncGenerator, AsyncIterator, Awaitable, Callable

from ...async_utils import CoroutineQueueExecutor
from ...model.chat import ChatMessageMeta, ToolCallMeta
from ...model.enums import ChatRole
from ...interfaces.models import ChatEvent, ToolCallDelta, ToolDefinition
from .callbacks import AsyncTool, PartialToolCallMeta, ToolContext


class AsyncToolManager:
    def __init__(self, log_tool_calls: bool = True, verbose: bool = False):
        self.logger = logging.getLogger(type(self).__name__)
        self.log_tool_calls = log_tool_calls
        self.verbose = verbose
        self.tools: dict[str, AsyncTool] = {}
        self.on_tool: Callable[[ToolCallMeta], None] | None = None
        self.tool_results_consumer: Callable[[list[ChatMessageMeta]], Awaitable[None] | None] | None = None

    def add_tool(self, tool: AsyncTool):
        self.tools[tool.name.lower()] = tool

    def get_tools_schema(self) -> list[ToolDefinition]:
        return [ToolDefinition(tool.name, tool.description, tool.parameters) for tool in self.tools.values()]

    async def get_tool_results(self, calls: list[ToolCallMeta], context: ToolContext) -> list[ChatMessageMeta]:
        if not calls:
            return []
        results = [ChatMessageMeta(ChatRole.ASSISTANT, content=None, tool_calls=calls)]
        log = self.logger.info if self.log_tool_calls else self.logger.debug
        for call in calls:
            tool = self.tools.get(call.name.lower())
            if tool is None:
                result = f"Tool '{call.name}' was not found."
                self.logger.warning(result)
            else:
                arguments = call.arguments or {}
                log("Calling %s(%s)...", call.name, arguments)
                try:
                    result = json.dumps(await tool.call(context, **arguments), ensure_ascii=False, indent=3)
                except Exception as error:
                    self.logger.exception("Error calling tool '%s'", call.name)
                    result = f"Tool error: {error}"
                log("Call %s(%s): %s", call.name, arguments, result)
            results.append(ChatMessageMeta(ChatRole.TOOL, content=result, tool_call_id=call.id))
        return results

    async def stream_tool_calls(
        self,
        stream: AsyncIterator[ChatEvent],
        tool_context: ToolContext,
    ) -> AsyncGenerator[ChatEvent, None]:
        """Execute complete calls during streaming; publish results after exhaustion."""
        partial: dict[int, PartialToolCallMeta] = {}
        queued: set[int] = set()
        completed_results: list[list[ChatMessageMeta]] = []
        async with CoroutineQueueExecutor() as queue:
            async def execute(call: ToolCallMeta):
                if self.on_tool is not None:
                    self.on_tool(call)
                completed_results.append(await self.get_tool_results([call], tool_context))

            async for event in stream:
                if isinstance(event, ToolCallDelta):
                    previous = partial.get(event.index)
                    if previous is None:
                        assert event.id is not None and event.name is not None, "Incomplete initial tool call"
                        partial[event.index] = PartialToolCallMeta(
                            name=event.name, index=event.index, id=event.id, arguments=event.arguments,
                        )
                    else:
                        if event.name:
                            previous.name += event.name
                        if event.arguments:
                            previous.arguments = (previous.arguments or "") + event.arguments

                    # Preserve call order, even when argument deltas are interleaved.
                    for index, pending in partial.items():
                        if index in queued:
                            continue
                        if not pending.arguments:
                            break
                        try:
                            call = pending.to_tool_call()
                        except json.JSONDecodeError:
                            break
                        if not isinstance(call.arguments, dict):
                            break
                        await queue.add_to_queue(execute(call))
                        queued.add(index)
                yield event

            for index, call in partial.items():
                if index not in queued:
                    await queue.add_to_queue(execute(call.to_tool_call()))

        for results in completed_results:
            if self.tool_results_consumer is None:
                self.logger.warning("tool results are being ignored")
            else:
                try:
                    value = self.tool_results_consumer(results)
                    if inspect.isawaitable(value):
                        await value
                except Exception:
                    self.logger.exception("Error consuming tool results")
