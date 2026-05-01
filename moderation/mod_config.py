"""
Moderation config — FrontOfisBot ichida VerifyMeUzBot sozlamalari
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class ModerationConfig:
    """Moderatsiya sozlamalari"""

    # Ogohlantirish tizimi
    WARN_LIMIT: int = 3
    MUTE_DAYS_PER_WARN: int = 7

    # Anti-flood
    RATE_LIMIT_MAX: int = 5        # xabarlar soni
    RATE_LIMIT_WINDOW: int = 10   # soniyada
    RATE_LIMIT_MUTE: int = 60     # flood uchun mute (soniya)

    # Tekshiruvlar
    CHECK_LINKS: bool = True
    CHECK_BANNED_WORDS: bool = True
    CHECK_HACKER_WORDS: bool = True
    CHECK_SHELL_PATTERNS: bool = True
    BLOCK_FILES: bool = True

    # Ma'lumotlar papkasi
    DATA_DIR: str = 'moderation_data'

    # Taqiqlangan sozlar
    BANNED_WORDS: List[str] = field(default_factory=lambda: [
        # Reklama / daromad
        'заработай', 'зарабатывай', 'заработок', 'заработать',
        'без вложений', 'пассивный доход', 'инвестиции', 'казино', 'ставки',
        # Narkotiklar
        'наркотики', 'наркота', 'закладка', 'закладки',
        'меф', 'мефедрон', 'героин', 'кокаин', 'амфетамин',
        'спайс', 'гашиш', 'марихуана', 'скорость', 'купить наркотик',
        # VPN reklama
        'nordvpn', 'expressvpn', 'обход блокировки',
        'bepul vpn', 'blokirovkani aylanish',
    ])

    HACKER_WORDS: List[str] = field(default_factory=lambda: [
        # Asboblar
        'kali linux', 'bettercap', 'ettercap', 'metasploit',
        'arpspoof', 'dsniff', 'tcpdump', 'wireshark', 'nmap',
        'aircrack', 'burpsuite', 'sqlmap', 'hydra', 'john the ripper',
        'hashcat', 'netcat', 'nikto', 'beef framework',
        # Hujumlar
        'mitm', 'man-in-the-middle', 'arp spoofing', 'ssl strip',
        'phishing', 'keylogger', 'rat trojan', 'reverse shell',
        'brute force', 'sql injection', 'xss attack', 'ddos',
        # PowerShell
        'powershell -e', 'invoke-expression', 'iex(', 'shellcode',
        'msfvenom', 'msfconsole', 'cmd /c',
        # Boshqalar
        'взломать', 'взлом сайта', 'обход защиты',
    ])

    BLOCKED_EXTENSIONS: List[str] = field(default_factory=lambda: [
        'exe', 'bat', 'cmd', 'ps1', 'vbs', 'js', 'jar', 'sh',
        'py', 'rb', 'php', 'pl', 'scr', 'pif', 'com', 'msi',
        'dll', 'reg', 'hta', 'wsf', 'lnk', 'apk', 'dmg',
    ])


# Global instance
mod_config = ModerationConfig()
