from typing import Protocol, Self


class DictSerializable(Protocol):
    """A protocol for classes that can be serialized to and from dictionaries."""

    @classmethod
    def from_dict(cls, data: dict) -> Self: ...
    def to_dict(self) -> dict: ...