from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from typing import Callable, Generator

from pixi.ai.chatting.callbacks import AsyncAction, InvocationContext
from pixi.async_utils import CoroutineQueueExecutor


class ActionOutcome:
    """Visible actions completed during one consumption."""

    def __init__(self):
        self.has_visible_actions = False


class AsyncActionManager:
    def __init__(self):
        self.logger = logging.getLogger(type(self).__name__)
        self.actions: dict[str, AsyncAction] = {}
        self.on_action: Callable[[str, str | None], None] | None = None

    def add_action(self, action: AsyncAction):
        self.actions[action.name.lower()] = action

    def get_prompt(self):
        return "\n".join(
            f"- [{action.name}:<{action.field_name}>]: {action.description or 'no description'}"
            for action in self.actions.values()
        )

    async def execute_action(
        self, action_str: str, action_context: InvocationContext, outcome: ActionOutcome
    ):
        text = action_str[1:-1]
        separator_idx = text.index(":") if ":" in text else None
        if separator_idx:
            name = text[:separator_idx].strip()
            value = text[separator_idx + 1 :].strip()
        else:
            name = text
            value = None
        action = self.actions.get(name.lower())
        if action is None:
            if self.on_action:
                self.on_action(name, value)
            self.logger.error(
                'Model tried to use the action "%s", which is not implemented.', name
            )
            return
        await self.invoke_action(action, action_context, value, outcome, name=name)

    async def invoke_action(
        self,
        action: AsyncAction,
        action_context: InvocationContext,
        value: str | None,
        outcome: ActionOutcome | None = None,
        *,
        name: str | None = None,
    ):
        if self.on_action:
            self.on_action(name if name is not None else action.name, value)
        try:
            await action.call(action_context, value)
            if action.is_visible and outcome is not None:
                outcome.has_visible_actions = True
        except Exception:
            self.logger.exception("an error occurred during action")

    async def consume(
        self,
        stream: Iterator | Generator | AsyncIterator,
        action_context: InvocationContext,
        outcome: ActionOutcome,
    ):
        depth = 0
        action = ""
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
                        await queue.add_to_queue(
                            self.execute_action(action, action_context, outcome)
                        )
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
