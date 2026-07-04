from enum import IntFlag, auto


class PixiFeatures(IntFlag):
    """
    A bitflag containing all the toggleable features of pixi
    """

    ToolCalling = auto()
    ToolLogging = auto()
    WikiSearch = auto()
    GIFSearch = auto()
    ImageSupport = auto()
    AudioSupport = auto()
    NewsProactive = auto()

    @classmethod
    def all(cls) -> 'PixiFeatures':
        return cls.ToolCalling | cls.ToolLogging | cls.WikiSearch | cls.GIFSearch | cls.ImageSupport | cls.AudioSupport | cls.NewsProactive

    @classmethod
    def default(cls) -> 'PixiFeatures':
        return cls.ToolCalling | cls.ToolLogging | cls.GIFSearch

    @classmethod
    def empty(cls) -> 'PixiFeatures':
        return cls(0)
