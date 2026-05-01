"""
Admin Callback Handler — admin tugmalari ishlov beruvchisi
"""

import re
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, ChatPermissions
from aiogram.enums import ChatMemberStatus

from moderation.mod_config import mod_config
from moderation.utils.storage import mod_storage

router = Router()


async def update_all_messages(notif_key: str, action_text: str, bot):
    entry = mod_storage.get_notification(notif_key)
    if not entry:
        return
    for msg in entry.get('msgs', []):
        try:
            await bot.edit_message_text(
                chat_id=msg['chat_id'],
                message_id=msg['message_id'],
                text=msg['text'] + f'\n\n✅ {action_text}',
                parse_mode='HTML'
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith('mod_'))
async def process_mod_action(callback: CallbackQuery):
    data = callback.data

    # Dismiss
    if data.startswith('mod_dismiss_'):
        notif_key = data.replace('mod_dismiss_', '')
        entry = mod_storage.get_notification(notif_key)
        if entry and entry.get('handled'):
            await callback.answer('Allaqachon ko\'rib chiqildi', show_alert=True)
            return

        # Admin tekshiruvi
        admin_check = False
        try:
            import sys
            parent = sys.modules.get('__main__')
            admin_ids = getattr(parent, 'ADMIN_IDS', [])
            if callback.from_user.id in admin_ids:
                admin_check = True
        except Exception:
            pass

        if not admin_check:
            await callback.answer('Faqat administratorlar uchun!', show_alert=True)
            return

        admin_name = callback.from_user.first_name or 'Admin'
        action_text = f'Rad etildi — {admin_name}'
        await callback.answer('Shikoyat rad etildi')
        mod_storage.mark_handled(notif_key, callback.from_user.id, action_text)
        await update_all_messages(notif_key, action_text, callback.bot)
        return

    # warn/mute/ban
    pattern = r'^mod_(warn|mute|ban)_(\-?\d+)_(\d+)_(\w{8})$'
    match = re.match(pattern, data)
    if not match:
        await callback.answer('Noto\'g\'ri ma\'lumot', show_alert=True)
        return

    action, group_chat_id, target_user_id, notif_key = match.groups()
    group_chat_id = int(group_chat_id)
    target_user_id = int(target_user_id)

    entry = mod_storage.get_notification(notif_key)
    if entry and entry.get('handled'):
        await callback.answer('Bu allaqachon ko\'rib chiqildi', show_alert=True)
        return

    # Admin tekshiruvi
    is_admin = False
    try:
        import sys
        parent = sys.modules.get('__main__')
        admin_ids = getattr(parent, 'ADMIN_IDS', [])
        if callback.from_user.id in admin_ids:
            is_admin = True
    except Exception:
        pass

    if not is_admin:
        try:
            member = await callback.bot.get_chat_member(group_chat_id, callback.from_user.id)
            is_admin = member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
        except Exception:
            pass

    if not is_admin:
        await callback.answer('Faqat administratorlar uchun!', show_alert=True)
        return

    admin_name = callback.from_user.first_name or 'Admin'
    bot = callback.bot

    if action == 'warn':
        count = mod_storage.add_warn(group_chat_id, target_user_id)
        days = mod_config.MUTE_DAYS_PER_WARN * count
        try:
            until_date = datetime.now() + timedelta(days=days)
            await bot.restrict_chat_member(
                chat_id=group_chat_id,
                user_id=target_user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
        except Exception as e:
            print(f'[Moderation] Warn error: {e}')
        mod_storage.increment_stat(group_chat_id, 'total_warns')
        mod_storage.increment_stat(group_chat_id, 'total_mutes')
        action_text = f'Ogohlantirish {count}/{mod_config.WARN_LIMIT} + jazo {days} kun — {admin_name}'
        await callback.answer(f'⚠️ Ogohlantirish berildi! Jazo: {days} kun')
        try:
            await bot.send_message(group_chat_id, f'⚠️ ID:{target_user_id} ogohlantirildi. Jazo: {days} kun')
        except Exception:
            pass

    elif action == 'mute':
        days = mod_config.MUTE_DAYS_PER_WARN
        try:
            until_date = datetime.now() + timedelta(days=days)
            await bot.restrict_chat_member(
                chat_id=group_chat_id,
                user_id=target_user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
        except Exception as e:
            print(f'[Moderation] Mute error: {e}')
        mod_storage.increment_stat(group_chat_id, 'total_mutes')
        action_text = f'Jazo {days} kun — {admin_name}'
        await callback.answer(f'🔇 Jazo qo\'llandi: {days} kun')
        try:
            await bot.send_message(group_chat_id, f'🔇 ID:{target_user_id} {days} kunga jazolandi.')
        except Exception:
            pass

    elif action == 'ban':
        try:
            await bot.ban_chat_member(group_chat_id, target_user_id)
        except Exception as e:
            print(f'[Moderation] Ban error: {e}')
        mod_storage.increment_stat(group_chat_id, 'total_bans')
        action_text = f'Bloklandi — {admin_name}'
        await callback.answer('🚫 Foydalanuvchi bloklandi')
        try:
            await bot.send_message(group_chat_id, f'🚫 ID:{target_user_id} butunlay bloklandi.')
        except Exception:
            pass

    else:
        action_text = 'Noma\'lum amal'

    mod_storage.mark_handled(notif_key, callback.from_user.id, action_text)
    await update_all_messages(notif_key, action_text, bot)
