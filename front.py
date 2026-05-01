import asyncio
import logging
import sys
import sqlite3
import json
import random
import openpyxl
import io
import os
from pathlib import Path
from datetime import datetime

# =============================================================================
# MODERATION — VerifyMeUzBot (121py) integratsiyasi
# =============================================================================
try:
    from moderation.handlers import (
        moderation_router, report_router, mod_callback_router, filter_router
    )
    from moderation.middlewares import RateLimitMiddleware, ModerationAdminMiddleware
    from moderation.mod_config import mod_config
    MODERATION_ENABLED = True
    logging.info("✅ Moderation moduli yuklandi")
except ImportError as e:
    MODERATION_ENABLED = False
    logging.warning(f"⚠️ Moderation moduli yuklanmadi: {e}")

BASE_DIR = Path(__file__).resolve().parent

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    BufferedInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

# -----------------------------------------------------------------------------
# NASTROYKALAR
# -----------------------------------------------------------------------------
TOKEN = "8550058562:AAFMl5EK-i1REFGGQIsIPyCGBYNwPpTh9dQ"
ADMIN_IDS = [2110945697, 1924892484]
STOP_NARKO_BOT_USERNAME = "stopnarko_bot"
BOT_USERNAME = "FrontOfisBot"

# ── MAJBURIY KANAL ───────────────────────────────────────────────────────────
# @ belgisi BILAN yozing, masalan: "@antinarko_front"
# Bo'sh qoldirsa (None) — tekshiruv o'chiriladi
REQUIRED_CHANNELS = ["@YoshlarFrontOfisi", "@BaxaTech2025"]

CERTIFICATE_THRESHOLD = 0.86
CERTIFICATE_TEMPLATE_PATH = str(BASE_DIR / "certificates" / "template.png")


# =============================================================================
# MAJBURIY KANAL TEKSHIRUVI
# =============================================================================
async def check_subscription(bot: Bot, user_id: int) -> bool:
    """Foydalanuvchi barcha kanallarga a'zo ekanligini tekshiradi."""
    if not REQUIRED_CHANNELS:
        return True
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in ["left", "kicked", "banned"]:
                return False
        except Exception as e:
            logging.warning(f"Kanal tekshirishda xato ({channel}): {e}")
    return True


