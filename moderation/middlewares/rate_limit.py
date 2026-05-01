"""
Rate Limit Middleware — flood himoyasi
"""

import time
from typing import Dict, List
from aiogram import BaseMiddleware
from aiogram.types import Message


class RateLimitMiddleware(BaseMiddleware):

    def __init__(self, max_messages: int = 5, window: int = 10, mute_seconds: int = 60):
        self.max_messages = max_messages
        self.window = window
        self.mute_seconds = mute_seconds
        self._history: Dict[tuple, List[float]] = {}
        super().__init__()

    async def __call__(self, handler, event, data):
        if not isinstance(event, Message):
            return await handler(event, data)

        if event.chat.type == 'private':
            return await handler(event, data)

        user_id = event.from_user.id if event.from_user else None
        chat_id = event.chat.id

        if not user_id:
            return await handler(event, data)

        key = (chat_id, user_id)
        now = time.time()

        if key in self._history:
            self._history[key] = [ts for ts in self._history[key] if ts > now - self.window]
        else:
            self._history[key] = []

        self._history[key].append(now)

        if len(self._history[key]) > self.max_messages:
            data['rate_limit_violation'] = True
            data['rate_limit_mute'] = self.mute_seconds
            self._history[key] = []

        return await handler(event, data)
