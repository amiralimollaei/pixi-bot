import json
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class AssistantPersona:
    name: str
    age: Optional[int] = None
    location: Optional[str] = None
    appearance: Optional[str] = None
    background: Optional[str] = None
    likes: Optional[str] = None
    dislikes: Optional[str] = None
    online: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'AssistantPersona':
        return cls(**data)

    @classmethod
    def from_json(cls, file: str) -> 'AssistantPersona':
        with open(file, "rb") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def __str__(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=3)