def sub_required_kb() -> InlineKeyboardMarkup:
    """Har bir kanal uchun alohida tugma + tekshirish tugmasi."""
    buttons = [
        [InlineKeyboardButton(
            text=f"📢 {ch} kanaliga a'zo bo'lish",
            url=f"https://t.me/{ch.lstrip('@')}"
        )]
        for ch in REQUIRED_CHANNELS
    ]
    buttons.append(
        [InlineKeyboardButton(text="✅ A'zo bo'ldim, tekshirish", callback_data="check_sub")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# -----------------------------------------------------------------------------
# DATABASE
# -----------------------------------------------------------------------------
class Database:
    def __init__(self, db_name="yoshlar_fronti.db"):
        db_path = BASE_DIR / db_name
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                passport_data TEXT,
                full_name TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                description TEXT,
                date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                time_limit INTEGER DEFAULT 30,
                question_count INTEGER DEFAULT 10,
                max_attempts INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migration: max_attempts ustuni qo'shish (eski DB uchun)
        self.cursor.execute("PRAGMA table_info(tests)")
        test_cols = [row[1] for row in self.cursor.fetchall()]
        if "max_attempts" not in test_cols:
            self.cursor.execute("ALTER TABLE tests ADD COLUMN max_attempts INTEGER DEFAULT 0")

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id INTEGER NOT NULL,
                question_text TEXT NOT NULL,
                option_a TEXT NOT NULL,
                option_b TEXT NOT NULL,
                option_c TEXT NOT NULL,
                option_d TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                FOREIGN KEY (test_id) REFERENCES tests(id) ON DELETE CASCADE
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_name TEXT,
                test_id INTEGER NOT NULL,
                score INTEGER DEFAULT 0,
                total INTEGER DEFAULT 0,
                passed INTEGER DEFAULT 0,
                certificate_issued INTEGER DEFAULT 0,
                cert_code TEXT,
                finished_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (test_id) REFERENCES tests(id)
            )
        """)
        self.cursor.execute("PRAGMA table_info(test_results)")
        columns = [row[1] for row in self.cursor.fetchall()]
        if "cert_code" not in columns:
            self.cursor.execute("ALTER TABLE test_results ADD COLUMN cert_code TEXT")

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT,
                phone TEXT,
                region TEXT,
                birth_year TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        existing = [row[1] for row in self.cursor.execute("PRAGMA table_info(users)").fetchall()]
        for col, col_type in [("phone", "TEXT"), ("region", "TEXT"), ("birth_year", "TEXT")]:
            if col not in existing:
                self.cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        self.conn.commit()

    def register_user(self, user_id, username):
        self.cursor.execute(
            "INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)",
            (user_id, username)
        )
        self.conn.commit()

    def get_user(self, user_id):
        self.cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
        return self.cursor.fetchone()

    def is_registered(self, user_id):
        self.cursor.execute(
            "SELECT id FROM users WHERE id=? AND full_name IS NOT NULL AND full_name != ''",
            (user_id,)
        )
        return self.cursor.fetchone() is not None

    def set_user_name(self, user_id, full_name):
        self.cursor.execute("UPDATE users SET full_name=? WHERE id=?", (full_name, user_id))
        self.conn.commit()

    def update_user_profile(self, user_id: int, full_name: str = None, phone: str = None,
                             region: str = None, birth_year: str = None):
        user = self.get_user(user_id)
        if not user:
            return
        self.cursor.execute(
            "UPDATE users SET full_name=?, phone=?, region=?, birth_year=? WHERE id=?",
            (
                full_name if full_name is not None else user["full_name"],
                phone if phone is not None else user["phone"],
                region if region is not None else user["region"],
                birth_year if birth_year is not None else user["birth_year"],
                user_id
            )
        )
        self.conn.commit()

    def get_active_tests(self):
        self.cursor.execute("SELECT * FROM tests WHERE is_active=1 ORDER BY created_at DESC")
        return self.cursor.fetchall()

    def get_all_tests(self):
        self.cursor.execute("SELECT * FROM tests ORDER BY created_at DESC")
        return self.cursor.fetchall()

    def get_test(self, test_id):
        self.cursor.execute("SELECT * FROM tests WHERE id=?", (test_id,))
        return self.cursor.fetchone()

    def create_test(self, title, description, time_limit, question_count, max_attempts=0):
        self.cursor.execute(
            "INSERT INTO tests (title, description, time_limit, question_count, max_attempts) VALUES (?, ?, ?, ?, ?)",
            (title, description, time_limit, question_count, max_attempts)
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def update_test(self, test_id, title, description, time_limit, question_count, max_attempts=None):
        if max_attempts is None:
            self.cursor.execute(
                "UPDATE tests SET title=?, description=?, time_limit=?, question_count=? WHERE id=?",
                (title, description, time_limit, question_count, test_id)
            )
        else:
            self.cursor.execute(
                "UPDATE tests SET title=?, description=?, time_limit=?, question_count=?, max_attempts=? WHERE id=?",
                (title, description, time_limit, question_count, max_attempts, test_id)
            )
        self.conn.commit()

    def toggle_test(self, test_id):
        self.cursor.execute("SELECT is_active FROM tests WHERE id=?", (test_id,))
        row = self.cursor.fetchone()
        if row:
            new_status = 0 if row["is_active"] else 1
            self.cursor.execute("UPDATE tests SET is_active=? WHERE id=?", (new_status, test_id))
            self.conn.commit()
            return new_status
        return None

    def delete_test(self, test_id):
        self.cursor.execute("DELETE FROM tests WHERE id=?", (test_id,))
        self.conn.commit()

    def add_question(self, test_id, question_text, a, b, c, d, correct):
        self.cursor.execute(
            "INSERT INTO questions (test_id, question_text, option_a, option_b, option_c, option_d, correct_answer) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (test_id, question_text, a, b, c, d, correct.upper())
        )
        self.conn.commit()

    def get_questions(self, test_id, limit=None):
        self.cursor.execute("SELECT * FROM questions WHERE test_id=?", (test_id,))
        rows = self.cursor.fetchall()
        if limit and len(rows) > limit:
            rows = random.sample(rows, limit)
        return rows

    def get_question_count(self, test_id):
        self.cursor.execute("SELECT COUNT(*) as cnt FROM questions WHERE test_id=?", (test_id,))
        return self.cursor.fetchone()["cnt"]

    def delete_questions(self, test_id):
        self.cursor.execute("DELETE FROM questions WHERE test_id=?", (test_id,))
        self.conn.commit()

    def get_user_test_attempt_count(self, user_id: int, test_id: int) -> int:
        """Foydalanuvchi ushbu testga necha marta uringanini qaytaradi."""
        self.cursor.execute(
            "SELECT COUNT(*) as cnt FROM test_results WHERE user_id=? AND test_id=?",
            (user_id, test_id)
        )
        return self.cursor.fetchone()["cnt"]

    def save_result(self, user_id, user_name, test_id, score, total):
        import uuid
        passed = 1 if (score / total) >= CERTIFICATE_THRESHOLD else 0
        cert_code = None
        if passed:
            raw = uuid.uuid4().hex[:8].upper()
            cert_code = f"{raw[:4]}-{raw[4:]}"
        self.cursor.execute(
            "INSERT INTO test_results (user_id, user_name, test_id, score, total, passed, certificate_issued, cert_code) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, user_name, test_id, score, total, passed, passed, cert_code)
        )
        self.conn.commit()
        return passed, cert_code

    def get_cert_by_code(self, cert_code: str):
        self.cursor.execute(
            "SELECT r.*, t.title FROM test_results r JOIN tests t ON r.test_id = t.id WHERE r.cert_code=?",
            (cert_code,)
        )
        return self.cursor.fetchone()

    def get_results(self, test_id=None, limit=None):
        """limit=None bo'lsa — barcha natijalar qaytariladi."""
        if test_id and limit:
            self.cursor.execute(
                "SELECT r.*, t.title FROM test_results r JOIN tests t ON r.test_id = t.id "
                "WHERE r.test_id=? ORDER BY r.finished_at DESC LIMIT ?", (test_id, limit)
            )
        elif test_id:
            self.cursor.execute(
                "SELECT r.*, t.title FROM test_results r JOIN tests t ON r.test_id = t.id "
                "WHERE r.test_id=? ORDER BY r.finished_at DESC", (test_id,)
            )
        elif limit:
            self.cursor.execute(
                "SELECT r.*, t.title FROM test_results r JOIN tests t ON r.test_id = t.id "
                "ORDER BY r.finished_at DESC LIMIT ?", (limit,)
            )
        else:
            self.cursor.execute(
                "SELECT r.*, t.title FROM test_results r JOIN tests t ON r.test_id = t.id "
                "ORDER BY r.finished_at DESC"
            )
        return self.cursor.fetchall()

    def get_passed_results(self):
        """Faqat sertifikat olgan natijalar."""
        self.cursor.execute(
            "SELECT r.*, t.title FROM test_results r JOIN tests t ON r.test_id = t.id "
            "WHERE r.passed=1 ORDER BY r.finished_at DESC"
        )
        return self.cursor.fetchall()

    def get_user_results(self, user_id):
        self.cursor.execute(
            "SELECT r.*, t.title FROM test_results r JOIN tests t ON r.test_id = t.id "
            "WHERE r.user_id=? ORDER BY r.finished_at DESC", (user_id,)
        )
        return self.cursor.fetchall()

    def save_reset_request(self, user_id, passport, full_name):
        self.cursor.execute(
            "INSERT INTO password_resets (user_id, passport_data, full_name) VALUES (?, ?, ?)",
            (user_id, passport, full_name)
        )
        self.conn.commit()

    def save_incident(self, user_id, description):
        self.cursor.execute(
            "INSERT INTO incidents (user_id, description) VALUES (?, ?)",
            (user_id, description)
        )
        self.conn.commit()

    def get_all_users(self):
        self.cursor.execute("SELECT * FROM users ORDER BY registered_at DESC")
        return self.cursor.fetchall()

    def get_user_count(self):
        self.cursor.execute("SELECT COUNT(*) as cnt FROM users")
        return self.cursor.fetchone()["cnt"]

    def get_kpi_stats(self):
        stats = {}
        self.cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE full_name IS NOT NULL AND full_name != ''")
        stats["total_users"] = self.cursor.fetchone()["cnt"]
        self.cursor.execute("SELECT COUNT(*) as cnt FROM test_results")
        stats["total_attempts"] = self.cursor.fetchone()["cnt"]
        self.cursor.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM test_results WHERE passed=1")
        stats["cert_users"] = self.cursor.fetchone()["cnt"]
        self.cursor.execute("SELECT COUNT(*) as cnt FROM test_results WHERE passed=1")
        stats["total_certs"] = self.cursor.fetchone()["cnt"]
        self.cursor.execute("SELECT COUNT(*) as cnt FROM test_results WHERE passed=0")
        stats["total_failed"] = self.cursor.fetchone()["cnt"]
        self.cursor.execute("SELECT AVG(CAST(score AS FLOAT)/total*100) as avg FROM test_results WHERE total>0")
        row = self.cursor.fetchone()
        stats["avg_score"] = round(row["avg"] or 0, 1)
        self.cursor.execute("SELECT COUNT(*) as cnt FROM test_results WHERE DATE(finished_at)=DATE('now')")
        stats["today_attempts"] = self.cursor.fetchone()["cnt"]
        self.cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE DATE(registered_at)=DATE('now')")
        stats["today_users"] = self.cursor.fetchone()["cnt"]
        return stats

    def get_per_test_kpi(self):
        self.cursor.execute("""
            SELECT t.id, t.title,
                COUNT(r.id) as attempts,
                SUM(COALESCE(r.passed,0)) as passed,
                COUNT(r.id) - SUM(COALESCE(r.passed,0)) as failed,
                COUNT(DISTINCT r.user_id) as unique_users,
                ROUND(AVG(CAST(r.score AS FLOAT)/r.total*100), 1) as avg_pct
            FROM tests t
            LEFT JOIN test_results r ON t.id = r.test_id
            GROUP BY t.id ORDER BY attempts DESC
        """)
        return self.cursor.fetchall()

    def get_top_users(self, limit=10):
        self.cursor.execute("""
            SELECT r.user_id, r.user_name, COUNT(*) as certs,
                   ROUND(AVG(CAST(r.score AS FLOAT)/r.total*100), 1) as avg_pct
            FROM test_results r WHERE r.passed=1
            GROUP BY r.user_id ORDER BY certs DESC, avg_pct DESC LIMIT ?
        """, (limit,))
        return self.cursor.fetchall()

    def create_extra_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS dynamic_admins (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                text TEXT,
                sent INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS question_answered (
                user_id INTEGER PRIMARY KEY,
                answered_by INTEGER,
                answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def get_dynamic_admins(self):
        self.cursor.execute("SELECT * FROM dynamic_admins ORDER BY added_at")
        return self.cursor.fetchall()

    def add_dynamic_admin(self, user_id: int, added_by: int):
        self.cursor.execute(
            "INSERT OR IGNORE INTO dynamic_admins (user_id, added_by) VALUES (?, ?)",
            (user_id, added_by)
        )
        self.conn.commit()

    def remove_dynamic_admin(self, user_id: int):
        self.cursor.execute("DELETE FROM dynamic_admins WHERE user_id=?", (user_id,))
        self.conn.commit()

    def log_broadcast(self, admin_id: int, text: str, sent: int, failed: int):
        self.cursor.execute(
            "INSERT INTO broadcast_log (admin_id, text, sent, failed) VALUES (?, ?, ?, ?)",
            (admin_id, text, sent, failed)
        )
        self.conn.commit()

    def get_broadcast_history(self, limit=10):
        try:
            self.cursor.execute(
                "SELECT * FROM broadcast_log ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            return self.cursor.fetchall()
        except Exception:
            return []

    def mark_question_answered(self, user_id: int, answered_by: int):
        self.cursor.execute(
            "INSERT OR REPLACE INTO question_answered (user_id, answered_by, answered_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, answered_by)
        )
        self.conn.commit()

    def is_question_answered(self, user_id: int) -> bool:
        try:
            self.cursor.execute("SELECT 1 FROM question_answered WHERE user_id=?", (user_id,))
            return self.cursor.fetchone() is not None
        except Exception:
            return False

    def clear_question_answered(self, user_id: int):
        try:
            self.cursor.execute("DELETE FROM question_answered WHERE user_id=?", (user_id,))
            self.conn.commit()
        except Exception:
            pass


db = Database()
db.create_extra_tables()

SUPERADMIN_ID = ADMIN_IDS[0]


def get_all_admin_ids() -> list:
    dynamic = [row["user_id"] for row in db.get_dynamic_admins()]
    return list(set(ADMIN_IDS + dynamic))


# -----------------------------------------------------------------------------
# YORDAMCHI
# -----------------------------------------------------------------------------
def is_admin(user_id: int) -> bool:
    return user_id in get_all_admin_ids()


def is_superadmin(user_id: int) -> bool:
    return user_id == SUPERADMIN_ID


async def safe_edit(message, text: str, reply_markup=None, parse_mode=ParseMode.HTML):
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def notify_admins(bot, text: str, reply_markup=None):
    for admin_id in get_all_admin_ids():
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.error(f"Admin {admin_id} ga xabar yuborilmadi: {e}")


# -----------------------------------------------------------------------------
# STATES
# -----------------------------------------------------------------------------
class RegisterState(StatesGroup):
    waiting_for_fullname = State()

class CertCheckState(StatesGroup):
    waiting_for_code = State()

class ResetPasswordState(StatesGroup):
    waiting_for_passport = State()
    waiting_for_name = State()

class QuestionState(StatesGroup):
    waiting_for_question = State()

class AdminState(StatesGroup):
    waiting_for_new_password = State()

class AdminTestState(StatesGroup):
    creating_title = State()
    creating_description = State()
    creating_time = State()
    creating_count = State()
    creating_max_attempts = State()   # YANGI
    editing_value = State()
    adding_q_text = State()
    adding_q_a = State()
    adding_q_b = State()
    adding_q_c = State()
    adding_q_d = State()
    adding_q_correct = State()
    waiting_excel = State()
    waiting_certificate = State()

class TestTakingState(StatesGroup):
    taking_test = State()

class ProfileEditState(StatesGroup):
    editing_name = State()
    editing_phone = State()
    editing_region = State()
    editing_birth_year = State()

# -----------------------------------------------------------------------------
# KLAVIATURALAR
# -----------------------------------------------------------------------------
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Testlar"), KeyboardButton(text="👤 Mening ma'lumotlarim")],
        [KeyboardButton(text="🔍 Sertifikat tekshirish")],
        [KeyboardButton(text="❓ Loyiha haqida savol berish")],
        [KeyboardButton(text="🔐 Parolni tiklash"), KeyboardButton(text="🚨 Xabar berish")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Biror narsa tanlang..."
)

cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
    resize_keyboard=True
)

router = Router()


# =============================================================================
# SERTIFIKAT GENERATSIYASI
# =============================================================================
_BOLD_FONTS = [
    "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
]
_REGULAR_FONTS = [
    "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def _load_font_strict(paths: list, size: int):
    from PIL import ImageFont
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    mac_dirs = [
        "/System/Library/Fonts", "/System/Library/Fonts/Supplemental",
        "/Library/Fonts", os.path.expanduser("~/Library/Fonts"),
    ]
    bold_keywords = ["bold", "Bold", "Heavy", "Black", "Semibold"]
    for d in mac_dirs:
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if not (fname.endswith(".ttf") or fname.endswith(".otf") or fname.endswith(".ttc")):
                continue
            is_bold = any(k in fname for k in bold_keywords)
            if "bold" in paths[0].lower() and not is_bold:
                continue
            try:
                return ImageFont.truetype(os.path.join(d, fname), size)
            except Exception:
                pass
    try:
        import subprocess
        result = subprocess.run(["fc-list", "--format=%{file}\n"],
                                capture_output=True, text=True, timeout=3)
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if line and (line.endswith('.ttf') or line.endswith('.otf')) and os.path.exists(line):
                try:
                    return ImageFont.truetype(line, size)
                except Exception:
                    pass
    except Exception:
        pass
    logging.warning(f"[FONT] Hech bir font topilmadi, load_default ishlatilmoqda!")
    return ImageFont.load_default()


def _find_line_y(arr, W: int, H: int) -> int:
    try:
        dark = (
            (arr[:, :, 0] < 160) &
            (arr[:, :, 1] < 160) &
            (arr[:, :, 2] < 160)
        )
        row_counts = dark.sum(axis=1)
        threshold = W * 0.30
        candidates = [(y, int(row_counts[y])) for y in range(H) if row_counts[y] > threshold]
        if not candidates:
            return int(H * 0.504)
        candidates.sort(key=lambda x: x[0])
        clusters = []
        cur_ys, cur_cnts = [candidates[0][0]], [candidates[0][1]]
        for y, cnt in candidates[1:]:
            if y - cur_ys[-1] <= 6:
                cur_ys.append(y)
                cur_cnts.append(cnt)
            else:
                clusters.append((int(sum(cur_ys) / len(cur_ys)), max(cur_cnts)))
                cur_ys, cur_cnts = [y], [cnt]
        clusters.append((int(sum(cur_ys) / len(cur_ys)), max(cur_cnts)))
        inner = [(y, c) for y, c in clusters if H * 0.15 < y < H * 0.90]
        if inner:
            best_y = max(inner, key=lambda x: x[1])[0]
        else:
            best_y = max(clusters, key=lambda x: x[1])[0]
        return best_y
    except Exception as e:
        logging.warning(f"Chiziq topishda xato: {e}")
        return int(H * 0.504)


async def generate_certificate(full_name, test_title, score, total, cert_code) -> bytes | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
        import qrcode as qrcode_lib

        if not os.path.exists(CERTIFICATE_TEMPLATE_PATH):
            logging.warning("Sertifikat shabloni topilmadi: " + CERTIFICATE_TEMPLATE_PATH)
            return None

        img = Image.open(CERTIFICATE_TEMPLATE_PATH).convert("RGBA")
        W, H = img.size
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        NAME_COLOR = (14, 52, 110, 255)

        WX1 = int(W * 0.050); WX2 = int(W * 0.951); WCX = (WX1 + WX2) // 2
        LINE_Y = int(H * 0.504)
        QR_X1 = int(W * 0.449); QR_X2 = int(W * 0.562)
        QR_Y1 = int(H * 0.696); QR_Y2 = int(H * 0.860)
        QR_CX = (QR_X1 + QR_X2) // 2; QR_CY = (QR_Y1 + QR_Y2) // 2
        QR_BOX_SIZE = min(QR_X2 - QR_X1, QR_Y2 - QR_Y1)
        RIGHT_LINE_Y  = int(H * 0.791)
        RIGHT_LINE_X1 = int(W * 0.563); RIGHT_LINE_X2 = int(W * 0.847)
        RIGHT_LINE_CX = (RIGHT_LINE_X1 + RIGHT_LINE_X2) // 2

        fs_name = max(int(H * 0.085), 52); fs_code = max(int(H * 0.046), 30)
        fs_label = max(int(H * 0.027), 18); fs_hint = max(int(H * 0.023), 15)

        font_name  = _load_font_strict(_BOLD_FONTS, fs_name)
        font_code  = _load_font_strict(_BOLD_FONTS, fs_code)
        font_label = _load_font_strict(_REGULAR_FONTS, fs_label)
        font_hint  = _load_font_strict(_REGULAR_FONTS, fs_hint)

        TARGET_W = int((WX2 - WX1) * 0.72)
        while fs_name > 30:
            font_name = _load_font_strict(_BOLD_FONTS, fs_name)
            bb = draw.textbbox((0, 0), full_name, font=font_name)
            if bb[2] - bb[0] <= TARGET_W:
                break
            fs_name -= 2

        bb = draw.textbbox((0, 0), full_name, font=font_name)
        nw, nh = bb[2] - bb[0], bb[3] - bb[1]
        nx = WCX - nw // 2; ny = LINE_Y - nh - max(10, int(H * 0.008))
        draw.text((nx + 2, ny + 2), full_name, font=font_name, fill=(0, 0, 0, 40))
        draw.text((nx, ny), full_name, font=font_name, fill=NAME_COLOR)

        qr_url = f"https://t.me/{BOT_USERNAME}?start=cert_{cert_code}"
        qr_obj = qrcode_lib.QRCode(version=2, box_size=8, border=1,
                                   error_correction=qrcode_lib.constants.ERROR_CORRECT_M)
        qr_obj.add_data(qr_url); qr_obj.make(fit=True)
        qr_pil = qr_obj.make_image(fill_color="black", back_color="white").convert("RGBA")
        PAD = int(QR_BOX_SIZE * 0.04); qr_size = QR_BOX_SIZE - PAD * 2
        qr_pil = qr_pil.resize((qr_size, qr_size), Image.LANCZOS)
        qr_x = QR_CX - qr_size // 2; qr_y = QR_CY - qr_size // 2

        def cx_text(text, font, cx, y, color):
            bb = draw.textbbox((0, 0), text, font=font)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            draw.text((cx - tw // 2, y), text, font=font, fill=color)
            return th

        bb_code  = draw.textbbox((0, 0), cert_code, font=font_code)
        bb_label = draw.textbbox((0, 0), "Sertifikat raqami", font=font_label)
        code_h = bb_code[3] - bb_code[1]; label_h = bb_label[3] - bb_label[1]
        GAP = max(6, int(H * 0.005))
        raqam_y = RIGHT_LINE_Y - code_h - GAP
        label_y = raqam_y - label_h - GAP // 2
        hint_y  = RIGHT_LINE_Y + GAP

        cx_text("Sertifikat raqami", font_label, RIGHT_LINE_CX, label_y, (90, 90, 90, 255))
        cx_text(cert_code, font_code, RIGHT_LINE_CX, raqam_y, NAME_COLOR)
        cx_text("@FrontOfisBot orqali tekshiring", font_hint, RIGHT_LINE_CX, hint_y, (100, 100, 100, 220))

        result = Image.alpha_composite(img, overlay)
        result.paste(qr_pil, (qr_x, qr_y), qr_pil)
        buf = io.BytesIO()
        result.convert("RGB").save(buf, format="PNG", dpi=(150, 150))
        logging.info(f"[CERT] OK — {len(buf.getvalue())} bytes")
        return buf.getvalue()

    except Exception as e:
        logging.error(f"[CERT] Xato: {e}", exc_info=True)
        return None


# =============================================================================
# MAJBURIY KANAL — CALLBACK HANDLER
# =============================================================================
@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery, state: FSMContext):
    """Foydalanuvchi 'A'zo bo'ldim' tugmasini bosganida tekshiradi."""
    subscribed = await check_subscription(callback.bot, callback.from_user.id)
    if subscribed:
        await callback.answer("✅ Rahmat! Endi botdan foydalanishingiz mumkin.", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        # Foydalanuvchini tizimga qaytarish
        user_id = callback.from_user.id
        db.register_user(user_id, callback.from_user.username or "")
        if db.is_registered(user_id):
            user = db.get_user(user_id)
            await callback.message.answer(
                f"Assalomu alaykum, <b>{user['full_name']}</b>!\n\n"
                "🏛 <b>ANTI-NARKO YOSHLAR FRONT OFISI</b> botiga xush kelibsiz.",
                reply_markup=main_menu, parse_mode=ParseMode.HTML
            )
        else:
            await state.set_state(RegisterState.waiting_for_fullname)
            await callback.message.answer(
                "🏛 <b>ANTI-NARKO YOSHLAR FRONT OFISI</b> botiga xush kelibsiz!\n\n"
                "✍️ Iltimos, <b>Ism va Familiyangizni</b> to'liq kiriting:\n"
                "<i>(masalan: Alisher Karimov)</i>",
                parse_mode=ParseMode.HTML
            )
    else:
        await callback.answer(
            "❌ Siz hali kanalga a'zo bo'lmadingiz! Iltimos, avval a'zo bo'ling.",
            show_alert=True
        )


# =============================================================================
# START — DEEP LINK BILAN
# =============================================================================

# Guruhda /start — tugmasiz, faqat ma'lumot
@router.message(CommandStart(), F.chat.type.in_({"group", "supergroup"}))
async def group_start_handler(message: Message):
    from aiogram.types import ReplyKeyboardRemove
    await message.answer(
        "✅ Bot guruhda moderatsiya rejimida ishlayapti.\n"
        "Admin buyruqlari: /warn /mute /ban /unban /unwarn /warns /report /moders /modstats /modstatus",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(CommandStart(deep_link=True))
async def command_start_deeplink(message: Message, state: FSMContext, command: CommandObject):
    payload = command.args or ""
    if payload.startswith("cert_"):
        cert_code = payload[5:].upper().strip()
        await _show_cert_info(message, cert_code)
        return
    await command_start_handler(message, state, command)


@router.message(CommandStart())
async def command_start_handler(message: Message, state: FSMContext, command: CommandObject = None):
    user_id = message.from_user.id
    db.register_user(user_id, message.from_user.username or "")

    # ── MAJBURIY KANAL TEKSHIRUVI ────────────────────────────────────────────
    if not is_admin(user_id):
        subscribed = await check_subscription(message.bot, user_id)
        if not subscribed:
            await message.answer(
                f"👋 Assalomu alaykum!\n\n"
                f"🏛 <b>ANTI-NARKO YOSHLAR FRONT OFISI</b> botidan foydalanish uchun\n"
                f"avval rasmiy kanalimizga a'zo bo'lishingiz kerak:\n\n"
                f"{' | '.join(REQUIRED_CHANNELS)}",
                reply_markup=sub_required_kb(),
                parse_mode=ParseMode.HTML
            )
            return

    if db.is_registered(user_id):
        user = db.get_user(user_id)
        await message.answer(
            f"Assalomu alaykum, <b>{user['full_name']}</b>!\n\n"
            "🏛 <b>ANTI-NARKO YOSHLAR FRONT OFISI</b> botiga xush kelibsiz.\n\n"
            "📝 Testlar bo'limida bilimingizni sinab ko'ring va <b>sertifikat</b> oling!",
            reply_markup=main_menu, parse_mode=ParseMode.HTML
        )
    else:
        await state.set_state(RegisterState.waiting_for_fullname)
        await message.answer(
            "🏛 <b>ANTI-NARKO YOSHLAR FRONT OFISI</b> botiga xush kelibsiz!\n\n"
            "✍️ Iltimos, <b>Ism va Familiyangizni</b> to'liq kiriting:\n"
            "<i>(masalan: Alisher Karimov)</i>",
            parse_mode=ParseMode.HTML
        )


@router.message(RegisterState.waiting_for_fullname, F.text)
async def register_fullname(message: Message, state: FSMContext):
    full_name = message.text.strip()
    if len(full_name.split()) < 2:
        await message.answer(
            "⚠️ Iltimos, <b>Ism va Familiyangizni</b> to'liq kiriting.\n"
            "<i>(masalan: Alisher Karimov)</i>",
            parse_mode=ParseMode.HTML
        )
        return
    db.set_user_name(message.from_user.id, full_name)
    await state.clear()
    await message.answer(
        f"✅ Ro'yxatdan o'tdingiz!\n\n"
        f"Xush kelibsiz, <b>{full_name}</b>!\n\n"
        "📝 Testlar bo'limida bilimingizni sinab ko'ring va <b>sertifikat</b> oling!",
        reply_markup=main_menu, parse_mode=ParseMode.HTML
    )


@router.message(RegisterState.waiting_for_fullname)
async def register_fullname_invalid(message: Message):
    await message.answer(
        "✍️ Iltimos, ism-familiyangizni <b>matn</b> ko'rinishida yozing.",
        parse_mode=ParseMode.HTML
    )


# =============================================================================
# SERTIFIKAT TEKSHIRISH
# =============================================================================
async def _show_cert_info(message: Message, cert_code: str):
    cert = db.get_cert_by_code(cert_code)
    if not cert:
        await message.answer(
            f"❌ <b>{cert_code}</b> raqamli sertifikat topilmadi.\n\nRaqamni tekshiring.",
            reply_markup=main_menu, parse_mode=ParseMode.HTML
        )
        return
    pct = int(cert["score"] / cert["total"] * 100) if cert["total"] else 0
    date_str = cert["finished_at"][:10] if cert["finished_at"] else "—"
    await message.answer(
        f"✅ <b>Sertifikat haqiqiy!</b>\n\n"
        f"👤 <b>Egasi:</b> {cert['user_name'] or '—'}\n"
        f"📋 <b>Test:</b> {cert['title']}\n"
        f"📊 <b>Natija:</b> {cert['score']}/{cert['total']} ({pct}%)\n"
        f"📅 <b>Sana:</b> {date_str}\n"
        f"🔖 <b>Raqam:</b> <code>{cert['cert_code']}</code>",
        reply_markup=main_menu, parse_mode=ParseMode.HTML
    )


# =============================================================================
# PROFIL
# =============================================================================
UZ_REGIONS = [
    "Toshkent shahri", "Toshkent viloyati", "Andijon", "Farg'ona", "Namangan",
    "Samarqand", "Buxoro", "Navoiy", "Qashqadaryo", "Surxondaryo",
    "Xorazm", "Sirdaryo", "Jizzax", "Qoraqalpog'iston"
]


def _profile_text(user) -> str:
    name = user["full_name"] or "—"; phone = user["phone"] or "—"
    region = user["region"] or "—"; birth = user["birth_year"] or "—"
    reg_date = (user["registered_at"] or "")[:10] or "—"
    tg = f"@{user['username']}" if user["username"] else "—"
    return (
        f"👤 <b>MENING MA'LUMOTLARIM</b>\n\n"
        f"📛 <b>Ism Familiya:</b> {name}\n"
        f"📱 <b>Telefon:</b> {phone}\n"
        f"🗺 <b>Viloyat:</b> {region}\n"
        f"🎂 <b>Tug'ilgan yil:</b> {birth}\n"
        f"✈️ <b>Telegram:</b> {tg}\n"
        f"📅 <b>Ro'yxatdan o'tgan:</b> {reg_date}\n"
    )


def _profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Ism Familiya", callback_data="edit_profile_name"),
            InlineKeyboardButton(text="📱 Telefon", callback_data="edit_profile_phone"),
        ],
        [
            InlineKeyboardButton(text="🗺 Viloyat", callback_data="edit_profile_region"),
            InlineKeyboardButton(text="🎂 Tug'ilgan yil", callback_data="edit_profile_birth"),
        ],
        [InlineKeyboardButton(text="📊 Natijalarim", callback_data="my_results")],
    ])


@router.message(F.text == "👤 Mening ma'lumotlarim")
async def my_profile(message: Message, state: FSMContext):
    await state.clear()
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Avval /start orqali ro'yxatdan o'ting.")
        return
    await message.answer(_profile_text(user), reply_markup=_profile_kb(), parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "edit_profile_name")
async def edit_name_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileEditState.editing_name)
    await callback.message.edit_text(
        "✏️ <b>Yangi Ism Familiyangizni kiriting:</b>\n\n<i>Misol: Alisher Karimov</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_profile_edit")]
        ])
    )
    await callback.answer()


