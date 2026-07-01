from typing import (Any, AsyncGenerator, AsyncIterator, Callable, Coroutine,
                    Generator, Iterator, Optional)

AsyncPredicate = Callable[..., Coroutine[Any, Any, bool]]
