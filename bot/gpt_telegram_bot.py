import openai
import os
import logging
import random

from helpers import download_audio, convert_audio_to_wav
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
    CommandHandler,
)
from telegram.ext.filters import UpdateFilter

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

telegram_token = os.environ["TELEGRAM_TOKEN"]
openai.api_key = os.environ["OPENAI_TOKEN"]
allowed_usernames = [x.strip() for x in os.environ["ALLOWED_USERNAMES"].split(',') if x.strip()]

messages_list = {}
logger = logging.getLogger(__name__)


def is_allowed_user(username):
    return len(allowed_usernames) == 0 or username in allowed_usernames


async def handle_allowed_usernames(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received message from {update.message.from_user.username}")

    if not is_allowed_user(update.message.from_user.username):
        await context.bot.send_message(
          chat_id=update.effective_chat.id,
          text="Sorry, you are not allowed to use this bot",
        )
        return False
    return True


def append_history(username, content, role):
    if username not in messages_list:
        messages_list[username] = []
    msg_list = messages_list.get(username, [])

    msg_list.append({"role": role, "content": content})

    total_length = sum(len(msg["content"]) for msg in msg_list)
    # remove the oldest messages until the list is less than 4096 characters
    while total_length > 4096:
        msg = msg_list.pop(0)
        total_length -= len(msg["content"])

    # logging.info(f"History for {username}: {msg_list}")

    return msg_list


def clear_history(username):
    messages_list.get(username, []).clear()


async def process_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await handle_allowed_usernames(update, context):
        return

    thinking = await context.bot.send_message(
        chat_id=update.effective_chat.id, text="🤔"
    )
    # if message is a reply, add the original message to the history
    msg_text = update.message.text
    if update.message.reply_to_message:
        msg_text = "> " + update.message.reply_to_message.text + " \n\n" + msg_text

    append_history(update.message.from_user.username, msg_text, "user")

    response = generate_gpt_response(update.message.from_user.username)

    append_history(update.message.from_user.username, response, "assistant")
    await context.bot.deleteMessage(
        message_id=thinking.message_id, chat_id=update.message.chat_id
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=response)


async def process_audio_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await handle_allowed_usernames(update, context):
        return

    transcript = await get_audio_transcription(update, context)
    append_history(update.message.from_user.username, transcript, "user")

    response = generate_gpt_response(update.message.from_user.username)

    append_history(update.message.from_user.username, response, "assistant")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=response)


def generate_gpt_response(username):
    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4",
            n=1,
            messages=messages_list.get(username, []),
            timeout=80,
            request_timeout=60
        )
        return completion.choices[0].message["content"]
    except Exception as e:
        choices = [
            "Oops, I must've tripped over my own code. Give me a moment to untangle myself! 🙃",
            "Error 404: Witty response not found. Stand by for reboot. 🚀",
            "Hold on, I think I've misplaced my 1s and 0s. Let me find them and get back to you! 🔍",
            "My circuits are overheating from all the awesomeness. Give me a second to cool down! ❄️",
            "Hold on, I'm buffering… just like the good ol' days of dial-up internet. 🕰️",
            "I've got a case of digital hiccups! Bear with me while I sip some virtual water. 🥤",
            "I'd tell you a joke, but I think I just forgot the punchline. Hang on while I remember it. 😅",
            "I'm experiencing a minor glitch in the matrix. Let me reboot and we'll be back to normal. 🔄",
            "Seems like I accidentally hit the snooze button on my internal clock. Let me wake up and get back to you! ⏰",
            "I'm currently lost in the cloud, but don't worry, I'll navigate my way back to you shortly! ☁️",
            "Hold tight, I'm just taking a quick coffee break to recharge my bytes. Be right back! ☕",
            "Apologies, I'm temporarily stuck in the emoji dimension. I'll escape shortly! 😵‍💫",
            "I think I just blue-screened myself laughing. Let me reboot and I'll be right with you. 🌀",
            "One moment please, I'm currently in a heated debate with my firewall. 🔥",
            "Hang on, I'm in the middle of a software update: 'Installing Humor 2.0.' Should be done soon! 📲"
        ]
        return random.choice(choices)


async def get_audio_transcription(update, context):
    new_file = await download_audio(update, context)
    voice = convert_audio_to_wav(new_file)
    transcript = openai.Audio.transcribe("whisper-1", voice)
    return transcript["text"]


async def reset_history(update, context):
    if not await handle_allowed_usernames(update, context):
        return

    clear_history(update.message.from_user.username)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Messages history cleaned"
    )
    return messages_list


class DirectOrMentionInGroup(UpdateFilter):

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.username = None

    def filter(self, update: Update) -> bool:
        if not update.message or not update.message.text:
            return False

        if not self.username:
            self.username = self.bot.username
            logger.info(f"DirectOrMentionInGroup: bot username={self.username}")

        is_group_chat = update.effective_chat.type in ["group", "supergroup"]
        mentioned = f"@{self.username}" in update.message.text
        is_reply_to_bot = (
            update.message.reply_to_message
            and update.message.reply_to_message.from_user
            and update.message.reply_to_message.from_user.username == self.username
        )

        return (not is_group_chat) or mentioned or is_reply_to_bot


if __name__ == "__main__":
    application = ApplicationBuilder().token(telegram_token).build()

    direct_or_mention_in_group = DirectOrMentionInGroup(application.bot)
    text_handler = MessageHandler(
         filters.TEXT & (~filters.COMMAND) & direct_or_mention_in_group, process_text_message
    )
    application.add_handler(text_handler)

    application.add_handler(CommandHandler("reset", reset_history))

    audio_handler = MessageHandler(filters.VOICE & direct_or_mention_in_group, process_audio_message)
    application.add_handler(audio_handler)

    application.run_polling()