@router.message(ProfileEditState.editing_name, F.text)
async def edit_name_save(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name.split()) < 2:
        await message.answer(
            "⚠️ Iltimos, <b>Ism va Familiyani</b> to'liq kiriting.",
            parse_mode=ParseMode.HTML
        )
        return
    db.update_user_profile(message.from_user.id, full_name=name)
    await state.clear()
    user = db.get_user(message.from_user.id)
    await message.answer(f"✅ Ism yangilandi!\n\n{_profile_text(user)}", reply_markup=_profile_kb(), parse_mode=ParseMode.HTML)


@router.message(ProfileEditState.editing_name)
async def edit_name_invalid(message: Message):
    await message.answer("✍️ Iltimos, ismni <b>matn</b> ko'rinishida yozing.", parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "edit_profile_phone")
async def edit_phone_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileEditState.editing_phone)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Telefon raqamni ulashish", request_contact=True)],
            [KeyboardButton(text="❌ Bekor qilish")]
        ],
        resize_keyboard=True
    )
    await callback.message.answer(
        "📱 <b>Telefon raqamingizni kiriting yoki ulashing:</b>\n\n<i>Misol: +998901234567</i>",
        parse_mode=ParseMode.HTML, reply_markup=kb
    )
    await callback.answer()


@router.message(ProfileEditState.editing_phone, F.contact)
async def edit_phone_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    if not phone.startswith("+"): phone = "+" + phone
    db.update_user_profile(message.from_user.id, phone=phone)
    await state.clear()
    user = db.get_user(message.from_user.id)
    await message.answer(f"✅ Telefon yangilandi!\n\n{_profile_text(user)}", reply_markup=_profile_kb(), parse_mode=ParseMode.HTML)


@router.message(ProfileEditState.editing_phone, F.text)
async def edit_phone_text(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        user = db.get_user(message.from_user.id)
        await message.answer(_profile_text(user), reply_markup=_profile_kb(), parse_mode=ParseMode.HTML)
        return
    phone = message.text.strip()
    digits = phone.replace("+", "").replace(" ", "").replace("-", "")
    if not digits.isdigit() or len(digits) < 9:
        await message.answer("⚠️ Noto'g'ri format. Misol: +998901234567"); return
    db.update_user_profile(message.from_user.id, phone=phone)
    await state.clear()
    user = db.get_user(message.from_user.id)
    await message.answer(f"✅ Telefon yangilandi!\n\n{_profile_text(user)}", reply_markup=_profile_kb(), parse_mode=ParseMode.HTML)


@router.message(ProfileEditState.editing_phone)
async def edit_phone_invalid(message: Message):
    await message.answer("⚠️ Iltimos, telefon raqamni matn yoki kontakt sifatida yuboring.")


@router.callback_query(F.data == "edit_profile_region")
async def edit_region_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileEditState.editing_region)
    buttons = []
    row = []
    for i, reg in enumerate(UZ_REGIONS):
        row.append(InlineKeyboardButton(text=reg, callback_data=f"set_region_{i}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_profile_edit")])
    await callback.message.edit_text("🗺 <b>Viloyatingizni tanlang:</b>", parse_mode=ParseMode.HTML,
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("set_region_"))
async def set_region(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split("_")[2])
    if idx < 0 or idx >= len(UZ_REGIONS):
        await callback.answer("Xato!"); return
    db.update_user_profile(callback.from_user.id, region=UZ_REGIONS[idx])
    await state.clear()
    user = db.get_user(callback.from_user.id)
    await safe_edit(callback.message, f"✅ Viloyat yangilandi!\n\n{_profile_text(user)}", reply_markup=_profile_kb())
    await callback.answer()


