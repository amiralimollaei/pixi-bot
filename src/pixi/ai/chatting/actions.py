from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from typing import Callable, Generator

from ...async_utils import CoroutineQueueExecutor
from .callbacks import ActionContext, AsyncAction


class AsyncActionManager:
    def __init__(self):
        self.logger = logging.getLogger(type(self).__name__)
        self.actions: dict[str, AsyncAction] = {}
        self.on_action: Callable[[str, str | None], None] | None = None
        self.visible_actions_taken = 0

    def add_action(self, action: AsyncAction):
        self.actions[action.name.lower()] = action

    def get_prompt(self):
        return "\n".join(
            f"- [{action.name}:<{action.field_name}>]: {action.description or 'no description'}"
            for action in self.actions.values()
        )

    async def execute_action(self, action_str: str, action_context: ActionContext):
        text = action_str[1:-1]
        separator_idx = text.index(":") if ":" in text else None
        if separator_idx:
            name = text[:separator_idx].strip()
            value = text[separator_idx + 1:].strip()
        else:
            name = text
            value = None
        if self.on_action:
            self.on_action(name, value)
        action = self.actions.get(name.lower())
        if action is None:
            self.logger.error('Model tried to use the action "%s", which is not implemented.', name)
            return
        await self._invoke_action(action, action_context, value)

    async def _invoke_action(self, action: AsyncAction, action_context: ActionContext, value: str | None):
        try:
            await action.call(action_context, value)
            if action.is_visible:
                self.visible_actions_taken += 1
        except Exception:
            self.logger.exception("an error occurred during action")

    async def consume(self, stream: Iterator | Generator | AsyncIterator, action_context: ActionContext):
        depth = 0
        action = ""
        self.visible_actions_taken = 0
        async with CoroutineQueueExecutor() as queue:
            async def process(char):
                nonlocal depth, action
                if char == "[":
                    depth += 1
                if depth:
                    action += char
                else:
                    return char
                if char == "]":
                    depth -= 1
                    if depth == 0:
                        await queue.add_to_queue(self.execute_action(action, action_context))
                        action = ""
                return None
            if isinstance(stream, (Iterator, Generator)):
                for c in stream:
                    result = await process(c)
                    if result is not None:
                        yield result
            else:
                async for c in stream:
                    result = await process(c)
                    if result is not None:
                        yield result

    def is_visible_actions_taken(self) -> bool:
        return self.visible_actions_taken > 0
