import json
import time

from .utils import ImageCache, exists, format_time_ago

class FunctionCall:
    def __init__(self, name: str, arguments: dict, index: int, id: str):
        assert name is not None and isinstance(name, str), f"expected `name` to be of type `str` but got {name}"
        assert arguments is not None and isinstance(arguments, dict), f"expected `arguments` to be of type `dict` but got {arguments}"
        assert index is not None and isinstance(index, int), f"expected `index` to be of type `int` but got {index}"
        assert id is not None and isinstance(id, str), f"expected `id` to be of type `str` but got {id}"

        self.name = name
        self.arguments = arguments
        self.index = index
        self.id = id

    def to_dict(self) -> dict:
        return dict(
            name = self.name,
            arguments = self.arguments,
            index = self.index,
            id = self.id
        )
    
    def to_openai_dict(self) -> dict:
        return dict(
            type = "function", 
            id = self.id,
            function = dict(
                name = self.name,
                arguments = json.dumps(self.arguments, ensure_ascii=False)
            )
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'FunctionCall':
        return cls(
            name = data.get("name"),
            arguments = data.get("arguments"),
            index = data.get("index"),
            id = data.get("id")
        )

class Role:
    SYSTEM: str = "system"
    ASSISTANT: str = "assistant"
    USER: str = "user"
    TOOL: str = "tool"

class RoleMessage:
    def __init__(
        self,
        role: str,
        content: str,
        metadata: dict = None, 
        message_time: float = -1, 
        images: ImageCache | list[ImageCache] = None, 
        tool_calls: list[FunctionCall] = None,
        tool_call_id: str = None
    ):
        assert role is not None, f"expected `role` to be or type str and not be None, but got `{role}`"
        if images is not None:
            assert isinstance(images, (ImageCache, list)), f"Images must be of type ImageCache or list[ImageCache], but got {images}."
            if isinstance(images, ImageCache):
                images = [images]
            else:
                assert all([isinstance(i, ImageCache) for i in images]), f"Images must be of type ImageCache or list[ImageCache], but at least one of the list elements is not of type ImageCache, got {images}."
        else:
            images = []
        
        # validating each role's requirements
        match role:
            case Role.SYSTEM:
                assert exists(content, True) and isinstance(content, str), f"expected SYSTEM to have a `content` of type `str` but got `{content}`"
                assert not exists(metadata), f"expected SYSTEM to not have `metadata` (e.g. the metadata should be None) but got `{metadata}`"
                assert not exists(tool_calls), f"expected SYSTEM to not have `tool_calls` (e.g. the tool_calls should be None) but got `{tool_calls}`"
                assert not exists(tool_call_id), f"expected SYSTEM to not have `tool_call_id` (e.g. the tool_call_id should be None) but got `{tool_call_id}`"
                assert not exists(images), f"Images can only be attached to user messages, but got {images} for role SYSTEM"
                
            case Role.ASSISTANT:
                assert exists(content, True) and isinstance(content, str), f"expected ASSISTANT to have a `content` of type `str` but got `{content}`"
                assert not exists(metadata), f"expected ASSISTANT to not have `metadata` (e.g. the metadata should be None) but got `{metadata}`"
                assert not exists(tool_call_id), f"expected ASSISTANT to not have `tool_call_id` (e.g. the tool_call_id should be None) but got `{tool_call_id}`"
                assert not exists(images), f"Images can only be attached to user messages, but got {images} for role ASSISTANT"

                if exists(tool_calls):
                    assert not exists(content, True), f"expected ASSISTANT to not have `content` (e.g. the content should be None) while `tool_calls` is not None but got `{content}`"
                    assert isinstance(list), f"expected TOOL to have `tool_calls` of type `list[FunctionCall]` but got `{tool_calls}`"
                    assert all([isinstance(tc, FunctionCall) for tc in tool_calls]), f"expected TOOL to have `tool_calls` of type `list[FunctionCall]` but at least one of the list elements is not of type FunctionCall, got `{tool_calls}`"

            case Role.USER:
                assert exists(content, True) and isinstance(content, str), f"expected USER to have a `content` of type `str` but got `{content}`"
                assert not exists(metadata) or isinstance(metadata, dict), f"expected `metadata` to be None or `metadata` to be of type `dict` but got `{metadata}`"
                assert not exists(tool_calls) or (isinstance(tool_calls, list) and tool_calls == []), f"expected SYSTEM to not have `tool_calls` (e.g. the tool_calls should be None) but got `{tool_calls}`"
                assert not exists(tool_call_id), f"expected USER to not have `tool_call_id` (e.g. the tool_call_id should be None) but got `{tool_call_id}`"
            
            case Role.TOOL:
                assert exists(content, True) and isinstance(content, str), f"expected TOOL to have a `content` of type `str` but got `{content}`"
                assert not exists(metadata), f"expected TOOL to not have `metadata` (e.g. the metadata should be None) but got `{metadata}`"
                assert exists(tool_call_id) and isinstance(tool_call_id, str), f"expected TOOL to have a `tool_call_id` of type `str` but got `{tool_call_id}`"
                assert not exists(images), f"Images can only be attached to user messages, but got {images} for role TOOL"

            case _:
                raise ValueError(f"Invalid role \"{role}\".")
        
        self.role = role
        self.content = content
        self.metadata = metadata
        self.time = (message_time if message_time > 0 else time.time())
    
        self.images = images  # Should be an ImageCache instance or a list of ImageCache instances or None
        
        # store function calls and function results
        self.tool_calls: list[FunctionCall] = tool_calls
        self.tool_call_id = tool_call_id
    
    def to_dict(self) -> dict:
        return dict(
            role = self.role,
            content = self.content,
            metadata = self.metadata,
            time = self.time,
            images = [i.to_dict() for i in self.images or []],
            tool_calls = [i.to_dict() for i in self.tool_calls or []],
            tool_call_id = self.tool_call_id
        )
    
    @classmethod
    def from_dict(cls, data: dict) -> 'RoleMessage':
        return cls(
            role = data["role"],
            content = data.get("content"),
            metadata = data.get("metadata"),
            message_time = data.get("time", time.time()),
            images = [ImageCache.from_dict(i) for i in data.get("images", [])],
            tool_calls = [FunctionCall.from_dict(d) for d in data.get("tool_calls", [])],
            tool_call_id = data.get("tool_call_id")
        )

    def to_openai_dict(self, timestamps: bool = True) -> dict:
        openai_dict = dict(role = self.role)
        match self.role:
            case Role.USER:
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
                content_dict = [dict(type = "text", text = "\n".join(content))]
                for img in self.images:
                    content_dict.append(dict(
                        type = "image_url",
                        image_url = dict(url = img.to_data_image_url())
                    ))
                openai_dict.update(dict(content = content_dict))
            case Role.ASSISTANT:
                if exists(self.content, True):
                    openai_dict.update(dict(content = self.content))
                else:
                    openai_dict.update(dict(
                        tool_calls = [i.to_openai_dict() for i in self.tool_calls]
                    ))
            case Role.TOOL:
                openai_dict.update(dict(
                    content = self.content,
                    tool_call_id = self.tool_call_id
                ))
            case _:
                openai_dict.update(dict(content = self.content))
        return openai_dict

class AssistantPersona:
    def __init__(self, name: str, age: int, occupation: str, memories: list[str], appearance: str, nationality: str):
        assert name is not None and isinstance(name, str), f"expected `name` to not be None and be of type `str` but got `{name}`"
        assert age is not None and isinstance(age, int), f"expected `age` to not be None and be of type `str` but got `{age}`"
        assert occupation is None or isinstance(occupation, str), f"expected `occupation` to be None or be of type `str` but got `{occupation}`"
        assert memories is None or isinstance(memories, list), f"expected `memories` to be None or be of type `list[str]` but got `{memories}`"
        assert memories is not None and all([isinstance(m, str) for m in memories]), f"expected `memories` to be None or be of type `list[str]` but at least one element in the list is not of type `str`, got `{memories}`"
        assert appearance is None or isinstance(appearance, str), f"expected `appearance` to be None or be of type `str` but got `{appearance}`"
        assert nationality is None or isinstance(nationality, str), f"expected `nationality` to be None or be of type `str` but got `{nationality}`"
        
        self.name = name
        self.age = age
        self.occupation = occupation
        self.memories = memories
        self.appearance = appearance
        self.nationality = nationality
    
    def to_dict(self) -> dict:
        return dict(
            name = self.name,
            age = self.age,
            occupation = self.occupation,
            memories = self.memories,
            appearance = self.appearance,
            nationality = self.nationality,
        )
    
    @staticmethod
    def from_dict(data: dict) -> 'RoleMessage':
        return AssistantPersona(
            name = data.get("name"),
            age = data.get("age"),
            occupation = data.get("occupation"),
            memories = data.get("memories", []),
            appearance = data.get("appearance"),
            nationality = data.get("nationality"),
        )
    
    def __str__(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

if __name__ == "__main__":
    persona = AssistantPersona.from_dict(json.load(open("persona.json", "rb")))
    print(persona)