@router.callback_query(F.data == "edit_profile_birth")
async def edit_birth_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileEditState.editing_birth_year)
    current_year = datetime.now().year
    years = list(range(current_year - 15, 1979, -1))
    buttons = []; row = []
    for y in years:
        row.append(InlineKeyboardButton(text=str(y), callback_data=f"set_birth_{y}"))
        if len(row) == 5:
            buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_profile_edit")])
    await callback.message.edit_text("🎂 <b>Tug'ilgan yilingizni tanlang:</b>", parse_mode=ParseMode.HTML,
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("set_birth_"))
async def set_birth(callback: CallbackQuery, state: FSMContext):
    year = callback.data.split("_")[2]
    db.update_user_profile(callback.from_user.id, birth_year=year)
    await state.clear()
    user = db.get_user(callback.from_user.id)
    await safe_edit(callback.message, f"✅ Tug'ilgan yil yangilandi!\n\n{_profile_text(user)}", reply_markup=_profile_kb())
    await callback.answer()


@router.callback_query(F.data == "cancel_profile_edit")
async def cancel_profile_edit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = db.get_user(callback.from_user.id)
    await safe_edit(callback.message, _profile_text(user), reply_markup=_profile_kb())
    await callback.answer()


@router.message(F.text.in_({"🔍 Sertifikat tekshirish", "/check"}))
async def cert_check_start(message: Message, state: FSMContext):
    await state.set_state(CertCheckState.waiting_for_code)
    await message.answer(
        "🔍 <b>Sertifikat tekshirish</b>\n\n"
        "Sertifikat raqamini kiriting (masalan: <code>A1B2-C3D4</code>):",
        reply_markup=cancel_kb, parse_mode=ParseMode.HTML
    )


@router.message(CertCheckState.waiting_for_code, F.text)
async def cert_check_code(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=main_menu)
        return
    await state.clear()
    await _show_cert_info(message, message.text.strip().upper())


@router.message(CertCheckState.waiting_for_code)
async def cert_check_code_invalid(message: Message):
    await message.answer("❗ Faqat sertifikat kodini matn ko'rinishida yuboring.")


# =============================================================================
# TESTLAR
# =============================================================================
@router.message(F.text == "📝 Testlar")
async def tests_menu(message: Message, state: FSMContext):
    await state.clear()
    # Kanalga a'zoligini tekshirish
    if not is_admin(message.from_user.id):
        subscribed = await check_subscription(message.bot, message.from_user.id)
        if not subscribed:
            await message.answer(
                f"📢 Testlarga kirish uchun kanalga a'zo bo'ling:",
                reply_markup=sub_required_kb()
            )
            return

    active_tests = db.get_active_tests()
    if not active_tests:
        await message.answer("📭 Hozircha faol testlar yo'q.\nYaqinda qo'shiladi!", reply_markup=main_menu)
        return

    my_results = {r["test_id"]: r for r in db.get_user_results(message.from_user.id)}
    text = "📝 <b>Mavjud testlar</b>\n\nBitta testni tanlang:\n\n"
    buttons = []

    for t in active_tests:
        result_info = ""
        if t["id"] in my_results:
            r = my_results[t["id"]]
            pct = int(r["score"] / r["total"] * 100) if r["total"] else 0
            result_info = f" ✅ {pct}%" if r["passed"] else f" ❌ {pct}%"
        # Max urinish ko'rsatish
        attempt_count = db.get_user_test_attempt_count(message.from_user.id, t["id"])
        max_att = t["max_attempts"] if t["max_attempts"] else 0
        att_info = ""
        if max_att > 0:
            att_info = f" [{attempt_count}/{max_att}]"
        buttons.append([InlineKeyboardButton(
            text=f"📋 {t['title']}{result_info}{att_info}",
            callback_data=f"start_test_{t['id']}"
        )])

    buttons.append([InlineKeyboardButton(text="📊 Mening natijalarim", callback_data="my_results")])
    buttons.append([InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="back_to_main")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith("start_test_"))
async def show_test_info(callback: CallbackQuery, state: FSMContext):
    test_id = int(callback.data.split("_")[2])
    test = db.get_test(test_id)
    if not test:
        await callback.answer("Test topilmadi!", show_alert=True); return

    q_count = db.get_question_count(test_id)
    limit = min(test["question_count"], q_count)

    # Max urinish tekshiruvi
    max_att = test["max_attempts"] if test["max_attempts"] else 0
    attempt_count = db.get_user_test_attempt_count(callback.from_user.id, test_id)
    att_text = ""
    if max_att > 0:
        att_text = f"🔄 Urinishlar: <b>{attempt_count}/{max_att}</b>\n"
        if attempt_count >= max_att:
            await callback.message.edit_text(
                f"⛔ <b>{test['title']}</b>\n\n"
                f"Siz bu testga belgilangan maksimal urinishlar soniga ({max_att} ta) yetdingiz.\n\n"
                f"Boshqa testlarni sinab ko'ring.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅Orqaga", callback_data="back_to_tests")]
                ]),
                parse_mode=ParseMode.HTML
            )
            await callback.answer(); return

    text = (
        f"📋 <b>{test['title']}</b>\n\n"
        f"📝 {test['description'] or 'Tavsif yoq'}\n\n"
        f"❓ Savollar soni: <b>{limit}</b>\n"
        f"⏱ Vaqt: <b>{test['time_limit']} daqiqa</b>\n"
        f"🏆 Sertifikat uchun: <b>{int(CERTIFICATE_THRESHOLD * 100)}% va undan yuqori</b>\n"
        f"{att_text}\n"
        f"<i>Boshlashga tayyormisiz?</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Boshlash", callback_data=f"begin_test_{test_id}")],
        [InlineKeyboardButton(text="⬅Orqaga", callback_data="back_to_tests")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "back_to_tests")
async def back_to_tests(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await tests_menu(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("begin_test_"))
async def begin_test(callback: CallbackQuery, state: FSMContext):
    test_id = int(callback.data.split("_")[2])
    test = db.get_test(test_id)
    if not test:
        await callback.answer("Test topilmadi!", show_alert=True); return

    # Max urinish qayta tekshiruv
    max_att = test["max_attempts"] if test["max_attempts"] else 0
    if max_att > 0:
        attempt_count = db.get_user_test_attempt_count(callback.from_user.id, test_id)
        if attempt_count >= max_att:
            await callback.answer(
                f"⛔ Maksimal urinishlar soni ({max_att} ta) tugadi!", show_alert=True
            )
            return

    questions = db.get_questions(test_id, limit=test["question_count"])
    if not questions:
        await callback.answer("Bu testda savollar yo'q!", show_alert=True); return

    q_list = [dict(q) for q in questions]
    random.shuffle(q_list)

    await state.set_state(TestTakingState.taking_test)
    await state.update_data(
        test_id=test_id, questions=q_list, current=0, answers={},
        start_time=datetime.now().isoformat()
    )
    await callback.message.edit_text(
        f"✅ Test boshlandi!\n\n<b>{test['title']}</b>\n"
        f"⏱ Vaqt: {test['time_limit']} daqiqa\n"
        f"Savollar soni: {len(q_list)}\n\nBirinchi savol...",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()
    await send_question(callback.message, state, callback.bot)


async def send_question(message: Message, state: FSMContext, bot: Bot = None):
    data = await state.get_data()
    questions = data.get("questions")
    current = data.get("current", 0)

    if not questions:
        await state.clear()
        try:
            await message.answer(
                "⚠️ Test sessiyasi tugagan. Iltimos, testni qaytadan boshlang.",
                reply_markup=main_menu
            )
        except Exception:
            pass
        return

    if current >= len(questions):
        await finish_test(message, state, bot)
        return

    q = questions[current]
    total = len(questions)
    progress = int((current / total) * 10)
    bar = "🟦" * progress + "⬜" * (10 - progress)

    text = (
        f"{bar}\n"
        f"<b>Savol {current + 1}/{total}</b>\n\n"
        f"❓ {q['question_text']}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"A) {q['option_a']}", callback_data="ans_A")],
        [InlineKeyboardButton(text=f"B) {q['option_b']}", callback_data="ans_B")],
        [InlineKeyboardButton(text=f"C) {q['option_c']}", callback_data="ans_C")],
        [InlineKeyboardButton(text=f"D) {q['option_d']}", callback_data="ans_D")],
        [InlineKeyboardButton(text="🛑 Testni to'xtatish", callback_data="stop_test")]
    ])
    try:
        if bot:
            await bot.send_message(message.chat.id, text, reply_markup=kb, parse_mode=ParseMode.HTML)
        else:
            await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Savol yuborishda xato: {e}")


@router.callback_query(F.data.startswith("ans_"), TestTakingState.taking_test)
async def process_answer(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    questions = data["questions"]
    current = data["current"]
    answers = data["answers"]

    chosen = callback.data.split("_")[1]
    q = questions[current]
    correct = q["correct_answer"]
    answers[str(current)] = {"chosen": chosen, "correct": correct, "is_correct": chosen == correct}
    await state.update_data(answers=answers, current=current + 1)

    if chosen == correct:
        feedback = "✅ To'g'ri! +1"
    else:
        opt = {"A": q["option_a"], "B": q["option_b"], "C": q["option_c"], "D": q["option_d"]}
        feedback = f"❌ Noto'g'ri. To'g'ri: <b>{correct}) {opt[correct]}</b>"

    try:
        await callback.message.edit_text(callback.message.text + f"\n\n{feedback}", parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await callback.answer()
    await asyncio.sleep(0.8)
    await send_question(callback.message, state, callback.bot)


@router.callback_query(F.data == "stop_test")
async def stop_test(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Ha, to'xtataman", callback_data="confirm_stop"),
        InlineKeyboardButton(text="Yo'q, davom etaman", callback_data="continue_test")
    ]])
    await callback.message.edit_text(
        "⚠️ Testni to'xtatmoqchimisiz?\n\nTo'xtatilsa natijalar saqlanmaydi!",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data == "confirm_stop")
