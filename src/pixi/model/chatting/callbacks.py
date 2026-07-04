import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable, Concatenate, Coroutine, Optional, ParamSpec

from ..storage.message import ChatMessageMeta, FunctionCall


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
class ToolContext:
    reference_message: Optional[ChatMessageMeta] = None
    parent_instance: Optional[Any] = None
    # more to be added


P = ParamSpec("P")
ToolFunction = Callable[Concatenate[ToolContext, P], Coroutine[Any, Any, Any]]


@dataclass
class ActionContext:
    reference_message: Optional[ChatMessageMeta] = None
    parent_instance: Optional[Any] = None
    # more fields to be added


Predicate = Callable[..., bool]
ActionFunction = Callable[[ActionContext, str], Coroutine[Any, Any, None]]


@dataclass(frozen=True)
class AsyncAction:
    name: str
    field_name: str
    function: ActionFunction
    description: Optional[str] = None
    is_visible: bool = True  # whether or not the action has a visible effect from the user's perspective
    predicate: Optional[Predicate] = None

    def get_syntax(self):
        desc = self.description or "no description"
        return f"[{self.name}:<{self.field_name}>]: {desc}"

    async def call(self, *args, **kwds):
        return await self.function(*args, **kwds)

    def __str__(self):
        return f"<async-action {self.name}>"

    def should_register(self, *args, **kwargs):
        return self.predicate(*args, **kwargs) if self.predicate else True


@dataclass(frozen=True)
class AsyncTool:
    name: str
    function: ToolFunction
    parameters: Optional[dict] = None
    description: Optional[str] = None
    predicate: Optional[Predicate] = None

    def get_syntax(self):
        desc = self.description or "no description"
        func_args_str = ""
        if self.parameters:
            func_args_str = ", ".join([
                (f"{k}=\"{v}\"" if isinstance(v, str) else f"{k}={v}")
                for k, v in self.parameters.items()
            ])
        return f"{self.name}({func_args_str}): {desc}"

    async def call(self, *args, **kwds):
        return await self.function(*args, **kwds)

    def __str__(self):
        return f"<async-tool {self.name}>"

    def should_register(self, *args, **kwargs):
        return self.predicate(*args, **kwargs) if self.predicate else True
