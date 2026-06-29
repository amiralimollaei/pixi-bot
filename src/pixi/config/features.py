from enum import IntFlag, auto


class PixiFeatures(IntFlag):
    """
    A bitflag containing all the toggleable features of pixi
    """
    
    EnableToolCalling = auto()
    EnableToolLogging = auto()
    EnableWikiSearch = auto()
    EnableGIFSearch = auto()
    EnableImageSupport = auto()
    EnableAudioSupport = auto()

    @classmethod
    def all(cls) -> 'PixiFeatures':
        return cls.EnableToolCalling | cls.EnableToolLogging | cls.EnableWikiSearch | cls.EnableGIFSearch | cls.EnableImageSupport | cls.EnableAudioSupport
    
    @classmethod
    def empty(cls) -> 'PixiFeatures':
        return cls(0)