async def confirm_stop(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🛑 Test to'xtatildi.")
    await callback.message.answer("Asosiy menyu:", reply_markup=main_menu)
    await callback.answer()


@router.callback_query(F.data == "continue_test")
async def continue_test_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Davom eting! 💪")
    await send_question(callback.message, state, callback.bot)


async def finish_test(message: Message, state: FSMContext, bot: Bot = None):
    data = await state.get_data()
    questions = data.get("questions")
    answers = data.get("answers", {})
    test_id = data.get("test_id")

    if not questions or not test_id:
        await state.clear()
        try:
            await message.answer("⚠️ Test sessiyasi tugagan. Qaytadan boshlang.", reply_markup=main_menu)
        except Exception:
            pass
        return

    test = db.get_test(test_id)
    total = len(questions)
    score = sum(1 for a in answers.values() if a["is_correct"])
    percent = int(score / total * 100)
    chat_id = message.chat.id

    user_row = db.get_user(chat_id)
    db_name = user_row["full_name"] if user_row and user_row["full_name"] else (
        getattr(message.chat, "full_name", None) or str(chat_id)
    )

    passed, cert_code = db.save_result(chat_id, db_name, test_id, score, total)

    wrong_list = []
    for i, q in enumerate(questions):
        a = answers.get(str(i))
        if a and not a["is_correct"]:
            opt = {"A": q["option_a"], "B": q["option_b"], "C": q["option_c"], "D": q["option_d"]}
            wrong_list.append(
                f"• {q['question_text'][:50]}...\n"
                f"  Siz: {a['chosen']}) | To'g'ri: {a['correct']}) {opt[a['correct']]}"
            )

    result_text = (
        f"🏁 <b>Test yakunlandi!</b>\n\n"
        f"📋 Test: <b>{test['title']}</b>\n\n"
        f"📊 Natija: <b>{score}/{total}</b> ({percent}%)\n"
    )
    if passed:
        result_text += "\n🏆 <b>TABRIKLAYMIZ! Sertifikat oldingiz!</b>\n"
    else:
        need = int(CERTIFICATE_THRESHOLD * total) - score
        result_text += f"\n❌ Sertifikat uchun yana <b>{need} ta</b> to'g'ri javob kerak edi.\n"

    if wrong_list:
        result_text += f"\n📌 Noto'g'ri javoblar ({len(wrong_list)} ta):\n"
        result_text += "\n".join(wrong_list[:5])
        if len(wrong_list) > 5:
            result_text += f"\n... va yana {len(wrong_list) - 5} ta"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Qayta urinish", callback_data=f"start_test_{test_id}")],
        [InlineKeyboardButton(text="📝 Boshqa testlar", callback_data="back_to_tests")],
        [InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="back_to_main")]
    ])
    await state.clear()

    try:
        if bot:
            await bot.send_message(chat_id, result_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        else:
            await message.answer(result_text, reply_markup=kb, parse_mode=ParseMode.HTML)

        if passed:
            cert_bytes = await generate_certificate(db_name, test["title"], score, total, cert_code)
            caption = (
                f"🎓 <b>Sertifikatingiz!</b>\n"
                f"🔖 Raqam: <code>{cert_code}</code>\n\n"
                f"QR kodni skanerlash orqali sertifikatni tekshirish mumkin.\n"
                f"Saqlang va ulashing 🌟"
            )
            if cert_bytes:
                cert_file = BufferedInputFile(cert_bytes, filename="sertifikat.png")
                if bot:
                    await bot.send_photo(chat_id, cert_file, caption=caption, parse_mode=ParseMode.HTML)
                else:
                    await message.answer_photo(cert_file, caption=caption, parse_mode=ParseMode.HTML)
            else:
                warn = (
                    f"🏆 <b>Tabriklaymiz!</b>\n\n"
                    f"🔖 Sertifikat raqami: <code>{cert_code}</code>\n"
                    f"Admin sertifikat shablonini yuklagandan so'ng avtomatik tayyorlanadi."
                )
                if bot:
                    await bot.send_message(chat_id, warn, parse_mode=ParseMode.HTML)
                else:
                    await message.answer(warn, parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Natija yuborishda xato: {e}", exc_info=True)


@router.callback_query(F.data == "my_results")
async def my_results(callback: CallbackQuery):
    results = db.get_user_results(callback.from_user.id)
    if not results:
        await callback.answer("Sizda hali natijalar yo'q!", show_alert=True); return
    text = "📊 <b>Mening natijalarim:</b>\n\n"
    cert_buttons = []
    for r in results[:10]:
        pct = int(r["score"] / r["total"] * 100) if r["total"] else 0
        status = "🏆 Sertifikat" if r["passed"] else "❌ O'tmadi"
        text += f"📋 {r['title']}\n{status} — {r['score']}/{r['total']} ({pct}%)\n\n"
        if r["passed"] and r["cert_code"]:
            cert_buttons.append([
                InlineKeyboardButton(
                    text=f"⬇️ {r['title'][:30]} sertifikatini yuklab olish",
                    callback_data=f"dl_cert_{r['cert_code']}"
                )
            ])
    inline_rows = cert_buttons + [
        [InlineKeyboardButton(text="⬅Orqaga", callback_data="back_to_tests")]
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=inline_rows)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data.startswith("dl_cert_"))
async def download_cert_callback(callback: CallbackQuery):
    cert_code = callback.data[len("dl_cert_"):]
    row = db.get_cert_by_code(cert_code)
    if not row:
        await callback.answer("❌ Sertifikat topilmadi!", show_alert=True)
        return
    if row["user_id"] != callback.from_user.id and not is_admin(callback.from_user.id):
        await callback.answer("❌ Bu sertifikat sizga tegishli emas!", show_alert=True)
        return
    await callback.answer("⏳ Sertifikat tayyorlanmoqda...")
    user = db.get_user(row["user_id"])
    full_name = user["full_name"] if user and user["full_name"] else row.get("user_name", "")
    cert_bytes = await generate_certificate(
        full_name, row["title"], row["score"], row["total"], cert_code
    )
    if cert_bytes:
        await callback.message.answer_document(
            BufferedInputFile(cert_bytes, filename=f"sertifikat_{cert_code}.png"),
            caption=(
                f"🏆 <b>Sertifikatingiz!</b>\n\n"
                f"📋 Test: <b>{row['title']}</b>\n"
                f"🔑 Kod: <code>{cert_code}</code>"
            ),
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.message.answer(
            "⚠️ Sertifikat fayli yaratishda xatolik yuz berdi. Admin sertifikat shablonini yuklaganidan so'ng qayta urinib ko'ring."
        )


# =============================================================================
# ADMIN PANEL
# =============================================================================
@router.message(F.text == "/admin")
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizga ruxsat yo'q!"); return
    await _send_admin_panel(message)


async def _send_admin_panel(message: Message, edit: bool = False, user_id: int = None):
    tests = db.get_all_tests()
    total_tests = len(tests)
    active_tests = sum(1 for t in tests if t["is_active"])
    kpi = db.get_kpi_stats()
    text = (
        f"⚙️ <b>ADMIN PANEL</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{kpi['total_users']}</b>  |  Bugun: <b>+{kpi['today_users']}</b>\n"
        f"📋 Testlar: <b>{total_tests}</b>  |  Faol: <b>{active_tests}</b>\n"
        f"🎯 Urinishlar: <b>{kpi['total_attempts']}</b>  |  Bugun: <b>{kpi['today_attempts']}</b>\n"
        f"🏆 Sertifikatlar: <b>{kpi['total_certs']}</b>  |  O'rtacha: <b>{kpi['avg_score']}%</b>\n"
    )
    uid = user_id if user_id is not None else message.from_user.id
    rows = [
        [
            InlineKeyboardButton(text="Testlar", callback_data="admin_tests_list"),
            InlineKeyboardButton(text="Test yaratish", callback_data="admin_create_test"),
        ],
        [
            InlineKeyboardButton(text="Natijalar", callback_data="admin_results"),
            InlineKeyboardButton(text="KPI", callback_data="admin_kpi"),
        ],
        [
            InlineKeyboardButton(text="📊 Excel (barcha)", callback_data="admin_export_results"),
            InlineKeyboardButton(text="🏆 Excel (sertifikat)", callback_data="admin_export_certs"),
        ],
        [
            InlineKeyboardButton(text="📋 Excel (foydalanuvchilar)", callback_data="admin_export_users"),
            InlineKeyboardButton(text="Sertifikat shabloni", callback_data="admin_certificate_template"),
        ],
        [
            InlineKeyboardButton(text="Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton(text="Top foydalanuvchilar", callback_data="admin_top_users"),
        ],
    ]
    if is_superadmin(uid):
        rows.append([InlineKeyboardButton(text="Adminlar boshqaruvi", callback_data="admin_manage_admins")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    if edit:
        await safe_edit(message, text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "admin_tests_list")
async def admin_tests_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    tests = db.get_all_tests()
    if not tests:
        await callback.message.edit_text(
            "📭 Hali testlar yo'q.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Test yaratish", callback_data="admin_create_test")],
                [InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_back")]
            ])
        )
        await callback.answer(); return

    text = "📋 <b>Barcha testlar:</b>\n\n"
    buttons = []
    for t in tests:
        q_count = db.get_question_count(t["id"])
        status = "✅" if t["is_active"] else "⛔"
        max_att = t["max_attempts"] if t["max_attempts"] else 0
        att_str = f" | max: {max_att}" if max_att else ""
        text += f"{status} <b>{t['title']}</b> ({q_count} savol{att_str})\n"
        buttons.append([InlineKeyboardButton(
            text=f"{status} {t['title'][:30]}",
            callback_data=f"admin_test_detail_{t['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_back")])
    await callback.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML
    )
    await callback.answer()


async def _render_test_detail(callback: CallbackQuery, test_id: int):
    """Test detail sahifasini ko'rsatuvchi yordamchi funksiya."""
    test = db.get_test(test_id)
    if not test:
        await callback.answer("Test topilmadi!", show_alert=True); return
    q_count = db.get_question_count(test_id)
    status_text = "✅ Faol" if test["is_active"] else "⛔ Nofaol"
    toggle_text = "⛔ O'chirish" if test["is_active"] else "✅ Faollashtirish"
    max_att = test["max_attempts"] if test["max_attempts"] else 0
    max_att_str = f"{max_att} ta" if max_att else "Cheksiz"
    text = (
        f"<b>{test['title']}</b>\n\n"
        f"Tavsif: {test['description'] or 'Yoq'}\n"
        f"Savollar: {q_count} ta\n"
        f"Ko'rsatiladi: {test['question_count']} ta\n"
        f"Vaqt: {test['time_limit']} daqiqa\n"
        f"Max urinish: {max_att_str}\n"
        f"Holat: {status_text}\n"
        f"Yaratilgan: {test['created_at'][:10]}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=toggle_text, callback_data=f"admin_toggle_{test_id}"),
            InlineKeyboardButton(text="Tahrirlash", callback_data=f"admin_edit_{test_id}")
        ],
        [
            InlineKeyboardButton(text="Savol (qo'lda)", callback_data=f"admin_add_q_{test_id}"),
            InlineKeyboardButton(text="Excel", callback_data=f"admin_excel_{test_id}")
        ],
        [
            InlineKeyboardButton(text="Natijalar", callback_data=f"admin_test_results_{test_id}"),
            InlineKeyboardButton(text="O'chirish", callback_data=f"admin_delete_{test_id}")
        ],
        [InlineKeyboardButton(text="⬅Orqaga", callback_data="admin_tests_list")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith("admin_test_detail_"))
async def admin_test_detail(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    test_id = int(callback.data.split("_")[3])
    await _render_test_detail(callback, test_id)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_toggle_"))
async def admin_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    test_id = int(callback.data.split("_")[2])
    new_status = db.toggle_test(test_id)
    msg = "✅ Faollashtirildi!" if new_status else "⛔ O'chirildi!"
    await callback.answer(msg, show_alert=True)
    await _render_test_detail(callback, test_id)


@router.callback_query(F.data.startswith("admin_delete_"))
async def admin_delete_test(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    test_id = int(callback.data.split("_")[2])
    test = db.get_test(test_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"admin_confirm_delete_{test_id}"),
            InlineKeyboardButton(text="❌ Bekor", callback_data=f"admin_test_detail_{test_id}")
        ]
    ])
    await callback.message.edit_text(
        f"⚠️ <b>'{test['title']}'</b> o'chirilsinmi?\nBarcha savollar ham o'chadi!",
        reply_markup=kb, parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_confirm_delete_"))
async def admin_confirm_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    test_id = int(callback.data.split("_")[3])
    db.delete_test(test_id)
    await callback.answer("✅ O'chirildi!", show_alert=True)
    await admin_tests_list(callback)


@router.callback_query(F.data == "admin_create_test")
async def admin_create_test_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    await state.set_state(AdminTestState.creating_title)
    await callback.message.edit_text(
        "📝 <b>Yangi test yaratish</b>\n\nTest nomini kiriting:",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.message(AdminTestState.creating_title)
async def admin_creating_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.update_data(title=message.text)
    await state.set_state(AdminTestState.creating_description)
    await message.answer("Tavsif kiriting (yoki 'yoq' deb yozing):", reply_markup=cancel_kb)


@router.message(AdminTestState.creating_description)
async def admin_creating_desc(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "❌ Bekor qilish":
        await state.clear(); await message.answer("Bekor.", reply_markup=main_menu); return
    desc = "" if message.text.lower() in ["yoq", "yo'q"] else message.text
    await state.update_data(description=desc)
    await state.set_state(AdminTestState.creating_time)
    await message.answer("Vaqt limitini daqiqada kiriting (masalan: 30):")


@router.message(AdminTestState.creating_time)
async def admin_creating_time(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "❌ Bekor qilish":
        await state.clear(); await message.answer("Bekor.", reply_markup=main_menu); return
    try:
        t = int(message.text)
    except Exception:
        await message.answer("Raqam kiriting!"); return
    await state.update_data(time_limit=t)
    await state.set_state(AdminTestState.creating_count)
    await message.answer("Testda ko'rsatiladigan savollar sonini kiriting:")


@router.message(AdminTestState.creating_count)
async def admin_creating_count(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "❌ Bekor qilish":
        await state.clear(); await message.answer("Bekor.", reply_markup=main_menu); return
    try:
        c = int(message.text)
    except Exception:
        await message.answer("Raqam kiriting!"); return
    await state.update_data(question_count=c)
    await state.set_state(AdminTestState.creating_max_attempts)
    await message.answer(
        "🔄 <b>Maksimal urinishlar soni</b>\n\n"
        "Har bir foydalanuvchi bu testga necha marta urinishi mumkin?\n\n"
        "<i>0 yoki 'cheksiz' deb yozing — cheksiz urinishga ruxsat berish uchun</i>",
        parse_mode=ParseMode.HTML
    )


@router.message(AdminTestState.creating_max_attempts)
async def admin_creating_max_attempts(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "❌ Bekor qilish":
        await state.clear(); await message.answer("Bekor.", reply_markup=main_menu); return
    try:
        if message.text.lower() in ["cheksiz", "0", "∞"]:
            max_att = 0
        else:
            max_att = int(message.text)
            if max_att < 0:
                max_att = 0
    except Exception:
        await message.answer("Raqam kiriting (masalan: 3) yoki 'cheksiz' deb yozing!"); return

    data = await state.get_data()
    test_id = db.create_test(
        data["title"], data.get("description", ""),
        data["time_limit"], data["question_count"], max_att
    )
    await state.clear()
    max_str = f"{max_att} ta" if max_att else "Cheksiz"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Savol qo'shish (qo'lda)", callback_data=f"admin_add_q_{test_id}")],
        [InlineKeyboardButton(text="📥 Excel orqali", callback_data=f"admin_excel_{test_id}")],
        [InlineKeyboardButton(text="📋 Ro'yxatga", callback_data="admin_tests_list")]
    ])
    await message.answer(
        f"✅ <b>Test yaratildi!</b>\n\n<b>{data['title']}</b>\n"
        f"🔄 Maksimal urinish: {max_str}\n\nEndi savol qo'shing:",
        reply_markup=kb, parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data.startswith("admin_add_q_"))
async def admin_add_question_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    test_id = int(callback.data.split("_")[3])
    test = db.get_test(test_id)
    q_count = db.get_question_count(test_id)
    await state.set_state(AdminTestState.adding_q_text)
    await state.update_data(adding_test_id=test_id)
    await callback.message.edit_text(
        f"📝 <b>{test['title']}</b> — {q_count} ta savol bor.\n\nSavol matnini kiriting:",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.message(AdminTestState.adding_q_text)
async def aq_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "❌ Bekor qilish":
        await state.clear(); await message.answer("Bekor.", reply_markup=main_menu); return
    await state.update_data(q_text=message.text)
    await state.set_state(AdminTestState.adding_q_a)
    await message.answer("A) variantini kiriting:", reply_markup=cancel_kb)


@router.message(AdminTestState.adding_q_a)
async def aq_a(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "❌ Bekor qilish":
        await state.clear(); await message.answer("Bekor.", reply_markup=main_menu); return
    await state.update_data(q_a=message.text)
    await state.set_state(AdminTestState.adding_q_b)
    await message.answer("B) variantini kiriting:")


@router.message(AdminTestState.adding_q_b)
async def aq_b(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "❌ Bekor qilish":
        await state.clear(); await message.answer("Bekor.", reply_markup=main_menu); return
    await state.update_data(q_b=message.text)
    await state.set_state(AdminTestState.adding_q_c)
    await message.answer("C) variantini kiriting:")


@router.message(AdminTestState.adding_q_c)
async def aq_c(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "❌ Bekor qilish":
        await state.clear(); await message.answer("Bekor.", reply_markup=main_menu); return
    await state.update_data(q_c=message.text)
    await state.set_state(AdminTestState.adding_q_d)
    await message.answer("D) variantini kiriting:")


@router.message(AdminTestState.adding_q_d)
async def aq_d(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "❌ Bekor qilish":
        await state.clear(); await message.answer("Bekor.", reply_markup=main_menu); return
    await state.update_data(q_d=message.text)
    await state.set_state(AdminTestState.adding_q_correct)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="A"), KeyboardButton(text="B"),
                   KeyboardButton(text="C"), KeyboardButton(text="D")]],
        resize_keyboard=True
    )
    await message.answer("To'g'ri javobni tanlang (A, B, C yoki D):", reply_markup=kb)


@router.message(AdminTestState.adding_q_correct)
async def aq_correct(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text not in ["A", "B", "C", "D"]:
        await message.answer("Faqat A, B, C yoki D!"); return
    data = await state.get_data()
    db.add_question(data["adding_test_id"], data["q_text"],
                    data["q_a"], data["q_b"], data["q_c"], data["q_d"], message.text)
    q_count = db.get_question_count(data["adding_test_id"])
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yana savol", callback_data=f"admin_add_q_{data['adding_test_id']}")],
        [InlineKeyboardButton(text="✅ Tugatish", callback_data=f"admin_test_detail_{data['adding_test_id']}")]
    ])
    await message.answer(f"✅ Savol qo'shildi! Jami: <b>{q_count} ta</b>", reply_markup=kb, parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith("admin_excel_"))
async def admin_excel_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    test_id = int(callback.data.split("_")[2])
    await state.set_state(AdminTestState.waiting_excel)
    await state.update_data(excel_test_id=test_id)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Savollar"
    ws.append(["Savol", "A variant", "B variant", "C variant", "D variant", "To'g'ri javob (A/B/C/D)"])
    ws.append(["Fotosintez qayerda sodir bo'ladi?", "Ildizda", "Bargda", "Poyada", "Urug'da", "B"])
    ws.append(["O'zbekiston poytaxti?", "Samarqand", "Toshkent", "Buxoro", "Namangan", "B"])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(
            max(len(str(c.value or "")) for c in col) + 4, 40
        )
    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    await callback.message.edit_text(
        "📥 <b>Excel orqali savollar yuklash</b>\n\nShablonni to'ldirib yuboring.\n\n"
        "⚠️ Mavjud savollar o'chiriladi!", parse_mode=ParseMode.HTML
    )
    await callback.message.answer_document(
        BufferedInputFile(buf.getvalue(), filename="savollar_shablon.xlsx"),
        caption="📋 Shablonni to'ldiring va yuboring:"
    )
    await callback.answer()


@router.message(AdminTestState.waiting_excel, F.document)
async def admin_process_excel(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id): return
    data = await state.get_data()
    test_id = data["excel_test_id"]
    try:
        file = await bot.get_file(message.document.file_id)
        file_bytes = await bot.download_file(file.file_path)
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes.read()))
        ws = wb.active
        db.delete_questions(test_id)
        count = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row[0]: continue
            q_text, a, b, c, d, correct = (str(row[i] or "").strip() for i in range(6))
            correct = correct.upper()
            if correct not in ["A", "B", "C", "D"]: continue
            db.add_question(test_id, q_text, a, b, c, d, correct)
            count += 1
        await state.clear()
        await message.answer(
            f"✅ <b>{count} ta savol yuklandi!</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Testga", callback_data=f"admin_test_detail_{test_id}")]
            ]),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
        logging.error(f"Excel xato: {e}")


