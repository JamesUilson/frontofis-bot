"""
Report Handler — /report shikoyat tizimi
"""

import hashlib
import time
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from moderation.mod_config import mod_config
from moderation.utils.storage import mod_storage

router = Router()


def get_report_keyboard(chat_id: int, target_id: int, notif_key: str):
    builder = InlineKeyboardBuilder()
    builder.button(text='⚠️ Ogohlantirish', callback_data=f'mod_warn_{chat_id}_{target_id}_{notif_key}')
    builder.button(text='🔇 Jazo (7 kun)', callback_data=f'mod_mute_{chat_id}_{target_id}_{notif_key}')
    builder.button(text='🚫 Bloklash', callback_data=f'mod_ban_{chat_id}_{target_id}_{notif_key}')
    builder.button(text='❌ Rad etish', callback_data=f'mod_dismiss_{notif_key}')
    builder.adjust(2)
    return builder.as_markup()


GROUP_FILTER = F.chat.type.in_({"group", "supergroup"})


@router.message(Command('report'), GROUP_FILTER)
async def cmd_report(message: Message):
    if not message.reply_to_message:
        await message.answer(
            '📢 Shikoyat uchun: /report sabab\n'
            '(Qoidabuzar xabariga javob qilib yozing)'
        )
        return

    target = message.reply_to_message.from_user
    sender = message.from_user

    if not target or not sender:
        return

    try:
        member = await message.bot.get_chat_member(message.chat.id, target.id)
        if member.status in ['administrator', 'creator']:
            await message.answer('❌ Administratorga shikoyat qilish mumkin emas!')
            return
    except Exception:
        pass

    chat_id = message.chat.id
    target_id = target.id

    args = message.text.split(maxsplit=1)
    reason = args[1] if len(args) > 1 else 'Sabab ko\'rsatilmagan'

    await message.answer(
        f'✅ Shikoyat yuborildi!\n'
        f'👤 Kim haqida: {target.full_name or f"ID:{target_id}"}\n'
        f'📋 Sabab: {reason}'
    )

    try:
        admins = await message.bot.get_chat_administrators(chat_id)
    except Exception:
        return

    notif_key = hashlib.md5(f"{chat_id}_{target_id}_report_{time.time()}".encode()).hexdigest()[:8]

    target_name = target.full_name or f'ID:{target_id}'
    sender_name = sender.full_name or f'ID:{sender.id}'
    chat_title = message.chat.title or 'Guruh'

    # Admin mention list (guruh adminlaridan)
    admin_mentions = ' '.join(
        f'@{a.user.username}' if a.user.username else f'<a href="tg://user?id={a.user.id}">{a.user.full_name}</a>'
        for a in admins if not a.user.is_bot
    )

    # Guruhda ommaviy shikoyat xabari
    public_text = (
        f'📢 <b>SHIKOYAT</b>\n'
        f'━━━━━━━━━━━━━━━━━━━\n'
        f'👤 Shikoyatchi: {sender_name}\n'
        f'🎯 Kim haqida: <b>{target_name}</b>\n'
        f'📋 Sabab: {reason}\n'
        f'⚠️ Ogohlantirishlar: {mod_storage.get_warns(chat_id, target_id)}/{mod_config.WARN_LIMIT}\n'
        f'🕐 Vaqt: {time.strftime("%d.%m.%Y %H:%M")}\n\n'
        f'👮 Adminlar: {admin_mentions}'
    )
    try:
        await message.bot.send_message(chat_id=chat_id, text=public_text, parse_mode='HTML')
    except Exception as e:
        print(f'[Report] Guruhga yuborishda xato: {e}')

    report_text = (
        f'📢 <b>SHIKOYAT (DM)</b>\n'
        f'━━━━━━━━━━━━━━━━━━━\n'
        f'🏠 Guruh: {chat_title}\n'
        f'👤 Kimdan: {sender_name}\n'
        f'🎯 Kim haqida: {target_name}\n'
        f'📋 Sabab: {reason}\n'
        f'🕐 Vaqt: {time.strftime("%d.%m.%Y %H:%M")}\n'
        f'⚠️ Ogohlantirishlar: {mod_storage.get_warns(chat_id, target_id)}/{mod_config.WARN_LIMIT}'
    )

    sent_messages = []
    for admin in admins:
        if admin.user.is_bot:
            continue
        try:
            msg = await message.bot.send_message(
                chat_id=admin.user.id,
                text=report_text,
                parse_mode='HTML',
                reply_markup=get_report_keyboard(chat_id, target_id, notif_key)
            )
            sent_messages.append({
                'chat_id': admin.user.id,
                'message_id': msg.message_id,
                'text': report_text
            })
        except Exception:
            pass

    if sent_messages:
        mod_storage.add_notification_group(notif_key, sent_messages)

    mod_storage.increment_stat(chat_id, 'total_reports')