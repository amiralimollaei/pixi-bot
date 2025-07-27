from typing import Any, Callable, Coroutine

AsyncFunction = Callable[..., Coroutine[Any, Any, Any]]
AsyncPredicate = Callable[..., Coroutine[Any, Any, bool]]