# =============================================================================
# EXCEL EKSPORTLAR
# =============================================================================
def _style_header(ws):
    """Excel sarlavha satrini ko'k rang bilan bezatish."""
    from openpyxl.styles import PatternFill, Font, Alignment
    fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    font = Font(color="FFFFFF", bold=True)
    for cell in ws[1]:
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center")


def _auto_width(ws):
    """Ustun kengliklarini avtomatik sozlash."""
    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 45)


@router.callback_query(F.data == "admin_results")
async def admin_results(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    results = db.get_results(limit=20)
    if not results:
        await callback.message.edit_text(
            "📭 Hali natijalar yo'q.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_back")]
            ])
        )
        await callback.answer(); return
    text = "📊 <b>So'nggi natijalar (20 ta):</b>\n\n"
    for r in results:
        pct = int(r["score"] / r["total"] * 100) if r["total"] else 0
        text += f"{'🏆' if r['passed'] else '❌'} {r['user_name'] or r['user_id']} — {r['title'][:20]}: {r['score']}/{r['total']} ({pct}%)\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Excel (barcha)", callback_data="admin_export_results")],
        [InlineKeyboardButton(text="🏆 Excel (sertifikat)", callback_data="admin_export_certs")],
        [InlineKeyboardButton(text="⬅Admin", callback_data="admin_back")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "admin_export_results")
