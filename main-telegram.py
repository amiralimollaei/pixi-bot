import asyncio
import json
import math
import logging

import telegram
from telegram.constants import ChatType, ParseMode, ChatAction
from telegram import Update
from telegram.ext import Application, ContextTypes, CommandHandler, MessageHandler, filters

from api.conversation import ConversationStorage, LLMConversation, SAVE_PATH
import api.chatting as Chat
from api.utils import ImageCache, load_dotenv

logging.basicConfig(
    format='[%(asctime)s] [%(levelname)s / %(name)s] %(message)s',
    level=logging.WARNING
)

HASH_PREFIX = "Telegram-3"
PERSONA = Chat.AssistantPersona.from_dict(json.load(open("persona.json", "rb")))

STORAGE = ConversationStorage(persona=PERSONA, hash_prefix=HASH_PREFIX)

# Helper to get unique chat identifier (similar to Discord)
def get_unique_chat_identifier(message: telegram.Message) -> str:
    chat = message.chat
    if chat.type == ChatType.PRIVATE:
        return f"user#{chat.id}"
    elif chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        return f"group#{chat.id}"
    elif chat.type == ChatType.CHANNEL:
        return f"channel#{chat.id}"
    return f"chat#{chat.id}"

async def get_convo_from_message(message: telegram.Message) -> LLMConversation:
    return STORAGE.get(get_unique_chat_identifier(message))

async def send_scheduled_message(context: ContextTypes.DEFAULT_TYPE):
    chat_id, messages = context.job.data
    for i, (response, reply_id) in enumerate(messages):
        retry = False
        while True:
            if not retry and (i != 0 or len(response) > 30):
                # wait_time adds realism
                wait_time = 0.5 + (1.8 ** math.log2(1+len(response))) / 20
                wait_time_ = wait_time 
                while True:
                    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
                    if wait_time_ > 2:
                        await asyncio.sleep(2)
                        wait_time_ -= 2
                    else:
                        await asyncio.sleep(wait_time_)
                        break

            try:
                await context.bot.send_message(chat_id, response, reply_to_message_id=reply_id, parse_mode=ParseMode.MARKDOWN)
                break
            except telegram.error.BadRequest:
                await context.bot.send_message(chat_id, response, reply_to_message_id=reply_id)
                break
            except telegram.error.TimedOut:
                retry = True

