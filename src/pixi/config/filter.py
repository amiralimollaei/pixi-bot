import dataclasses
from enum import IntEnum, auto


class FilterType(IntEnum):
    Whitelist = auto()
    Blacklist = auto()
    Allow = auto()
    Deny = auto()


@dataclasses.dataclass(frozen=True)
class IdFilter:
    """
    A dataclass that defines a filtering logic based on a list of string identifiers
    """
    
    type: FilterType
    ids: list[str] | None = None

    @classmethod
    def whitelist(cls, ids: list[str]) -> 'IdFilter':
        return IdFilter(
            FilterType.Whitelist, ids=ids
        )

    @classmethod
    def blacklist(cls, ids: list[str]) -> 'IdFilter':
        return IdFilter(
            FilterType.Blacklist, ids=ids
        )

    @classmethod
    def allow(cls) -> 'IdFilter':
        return IdFilter(
            FilterType.Allow
        )

    @classmethod
    def deny(cls) -> 'IdFilter':
        return IdFilter(
            FilterType.Deny
        )

    def is_allowed(self, id: str):
        match self.type:
            case FilterType.Whitelist:
                return id in self.ids if self.ids else True  # yes, even when whitelising, if ids is not defined we allow everything
            case FilterType.Blacklist:
                return id not in self.ids if self.ids else True
            case FilterType.Allow:
                return True
            case FilterType.Deny:
                return False
