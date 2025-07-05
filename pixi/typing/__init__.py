from typing import Any, Callable, Coroutine, Iterator, AsyncGenerator, Optional

AsyncFunction = Callable[..., Coroutine[Any, Any, Any]]
AsyncPredicate = Callable[..., Coroutine[Any, Any, bool]]
