from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pixi.ai.chatting.callbacks import ActionContext
from pixi.utils import format_time_later

if TYPE_CHECKING:
    from pixi.bot.conversations import AsyncChatbotInstance
    from pixi.interfaces.gifs import GifSearchAPI


@dataclass(frozen=True)
class ScheduleData:
    action: str
    value: str
    delay: float
    id: str


class ScheduleAction:
    name = "schedule"
    field_name = "json"
    description = 'schedules an action to be executed later, the value for this action is a json with the following schema: {"action": <action-name>, "value": <action-value>, "delay": <delay-in-seconds>, "id": <unique-number>}'
    is_visible = True
    logger = logging.getLogger("ScheduleAction")

    @classmethod
    def should_register(cls, instance: AsyncChatbotInstance) -> bool:
        return True

    @classmethod
    async def call(cls, context: ActionContext, value: str | None) -> None:
        if not value:
            return
        if context.reference_message is None:
            cls.logger.error("reference_message is None")
            return
        if context.parent_instance is None:
            cls.logger.error("parent_instance is None")
            return

        try:
            schedule_data = ScheduleData(**json.loads(value))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            cls.logger.exception(f"Invalid schedule JSON: {e}")
            return

        if (
            not schedule_data.action
            or not schedule_data.value
            or schedule_data.delay is None
            or not schedule_data.id
        ):
            cls.logger.error(
                "Schedule JSON must include 'action', 'value', 'delay', and 'id' fields."
            )
            return

        if (
            not isinstance(schedule_data.delay, (int, float))
            or schedule_data.delay <= 0
        ):
            cls.logger.error("'delay' must be a positive number.")
            return

        action = context.parent_instance.action_manager.actions.get(
            schedule_data.action.strip().lower()
        )
        if action is None:
            cls.logger.error(
                f'Cannot schedule unknown action "{schedule_data.action}".'
            )
            return

        if context.parent_instance.schedule_action(
            action=action,
            value=schedule_data.value,
            action_context=context,
            id=schedule_data.id,
            delay=schedule_data.delay,
        ):
            cls.logger.info(
                f"scheduled action for {format_time_later(schedule_data.delay)}: {value}"
            )
        else:
            cls.logger.info(f"schedule action failed: {value}")


class CancelScheduleAction:
    name = "cancel_schedule"
    field_name = "id"
    description = "cancels a previously scheduled action by its id (the ID for each schedule should be a unique number)"
    is_visible = True
    logger = logging.getLogger("CancelScheduleAction")

    @classmethod
    def should_register(cls, instance: AsyncChatbotInstance) -> bool:
        return True

    @classmethod
    async def call(cls, context: ActionContext, value: str | None) -> None:
        if not value or context.reference_message is None:
            return

        schedule_id = value.strip()
        if not schedule_id:
            cls.logger.error("Model did not provide a schedule id to cancel.")
            return

        if context.parent_instance and context.parent_instance.cancel_schedule(
            schedule_id
        ):
            cls.logger.info(f"Cancelled the schedule with id '{schedule_id}'.")
        else:
            cls.logger.info(f"No schedule found with id '{schedule_id}'.")


class SendAction:
    name = "send"
    field_name = "message"
    description = "sends a message in the current chat"
    is_visible = True

    @classmethod
    def should_register(cls, instance: AsyncChatbotInstance) -> bool:
        return True

    @classmethod
    async def call(cls, context: ActionContext, value: str | None) -> None:
        if not value or context.platform_message is None:
            return
        await context.platform_message.send(value)


class SendGifAction:
    name = "send_gif"
    field_name = "gif description"
    description = "sends a gif in the current chat, the gif is chosen based on the provided description (description must be in English)"
    is_visible = True

    def __init__(self, gif_api: GifSearchAPI | None):
        self.gif_api = gif_api

    def should_register(self, instance: AsyncChatbotInstance) -> bool:
        return self.gif_api is not None

    async def call(self, context: ActionContext, value: str | None) -> None:
        message = context.platform_message
        if not value or message is None:
            return
        assert self.gif_api is not None, "gif_api is not initialized"

        result = await self.gif_api.search(value)
        if result.results:
            await message.send(result.results[0].url)


class NoteAction:
    name = "note"
    field_name = "thoughts"
    description = "annotates your thoughts, the user will not see these, it is completey private and only available to you, you must do this before each message, thoughts should be at least 50 words"
    is_visible = False

    @classmethod
    def should_register(cls, instance: AsyncChatbotInstance) -> bool:
        return True

    @classmethod
    async def call(cls, context: ActionContext, value: str | None) -> None:
        message = context.platform_message
        if not value or message is None:
            return

        if context.parent_instance and context.parent_instance.is_notes_visible:
            await message.send(f"> thoughts: {value}")


class ReactAction:
    name = "react"
    field_name = "emoji"
    description = "react with an emoji (presented in utf-8) to the current message that you are responding to, you may react to messages that are shocking or otherwise in need of immediate emotional reaction, you can send multiple reactions by using this command multuple times."
    is_visible = True
    logger = logging.getLogger("ReactAction")

    @classmethod
    def should_register(cls, instance: AsyncChatbotInstance) -> bool:
        return True

    @classmethod
    async def call(cls, context: ActionContext, value: str | None) -> None:
        if not value or context.platform_message is None:
            return
        message = context.platform_message

        try:
            await message.add_reaction(value)
        except Exception:
            cls.logger.exception(
                f"Failed to add reaction {value} to message {message.id}"
            )
