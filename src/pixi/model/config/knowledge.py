import dataclasses


@dataclasses.dataclass(frozen=True)
class KnowledgeBaseConfig:
    name: str