async def admin_export_results(callback: CallbackQuery):
    """Barcha natijalarni to'liq Excel da eksport qilish."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return

    await callback.answer("⏳ Excel tayyorlanmoqda...")
    results = db.get_results()   # limit yo'q — hammasi
    users = db.get_all_users()

    wb = openpyxl.Workbook()

    # ── 1-sheet: Barcha natijalar ────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Barcha natijalar"
    ws1.append(["#", "Foydalanuvchi", "Telegram ID", "Test", "Ball", "Jami", "%",
                "Sertifikat", "Sertifikat raqami", "Sana"])
    for i, r in enumerate(results, 1):
        pct = int(r["score"] / r["total"] * 100) if r["total"] else 0
        ws1.append([
            i,
            r["user_name"] or "—",
            r["user_id"],
            r["title"],
            r["score"],
            r["total"],
            f"{pct}%",
            "Ha" if r["passed"] else "Yo'q",
            r["cert_code"] or "—",
            r["finished_at"][:16] if r["finished_at"] else "—"
        ])
    _style_header(ws1)
    _auto_width(ws1)

    # ── 2-sheet: Foydalanuvchilar ro'yxati ───────────────────────────────────
    ws2 = wb.create_sheet("Foydalanuvchilar")
    ws2.append(["#", "Ism Familiya", "Username", "Telefon", "Viloyat",
                "Tug'ilgan yil", "Telegram ID", "Ro'yxatdan o'tgan"])
    for i, u in enumerate(users, 1):
        ws2.append([
            i,
            u["full_name"] or "—",
            f"@{u['username']}" if u["username"] else "—",
            u["phone"] or "—",
            u["region"] or "—",
            u["birth_year"] or "—",
            u["id"],
            (u["registered_at"] or "")[:16] or "—"
        ])
    _style_header(ws2)
    _auto_width(ws2)

    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    fname = f"barcha_natijalar_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    await callback.message.answer_document(
        BufferedInputFile(buf.getvalue(), filename=fname),
        caption=(
            f"📊 <b>To'liq Excel eksport</b>\n\n"
            f"📋 Natijalar: <b>{len(results)} ta</b>\n"
            f"👥 Foydalanuvchilar: <b>{len(users)} ta</b>\n\n"
            f"<i>2 ta sheet: «Barcha natijalar» + «Foydalanuvchilar»</i>"
        ),
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "admin_export_certs")
async def admin_export_certs(callback: CallbackQuery):
    """Faqat sertifikat olganlarni eksport qilish."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return

    await callback.answer("⏳ Sertifikat Excel tayyorlanmoqda...")
    results = db.get_passed_results()

    if not results:
        await callback.message.answer("📭 Hali sertifikat olgan foydalanuvchi yo'q.")
        return

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sertifikat olganlar"
    ws.append(["#", "Ism Familiya", "Telegram ID", "Test", "Ball", "Jami", "%",
               "Sertifikat raqami", "Sana"])
    for i, r in enumerate(results, 1):
        pct = int(r["score"] / r["total"] * 100) if r["total"] else 0
        ws.append([
            i,
            r["user_name"] or "—",
            r["user_id"],
            r["title"],
            r["score"],
            r["total"],
            f"{pct}%",
            r["cert_code"] or "—",
            r["finished_at"][:16] if r["finished_at"] else "—"
        ])
    _style_header(ws)
    _auto_width(ws)

    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    fname = f"sertifikat_olganlar_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    await callback.message.answer_document(
        BufferedInputFile(buf.getvalue(), filename=fname),
        caption=(
            f"🏆 <b>Sertifikat olganlar</b>\n\n"
            f"Jami: <b>{len(results)} ta</b> natija"
        ),
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "admin_export_users")
async def admin_export_users(callback: CallbackQuery):
    """Faqat foydalanuvchilar ro'yxatini eksport qilish."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return

    await callback.answer("⏳ Foydalanuvchilar Excel tayyorlanmoqda...")
    users = db.get_all_users()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Foydalanuvchilar"
    ws.append(["#", "Ism Familiya", "Username", "Telefon", "Viloyat",
               "Tug'ilgan yil", "Telegram ID", "Ro'yxatdan o'tgan"])
    for i, u in enumerate(users, 1):
        ws.append([
            i,
            u["full_name"] or "—",
            f"@{u['username']}" if u["username"] else "—",
            u["phone"] or "—",
            u["region"] or "—",
            u["birth_year"] or "—",
            u["id"],
            (u["registered_at"] or "")[:16] or "—"
        ])
    _style_header(ws)
    _auto_width(ws)

    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    fname = f"foydalanuvchilar_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    await callback.message.answer_document(
        BufferedInputFile(buf.getvalue(), filename=fname),
        caption=f"👥 <b>Foydalanuvchilar ro'yxati</b>\n\nJami: <b>{len(users)} ta</b>",
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data.startswith("admin_edit_"))
async def admin_edit_test(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    test_id = int(callback.data.split("_")[2])
    test = db.get_test(test_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Nom", callback_data=f"edit_field_{test_id}_title")],
        [InlineKeyboardButton(text="Tavsif", callback_data=f"edit_field_{test_id}_description")],
        [InlineKeyboardButton(text="Vaqt", callback_data=f"edit_field_{test_id}_time_limit")],
        [InlineKeyboardButton(text="Savollar soni", callback_data=f"edit_field_{test_id}_question_count")],
        [InlineKeyboardButton(text="🔄 Max urinish", callback_data=f"edit_field_{test_id}_max_attempts")],
        [InlineKeyboardButton(text="⬅Orqaga", callback_data=f"admin_test_detail_{test_id}")]
    ])
    await callback.message.edit_text(
        f"✏️ <b>Tahrirlash: {test['title']}</b>\n\nNimani o'zgartirmoqchisiz?",
        reply_markup=kb, parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_field_"))
async def edit_field_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    parts = callback.data.split("_")
    test_id = int(parts[2])
    field = parts[3]
    labels = {
        "title": "Nom", "description": "Tavsif",
        "time_limit": "Vaqt (daqiqa)", "question_count": "Savollar soni",
        "max_attempts": "Maksimal urinishlar soni (0 = cheksiz)"
    }
    await state.set_state(AdminTestState.editing_value)
    await state.update_data(edit_test_id=test_id, edit_field=field)
    await callback.message.edit_text(
        f"✏️ Yangi <b>{labels.get(field, field)}</b>ni kiriting:", parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.message(AdminTestState.editing_value)
async def edit_field_value(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    data = await state.get_data()
    test_id = data["edit_test_id"]
    field = data["edit_field"]
    test = db.get_test(test_id)
    new_val = message.text

    if field in ["time_limit", "question_count", "max_attempts"]:
        try:
            if field == "max_attempts" and new_val.lower() in ["cheksiz", "∞"]:
                new_val = 0
            else:
                new_val = int(new_val)
                if new_val < 0: new_val = 0
        except Exception:
            await message.answer("Raqam kiriting!"); return

    updates = {
        "title": test["title"], "description": test["description"],
        "time_limit": test["time_limit"], "question_count": test["question_count"],
        "max_attempts": test["max_attempts"] if test["max_attempts"] is not None else 0
    }
    updates[field] = new_val
    db.update_test(
        test_id, updates["title"], updates["description"],
        updates["time_limit"], updates["question_count"], updates["max_attempts"]
    )
    await state.clear()
    await message.answer(
        "✅ O'zgartirildi!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Testga", callback_data=f"admin_test_detail_{test_id}")]
        ])
    )


@router.callback_query(F.data.startswith("admin_test_results_"))
async def admin_test_results_detail(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    test_id = int(callback.data.split("_")[3])
    test = db.get_test(test_id)
    results = db.get_results(test_id=test_id, limit=30)
    if not results:
        await callback.answer("Bu test uchun natijalar yo'q!", show_alert=True); return
    total_count = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    text = (
        f"📊 <b>{test['title']} — natijalar</b>\n\n"
        f"Jami: {total_count} | O'tdi: {passed_count} | O'tmadi: {total_count - passed_count}\n\n"
    )
    for r in results:
        pct = int(r["score"] / r["total"] * 100) if r["total"] else 0
        text += f"{'🏆' if r['passed'] else '❌'} {r['user_name'] or r['user_id']} — {r['score']}/{r['total']} ({pct}%)\n"
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅Orqaga", callback_data=f"admin_test_detail_{test_id}")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# --- Sertifikat shabloni ---
@router.callback_query(F.data == "admin_certificate_template")
async def admin_certificate_template(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    has_template = os.path.exists(CERTIFICATE_TEMPLATE_PATH)
    status_text = (
        "✅ <b>Shablon mavjud.</b>" if has_template
        else "⚠️ <b>Shablon yuklanmagan.</b> Foydalanuvchilarga sertifikat berilmaydi."
    )
    rows = [
        [InlineKeyboardButton(text="📤 Yangi shablon yuklash", callback_data="admin_upload_cert")],
        [InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_back")]
    ]
    if has_template:
        rows.insert(1, [InlineKeyboardButton(text="👁 Ko'rish", callback_data="admin_view_cert")])
    text = (
        f"📜 <b>Sertifikat shabloni</b>\n\n{status_text}\n\n"
        "<i>Shablon — foydalanuvchi sertifikat olganda ustiga ismi yoziladigan rasm (PNG yoki JPG).</i>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode=ParseMode.HTML)
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "admin_view_cert")
async def admin_view_cert(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    if not os.path.exists(CERTIFICATE_TEMPLATE_PATH):
        await callback.answer("Shablon topilmadi!", show_alert=True); return
    with open(CERTIFICATE_TEMPLATE_PATH, "rb") as f:
        photo = BufferedInputFile(f.read(), filename="template.png")
    await callback.message.answer_photo(
        photo, caption="📜 <b>Amaldagi sertifikat shabloni</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Yangilash", callback_data="admin_upload_cert")],
            [InlineKeyboardButton(text="⬅Orqaga", callback_data="admin_certificate_template")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data == "admin_upload_cert")
async def admin_upload_cert_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    await state.set_state(AdminTestState.waiting_certificate)
    await callback.message.edit_text(
        "📤 <b>Sertifikat shablonini yuboring</b>\n\nPNG yoki JPG rasm sifatida yuboring.\nBekor qilish: /admin",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.message(AdminTestState.waiting_certificate, F.photo)
async def admin_save_certificate_template(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id): return
    try:
        os.makedirs(str(BASE_DIR / "certificates"), exist_ok=True)
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        with open(CERTIFICATE_TEMPLATE_PATH, "wb") as f:
            f.write(file_bytes.read())
        await state.clear()
        await message.answer(
            "✅ <b>Sertifikat shabloni saqlandi!</b>\n\n"
            "Endi 86%+ natija olgan foydalanuvchilarga shu shablon ustiga ismi yozilgan sertifikat yuboriladi.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_back")]
            ]),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
        logging.error(f"Shablon saqlashda xato: {e}")


@router.message(AdminTestState.waiting_certificate)
async def admin_cert_not_photo(message: Message):
    if not is_admin(message.from_user.id): return
    await message.answer("⚠️ Iltimos, <b>rasm</b> yuboring (PNG yoki JPG).", parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    await _send_admin_panel(callback.message, edit=True, user_id=callback.from_user.id)
    await callback.answer()


# =============================================================================
# KPI
# =============================================================================
@router.callback_query(F.data == "admin_kpi")
async def admin_kpi(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    kpi = db.get_kpi_stats()
    per_test = db.get_per_test_kpi()

    total = kpi["total_attempts"]
    pass_rate = round(kpi["total_certs"] / total * 100, 1) if total else 0
    fail_rate = round(kpi["total_failed"] / total * 100, 1) if total else 0

    text = (
        f"📈 <b>KPI HISOBOTI</b>\n\n"
        f"👥 <b>Foydalanuvchilar:</b> {kpi['total_users']}\n"
        f"   └ Bugun yangi: +{kpi['today_users']}\n\n"
        f"🎯 <b>Urinishlar:</b> {kpi['total_attempts']}\n"
        f"   └ Bugun: {kpi['today_attempts']}\n\n"
        f"🏆 <b>Sertifikatlar:</b> {kpi['total_certs']} ({pass_rate}%)\n"
        f"   └ Unikal sohiblar: {kpi['cert_users']}\n\n"
        f"❌ <b>Muvaffaqiyatsiz:</b> {kpi['total_failed']} ({fail_rate}%)\n\n"
        f"📊 <b>O'rtacha ball:</b> {kpi['avg_score']}%\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n<b>Testlar bo'yicha:</b>\n\n"
    )
    for t in per_test:
        attempts = t["attempts"] or 0
        passed = t["passed"] or 0
        p_rate = round(passed / attempts * 100, 1) if attempts else 0.0
        text += (
            f"📋 <b>{t['title'][:30]}</b>\n"
            f"   👤 {t['unique_users']} kishi  |  🎯 {attempts} urinish\n"
            f"   ✅ {passed} o'tdi ({p_rate}%)  |  📊 o'rtacha {t['avg_pct'] or 0}%\n\n"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏅 Top foydalanuvchilar", callback_data="admin_top_users")],
        [InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_back")],
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "admin_top_users")
async def admin_top_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    top = db.get_top_users(10)
    if not top:
        await callback.answer("Hali sertifikat olgan foydalanuvchi yo'q!", show_alert=True); return
    text = "🏅 <b>TOP-10 (sertifikat soni bo'yicha)</b>\n\n"
    medals = ["🥇", "🥈", "🥉"] + ["🎖"] * 7
    for i, u in enumerate(top):
        text += f"{medals[i]} {u['user_name'] or u['user_id']} — {u['certs']} sertifikat | o'rtacha {u['avg_pct']}%\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ KPI", callback_data="admin_kpi")],
        [InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_back")],
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()


# =============================================================================
# BROADCAST
# =============================================================================
class BroadcastState(StatesGroup):
    waiting_text = State()
    confirm = State()


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    users_count = db.get_user_count()
    history = db.get_broadcast_history(3)
    hist_text = ""
    if history:
        hist_text = "\n\n📜 <b>Oxirgi xabarlar:</b>\n"
        for h in history:
            date = h["created_at"][:16] if h["created_at"] else "—"
            preview = (h["text"] or "")[:40].replace("\n", " ")
            hist_text += f"  • {date}: {preview}... ({h['sent']} yuborildi)\n"
    await state.set_state(BroadcastState.waiting_text)
    await callback.message.edit_text(
        f"📢 <b>BROADCAST</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{users_count}</b>\n"
        f"{hist_text}\n\n"
        f"Yubormoqchi bo'lgan xabaringizni yozing:\n"
        f"<i>(HTML format: &lt;b&gt;, &lt;i&gt;, &lt;code&gt;)</i>",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.message(BroadcastState.waiting_text)
async def broadcast_got_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "❌ Bekor qilish":
        await state.clear(); await message.answer("Bekor qilindi.", reply_markup=main_menu); return
    await state.update_data(broadcast_text=message.text)
    await state.set_state(BroadcastState.confirm)
    users_count = db.get_user_count()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yuborish", callback_data="broadcast_confirm"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="broadcast_cancel"),
    ]])
    await message.answer(
        f"📋 <b>Xabar ko'rinishi:</b>\n\n{message.text}\n\n"
        f"👥 <b>{users_count} ta</b> foydalanuvchiga yuboriladi.\n\nTasdiqlaysizmi?",
        reply_markup=kb, parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()


@router.callback_query(F.data == "broadcast_confirm")
async def broadcast_confirm(callback: CallbackQuery, state: FSMContext, bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    await state.clear()
    users = db.get_all_users()
    sent = 0; failed = 0
    progress_msg = await callback.message.edit_text(f"⏳ Yuborilmoqda... 0/{len(users)}")
    for i, user in enumerate(users):
        try:
            await bot.send_message(user["id"], text, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1
        if (i + 1) % 30 == 0:
            try:
                await progress_msg.edit_text(f"⏳ Yuborilmoqda... {i+1}/{len(users)}")
            except Exception:
                pass
        await asyncio.sleep(0.05)
    db.log_broadcast(callback.from_user.id, text, sent, failed)
    await progress_msg.edit_text(
        f"✅ <b>Broadcast yakunlandi!</b>\n\n📤 Yuborildi: <b>{sent}</b>\n❌ Xatolik: <b>{failed}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_back")]
        ])
    )
    await callback.answer()


# =============================================================================
# ADMINLAR BOSHQARUVI
# =============================================================================
class SuperAdminState(StatesGroup):
    adding_admin_id = State()


@router.callback_query(F.data == "admin_manage_admins")
async def admin_manage_admins(callback: CallbackQuery):
    if not is_superadmin(callback.from_user.id):
        await callback.answer("❌ Bu funksiya faqat bosh admin uchun!", show_alert=True); return
    dynamic = db.get_dynamic_admins()
    text = "👮 <b>ADMINLAR BOSHQARUVI</b>\n\n<b>Asosiy adminlar:</b>\n"
    for aid in ADMIN_IDS:
        u = db.get_user(aid)
        name = u["full_name"] if u and u["full_name"] else f"ID: {aid}"
        star = " ⭐" if aid == SUPERADMIN_ID else ""
        text += f"  👤 {name}{star}\n"
    if dynamic:
        text += "\n<b>Qo'shilgan adminlar:</b>\n"
        for d in dynamic:
            u = db.get_user(d["user_id"])
            name = u["full_name"] if u and u["full_name"] else f"ID: {d['user_id']}"
            text += f"  👤 {name} (ID: {d['user_id']})\n"
    rows = [[InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="superadmin_add")]]
    for d in dynamic:
        u = db.get_user(d["user_id"])
        name = (u["full_name"] if u and u["full_name"] else str(d["user_id"]))[:20]
        rows.append([InlineKeyboardButton(
            text=f"🗑 {name}ni o'chirish",
            callback_data=f"superadmin_remove_{d['user_id']}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Admin", callback_data="admin_back")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "superadmin_add")
async def superadmin_add_start(callback: CallbackQuery, state: FSMContext):
    if not is_superadmin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    await state.set_state(SuperAdminState.adding_admin_id)
    await callback.message.edit_text(
        "👮 <b>Yangi admin qo'shish</b>\n\nAdmin qilmoqchi bo'lgan foydalanuvchining <b>Telegram ID</b>sini yuboring:",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.message(SuperAdminState.adding_admin_id)
async def superadmin_add_id(message: Message, state: FSMContext):
    if not is_superadmin(message.from_user.id): return
    try:
        new_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Faqat raqam kiriting!"); return
    if new_id in get_all_admin_ids():
        await state.clear()
        await message.answer(
            "⚠️ Bu foydalanuvchi allaqachon admin!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Adminlar", callback_data="admin_manage_admins")]
            ])
        )
        return
    db.add_dynamic_admin(new_id, message.from_user.id)
    await state.clear()
    u = db.get_user(new_id)
    name = u["full_name"] if u and u["full_name"] else f"ID: {new_id}"
    await message.answer(
        f"✅ <b>{name}</b> admin qilib qo'shildi!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Adminlar", callback_data="admin_manage_admins")]
        ]),
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data.startswith("superadmin_remove_"))
async def superadmin_remove(callback: CallbackQuery):
    if not is_superadmin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    uid = int(callback.data.split("_")[2])
    if uid in ADMIN_IDS:
        await callback.answer("❌ Asosiy adminni o'chirib bo'lmaydi!", show_alert=True); return
    db.remove_dynamic_admin(uid)
    await callback.answer("✅ Admin o'chirildi!", show_alert=True)
    await admin_manage_admins(callback)


# =============================================================================
# BOSHQA FUNKSIYALAR
# =============================================================================
@router.message(F.text == "🔐 Parolni tiklash")
async def reset_password_start(message: Message, state: FSMContext):
    await state.set_state(ResetPasswordState.waiting_for_passport)
    await message.answer(
        "🔒 <b>Parolni tiklash.</b>\n\nID raqamingizni yozing (guvohnomadagi):",
        reply_markup=cancel_kb, parse_mode=ParseMode.HTML
    )


@router.message(ResetPasswordState.waiting_for_passport)
async def process_passport(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear(); await message.answer("Bekor.", reply_markup=main_menu); return
    await state.update_data(passport=message.text)
    await state.set_state(ResetPasswordState.waiting_for_name)
    await message.answer("Ism Familyangizni to'liq kiriting:", reply_markup=cancel_kb)


@router.message(ResetPasswordState.waiting_for_name)
async def process_fullname(message: Message, state: FSMContext, bot: Bot):
    if message.text == "❌ Bekor qilish":
        await state.clear(); await message.answer("Bekor.", reply_markup=main_menu); return
    data = await state.get_data()
    passport = data.get("passport")
    full_name = message.text
    user_id = message.from_user.id
    db.save_reset_request(user_id, passport, full_name)
    await message.answer(
        "⏳ <b>So'rov ketdi.</b>\n\nAdmin tekshirib javob beradi, kutib turin.",
        reply_markup=main_menu, parse_mode=ParseMode.HTML
    )
    await state.clear()
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tiklash", callback_data=f"restore_{user_id}"),
        InlineKeyboardButton(text="❌ Bekor", callback_data=f"reject_{user_id}")
    ]])
    await notify_admins(
        bot,
        f"📢 <b>YANGI PAROL SO'ROVI!</b>\n\n"
        f"👤 <b>Kim:</b> {full_name}\n"
        f"📄 <b>Pasport:</b> {passport}\n"
        f"🆔 <b>ID:</b> {user_id}",
        reply_markup=admin_kb
    )


@router.callback_query(F.data.startswith("reject_"))
async def admin_reject(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Siz admin emassiz!", show_alert=True); return
    user_id = int(callback.data.split("_")[1])
    await callback.message.edit_text("❌ Bekor qilindi.")
    await bot.send_message(user_id, "❌ <b>Admin ruxsat bermadi.</b>", parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data.startswith("restore_"))
async def admin_restore_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Siz admin emassiz!", show_alert=True); return
    user_id = int(callback.data.split("_")[1])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminState.waiting_for_new_password)
    await callback.message.edit_text("✍️ <b>Yangi parolni yozin:</b>", parse_mode=ParseMode.HTML)
    await callback.answer()


@router.message(AdminState.waiting_for_new_password)
async def admin_send_password(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in ADMIN_IDS: return
    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    try:
        await bot.send_message(
            target_user_id,
            f"✅ <b>Parol tiklandi!</b>\n\n🔑 <b>Yangi paroliz:</b> <code>{message.text}</code>",
            parse_mode=ParseMode.HTML
        )
        await message.answer("✅ Userga ketti.")
    except Exception as e:
        await message.answer(f"Xato: {e}")
    await state.clear()


@router.message(F.text == "❓ Loyiha haqida savol berish")
async def ask_question_start(message: Message, state: FSMContext):
    await state.set_state(QuestionState.waiting_for_question)
    await message.answer("Savolingizni yozing:", reply_markup=cancel_kb)


@router.message(QuestionState.waiting_for_question)
async def process_question(message: Message, state: FSMContext, bot: Bot):
    if message.text != "❌ Bekor qilish":
        user_id = message.from_user.id
        user_name = message.from_user.full_name
        username = message.from_user.username or "yoq"
        db.clear_question_answered(user_id)
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💬 Javob berish", callback_data=f"reply_user_{user_id}")
        ]])
        await notify_admins(
            bot,
            f"❓ <b>SAVOL KELDI!</b>\n\n"
            f"👤 {user_name}\n"
            f"🆔 <b>ID:</b> {user_id}\n"
            f"📱 @{username}\n\n"
            f"📝 {message.text}\n\n<i>Reply qiling yoki tugmani bosing!</i>",
            reply_markup=admin_kb
        )
        await message.answer("✅ Savolingiz adminga yuborildi!", reply_markup=main_menu)
    else:
        await message.answer("Bekor boldi", reply_markup=main_menu)
    await state.clear()


@router.message(F.text == "🚨 Xabar berish")
async def report_start(message: Message, bot: Bot):
    await notify_admins(
        bot,
        f"🚨 <b>STOP NARKO BOTGA O'TDI!</b>\n\n"
        f"👤 {message.from_user.full_name}\n"
        f"🆔 <code>{message.from_user.id}</code>\n"
        f"📱 @{message.from_user.username or 'yoq'}\n"
        f"⏱ {message.date.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await message.answer(
        f"🚨 <b>Xabar berish</b>\n\n<b>@{STOP_NARKO_BOT_USERNAME}</b> botiga o'ting:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 STOP NARKO BOT", url=f"https://t.me/{STOP_NARKO_BOT_USERNAME}")],
            [InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="back_to_main")]
        ]),
        parse_mode=ParseMode.HTML
    )


@router.message(F.text == "🏠 Asosiy menyu", F.chat.type == "private")
async def back_to_main_text(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Asosiy menyu:", reply_markup=main_menu)


@router.callback_query(F.data == "back_to_main")
async def back_to_main_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("Asosiy menyu:", reply_markup=main_menu)
    await callback.answer()


class AdminReplyState(StatesGroup):
    waiting_reply = State()


@router.callback_query(F.data.startswith("reply_user_"))
async def reply_user_btn(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True); return
    user_id = int(callback.data.split("_")[2])
    if db.is_question_answered(user_id):
        await callback.answer("⚠️ Bu savolga allaqachon javob berilgan!", show_alert=True); return
    await state.set_state(AdminReplyState.waiting_reply)
    await state.update_data(reply_target_id=user_id, reply_msg_id=callback.message.message_id)
    await callback.message.answer(
        f"✍️ <b>Foydalanuvchi (ID: {user_id})ga javobingizni yozing:</b>\n\nBekor qilish uchun /admin",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.message(AdminReplyState.waiting_reply)
async def admin_send_reply(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id): return
    data = await state.get_data()
    target_id = data.get("reply_target_id")
    try:
        await bot.send_message(
            target_id,
            f"☎️ <b>Admindan javob keldi:</b>\n\n{message.text}",
            parse_mode=ParseMode.HTML
        )
        await message.answer("✅ Javob yetkazildi!")
        db.mark_question_answered(target_id, message.from_user.id)
        answerer_name = message.from_user.full_name
        for aid in get_all_admin_ids():
            if aid == message.from_user.id: continue
            try:
                await bot.send_message(
                    aid,
                    f"✅ <b>Savolga javob berildi</b>\n\n"
                    f"👤 Javob bergan: {answerer_name}\n"
                    f"🆔 Foydalanuvchi ID: {target_id}",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")
    await state.clear()


@router.message(F.reply_to_message, F.chat.type == "private")
async def admin_reply_handler(message: Message, bot: Bot):
    if not is_admin(message.from_user.id): return
    try:
        original_text = message.reply_to_message.text or ""
        if "ID:" in original_text:
            parts = original_text.split("ID:")[1].split()
            user_id = int(parts[0].strip().replace(',', '').replace('.', ''))
            if db.is_question_answered(user_id):
                await message.answer("⚠️ Bu savolga allaqachon boshqa admin javob bergan!")
                return
            await bot.send_message(
                user_id,
                f"☎️ <b>Admindan javob keldi:</b>\n\n{message.text}",
                parse_mode=ParseMode.HTML
            )
            await message.answer("✅ Yetkazildi!")
            db.mark_question_answered(user_id, message.from_user.id)
            answerer_name = message.from_user.full_name
            for aid in get_all_admin_ids():
                if aid == message.from_user.id: continue
                try:
                    await bot.send_message(
                        aid,
                        f"✅ <b>Savolga javob berildi</b>\n\n"
                        f"👤 Javob bergan: {answerer_name}\n"
                        f"🆔 Foydalanuvchi ID: {user_id}",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
        else:
            await message.answer("Bu xabarda user ID si topilmadi.")
    except Exception as e:
        await message.answer(f"Xatolik: {e}")


@router.message(F.text == "/admins")
async def show_admins(message: Message):
    if message.from_user.id in ADMIN_IDS:
        await message.answer(
            "<b>Adminlar:</b>\n" + "\n".join(f"👤 {a}" for a in ADMIN_IDS),
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer("Bu buyruq faqat adminlar uchun!")


@router.message(F.chat.type == "private")
async def other_messages(message: Message):
    try:
        await message.answer("Iltimos, menyudan biror buyruqni tanlang.", reply_markup=main_menu)
    except Exception as e:
        logging.warning(f"[other_messages] Xabar yuborib bo'lmadi (chat={message.chat.id}): {e}")


# =============================================================================
# ISHGA TUSHIRISH
# =============================================================================
async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # ==========================================================================
    # MODERATION INTEGRATSIYASI
    # Guruhda spam, havola, xakerlik, havfli fayl filtrlari +
    # /warn /mute /ban /unban /unwarn /warns /report /modstats /modstatus
    # ==========================================================================
    if MODERATION_ENABLED:
        # Anti-flood middleware
        dp.message.middleware(RateLimitMiddleware(
            max_messages=mod_config.RATE_LIMIT_MAX,
            window=mod_config.RATE_LIMIT_WINDOW,
            mute_seconds=mod_config.RATE_LIMIT_MUTE
        ))
        # Admin tekshiruvi middleware
        dp.message.middleware(ModerationAdminMiddleware())
        dp.callback_query.middleware(ModerationAdminMiddleware())

        # Routerlar (tartib muhim — filter oxirida)
        dp.include_router(moderation_router)   # /warn /mute /ban va boshqalar
        dp.include_router(report_router)       # /report
        dp.include_router(mod_callback_router) # admin tugmalari
        dp.include_router(filter_router)       # matn/fayl filtri (OXIRDA!)

        # Yangi a'zo xush kelibsiz xabari
        from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION
        from aiogram.types import ChatMemberUpdated

        @dp.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
        async def welcome_new_member(event: ChatMemberUpdated):
            member = event.new_chat_member
            if not member or not member.user or member.user.is_bot:
                return
            chat_id = event.chat.id
            user = member.user
            chat_title = event.chat.title or 'guruh'
            from moderation.utils.storage import mod_storage
            mod_storage.increment_stat(chat_id, 'new_members')
            text = (
                f'👋 Assalomu alaykum, <b>{user.full_name}</b>!\n\n'
                f'Siz <b>{chat_title}</b> guruhiga qo\'shildingiz.\n\n'
                f'Guruh qoidalari bilan tanishing.\n'
                f'Qoidabuzarlikni ko\'rsangiz: /report sabab'
            )
            try:
                await event.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
            except Exception as e:
                logging.warning(f"[Welcome] Xato: {e}")

        logging.info("✅ Moderation routerlari va middleware'lar ro'yxatga olindi")

    # ── GLOBAL ERROR HANDLER ─────────────────────────────────────────────────
    @dp.errors()
    async def global_error_handler(event, exception: Exception):
        if isinstance(exception, TelegramForbiddenError):
            # Foydalanuvchi botni bloklagan — jim o'tkazib yuboramiz
            logging.warning(f"[BLOCKED] Foydalanuvchi botni bloklagan: {exception}")
            return True
        if isinstance(exception, TelegramBadRequest):
            msg = str(exception)
            if "query is too old" in msg or "query ID is invalid" in msg:
                # Bot o'chirilgan paytda bosilgan eski tugma — normal holat
                logging.warning(f"[OLD_QUERY] Eski callback, e'tiborsiz: {exception}")
                return True
        # Boshqa xatolar — odatdagidek log yoziladi
        logging.exception(f"[ERROR] Kutilmagan xato: {exception}")
        return False

    print(f"Bot ishga tushdi! Adminlar: {ADMIN_IDS}")
    print(f"Majburiy kanallar: {REQUIRED_CHANNELS or 'O`chirilgan'}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot to'xtatildi")