async def pixi_resp(bot: telegram.Bot, msg: Chat.RoleMessage, message: telegram.Message):
    chat_type = message.chat.type
    convo_id = get_unique_chat_identifier(message)
    try:
        convo = await get_convo_from_message(message)
    except Exception as e:
        logging.exception(f"Failed to get conversation for {convo_id}")
        await bot.send_message(message.chat.id, "Internal error: could not load conversation.")
        return
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    for attempt in range(3):
        messages_checkpoint = convo.get_messages().copy()
        rt_data = {"Platform": "Telegram", "Chat type": chat_type, "Chat title": message.chat.title}
        convo.realtime_data.update(rt_data)
        responded = False
        responses = []
        try:
            for resp in convo.live_chat(msg):
                resp = convo.proccess_response(resp)
                if resp == "NO_RESPONSE":
                    responded = True
                    continue
                if resp.strip() != "":
                    reply_to_message_id = message.message_id if not responded else None
                    responses.append((resp, reply_to_message_id))
                    responded = True
            if responded:
                logging.info(f"Responded to message in {convo_id} (attempt {attempt+1})")
                jqueue.run_once(send_scheduled_message, when=0, data=(message.chat.id, responses))
                break
            convo.set_messages(messages_checkpoint)
            convo.save()
        except Exception as e:
            logging.exception(f"Error in live_chat for {convo_id} (attempt {attempt+1})")
            continue
    if not responded:
        logging.warning(f"No response received after 3 retries for {convo_id}.")
        try:
            convo.client.add_message(msg)
            resp_ = "I'd rather not answer that honestly."
            convo.client.add_message(Chat.RoleMessage(
                role=Chat.Role.ASSISTANT,
                content=resp_ + " [SEND]"
            ))
            convo.save()
            await bot.send_message(message.chat.id, resp_, reply_to_message_id=message.message_id, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logging.exception(f"Failed fallback response for {convo_id}")
            await bot.send_message(message.chat.id, "Internal error: could not respond.")
    else:
        convo.save()
    logging.info(f"Finished handling message in {convo_id}")

async def pixi_resp_retry(bot: telegram.Bot, _msg: Chat.RoleMessage, message: telegram.Message):
    for i in range(3):
        try:
            return await pixi_resp(bot, _msg, message)
        except telegram.error.TimedOut as e:
            logging.exception(f"Timed out in pixi_resp_retry (attempt {i+1})")
            continue
        except Exception as e:
            logging.exception(f"Error in pixi_resp_retry (attempt {i+1})")
            continue
    logging.error("pixi_resp_retry failed after 3 attempts.")
    await bot.send_message(message.chat.id, "Sorry, something went wrong after several tries.")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    convo_id = get_unique_chat_identifier(message)
    try:
        STORAGE.remove(convo_id)
        logging.info(f"The conversation in {convo_id} has been reset.")
        await context.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        await context.bot.send_message(chat_id=update.effective_chat.id, reply_to_message_id=message.message_id, text="Wha- Where am I?!")
    except Exception as e:
        logging.exception(f"Failed to reset conversation for {convo_id}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Failed to reset conversation.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hiiiii, how's it going?")

async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    try:
        convo = await get_convo_from_message(message)
        is_notes_visible = convo.toggle_notes()
        await context.bot.send_message(chat_id=message.chat.id, text=f"notes set to {is_notes_visible}")
        logging.info(f"Notes toggled for {get_unique_chat_identifier(message)}: {is_notes_visible}")
    except Exception as e:
        logging.exception(f"Failed to toggle notes")
        await context.bot.send_message(chat_id=message.chat.id, text="Failed to toggle notes.")

def strip_message(message: str):
    """
    removes `remove_starts` from the start of the message.
    """
    remove_starts = ["!pixi", "!pix", "!p", "@pixiaibot", "@pixiai", "@pixi", "@pixibot"]

    for rs in remove_starts:
        if message.lower().startswith(rs):
            message = message[len(rs):]

    return message

def trace_message(message: telegram.Message):
    """
    removes `remove_starts` from the start of the message and traces
    replies that are empty to the original message the was replied to
    """
    replmessage = message.reply_to_message
    msg_text = message.text_markdown_v2

    # if message is empty and there's a reply message, trace the reply message
    msg_text = strip_message(msg_text)
    if msg_text == "" and replmessage:
        msg_text, message = trace_message(replmessage)
   
    return msg_text, message

async def on_message(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    if message is None or (message.text is None and not message.photo and not message.document):
        return

    replmessage = message.reply_to_message
    metadata = {"from": message.from_user.full_name}
    clean_message = ""
    attached_images = []

    # --- IMAGE HANDLING START ---
    # Telegram sends images as 'photo' (list of sizes) or as 'document' (if sent as file)
    if message.photo:
        # Get the highest resolution photo
        photo = message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        attached_images.append(ImageCache(image_bytes=bytes(image_bytes)))
    elif message.document and message.document.mime_type and message.document.mime_type.startswith('image/'):
        file = await context.bot.get_file(message.document.file_id)
        image_bytes = await file.download_as_bytearray()
        attached_images.append(ImageCache(image_bytes=bytes(image_bytes)))
    # --- IMAGE HANDLING END ---

    if message.text:
        if message.text.lower().startswith("!p") or message.text.lower().startswith("!pixi"):
            clean_message, message = trace_message(message)
        elif replmessage and replmessage.from_user.id == context.bot.id:
            clean_message, message = trace_message(message)
        elif message.chat.type == ChatType.PRIVATE:
            clean_message, message = trace_message(message)
    # If no text, but image exists, allow image-only message
    if not clean_message and not attached_images:
        return
    if replmessage:
        metadata.update({"reply to message": {}})
        replmessage_text = replmessage.text_markdown_v2
        if replmessage_text is None: 
            replmessage_text = replmessage.caption_markdown_v2
            metadata["reply to message"].update({"details": "this message contains media (unsupported)"})
        if replmessage_text is None:
            replmessage_text = ""
        if replmessage_text.lower().startswith("!pixi"):
            replmessage_text = replmessage_text[6:]
        elif replmessage_text.lower().startswith("!p"):
            replmessage_text = replmessage_text[3:]
        reply_optimization = -1
        try:
            convo = await get_convo_from_message(message)
            convo_messages = convo.get_messages()
            matching_messages = [msg.content for msg in convo_messages if replmessage_text in msg.content]
            if convo_messages and convo_messages[-1].content in matching_messages:
                reply_optimization = 2
            elif len(matching_messages) != 0:
                reply_optimization = 1
        except Exception as e:
            logging.exception(f"Error fetching conversation for reply optimization")
        if reply_optimization == 2:
            pass
        elif replmessage and replmessage.from_user.id == context.bot.id:
            if reply_optimization == 1:
                metadata["reply to message"].update({
                    "from": "[YOU]",
                    "partial content": replmessage_text[:64]
                })
            else:
                metadata["reply to message"].update({
                    "from": "[YOU]",
                    "content": replmessage_text
                })
        else:
            if reply_optimization == 1:
                metadata["reply to message"].update({
                    "from": replmessage.from_user.full_name,
                    "partial content": replmessage_text[:64]
                })
            else:
                metadata["reply to message"].update({
                    "from": replmessage.from_user.full_name,
                    "content": replmessage_text
                })
    # --- IMAGE-AWARE ROLE MESSAGE ---
    role_message = Chat.RoleMessage(role=Chat.Role.USER, content=clean_message, metadata=metadata, images=attached_images)
    return await pixi_resp_retry(context.bot, role_message, message)

if __name__ == '__main__':
    import os

    logging.info("loading...")
    load_dotenv()

    application = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('reset', reset))
    application.add_handler(CommandHandler('notes', notes))
    application.add_handler(MessageHandler(filters.TEXT, callback=on_message))
    application.add_handler(MessageHandler(filters.PHOTO, callback=on_message))
    
    jqueue = application.job_queue

    print("running...")
    application.run_polling()
