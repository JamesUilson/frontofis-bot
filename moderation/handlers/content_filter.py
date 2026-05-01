"""
Content Filter Handler — xabarlarni tekshirish va ogohlantirish
"""

import hashlib
import time
from aiogram import Router, F
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from moderation.mod_config import mod_config
from moderation.utils.storage import mod_storage
from moderation.utils.filters import get_content_filter

router = Router()


def get_violation_keyboard(chat_id: int, target_id: int, notif_key: str):
    builder = InlineKeyboardBuilder()
    builder.button(text='⚠️ Ogohlantirish', callback_data=f'mod_warn_{chat_id}_{target_id}_{notif_key}')
    builder.button(text='🔇 Jazo (7 kun)', callback_data=f'mod_mute_{chat_id}_{target_id}_{notif_key}')
    builder.button(text='🚫 Bloklash', callback_data=f'mod_ban_{chat_id}_{target_id}_{notif_key}')
    builder.button(text='❌ Rad etish', callback_data=f'mod_dismiss_{notif_key}')
    builder.adjust(2)
    return builder.as_markup()


async def process_violation(message: Message, reason: str, found: str):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0

    try:
        await message.delete()
    except Exception as e:
        print(f'[Moderation] Delete error: {e}')
        return

    mod_storage.increment_stat(chat_id, 'deleted_messages')

    user_name = message.from_user.full_name if message.from_user else f'ID:{user_id}'
    user_link = f'@{message.from_user.username}' if (message.from_user and message.from_user.username) else f'ID:{user_id}'

    print(f'[Moderation] DELETED: {user_name} — {reason}: {found}')

    try:
        admins = await message.bot.get_chat_administrators(chat_id)
    except Exception:
        return

    notif_key = hashlib.md5(f"{chat_id}_{user_id}_{time.time()}".encode()).hexdigest()[:8]
    warn_count = mod_storage.get_warns(chat_id, user_id)
    time_str = time.strftime('%d.%m.%Y %H:%M')

    text = (
        f'⚠️ <b>Guruhda qoidabuzarlik</b>\n'
        f'━━━━━━━━━━━━━━━━━━━\n'
        f'👤 Qoidabuzar: {user_name} ({user_link})\n'
        f'📋 Sabab: {reason}\n'
        f'🔍 Topildi: <code>{found[:50]}</code>\n'
        f'⚡ Ogohlantirishlar: {warn_count}/{mod_config.WARN_LIMIT}\n'
        f'🕐 Vaqt: {time_str}\n\n'
        f'Amalni tanlang:'
    )

    sent_messages = []
    for admin in admins:
        if admin.user.is_bot:
            continue
        try:
            msg = await message.bot.send_message(
                chat_id=admin.user.id,
                text=text,
                parse_mode='HTML',
                reply_markup=get_violation_keyboard(chat_id, user_id, notif_key)
            )
            sent_messages.append({
                'chat_id': admin.user.id,
                'message_id': msg.message_id,
                'text': text
            })
        except Exception:
            pass

    if sent_messages:
        mod_storage.add_notification_group(notif_key, sent_messages)


@router.message(F.text)
async def check_text_message(message: Message, rate_limit_violation: bool = False,
                              rate_limit_mute: int = 0):
    # Flood tekshiruvi
    if rate_limit_violation:
        try:
            from aiogram.types import ChatPermissions
            from datetime import datetime, timedelta
            until_date = datetime.now() + timedelta(seconds=rate_limit_mute)
            await message.bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                until_date=until_date,
                permissions=ChatPermissions(can_send_messages=False)
            )
            await message.answer(
                f'🔇 {message.from_user.full_name or "Foydalanuvchi"} '
                f'flood uchun {rate_limit_mute} soniyaga jazolandi!'
            )
        except Exception as e:
            print(f'[Moderation] Rate limit mute error: {e}')
        return

    # Faqat guruh va superguruhda ishlaydi (kanal va private emas)
    if message.chat.type in ('private', 'channel'):
        return

    try:
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        if member.status in ['administrator', 'creator']:
            return
    except Exception:
        pass

    text = message.text or message.caption or ''
    if not text:
        return

    cf = get_content_filter()

    if mod_config.CHECK_BANNED_WORDS:
        found = cf.contains_banned_word(text)
        if found:
            await process_violation(message, 'Taqiqlangan so\'z', found)
            return

    if mod_config.CHECK_HACKER_WORDS:
        found = cf.contains_hacker_word(text)
        if found:
            await process_violation(message, 'Xakerlik mazmuni', found)
            return

    if mod_config.CHECK_LINKS:
        found = cf.contains_link(text)
        if found:
            await process_violation(message, 'Ruxsatsiz havola', found)
            return

    if mod_config.CHECK_SHELL_PATTERNS:
        found = cf.contains_shell_pattern(text)
        if found:
            await process_violation(message, 'Shell/buyruq kodi', found)
            return


@router.message(F.document | F.audio | F.video | F.animation)
async def check_files(message: Message):
    if message.chat.type in ('private', 'channel'):
        return

    try:
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
        if member.status in ['administrator', 'creator']:
            return
    except Exception:
        pass

    if not mod_config.BLOCK_FILES:
        return

    file_obj = message.document or message.audio or message.video or message.animation
    if not file_obj:
        return

    file_name = getattr(file_obj, 'file_name', '') or ''
    mime_type = getattr(file_obj, 'mime_type', '') or ''

    cf = get_content_filter()
    found = cf.is_blocked_file(file_name)
    if found:
        await process_violation(message, 'Havfli fayl', f'.{found}')
        return

    blocked_mimes = [
        'application/x-msdownload', 'application/x-msdos-program',
        'application/x-bat', 'application/x-sh',
        'text/x-python', 'application/x-php',
    ]
    if mime_type in blocked_mimes:
        await process_violation(message, 'Havfli fayl (MIME)', mime_type)