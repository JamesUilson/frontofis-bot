"""
Content Filters — taqiqlangan sozlar, havolalar, xakerlik terminlari
"""

import re
from typing import Optional, List


class ContentFilter:

    def __init__(self, banned_words: List[str], hacker_words: List[str],
                 blocked_extensions: List[str]):
        self.banned_words = [w.lower() for w in banned_words]
        self.hacker_words = [w.lower() for w in hacker_words]
        self.blocked_extensions = blocked_extensions

        # Latin → Kirill almashtirish
        self.latin_to_cyrillic = {
            'a': 'а', 'b': 'в', 'c': 'с', 'd': 'д', 'e': 'е',
            'h': 'н', 'k': 'к', 'm': 'м', 'n': 'н', 'o': 'о',
            'p': 'р', 'r': 'р', 's': 'с', 't': 'т', 'u': 'у',
            'x': 'х', 'y': 'у', 'i': 'и',
        }

        self.link_patterns = [
            re.compile(r't\.me/[a-zA-Z0-9_]+', re.IGNORECASE),
            re.compile(r'https?://[^\s]+', re.IGNORECASE),
            re.compile(r'bit\.ly', re.IGNORECASE),
            re.compile(r'tinyurl\.com', re.IGNORECASE),
            re.compile(r'goo\.gl', re.IGNORECASE),
        ]

        self.shell_patterns = [
            re.compile(r'ip_forward\s*=\s*1'),
            re.compile(r'/proc/sys/net'),
            re.compile(r'arpspoof\s+-i'),
            re.compile(r'iptables\s+-t\s+nat'),
            re.compile(r'echo\s+1\s*>\s*/proc/sys'),
        ]

    def normalize_text(self, text: str) -> str:
        result = text
        for latin, cyr in self.latin_to_cyrillic.items():
            result = result.replace(latin, cyr)
        invisible = '\u200B\u200C\u200D\u200E\u200F\uFEFF\u00AD'
        for char in invisible:
            result = result.replace(char, '')
        return result

    def contains_banned_word(self, text: str) -> Optional[str]:
        normalized = self.normalize_text(text).lower()
        for word in self.banned_words:
            if word in normalized:
                return word
        return None

    def contains_hacker_word(self, text: str) -> Optional[str]:
        normalized = self.normalize_text(text).lower()
        for word in self.hacker_words:
            if word in normalized:
                return word
        return None

    def contains_link(self, text: str) -> Optional[str]:
        for pattern in self.link_patterns:
            match = pattern.search(text)
            if match:
                return match.group(0)
        return None

    def contains_shell_pattern(self, text: str) -> Optional[str]:
        for pattern in self.shell_patterns:
            match = pattern.search(text)
            if match:
                return match.group(0)
        return None

    def is_blocked_file(self, filename: str) -> Optional[str]:
        if not filename:
            return None
        ext = filename.split('.')[-1].lower() if '.' in filename else ''
        if ext in self.blocked_extensions:
            return ext
        return None


_filter_instance: Optional[ContentFilter] = None


def get_content_filter() -> ContentFilter:
    global _filter_instance
    if _filter_instance is None:
        from moderation.mod_config import mod_config
        _filter_instance = ContentFilter(
            mod_config.BANNED_WORDS,
            mod_config.HACKER_WORDS,
            mod_config.BLOCKED_EXTENSIONS
        )
    return _filter_instance
