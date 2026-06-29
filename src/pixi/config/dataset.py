import dataclasses


@dataclasses.dataclass(frozen=True)
class DatasetConfig:
    name: str