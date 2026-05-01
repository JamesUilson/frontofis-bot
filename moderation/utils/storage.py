"""
Moderation Storage — warns, stats, notifications (JSON)
"""

import json
import os
import time
from typing import Dict, List, Any, Optional
from pathlib import Path


class ModerationStorage:
    """JSON asosidagi ma'lumotlar ombori"""

    def __init__(self, data_dir: str = 'moderation_data'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        self.warns_file = self.data_dir / 'warns.json'
        self.stats_file = self.data_dir / 'stats.json'
        self.notifications_file = self.data_dir / 'notifications.json'

        self._warns: Dict[str, int] = {}
        self._stats: Dict[str, Dict[str, Any]] = {}
        self._notifications: Dict[str, Dict] = {}

        self._load_all()

    def _load_json(self, path: Path) -> dict:
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_json(self, path: Path, data: dict):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_all(self):
        self._warns = self._load_json(self.warns_file)
        self._stats = self._load_json(self.stats_file)
        self._notifications = self._load_json(self.notifications_file)
        self._cleanup_notifications()

    def _cleanup_notifications(self):
        now = time.time()
        self._notifications = {
            k: v for k, v in self._notifications.items()
            if v.get('time', 0) > now - 86400
        }
        self._save_json(self.notifications_file, self._notifications)

    # === WARNS ===

    def get_warns(self, chat_id: int, user_id: int) -> int:
        key = f"{chat_id}_{user_id}"
        return self._warns.get(key, 0)

    def add_warn(self, chat_id: int, user_id: int) -> int:
        key = f"{chat_id}_{user_id}"
        self._warns[key] = self._warns.get(key, 0) + 1
        self._save_json(self.warns_file, self._warns)
        return self._warns[key]

    def reset_warns(self, chat_id: int, user_id: int):
        key = f"{chat_id}_{user_id}"
        if key in self._warns:
            del self._warns[key]
            self._save_json(self.warns_file, self._warns)

    # === STATS ===

    def get_stats(self, chat_id: int) -> Dict[str, Any]:
        return self._stats.get(str(chat_id), {
            'total_messages': 0, 'deleted_messages': 0,
            'total_warns': 0, 'total_mutes': 0,
            'total_bans': 0, 'total_reports': 0,
            'new_members': 0,
            'since': time.strftime('%d.%m.%Y')
        })

    def increment_stat(self, chat_id: int, stat_name: str):
        chat_key = str(chat_id)
        if chat_key not in self._stats:
            self._stats[chat_key] = self.get_stats(chat_id)
        self._stats[chat_key][stat_name] = self._stats[chat_key].get(stat_name, 0) + 1
        self._save_json(self.stats_file, self._stats)

    # === NOTIFICATIONS ===

    def add_notification_group(self, key: str, messages: List[Dict]):
        self._notifications[key] = {
            'msgs': messages,
            'time': time.time(),
            'handled': False
        }
        self._save_json(self.notifications_file, self._notifications)

    def get_notification(self, key: str) -> Optional[Dict]:
        return self._notifications.get(key)

    def mark_handled(self, key: str, handled_by: int, action_text: str) -> List[Dict]:
        if key not in self._notifications:
            return []
        entry = self._notifications[key]
        if entry.get('handled'):
            return []
        entry['handled'] = True
        entry['handled_by'] = handled_by
        self._save_json(self.notifications_file, self._notifications)
        return entry.get('msgs', [])


# Global instance
mod_storage = ModerationStorage()
