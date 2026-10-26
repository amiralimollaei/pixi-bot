from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

from pixi.caching import InMemoryCache
from pixi.model.chat import ChatMessageMeta, ToolCallMeta
from pixi.model.enums import ChatRole
from pixi.utils import clean_dict, exists, format_time_ago


class MediaReader(Protocol):
    def load_cache(self, hash: bytes) -> InMemoryCache | None: ...


def _validate_message(meta: ChatMessageMeta) -> None:
    if meta.role != ChatRole.USER:
        assert not exists(meta.metadata), "Metadata is only supported on user messages"
        assert not exists(meta.image_hashes), (
            "Images are only supported on user messages"
        )
        assert not exists(meta.audio_hashes), "Audio is only supported on user messages"
    if meta.role != ChatRole.TOOL:
        assert not exists(meta.tool_call_id), (
            "tool_call_id is only supported on tool results"
        )
    match meta.role:
        case ChatRole.SYSTEM | ChatRole.USER:
            if meta.role == ChatRole.SYSTEM:
                assert exists(meta.content, True), "Message content is required"
            assert not exists(meta.tool_calls), (
                "Tool calls are only supported on assistant messages"
            )
        case ChatRole.ASSISTANT:
            if exists(meta.tool_calls):
                assert meta.content is None, (
                    "Tool-call messages cannot also have text content"
                )
                assert all(
                    isinstance(call, ToolCallMeta) for call in meta.tool_calls
                ), "Invalid tool call"
            else:
                assert exists(meta.content, True), "Assistant content is required"
        case ChatRole.TOOL:
            assert exists(meta.content, True), "Tool result content is required"
        case _:
            raise ValueError(f"Invalid role {meta.role!r}.")


def serialize_message(
    meta: ChatMessageMeta,
    *,
    timestamps: bool = True,
    media_cache: MediaReader | None = None,
) -> dict:
    _validate_message(meta)
    result: dict[str, Any] = dict(role=str(meta.role).lower())
    if meta.role == ChatRole.USER:
        content = [f"User: {meta.content or ''}"]
        if timestamps:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(meta.time))
            content.append(
                f"Sent At: {stamp} ({format_time_ago(time.time() - meta.time)})"
            )
        if meta.metadata is not None:
            content.extend(
                [
                    "Metadata:",
                    "```json",
                    json.dumps(meta.metadata, ensure_ascii=False, indent=3),
                    "```",
                ]
            )
        parts: list[dict[str, Any]] = [dict(type="text", text="\n".join(content))]
        for hashes, kind in (
            (meta.image_hashes, "image"),
            (meta.audio_hashes, "audio"),
        ):
            for digest in hashes:
                media = (
                    media_cache.load_cache(digest) if media_cache is not None else None
                )
                if media is None:
                    logging.getLogger(__name__).warning(
                        "Failed to load %s from cache.", kind
                    )
                    continue
                if kind == "image":
                    parts.append(
                        dict(type="image_url", image_url=dict(url=media.to_data_url()))
                    )
                else:
                    parts.append(
                        dict(
                            type="input_audio",
                            input_audio=dict(data=media.to_base64(), format="wav"),
                        )
                    )
        result["content"] = parts
    elif meta.role == ChatRole.ASSISTANT and meta.tool_calls:
        result["tool_calls"] = [
            dict(
                type="function",
                id=tool.id,
                function=dict(
                    name=tool.name,
                    arguments=json.dumps(tool.arguments, ensure_ascii=False),
                ),
            )
            for tool in meta.tool_calls
        ]
    elif meta.role == ChatRole.TOOL:
        result.update(content=meta.content, tool_call_id=meta.tool_call_id)
    else:
        result["content"] = meta.content
    return clean_dict(result)
