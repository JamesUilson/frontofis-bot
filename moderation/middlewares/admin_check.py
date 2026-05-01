"""
Admin Check Middleware — frontofisbot ADMIN_IDS bilan integratsiya
"""

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated
from aiogram.enums import ChatMemberStatus


class ModerationAdminMiddleware(BaseMiddleware):

    async def __call__(self, handler, event, data):
        # frontofisbot dan ADMIN_IDS ni import qilamiz
        try:
            import sys, os
            # front.py dagi ADMIN_IDS
            parent_module = sys.modules.get('__main__')
            admin_ids = getattr(parent_module, 'ADMIN_IDS', [])
        except Exception:
            admin_ids = []

        user_id = None
        chat_id = None
        chat_type = 'private'

        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
            chat_id = event.chat.id
            chat_type = event.chat.type
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None
            if event.message:
                chat_id = event.message.chat.id
                chat_type = event.message.chat.type
        elif isinstance(event, ChatMemberUpdated):
            user_id = event.from_user.id if event.from_user else None
            chat_id = event.chat.id
            chat_type = event.chat.type

        is_owner = user_id in admin_ids if user_id else False

        is_admin = False
        if chat_type != 'private' and user_id and chat_id:
            try:
                bot = data.get('bot')
                if bot:
                    member = await bot.get_chat_member(chat_id, user_id)
                    is_admin = member.status in [
                        ChatMemberStatus.ADMINISTRATOR,
                        ChatMemberStatus.CREATOR
                    ]
            except Exception:
                pass

        data['mod_is_owner'] = is_owner
        data['mod_is_admin'] = is_admin or is_owner
        data['mod_user_id'] = user_id
        data['mod_chat_id'] = chat_id

        return await handler(event, data)
