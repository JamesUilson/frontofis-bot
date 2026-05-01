"""
Moderation Commands — guruhda ishlaydi
/warn /unwarn /warns /mute /unmute /ban /unban /moders /modstats /modstatus
"""

from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, ChatPermissions
from aiogram.filters import Command

from moderation.mod_config import mod_config
from moderation.utils.storage import mod_storage

router = Router()

# Faqat guruh va superguruh
GROUP_FILTER = F.chat.type.in_({"group", "supergroup"})


def _get_admin_ids() -> list:
    """front.py dagi ADMIN_IDS ni oladi"""
    try:
        import sys
        parent = sys.modules.get('__main__')
        return getattr(parent, 'ADMIN_IDS', [])
    except Exception:
        return []


async def _is_admin(message: Message) -> bool:
    """Xabar yuboruvchi admin ekanligini tekshiradi"""
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return False
    if user_id in _get_admin_ids():
        return True
    try:
        member = await message.bot.get_chat_member(message.chat.id, user_id)
        return member.status in ['administrator', 'creator']
    except Exception:
        return False


async def _target_is_admin(message: Message, target_id: int) -> bool:
    if target_id in _get_admin_ids():
        return True
    try:
        mb = await message.bot.get_chat_member(message.chat.id, target_id)
        return mb.status in ['administrator', 'creator']
    except Exception:
        return False


def _fmt(minutes: int) -> str:
    if minutes < 60:
        return f'{minutes} daqiqa'
    h = minutes // 60
    if h < 24:
        return f'{h} soat'
    return f'{h // 24} kun'


# /moders
@router.message(Command('moders'), GROUP_FILTER)
async def cmd_moders(message: Message):
    if not await _is_admin(message):
        return
    admin_ids = _get_admin_ids()
    lines = '\n'.join(f'{i+1}. <code>{a}</code>' for i, a in enumerate(admin_ids))
    try:
        tg_admins = await message.bot.get_chat_administrators(message.chat.id)
        tg_lines = '\n'.join(
            f'• {a.user.full_name} (@{a.user.username or "—"}) — <code>{a.user.id}</code>'
            for a in tg_admins if not a.user.is_bot
        )
    except Exception:
        tg_lines = '(aniqlab bolmadi)'
    await message.answer(
        f'<b>Bot adminlari:</b>\n{lines or "(bosh)"}\n\n'
        f'<b>Guruh adminlari:</b>\n{tg_lines}',
        parse_mode='HTML'
    )


