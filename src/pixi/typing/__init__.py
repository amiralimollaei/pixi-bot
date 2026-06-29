from typing import Any, Callable, Coroutine, Optional, Iterator, Generator, AsyncIterator, AsyncGenerator

AsyncFunction = Callable[..., Coroutine[Any, Any, Any]]
AsyncPredicate = Callable[..., Coroutine[Any, Any, bool]]
