import json
import time

from .enums import ChatRole
from .utils import exists, format_time_ago
from .caching import AudioCache, ImageCache, UnsupportedMediaException


class FunctionCall:
    def __init__(self, name: str, arguments: dict, index: int, id: str):
        assert exists(name) and isinstance(name, str), f"expected `name` to be of type `str` but got {name}"
        assert exists(arguments) and isinstance(
            arguments, dict), f"expected `arguments` to be of type `dict` but got {arguments}"
        assert exists(index) and isinstance(index, int), f"expected `index` to be of type `int` but got {index}"
        assert exists(id) and isinstance(id, str), f"expected `id` to be of type `str` but got {id}"

        self.name = name
        self.arguments = arguments
        self.index = index
        self.id = id

    def to_dict(self) -> dict:
        return dict(
            name=self.name,
            arguments=self.arguments,
            index=self.index,
            id=self.id
        )

    def to_openai_dict(self) -> dict:
        return dict(
            type="function",
            id=self.id,
            function=dict(
                name=self.name,
                arguments=json.dumps(self.arguments, ensure_ascii=False)
            )
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'FunctionCall':
        return cls(
            name=data.get("name"),
            arguments=data.get("arguments"),
            index=data.get("index"),
            id=data.get("id")
        )


class ChatMessage:
    def __init__(
        self,
        role: ChatRole,
        content: str,
        metadata: dict = None,
        message_time: float = -1,
        images: ImageCache | list[ImageCache] = None,
        audio: AudioCache | list[AudioCache] = None,
        tool_calls: list[FunctionCall] = None,
        tool_call_id: str = None
    ):
        assert role is not None, f"expected `role` to be of type `Role` and not be None, but got `{role}`"
        if images is not None:
            assert isinstance(images, (ImageCache, list)
                              ), f"Images must be of type ImageCache or list[ImageCache], but got {images}."
            if isinstance(images, ImageCache):
                images = [images]
            else:
                assert all([isinstance(i, ImageCache) for i in images]
                           ), f"Images must be of type ImageCache or list[ImageCache], but at least one of the list elements is not of type ImageCache, got {images}."
        else:
            images = []
        
        if audio is not None:
            assert isinstance(audio, (AudioCache, list)
                              ), f"audio must be of type AudioCache or list[AudioCache], but got {audio}."
            if isinstance(audio, AudioCache):
                audio = [audio]
            else:
                assert all([isinstance(i, AudioCache) for i in audio]
                           ), f"audio must be of type AudioCache or list[AudioCache], but at least one of the list elements is not of type ImageCache, got {audio}."
        else:
            audio = []

        # validating each role's requirements
        match role:
            case ChatRole.SYSTEM:
                assert exists(content, True) and isinstance(
                    content, str), f"expected SYSTEM to have a `content` of type `str` but got `{content}`"
                assert not exists(
                    metadata), f"expected SYSTEM to not have `metadata` (e.g. the metadata should be None) but got `{metadata}`"
                assert not exists(
                    tool_calls), f"expected SYSTEM to not have `tool_calls` (e.g. the tool_calls should be None) but got `{tool_calls}`"
                assert not exists(
                    tool_call_id), f"expected SYSTEM to not have `tool_call_id` (e.g. the tool_call_id should be None) but got `{tool_call_id}`"
                assert not exists(
                    images), f"Images can only be attached to user messages, but got {images} for role SYSTEM"

            case ChatRole.ASSISTANT:
                assert content is None or isinstance(
                    content, str), f"expected ASSISTANT to have a `content` of type `str` but got `{content}`"
                assert not exists(
                    metadata), f"expected ASSISTANT to not have `metadata` (e.g. the metadata should be None) but got `{metadata}`"
                assert not exists(
                    tool_call_id), f"expected ASSISTANT to not have `tool_call_id` (e.g. the tool_call_id should be None) but got `{tool_call_id}`"
                assert not exists(
                    images), f"Images can only be attached to user messages, but got {images} for role ASSISTANT"

                if exists(tool_calls):
                    assert not exists(
                        content, True), f"expected ASSISTANT to not have `content` (e.g. the content should be None) while `tool_calls` is not None but got `{content}`"
                    assert isinstance(
                        tool_calls, list), f"expected TOOL to have `tool_calls` of type `list[FunctionCall]` but got `{tool_calls}`"
                    for tc in tool_calls:
                        assert isinstance(
                            tc, FunctionCall), f"expected TOOL to have `tool_calls` of type `list[FunctionCall]` but at least one of the list elements is not of type FunctionCall, got `{tool_calls}`"

            case ChatRole.USER:
                assert exists(content, True) and isinstance(
                    content, str), f"expected USER to have a `content` of type `str` but got `{content}`"
                assert not exists(metadata) or isinstance(
                    metadata, dict), f"expected `metadata` to be None or `metadata` to be of type `dict` but got `{metadata}`"
                assert not exists(tool_calls) or (isinstance(tool_calls, list) and tool_calls == [
                ]), f"expected SYSTEM to not have `tool_calls` (e.g. the tool_calls should be None) but got `{tool_calls}`"
                assert not exists(
                    tool_call_id), f"expected USER to not have `tool_call_id` (e.g. the tool_call_id should be None) but got `{tool_call_id}`"

            case ChatRole.TOOL:
                assert exists(content, True) and isinstance(
                    content, str), f"expected TOOL to have a `content` of type `str` but got `{content}`"
                assert not exists(
                    metadata), f"expected TOOL to not have `metadata` (e.g. the metadata should be None) but got `{metadata}`"
                assert exists(tool_call_id) and isinstance(
                    tool_call_id, str), f"expected TOOL to have a `tool_call_id` of type `str` but got `{tool_call_id}`"
                assert not exists(
                    images), f"Images can only be attached to user messages, but got {images} for role TOOL"

            case _:
                raise ValueError(f"Invalid role \"{role}\".")

        self.role = role
        self.content = content
        self.metadata = metadata
        self.time = (message_time if message_time > 0 else time.time())

        self.images = images  # Should be an ImageCache instance or a list of ImageCache instances or None
        self.audio = audio

        # store function calls and function results
        self.tool_calls: list[FunctionCall] = tool_calls
        self.tool_call_id = tool_call_id

    def to_dict(self) -> dict:
        return dict(
            role=self.role,
            content=self.content,
            metadata=self.metadata,
            time=self.time,
            images=[x.to_dict() for x in self.images or []],
            audio=[x.to_dict() for x in self.audio or []],
            tool_calls=[x.to_dict() for x in self.tool_calls or []],
            tool_call_id=self.tool_call_id
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'ChatMessage':
        return cls(
            role=data["role"],
            content=data.get("content"),
            metadata=data.get("metadata"),
            message_time=data.get("time", time.time()),
            images=[ImageCache.from_dict(i) for i in data.get("images", [])],
            tool_calls=[FunctionCall.from_dict(d) for d in data.get("tool_calls", [])],
            tool_call_id=data.get("tool_call_id")
        )

    def to_openai_dict(self, timestamps: bool = True) -> dict:
        openai_dict = dict(role=self.role)
        match self.role:
            case ChatRole.USER:
                content = [f"User: {self.content}"]
                if timestamps:
                    timefmt = format_time_ago(time.time()-self.time)
                    content.append(f"Time: {timefmt}")
                if self.metadata is not None:
                    content += [
                        "Metadata:",
                        ""
                        "```json",
                        json.dumps(self.metadata, ensure_ascii=False),
                        "```"
                    ]
                content_dict = [dict(type="text", text="\n".join(content))]
                for img in self.images:
                    content_dict.append(dict(
                        type="image_url",
                        image_url=dict(url=img.to_data_url())
                    ))
                for audio in self.audio:
                    content_dict.append(dict(
                        input_audio = dict(
                            data = audio.to_base64(),
                            format = "wav" # for some reason this value is not used by the API is required to be mp3 or wav
                        ),
                        type="input_audio",
                    ))
                openai_dict.update(dict(content=content_dict))
            case ChatRole.ASSISTANT:
                if exists(self.content, True):
                    openai_dict.update(dict(content=self.content))
                else:
                    openai_dict.update(dict(
                        tool_calls=[i.to_openai_dict() for i in self.tool_calls]
                    ))
            case ChatRole.TOOL:
                openai_dict.update(dict(
                    content=self.content,
                    tool_call_id=self.tool_call_id
                ))
            case _:
                openai_dict.update(dict(content=self.content))
        return openai_dict