# /warn
@router.message(Command('warn'), GROUP_FILTER)
async def cmd_warn(message: Message):
    if not await _is_admin(message):
        return
    if not message.reply_to_message:
        await message.answer('Foydalanuvchi xabariga <b>reply</b> qilib /warn yozing.', parse_mode='HTML')
        return
    target = message.reply_to_message.from_user
    if not target:
        return
    if await _target_is_admin(message, target.id):
        await message.answer('Adminlarni ogohlantirish mumkin emas!')
        return

    # Supergroup emasligi tekshiruv
    is_supergroup = message.chat.type == 'supergroup'

    chat_id = message.chat.id
    count = mod_storage.add_warn(chat_id, target.id)
    days = mod_config.MUTE_DAYS_PER_WARN * count
    mute_ok = False

    if is_supergroup:
        try:
            until_date = datetime.now() + timedelta(days=days)
            await message.bot.restrict_chat_member(
                chat_id=chat_id, user_id=target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            mute_ok = True
        except Exception as e:
            print(f'[Mod] warn mute: {e}')

    mod_storage.increment_stat(chat_id, 'total_warns')
    if mute_ok:
        mod_storage.increment_stat(chat_id, 'total_mutes')

    mute_note = f'⏱ Jazo: <b>{days} kun</b>' if mute_ok else '⚠️ Guruh superguruhga o\'tkazilmagan, faqat warn yozildi'
    await message.answer(
        f'<b>{target.full_name}</b> ogohlantirildi.\n'
        f'{mute_note} | {count}/{mod_config.WARN_LIMIT}',
        parse_mode='HTML'
    )


# /unwarn
@router.message(Command('unwarn'), GROUP_FILTER)
async def cmd_unwarn(message: Message):
    if not await _is_admin(message):
        return
    if not message.reply_to_message:
        await message.answer('Xabarga <b>reply</b> qiling.', parse_mode='HTML')
        return
    target = message.reply_to_message.from_user
    if not target:
        return
    mod_storage.reset_warns(message.chat.id, target.id)
    await message.answer(
        f'<b>{target.full_name}</b> ning ogohlantirishlari olib tashlandi.', parse_mode='HTML'
    )


# /warns
@router.message(Command('warns'), GROUP_FILTER)
async def cmd_warns(message: Message):
    if not message.reply_to_message:
        await message.answer('Xabarga <b>reply</b> qiling.', parse_mode='HTML')
        return
    target = message.reply_to_message.from_user
    if not target:
        return
    count = mod_storage.get_warns(message.chat.id, target.id)
    await message.answer(
        f'<b>{target.full_name}</b>: {count}/{mod_config.WARN_LIMIT} ogohlantirish',
        parse_mode='HTML'
    )


# /mute [daqiqa]
@router.message(Command('mute'), GROUP_FILTER)
async def cmd_mute(message: Message):
    if not await _is_admin(message):
        return
    if not message.reply_to_message:
        await message.answer('Xabarga <b>reply</b> qilib /mute [daqiqa] yozing.', parse_mode='HTML')
        return
    target = message.reply_to_message.from_user
    if not target:
        return
    if await _target_is_admin(message, target.id):
        await message.answer('Adminlarni jazolash mumkin emas!')
        return
    args = message.text.split()[1:]
    minutes = 60
    if args and args[0].isdigit():
        minutes = int(args[0])
    if message.chat.type != 'supergroup':
        await message.answer('⚠️ /mute faqat <b>superguruhda</b> ishlaydi. Guruhni superguruhga o\'tkazing.', parse_mode='HTML')
        return
    try:
        until_date = datetime.now() + timedelta(minutes=minutes)
        await message.bot.restrict_chat_member(
            chat_id=message.chat.id, user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        mod_storage.increment_stat(message.chat.id, 'total_mutes')
        await message.answer(
            f'<b>{target.full_name}</b> {_fmt(minutes)}ga jazolandi.', parse_mode='HTML'
        )
    except Exception as e:
        await message.answer(f'Xatolik: {e}')


# /unmute
@router.message(Command('unmute'), GROUP_FILTER)
async def cmd_unmute(message: Message):
    if not await _is_admin(message):
        return
    if not message.reply_to_message:
        await message.answer('Xabarga <b>reply</b> qiling.', parse_mode='HTML')
        return
    target = message.reply_to_message.from_user
    if not target:
        return
    if message.chat.type != 'supergroup':
        await message.answer('⚠️ /unmute faqat <b>superguruhda</b> ishlaydi.', parse_mode='HTML')
        return
    try:
        await message.bot.restrict_chat_member(
            chat_id=message.chat.id, user_id=target.id,
            permissions=ChatPermissions(
                can_send_messages=True, can_send_media_messages=True,
                can_send_other_messages=True, can_add_web_page_previews=True
            )
        )
        await message.answer(
            f'<b>{target.full_name}</b> jazodan ozod qilindi.', parse_mode='HTML'
        )
    except Exception as e:
        await message.answer(f'Xatolik: {e}')


# /ban
@router.message(Command('ban'), GROUP_FILTER)
async def cmd_ban(message: Message):
    if not await _is_admin(message):
        return
    if not message.reply_to_message:
        await message.answer('Xabarga <b>reply</b> qilib /ban yozing.', parse_mode='HTML')
        return
    target = message.reply_to_message.from_user
    if not target:
        return
    if await _target_is_admin(message, target.id):
        await message.answer('Adminlarni bloklash mumkin emas!')
        return
    if message.chat.type != 'supergroup':
        await message.answer('⚠️ /ban faqat <b>superguruhda</b> ishlaydi. Guruhni superguruhga o\'tkazing.', parse_mode='HTML')
        return
    try:
        await message.bot.ban_chat_member(message.chat.id, target.id)
        mod_storage.increment_stat(message.chat.id, 'total_bans')
        await message.answer(
            f'<b>{target.full_name}</b> guruhdan bloklandi.', parse_mode='HTML'
        )
    except Exception as e:
        await message.answer(f'Xatolik: {e}')


# /unban
@router.message(Command('unban'), GROUP_FILTER)
async def cmd_unban(message: Message):
    if not await _is_admin(message):
        return
    args = message.text.split()[1:]
    if not args or not args[0].lstrip('-').isdigit():
        await message.answer('ID kiriting: /unban 123456789')
        return
    if message.chat.type != 'supergroup':
        await message.answer('⚠️ /unban faqat <b>superguruhda</b> ishlaydi. Guruhni superguruhga o\'tkazing.', parse_mode='HTML')
        return
    target_id = int(args[0])
    try:
        await message.bot.unban_chat_member(message.chat.id, target_id)
        await message.answer(f'ID:{target_id} blokdan ochildi.')
    except Exception as e:
        await message.answer(f'Xatolik: {e}')


# /modstats
@router.message(Command('modstats'), GROUP_FILTER)
async def cmd_modstats(message: Message):
    stats = mod_storage.get_stats(message.chat.id)
    since = stats.get('since', "Noma'lum")
    ochirilgan = stats.get('deleted_messages', 0)
    await message.answer(
        f'<b>Moderatsiya statistikasi</b>\n'
        f'Ochirilgan: {ochirilgan}\n'
        f'Ogohlantirishlar: {stats.get("total_warns", 0)}\n'
        f'Jazolar: {stats.get("total_mutes", 0)}\n'
        f'Bloklar: {stats.get("total_bans", 0)}\n'
        f'Shikoyatlar: {stats.get("total_reports", 0)}\n'
        f'Boshlangan: {since}',
        parse_mode='HTML'
    )


# /modstatus
@router.message(Command('modstatus'), GROUP_FILTER)
async def cmd_modstatus(message: Message):
    cfg = mod_config
    await message.answer(
        f'<b>Moderatsiya holati</b>\n'
        f'Sozlar filtri: {"On" if cfg.CHECK_BANNED_WORDS else "Off"}\n'
        f'Xakerlik filtri: {"On" if cfg.CHECK_HACKER_WORDS else "Off"}\n'
        f'Havola filtri: {"On" if cfg.CHECK_LINKS else "Off"}\n'
        f'Fayl filtri: {"On" if cfg.BLOCK_FILES else "Off"}\n'
        f'Anti-flood: {cfg.RATE_LIMIT_MAX} xabar/{cfg.RATE_LIMIT_WINDOW}s\n'
        f'Warn limiti: {cfg.WARN_LIMIT} | Har warn: {cfg.MUTE_DAYS_PER_WARN} kun',
        parse_mode='HTML'
    )