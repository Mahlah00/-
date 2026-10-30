"""
سلف‌بات تلگرام با Telethon
ساخته شده توسط @MRZverse

قابلیت‌ها (خلاصه‌شده):
  - میو دوره‌ای در یک گپ
  - ساعت خودکار روی بیو و نام خانوادگی (با فونت شیک)
  - افک (پاسخ خودکار وقتی نیستی)
  - فارم خودکار بات میویی، داخل یه گروه مشخص
  - کنترل کامل از راه دور توسط مدیر(ها) از طریق پیوی همین اکانت

نصب پیش‌نیاز:
    pip install telethon jdatetime

قبل از اجرا:
    1) برو به https://my.telegram.org و یه اپلیکیشن بساز
    2) مقدار api_id و api_hash رو زیر جایگزین کن
    3) آیدی عددی مدیر(ها) رو توی ADMIN_IDS بذار
    4) اولین بار که اجرا می‌کنی، شماره تلفن و کد تایید رو ازت می‌پرسه

نکته‌ی مهم درباره‌ی دستورها:
    دستورهای فعال‌سازی/تنظیم به‌عمد انگلیسی نوشته شدن (on/off) تا با
    مشکلات رایج تطبیق حروف فارسی (مثل «ي» عربی به‌جای «ی» فارسی، یا
    نویسه‌های نیم‌فاصله) روبه‌رو نشیم. جواب‌های ربات همچنان فارسی‌ان.
"""

import asyncio
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone, timedelta

import jdatetime  # برای تبدیل درست تاریخ شمسی -> نصب: pip install jdatetime

from telethon import TelegramClient, events
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import FloodWaitError
from telethon.tl.types import PeerChannel

# ====== تنظیمات ======
api_id = 30213358          # <-- اینجا رو با api_id خودت جایگزین کن
api_hash = "74b35d20203b6670dafcc595f81c4e46"  # <-- اینجا رو با api_hash خودت جایگزین کن
session_name = "R"

tz_offset_hours = 3.5            # تایم‌زون تهران (UTC+3:30)
clock_interval_seconds = 60      # فاصله‌ی آپدیت ساعت بیو/اسم

ADMIN_IDS: list[int] = [5888377320]        # <-- آیدی عددی اکانت‌های مدیر (از @userinfobot بگیر)

MEOWIE_TRIGGER_TEXT = "پیشی"      # پیامی که برای فارم به گروه فرستاده میشه
MEOWIE_BUTTON_KEYWORD = "برداشت میو پوینت ها"  # عبارت کامل دکمه، تا با دکمه‌های دیگه (مثلاً بانکی) اشتباه گرفته نشه
FRIDGE_TRIGGER_TEXT = "یخچال میویی"     # پیامی که برای بررسی یخچال فرستاده میشه
RESCUE_BUTTON_KEYWORD = "نجات پیشی خیابونی"   # دکمه‌ی پیام «پیشی خیابونی»
FISH_TRIGGER_TEXT = "ماهی"                 # دستور ماهی‌گیری
FRIDGE_STORE_KEYWORD = "بندازش تو یخچال"   # دکمه‌ی گذاشتن ماهی توی یخچال
FEED_BUTTON_KEYWORD = "بده پیشی بخوره"
COOK_BUTTON_KEYWORD = "بپوخش"
MAX_FISH_VALUE = 2000            # فقط ماهی‌هایی که ارزششون کمتر از این عدده خورانده/پخته میشن
# ======================

client = TelegramClient(session_name, api_id, api_hash)

OWNER_ID: int | None = None  # موقع اجرا پر میشه

# --- وضعیت‌های سراسری ---
active_meow_tasks: dict[int, asyncio.Task] = {}
meow_default_seconds = 10 * 60

clock_bio_task: asyncio.Task | None = None
clock_name_task: asyncio.Task | None = None

TELEGRAM_SERVICE_IDS = (777000, 42777, 333000, 429000, 93372553, 178220800)  # اکانت‌های رسمی تلگرام
dm_log_enabled = False          # ذخیره‌ی پیام‌های پیوی توی کانال
dm_log_target = None            # کانال مقصد (با «log channel <id|link>» تنظیم میشه)
ttl_save_enabled = True  # ذخیره‌ی عکس/ویدیوی نابودشونده توی Saved Messages
feed_interval_seconds: float | None = None   # None = غذا دادن همراه فارم؛ عدد = چک جدا هر چند ثانیه
feed_task: asyncio.Task | None = None
rescue_enabled = True   # کلیک خودکار روی «نجات پیشی خیابونی»
feed_enabled = True     # وقتی پیشی گشنمیوئه: یخچال رو چک کن و غذا بده
feed_lock = asyncio.Lock()
rescued_msg_ids: set[tuple[int, int]] = set()
RESCUE_DONE_WORDS = ("کشته شد", "علت مرگ", "نجات پیدا", "نجات یافت", "نجات داده شد", "نجات داد", "صاحب پیدا کرد", "صاحب یک خونه")
rescue_max_tries = 10          # حداکثر تعداد کلیک روی هر پیام نجات
rescue_delay_seconds = 1.2     # فاصله‌ی بین کلیک‌ها

afk_enabled = False
afk_message = "فعلاً نیستم، بعداً جواب می‌دم 🌙"
afk_replied_chats: set[int] = set()

farm_task: asyncio.Task | None = None
farm_chat_id: int | None = None
farm_interval_seconds = 60 * 60  # هر یک ساعت

awaiting_farm_group = False           # منتظر آیدی گروه از طرف خودِ اکانت
admin_awaiting_group: set[int] = set()  # منتظر آیدی گروه از طرف مدیر (توی پیوی)

# فلوی گفتگویی «delete messages»: None / "await_type" / "await_group" / "await_private"
delete_flow_stage: str | None = None


def normalize(text: str) -> str:
    """برای جلوگیری از مشکلات تطبیق حروف عربی/فارسی و نیم‌فاصله"""
    return (
        text.replace("ي", "ی")
        .replace("ك", "ک")
        .replace("\u200c", " ")  # نیم‌فاصله -> فاصله‌ی معمولی
        .strip()
    )


def parse_duration_seconds(raw: str) -> float | None:
    """'30' یا '30m' -> ۳۰ دقیقه، '2h' -> ۲ ساعت. خروجی به ثانیه، یا None اگه نامعتبر بود"""
    raw = raw.strip().lower()
    if not raw:
        return None
    try:
        if raw.endswith("h"):
            return float(raw[:-1]) * 3600
        if raw.endswith("m"):
            return float(raw[:-1]) * 60
        return float(raw) * 60  # پیش‌فرض: دقیقه
    except ValueError:
        return None


def now_str() -> str:
    tz = timezone(timedelta(hours=tz_offset_hours))
    return datetime.now(tz).strftime("%H:%M")


def _local_now():
    tz = timezone(timedelta(hours=tz_offset_hours))
    return datetime.now(tz)


JALALI_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]


def jalali_date_str() -> str:
    now = _local_now()
    jd = jdatetime.date.fromgregorian(date=now.date())
    return f"{jd.day} {JALALI_MONTHS[jd.month - 1]} {jd.year}"


# چند سبک فونت اعداد یونیکد که می‌شه برای ساعت روی بیو/اسم انتخاب کرد
DIGIT_FONTS = {
    "circle": {"0": "⓿", **{str(i): chr(0x2775 + i) for i in range(1, 10)}},   # ➊➋➌ + ⓿
    "bold":   {str(i): chr(0x1D7CE + i) for i in range(10)},                    # 𝟎𝟏𝟐
    "double": {str(i): chr(0x1D7D8 + i) for i in range(10)},                    # 𝟘𝟙𝟚
    "sans":   {str(i): chr(0x1D7E2 + i) for i in range(10)},                    # 𝟢𝟣𝟤
    "mono":   {str(i): chr(0x1D7F6 + i) for i in range(10)},                    # 𝟶𝟷𝟸
    "boldsans": {str(i): chr(0x1D7EC + i) for i in range(10)},                 # 𝟬𝟭𝟮
    "circled": {"0": "⓪", **{str(i): chr(0x2460 + i - 1) for i in range(1, 10)}},   # ①②③
    "sans_circle": {"0": "⓪", **{str(i): chr(0x2780 + i - 1) for i in range(1, 10)}},  # ➀➁➂
    "dbl_circle": {"0": "⓪", **{str(i): chr(0x24F5 + i - 1) for i in range(1, 10)}},   # ⓵⓶⓷
    "keycap": {**{str(i): f"{i}\ufe0f\u20e3" for i in range(10)}, ":": ":"},           # 1️⃣2️⃣3️⃣
    "fullwidth": {**{str(i): chr(0xFF10 + i) for i in range(10)}, ":": "："},            # ０１２
    "paren":  {"0": "⓪", **{str(i): chr(0x2474 + i - 1) for i in range(1, 10)}},   # ⑴⑵⑶
    "normal": {str(i): str(i) for i in range(10)},                              # بدون تغییر
}

bio_reverse = False          # با «clock bio reverse on» ساعت بیو از قبل برعکس نوشته میشه (اگه LRM جواب نداد)
bio_digit_font = "circle"    # فونت ساعت بیو؛ با «clock bio font <name>» عوض میشه
name_digit_font = "circle"   # فونت ساعت نام خانوادگی؛ با «clock name font <name>» عوض میشه


def fancy_digits(s: str, font: str = "circle") -> str:
    mapping = DIGIT_FONTS.get(font, DIGIT_FONTS["circle"])
    return "".join(mapping.get(ch, ch) for ch in s)


def fancy_digits_preview(font_name: str) -> str:
    mapping = DIGIT_FONTS.get(font_name, DIGIT_FONTS["circle"])
    return "".join(mapping.get(ch, ch) for ch in "12:34")


LRM = "\u200e"  # علامت چپ‌به‌راست (نامرئی)


def fancy_time(font: str = "circle", reverse: bool = False) -> str:
    """ساعت با سبک فونت اعداد انتخاب‌شده، برای بیو/اسم.
    بین همه‌ی نویسه‌ها LRM می‌ذاریم تا اعداد دایره‌ای/نمادی (که توی متن راست‌به‌چپ معکوس می‌شن)
    همیشه چپ‌به‌راست نمایش داده بشن: 01:57 و نه 75:10"""
    chars = []
    for ch in now_str():
        chars.append(fancy_digits(ch, font))
    if reverse:
        # حالت پشتیبان: اگه تلگرام علامت LRM رو نادیده بگیره، ساعت رو از قبل برعکس می‌نویسیم
        # تا موقع نمایش (که معکوس میشه) درست دیده بشه
        return "".join(reversed(chars))
    return LRM + LRM.join(chars) + LRM


BIO_STYLES = {
    "1": "🌙 {d}  ┃  🕰 {t}",
    "2": "🗓 {d}  ✦  {wd}  ✦  ⏰ {t}",
    "3": "✨ {d} ⋆ 🕐 {t} ✨",
    "4": "🌸 {d} ‹ ⏳ {t} › 🌸",
    "5": "💫 {d}  •  🕒 {t}",
}
bio_style = "1"  # با دستور «clock bio style <1-5>» عوض میشه


def fancy_bio_text() -> str:
    """تاریخ شمسی + ساعت، با ایموجی و فونت اعداد انتخاب‌شده، برای بیو"""
    now = _local_now()
    d = now.strftime("%d %b %Y")   # تاریخ میلادی، مثلاً 20 Oct 2026 (هر روز خودکار عوض میشه)
    wd = now.strftime("%a")        # روز هفته، مثلاً Tue
    prefix = "" if bio_reverse else LRM  # LRM اول متن: جهت کل بیو چپ‌به‌راست میشه
    text = BIO_STYLES.get(bio_style, BIO_STYLES["1"]).format(
        d=d, t=fancy_time(bio_digit_font, bio_reverse), wd=wd, gd=now.day, gm=now.strftime("%b")
    )
    return prefix + text


# ---------- میو دوره‌ای ----------
async def meow_loop(chat_id: int, seconds: float):
    try:
        while True:
            await asyncio.sleep(seconds)
            await client.send_message(chat_id, "میو")
    except asyncio.CancelledError:
        pass


async def toggle_meow(chat_id: int, minutes: float | None = None) -> str:
    if chat_id in active_meow_tasks:
        return "میو فعال می‌باشد 🐱 (از قبل روشن بود)"
    seconds = (minutes * 60) if minutes else meow_default_seconds
    active_meow_tasks[chat_id] = asyncio.create_task(meow_loop(chat_id, seconds))
    shown = minutes if minutes else meow_default_seconds / 60
    return f"میو فعال شد ✅ (هر {shown:g} دقیقه)"


async def untoggle_meow(chat_id: int) -> str:
    task = active_meow_tasks.pop(chat_id, None)
    if task:
        task.cancel()
        return "میو غیرفعال شد ❌"
    return "میو تو این گپ فعال نبود"


# ---------- ساعت خودکار بیو/اسم ----------
lrm_checked = False  # فقط یک بار چک می‌کنیم تلگرام علامت LRM رو نگه داشته یا نه


async def _safe_profile_update(**kwargs):
    """آپدیت پروفایل؛ خطاها (مثل FloodWait) حلقه‌ی ساعت رو نمی‌کشن"""
    try:
        await client(UpdateProfileRequest(**kwargs))
    except FloodWaitError as e:
        print(f"FloodWait: {e.seconds}s صبر می‌کنم")
        await asyncio.sleep(e.seconds + 1)
    except Exception as e:
        print(f"آپدیت پروفایل: {e}")


async def _check_lrm_in_bio():
    """اگه تلگرام علامت LRM رو از بیو حذف کرده باشه، خودکار حالت «برعکس‌نویسی» رو روشن می‌کنیم"""
    global bio_reverse, lrm_checked
    if lrm_checked or bio_reverse:
        return
    lrm_checked = True
    try:
        full = await client(GetFullUserRequest("me"))
        about = full.full_user.about or ""
        if LRM not in about:
            bio_reverse = True
            print("ساعت بیو: تلگرام LRM رو حذف کرد، حالت reverse خودکار روشن شد")
            await _safe_profile_update(about=fancy_bio_text())
    except Exception as e:
        print(f"چک LRM: {e}")


async def clock_bio_loop():
    try:
        while True:
            await _safe_profile_update(about=fancy_bio_text())
            await _check_lrm_in_bio()
            await asyncio.sleep(clock_interval_seconds)
    except asyncio.CancelledError:
        pass


async def clock_name_loop():
    try:
        while True:
            await _safe_profile_update(last_name=f"{LRM}✨ {fancy_time(name_digit_font)}")
            await asyncio.sleep(clock_interval_seconds)
    except asyncio.CancelledError:
        pass


async def toggle_clock_bio() -> str:
    global clock_bio_task
    if clock_bio_task:
        return "ساعت بیو فعال می‌باشد 🕐 (از قبل روشن بود)"
    clock_bio_task = asyncio.create_task(clock_bio_loop())
    return "ساعت خودکار بیو فعال شد ✅"


async def untoggle_clock_bio() -> str:
    global clock_bio_task
    if clock_bio_task:
        clock_bio_task.cancel()
        clock_bio_task = None
        return "ساعت بیو غیرفعال شد ❌"
    return "ساعت بیو فعال نبود"


async def toggle_clock_name() -> str:
    global clock_name_task
    if clock_name_task:
        return "ساعت اسم فعال می‌باشد 🕐 (از قبل روشن بود)"
    clock_name_task = asyncio.create_task(clock_name_loop())
    return "ساعت خودکار نام خانوادگی فعال شد ✅"


async def untoggle_clock_name() -> str:
    global clock_name_task
    if clock_name_task:
        clock_name_task.cancel()
        clock_name_task = None
        return "ساعت اسم غیرفعال شد ❌"
    return "ساعت اسم فعال نبود"


# ---------- افک ----------
async def toggle_afk(custom_message: str = "") -> str:
    global afk_enabled, afk_message
    if afk_enabled and not custom_message:
        return "حالت افک فعال می‌باشد 🌙 (از قبل روشن بود)"
    if custom_message:
        afk_message = custom_message
    afk_enabled = True
    afk_replied_chats.clear()
    return f"حالت افک فعال شد ✅\nپیام: {afk_message}"


async def untoggle_afk() -> str:
    global afk_enabled
    if not afk_enabled:
        return "حالت افک غیرفعال می‌باشد ❌ (از قبل خاموش بود)"
    afk_enabled = False
    afk_replied_chats.clear()
    return "حالت افک غیرفعال شد ❌ خوش اومدی 👋"


# ---------- فارم خودکار (داخل یه گروه مشخص) ----------
async def click_farm_button(chat_id: int, sent_msg_id: int):
    """منتظر پیامی می‌مونه که دقیقاً روی sent_msg_id ریپلای زده باشه، و دکمه‌ی برداشت رو می‌زنه.
    اگه توی پیام پاسخ، شکم «گشنمیو» بود، فلوی غذا دادن (یخچال) رو هم راه می‌ندازه."""
    for _ in range(15):  # حداکثر ۱۵ ثانیه صبر
        await asyncio.sleep(1)
        async for msg in client.iter_messages(chat_id, limit=40):
            if msg.reply_to_msg_id == sent_msg_id and not msg.out and msg.buttons and await _is_bot_msg(msg):
                text = msg.raw_text or ""
                try:
                    await msg.click(text=lambda t: t and MEOWIE_BUTTON_KEYWORD in t)
                except Exception:
                    pass
                hungry, room = feed_decision(text)
                print(f"شکم: {parse_stomach(text)} | متن‌های گرسنگی: {feed_hunger_texts} | غذا بده؟ {hungry}")
                if hungry and feed_enabled and feed_interval_seconds is None:
                    asyncio.create_task(feed_cat_flow(chat_id, room))
                return


# ---------- غذا دادن به پیشی (یخچال میویی) ----------
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


async def _is_bot_msg(msg) -> bool:
    """فقط پیام‌های ربات (میویی) رو قبول می‌کنیم، نه آدم‌های دیگه‌ی گروه"""
    try:
        sender = msg.sender or await msg.get_sender()
        return bool(getattr(sender, "bot", False))
    except Exception:
        return False


def _flat_buttons(msg):
    return [b for row in (msg.buttons or []) for b in row]


async def wait_reply_to(chat_id: int, sent_id: int, timeout: int = 15, need_buttons: bool = True):
    """پاسخ (ریپلای) ربات به پیام sent_id رو که دکمه داره برمی‌گردونه"""
    for _ in range(timeout):
        await asyncio.sleep(1)
        async for msg in client.iter_messages(chat_id, limit=40):
            if msg.reply_to_msg_id == sent_id and not msg.out and (msg.buttons or not need_buttons) \
                    and await _is_bot_msg(msg):
                return msg
    return None


async def wait_button(chat_id: int, msg_id: int, keyword: str, timeout: int = 10):
    """پیام msg_id (که ربات ادیتش می‌کنه) رو دوباره می‌خونه تا دکمه‌ای با keyword توش پیدا بشه"""
    for _ in range(timeout):
        await asyncio.sleep(1)
        m = await client.get_messages(chat_id, ids=msg_id)
        if m and m.buttons:
            for b in _flat_buttons(m):
                if b.text and keyword in b.text:
                    return b
    return None


# ---------- یخچال، ماهی، غذا دادن، پخت و فروش ----------
SELL_BUTTON_KEYWORD = "فروش ماهی"
SOLD_WORDS = ("فروخته", "فروش رفت", "فروخت")
FED_WORDS = ("خوردش", "خورد")
BACK_KEYWORDS = ("BK", "🔙", "بازگشت", "برگشت", "◀", "⬅", "↩")
fish_feed_max = 10**12  # بدون محدودیت قیمت؛ با «fish feed below n» میشه محدود کرد  #      # ماهی پخته‌ی ارزان‌تر از این عدد به پیشی داده میشه (و ماهی خام ارزان‌تر پخته میشه)
fish_sell_min = 50000                # ماهی پخته‌ی با ارزش مساوی یا بیشتر از این عدد فروخته میشه
fish_sell_enabled = True
fish_cook_enabled = True             # همه‌ی ماهی‌های خام پخته میشن
fish_cook_min = 0                    # فقط ماهی خام با ارزش >= این عدد پخته میشه (0 = بدون استثنا همه)
feed_setup_stage = None              # فلوی گفتگویی دستور feed: None | cap | need
feed_setup_cap = None
cook_timers: dict[int, asyncio.Task] = {}


def parse_int(raw: str) -> int | None:
    """عدد با ویرگول یا پسوند k/m: 50000 ، 50,000 ، 50k ، 1.5m"""
    raw = (raw or "").translate(_DIGITS).replace(",", "").replace("،", "").strip().lower()
    mult = 1
    if raw.endswith("k"):
        mult, raw = 1000, raw[:-1]
    elif raw.endswith("m"):
        mult, raw = 1_000_000, raw[:-1]
    try:
        v = int(float(raw) * mult)
        return v if v >= 0 else None
    except ValueError:
        return None


def parse_fridge(msg):
    """پیام یخچال رو به لیست ماهی‌ها تبدیل می‌کنه (به‌ترتیب نمایش).
    هر ماهی: {'emoji', 'status': cooked|raw|other, 'cooked', 'raw', 'value'}"""
    text = _clean(msg.raw_text)
    fish, cur = [], None
    for ln in text.splitlines():
        if "|" in ln and any(w in ln for w in ("پخته", "خام", "پخت", "پخیدن")):
            status = "cooked" if "پخته" in ln else ("raw" if "خام" in ln else "other")
            cur = {"emoji": ln.split("|")[0].strip(), "status": status,
                   "cooked": status == "cooked", "raw": status == "raw", "value": None, "food": None}
            fish.append(cur)
            continue
        if cur is not None:
            mf = re.search(r"ارزش\s*غذایی[^\d\n]*(\d+)", ln)
            if mf:
                cur["food"] = int(mf.group(1))
            elif cur["value"] is None:
                m = re.search(r"ارزش[^\d\n:]*:[^\d\n]*([0-9][0-9,]*)", ln)
                if m:
                    cur["value"] = int(m.group(1).replace(",", ""))
    for f in fish:
        if f["value"] is None:
            f["value"] = 0
    return fish


def parse_capacity(text: str):
    """ظرفیت یخچال : 3 / 5  →  (3, 5)  (یا None)"""
    t = _clean(text)
    m = re.search(r"ظرفیت[^\n:：]*[:：][\s‎‏]*(\d+)[\s‎‏]*/[\s‎‏]*(\d+)", t)
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_cook_seconds(text: str) -> int | None:
    """«زمان مورد نیاز پخیدن : 5:07» → ساعت:دقیقه (یا ساعت:دقیقه:ثانیه) به ثانیه"""
    t = _clean(text)
    m = re.search(r"زمان[^\n]*?(\d+)\s*:\s*(\d{1,2})(?:\s*:\s*(\d{1,2}))?", t) or \
        re.search(r"(\d+)\s*:\s*(\d{1,2})(?:\s*:\s*(\d{1,2}))?", t)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    s = int(m.group(3)) if m.group(3) else 0
    return h * 3600 + mi * 60 + s


def is_hungry_text(text: str) -> bool:
    return any("شکم" in ln and "گشنمیو" in ln for ln in (text or "").splitlines())


feed_hunger_texts: list[str] = ["گشنمیو", "دیگه کار نمیکنمیو"]   # متن‌هایی که اگه جلوی «شکم» باشن سلف غذا میده
feed_rules: dict[int, int] = {}   # {ظرفیت شکم: حداکثر عددی که تا اون سلف غذا میده}  مثلا feed 15/5 → {15: 5}


_INVIS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069\u200b\u200c]")


def _clean(t: str) -> str:
    """علامت‌های نامرئی جهت (LRM/RLM/...) رو برمیداره و ارقام فارسی رو انگلیسی می‌کنه"""
    return _INVIS.sub("", (t or "")).translate(_DIGITS)


def parse_stomach(text: str):
    """«شکم : ... (15 / 7)» → (ظرفیت شکم=15، پُری فعلی=7). عدد اول ظرفیتِ مقام گربه‌ست.
    مستقل از متن جلوی شکم (گشنمیو، پره، ...) و از علامت‌های نامرئی"""
    t = _clean(text)
    pat = r"\(\s*(\d+)\s*/\s*(\d+)\s*\)"
    for ln in t.splitlines():
        if "شکم" in ln:
            m = re.search(pat, ln)
            if m:
                return int(m.group(1)), int(m.group(2))
    m = re.search(pat, t)  # اگه «شکم» و عدد توی یه خط نبودن
    return (int(m.group(1)), int(m.group(2))) if m else None


def _loose(t: str) -> str:
    """برای مقایسه‌ی متن‌ها: نویسه‌های نامرئی و فاصله‌ها حذف، حرف‌های تکراری (گشنمیووو) یکی میشن"""
    t = _clean(normalize(t or "")).replace(" ", "").replace(".", "")
    return re.sub(r"(.)\1+", r"\1", t)


def feed_decision(text: str):
    """(باید غذا بده؟، جای خالی شکم).
    اصلی‌ترین ملاک: اگه خط «شکم» یکی از متن‌های گرسنگیِ تنظیم‌شده رو داشته باشه (feed text add ...)
    ملاک دوم (اختیاری): قانون عددی feed 12/7"""
    t = _clean(text)
    line = next((ln for ln in t.splitlines() if "شکم" in ln), t)
    lline = _loose(line)
    text_hit = any(_loose(p) and _loose(p) in lline for p in feed_hunger_texts)
    st = parse_stomach(text)
    room = None
    rule_hit = False
    if st:
        cap, cur = st
        room = max(cap - cur, 0)
        rule = feed_rules.get(cap)
        rule_hit = rule is not None and cur <= rule
    need = text_hit or rule_hit
    if room == 0:
        need = False
    return need, room


async def safe_click(btn) -> bool:
    """کلیک روی دکمه‌ی اینلاین؛ خطای «BOT_RESPONSE_TIMEOUT» و مشابهش رو نادیده می‌گیره"""
    try:
        await btn.click()
        return True
    except Exception as e:
        if "TIMEOUT" in str(e).upper() or "timed out" in str(e).lower():
            return True  # ربات جواب کوتاه نداد ولی کلیک ثبت شده
        print(f"کلیک ناموفق: {e}")
        return False


async def wait_msg(chat_id: int, msg_id: int, pred, timeout: int = 10):
    """پیام (که ربات ادیتش می‌کنه) رو دوباره می‌خونه تا pred(m) درست بشه"""
    for _ in range(int(timeout / 0.7) + 1):
        await asyncio.sleep(0.7)
        m = await client.get_messages(chat_id, ids=msg_id)
        if m and pred(m):
            return m
    return None


def find_back_button(m):
    """دکمه‌ی قرمز «BK» (بازگشت). اگه متنش ایموجی/خالی بود: تک‌دکمه‌ی آخرین ردیف"""
    btns = _flat_buttons(m)
    for b in btns:
        t = b.text or ""
        if any(k.lower() in t.lower() for k in BACK_KEYWORDS):
            return b
    if len(btns) == 1:
        return btns[0]
    forbidden = ("فروش", "بده", "بپوخش", "ارتقا", "✅", "❌", "✔", "✖")
    if m.buttons:
        last = m.buttons[-1]
        if len(last) == 1 and not any(x in (last[0].text or "") for x in forbidden):
            return last[0]
    return None


async def click_back(chat_id: int, msg_id: int) -> bool:
    """دکمه‌ی BK رو می‌زنه تا برگرده به منوی قبلی (یخچال)"""
    for _ in range(12):
        await asyncio.sleep(0.7)
        m = await client.get_messages(chat_id, ids=msg_id)
        if m and m.buttons:
            b = find_back_button(m)
            if b:
                ok = await safe_click(b)
                await asyncio.sleep(1.0)
                return ok
    print("دکمه‌ی BK پیدا نشد")
    return False


def map_fish_buttons(fmsg, fish) -> bool:
    """دکمه‌ی هر ماهی رو پیدا می‌کنه: اول با ایموجی گوشه‌ی هر ماهی، وگرنه به‌ترتیب نمایش"""
    btns = [b for b in _flat_buttons(fmsg)
            if "ارتقا" not in (b.text or "") and not any(k.lower() in (b.text or "").lower() for k in BACK_KEYWORDS)]
    if len(btns) != len(fish):
        print(f"fish: تعداد ماهی‌ها ({len(fish)}) با دکمه‌ها ({len(btns)}) نمی‌خونه")
        return False
    matched = []
    for f in fish:
        hits = [b for b in btns if f["emoji"] and (b.text or "").strip() == f["emoji"]]
        matched.append(hits[0] if len(hits) == 1 else None)
    if None not in matched and len({id(b) for b in matched}) == len(fish):
        for f, b in zip(fish, matched):
            f["btn"] = b
    else:
        for f, b in zip(fish, btns):
            f["btn"] = b
    return True


async def sell_fish(chat_id: int, msg_id: int, f) -> bool:
    """ماهی → «فروش ماهی» → صبر برای «فروخته شد» → BK"""
    if not await safe_click(f["btn"]):
        return False
    b = await wait_button(chat_id, msg_id, SELL_BUTTON_KEYWORD)
    if not b or not await safe_click(b):
        return False
    m = await wait_msg(chat_id, msg_id, lambda m: any(w in (m.raw_text or "") for w in SOLD_WORDS), 8)
    await click_back(chat_id, msg_id)
    print(f"fish: ماهی با ارزش {f['value']:,} {'فروخته شد' if m else '(تأیید فروش دیده نشد)'}")
    return bool(m)


async def feed_fish(chat_id: int, msg_id: int, f) -> bool:
    """ماهی پخته → «بده پیشی بخوره» → «پیشی خوردش» → BK"""
    if not await safe_click(f["btn"]):
        return False
    b = await wait_button(chat_id, msg_id, FEED_BUTTON_KEYWORD)
    if not b or not await safe_click(b):
        return False
    m = await wait_msg(chat_id, msg_id, lambda m: any(w in (m.raw_text or "") for w in FED_WORDS), 8)
    await click_back(chat_id, msg_id)
    print("fish: ماهی پخته به پیشی داده شد" if m else "fish: ماهی داده شد (تأیید «خوردش» دیده نشد)")
    return True


async def cook_fish(chat_id: int, msg_id: int, f):
    """ماهی خام → «بپوخش» → تأیید با دکمه‌ی سبز ✓ → «درحال پخیدن» → BK. زمان پخت (ثانیه) یا None"""
    if not await safe_click(f["btn"]):
        return None
    b = await wait_button(chat_id, msg_id, COOK_BUTTON_KEYWORD)
    if not b or not await safe_click(b):
        return None
    m = await wait_msg(chat_id, msg_id, lambda m: "اطمینان" in (m.raw_text or "") and bool(m.buttons), 8)
    if not m:
        print("cook: منوی تأیید نیومد")
        return None
    bad = ("❌", "✖", "✕", "×", "✗", "❎")
    btns = _flat_buttons(m)
    good = [x for x in btns if not any(c in (x.text or "") for c in bad)] or btns
    # دکمه‌ی سبز ✓ اولین دکمه است؛ قرمز × (انصراف) دومیه
    if not good or not await safe_click(good[0]):
        return None
    m2 = await wait_msg(chat_id, msg_id,
                        lambda m: "اطمینان" not in (m.raw_text or "") and ("پخیدن" in (m.raw_text or "") or "پخت" in (m.raw_text or "")), 10)
    seconds = parse_cook_seconds(m2.raw_text) if m2 else None
    await click_back(chat_id, msg_id)
    print(f"cook: پخت شروع شد، زمان لازم {seconds} ثانیه" if seconds else "cook: پخت شروع شد (زمان خونده نشد)")
    return seconds if seconds else 3600


async def catch_and_store_fish(chat_id: int) -> bool:
    """«ماهی» می‌فرسته و روی «بندازش تو یخچال» می‌زنه. اگه انجام شد True برمی‌گردونه"""
    sent = await client.send_message(chat_id, FISH_TRIGGER_TEXT)
    msg = await wait_reply_to(chat_id, sent.id)
    if not msg:
        print("fish: پاسخ ماهی نیومد")
        return False
    for b in _flat_buttons(msg):
        if b.text and FRIDGE_STORE_KEYWORD in b.text:
            ok = await safe_click(b)
            print("fish: ماهی توی یخچال انداخته شد" if ok else "fish: کلیک ناموفق")
            return ok
    print("fish: دکمه‌ی «بندازش تو یخچال» پیدا نشد")
    return False


def schedule_post_cook(chat_id: int, seconds: int):
    """بعد از تمام شدن زمان پخت، یخچال رو چک می‌کنه (فروش ماهی‌های گرون، ...)"""
    old = cook_timers.pop(chat_id, None)
    if old and old is not asyncio.current_task():
        old.cancel()
    cook_timers[chat_id] = asyncio.create_task(_post_cook(chat_id, seconds + 60))


async def _post_cook(chat_id: int, wait: float):
    try:
        await asyncio.sleep(wait)
        async with feed_lock:
            await fridge_session(chat_id, hungry=False, allow_fish=False)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"post-cook: {e}")


async def fridge_session(chat_id: int, hungry: bool, allow_fish: bool, room=None):
    """یه نشست کامل یخچال (بعد از هر کار با BK به یخچال برمی‌گرده و دوباره بررسی میشه):
    ۱) ماهی پخته با ارزش >= حد فروش → فروش
    ۲) اگه باید غذا بده: ماهی پخته‌ای که ارزش غذاییش تو جای خالی شکم جا بشه → بده بخوره
    ۳) همه‌ی ماهی‌های خام (بدون استثنا) → بپوخش → ✓ → BK، و تایمر/پیام پخت
    ۴) اگه یخچال پر نیست (دو عدد ظرفیت برابر نیستن) → «ماهی» + «بندازش تو یخچال»"""
    for _round in range(10):
        try:
            sent = await client.send_message(chat_id, FRIDGE_TRIGGER_TEXT)
            fmsg = await wait_reply_to(chat_id, sent.id, need_buttons=False)
            if not fmsg:
                print("fridge: پاسخ یخچال نیومد")
                return
            fish = parse_fridge(fmsg)
            cap = parse_capacity(fmsg.raw_text)
            if fish and not map_fish_buttons(fmsg, fish):
                return
            cooking = any(f["status"] == "other" for f in fish)
            print(f"یخچال: {len(fish)} ماهی (پخته {sum(1 for f in fish if f['cooked'])}، خام {sum(1 for f in fish if f['raw'])}) | ظرفیت {cap} | جای خالی شکم {room} | باید غذا بده؟ {hungry}")

            def fits(f):  # ارزش غذایی ماهی نباید از جای خالی شکم بیشتر باشه
                return room is None or f["food"] is None or f["food"] <= room
            best = lambda f: (-(f["food"] or 0), f["value"])

            # ۱) فروش
            if fish_sell_enabled:
                sellable = [f for f in fish if f["cooked"] and f["value"] >= fish_sell_min]
                if sellable:
                    if await sell_fish(chat_id, fmsg.id, max(sellable, key=lambda f: f["value"])):
                        continue
                    return

            # ۲) غذا دادن
            if hungry:
                cooked_fit = [f for f in fish if f["cooked"] and f["value"] < fish_feed_max and fits(f)]
                if not cooked_fit:
                    print("یخچال: ماهی پخته‌ی مناسب پیدا نشد (ارزش غذایی بیشتر از جای خالی شکم، یا گرون‌تر از حد غذادهی، یا ماهی پخته نیست)")
                if cooked_fit:
                    if not await feed_fish(chat_id, fmsg.id, min(cooked_fit, key=best)):
                        return
                    hungry = False
                    continue

            # ۳) پختن همه‌ی ماهی‌های خام
            if fish_cook_enabled and not cooking:
                raws = [f for f in fish if f["raw"] and f["value"] >= fish_cook_min]
                if raws:
                    pool = [f for f in raws if fits(f)] if hungry else []
                    pick = min(pool, key=best) if pool else max(raws, key=lambda f: f["value"])
                    seconds = await cook_fish(chat_id, fmsg.id, pick)
                    if seconds:
                        schedule_post_cook(chat_id, seconds)
                    return

            # ۴) یخچال پر نیست → ماهی بگیر
            if allow_fish and (cap is None or cap[0] != cap[1]):
                allow_fish = False
                if await catch_and_store_fish(chat_id):
                    await asyncio.sleep(2)
                    continue
            return
        except Exception as e:
            print(f"خطا توی یخچال: {e}")
            return


async def feed_cat_flow(chat_id: int, room=None):
    """قفل می‌گیره تا دو فلوی یخچال همزمان اجرا نشن"""
    async with feed_lock:
        await asyncio.sleep(3)
        await fridge_session(chat_id, hungry=True, allow_fish=True, room=room)

# ---------- کارخونه میویی ----------
FACTORY_TRIGGER_TEXT = "کارخونه میویی"
FACTORY_CATEGORIES = {"1": "آبنبات", "2": "کیک", "3": "تکنولوژی", "4": "خودرو", "5": "هواپیما", "6": "تکنولوژی پیشرفته"}
FACTORY_SOLD_WORDS = ("فروخته", "فروش رفت", "فروخت", "با موفقیت")
factory_enabled = False
factory_chat_id = None            # گروهی که کارخونه توش بررسی میشه (پیش‌فرض: گروه فارم)
factory_sell_min = None           # قیمت بازار >= این عدد → فروش محصول (None = فروش خاموش)
factory_cost_max = 0              # هزینه‌ی ساخت هر عدد باید <= این عدد باشه (0 = بدون محدودیت)
factory_targets = [{"cat": "تکنولوژی پیشرفته", "item": 1}]   # لیست اولویت تولید: هر کدوم «محصول از دسته»؛ اولی که شد تولید میشه
# ترتیب دکمه‌های هر دسته از سمت راست (مثل نمایش توی تلگرام) و اسم/شکل‌هایی که میشه براشون نوشت
FACTORY_LAYOUT = {
    "آبنبات": [("🍫", "شکلات"), ("🍭", "آبنبات چوبی", "آبنبات"), ("🎊", "جشن")],
    "کیک": [("🎂", "کیک تولد"), ("🍰", "کیک"), ("🧁", "کاپ کیک")],
    "تکنولوژی": [("🤖", "ربات"), ("💻", "لپ تاپ", "لپتاپ"), ("📱", "موبایل")],
    "خودرو": [("🏎", "ماشین مسابقه"), ("🚕", "تاکسی"), ("🚗", "ماشین")],
    "هواپیما": [("🚀", "موشک"), ("🛩", "جت"), ("✈", "هواپیما")],
    "تکنولوژی پیشرفته": [("⭐", "ستاره", "star"), ("AI", "ای آی", "هوش مصنوعی"), ("HPC", "اچ پی سی")],
}
factory_percent = 100             # درصد پر کردن انبار: 25 / 50 / 75 / 100
factory_interval_seconds = 3600
factory_busy_until = 0.0          # تا این زمان (epoch) تولید در جریانه
factory_task = None
factory_timer = None
factory_lock = asyncio.Lock()
_FA_ONLY = re.compile("[^؀-ۿ ]")


def _fa(t) -> str:
    """فقط حروف فارسی (ایموجی و عدد و علامت حذف میشه) برای مقایسه‌ی متن دکمه‌ها"""
    return re.sub(r"\s+", " ", _FA_ONLY.sub("", normalize(_clean(t or "")))).strip()


def _toint(x: str) -> int:
    return int(x.replace(",", ""))


def parse_factory_storage(text: str):
    m = re.search(r"ظرفیت\s*انبار[^\d\n]*(\d[\d,]*)\s*/\s*(\d[\d,]*)", _clean(text))
    return (_toint(m.group(1)), _toint(m.group(2))) if m else None


def parse_market_price(text: str):
    m = re.search(r"قیمت[^\n:]*بازار[^\d\n]*(\d[\d,]*)", _clean(text))
    return _toint(m.group(1)) if m else None


def parse_unit_cost(text: str):
    m = re.search(r"هر\s*یک\s*عدد[^\d\n]*(\d[\d,]*)", _clean(text))
    return _toint(m.group(1)) if m else None


def _factory_is_main(m) -> bool:
    names = [_fa(b.text) for b in _flat_buttons(m)]
    return any("کارکنان" in n or "دستگاه" in n for n in names)


def _pick_btn(m, exact=None, contains=None):
    for b in _flat_buttons(m):
        n = _fa(b.text)
        if exact is not None and n == exact:
            return b
        if contains is not None and contains in n:
            return b
    return None


def _confirm_btn(m):
    for b in _flat_buttons(m):
        if any(c in (b.text or "") for c in ("✅", "✔", "☑", "✓", "تایید", "تأیید", "بله")):
            return b
    return None


async def factory_home(chat_id: int, mid: int) -> bool:
    """با دکمه‌ی قرمز BK آن‌قدر برمی‌گرده تا صفحه‌ی اول کارخونه"""
    for _ in range(6):
        m = await client.get_messages(chat_id, ids=mid)
        if m and _factory_is_main(m):
            return True
        if not await click_back(chat_id, mid):
            return False
        await asyncio.sleep(0.8)
    m = await client.get_messages(chat_id, ids=mid)
    return bool(m and _factory_is_main(m))


async def factory_sell_flow(chat_id: int, mid: int) -> int:
    """انبار → هر محصول → اگه قیمت بازار >= حد فروش: «فروش محصول» (و تیک سبز) → BK ... تا صفحه‌ی اول"""
    sold, i = 0, 0
    for _ in range(12):
        m = await client.get_messages(chat_id, ids=mid)
        if not m or not _factory_is_main(m):
            if not await factory_home(chat_id, mid):
                return sold
            m = await client.get_messages(chat_id, ids=mid)
        b = _pick_btn(m, exact="انبار")
        if not b or not await safe_click(b):
            print("کارخونه: دکمه‌ی انبار پیدا نشد")
            return sold
        wh = await wait_msg(chat_id, mid, lambda x: bool(x.buttons) and not _factory_is_main(x), 8)
        if not wh:
            return sold
        bk = find_back_button(wh)
        prods = [x for x in _flat_buttons(wh) if x is not bk]
        if i >= len(prods):
            break
        if not await safe_click(prods[i]):
            return sold
        pm = await wait_msg(chat_id, mid, lambda x: "محصول انتخابی" in _clean(x.raw_text) or "بازار" in _clean(x.raw_text), 8)
        if not pm:
            print("کارخونه: صفحه‌ی محصول باز نشد")
            i += 1
            continue
        price = parse_market_price(pm.raw_text)
        if price is not None and factory_sell_min is not None and price >= factory_sell_min:
            sb = _pick_btn(pm, contains="فروش")
            if sb and await safe_click(sb):
                r = await wait_msg(chat_id, mid, lambda x: any(w in _clean(x.raw_text) for w in FACTORY_SOLD_WORDS) or "محصول انتخابی" not in _clean(x.raw_text) or _confirm_btn(x) is not None, 8)
                if r is not None and not any(w in _clean(r.raw_text) for w in FACTORY_SOLD_WORDS):
                    cb = _confirm_btn(r)
                    if cb and await safe_click(cb):   # تیک سبز
                        await wait_msg(chat_id, mid, lambda x: any(w in _clean(x.raw_text) for w in FACTORY_SOLD_WORDS) or _confirm_btn(x) is None, 8)
                sold += 1
                print(f"کارخونه: محصول با قیمت بازار {price:,} فروخته شد")
                await factory_home(chat_id, mid)
                continue  # لیست انبار کوتاه شده؛ همون اندیس دوباره
            i += 1
        else:
            print(f"کارخونه: قیمت بازار {price} به حد فروش {factory_sell_min} نرسیده؛ فروخته نشد")
            i += 1
        await factory_home(chat_id, mid)
    await factory_home(chat_id, mid)
    return sold


def _resolve_item_index(cat: str, item, prods):
    """محصول (شماره / شکل / اسم) رو به اندیس دکمه تبدیل می‌کنه؛ None اگه پیدا نشد"""
    if isinstance(item, int):
        return min(max(item, 1), len(prods)) - 1
    key = str(item).replace("\ufe0f", "").strip().lower()
    for pos, names in enumerate(FACTORY_LAYOUT.get(cat, [])):
        if any(key == n.replace("\ufe0f", "").lower() for n in names):
            return min(pos, len(prods) - 1)
    for k, y in enumerate(prods):   # اگه متن دکمه خودش شکل رو داشت
        if key and key in (y.text or "").replace("\ufe0f", "").lower():
            return k
    return None


async def factory_produce_target(chat_id: int, mid: int, cat_name: str, item) -> bool:
    """تولید → دسته → محصول (با شکل/شماره) → درصد → اگه هزینه‌ی ساخت اوکی بود «شروع تولید»"""
    global factory_busy_until
    m = await client.get_messages(chat_id, ids=mid)
    if not m or not _factory_is_main(m):
        if not await factory_home(chat_id, mid):
            return False
        m = await client.get_messages(chat_id, ids=mid)
    b = _pick_btn(m, exact="تولید")
    if not b or not await safe_click(b):
        print("کارخونه: دکمه‌ی تولید پیدا نشد")
        return False
    cat = await wait_msg(chat_id, mid, lambda x: any("تولیدی" in _fa(y.text) for y in _flat_buttons(x)), 8)
    if not cat:
        print("کارخونه: صفحه‌ی دسته‌ها باز نشد (شاید تولید در جریانه)")
        await factory_home(chat_id, mid)
        return False
    target = ("تولیدی " + cat_name).replace(" ", "")
    cb = next((y for y in _flat_buttons(cat) if _fa(y.text).replace(" ", "") == target), None)
    if not cb:
        print(f"کارخونه: دسته‌ی «{cat_name}» پیدا نشد")
        await factory_home(chat_id, mid)
        return False
    await safe_click(cb)
    pg = await wait_msg(chat_id, mid, lambda x: len(_flat_buttons(x)) >= 2 and not any("تولیدی" in _fa(y.text) for y in _flat_buttons(x)), 8)
    if not pg:
        print("کارخونه: صفحه‌ی محصولات باز نشد")
        await factory_home(chat_id, mid)
        return False
    bk = find_back_button(pg)
    prods = [y for y in _flat_buttons(pg) if y is not bk]
    print("کارخونه: دکمه‌های محصول (از سمت راست):", ", ".join(f"{k + 1}={y.text or '?'}" for k, y in enumerate(prods)))
    idx = _resolve_item_index(cat_name, item, prods) if prods else None
    if idx is None:
        print(f"کارخونه: محصول «{item}» توی دسته‌ی «{cat_name}» پیدا نشد")
        await factory_home(chat_id, mid)
        return False
    await safe_click(prods[idx])
    pc = await wait_msg(chat_id, mid, lambda x: any("%" in (y.text or "") for y in _flat_buttons(x)), 8)
    if not pc:
        print("کارخونه: صفحه‌ی درصد باز نشد")
        await factory_home(chat_id, mid)
        return False
    pb = next((y for y in _flat_buttons(pc) if "%" in (y.text or "") and re.sub(r"\D", "", _clean(y.text)) == str(factory_percent)), None)
    if not pb:
        print(f"کارخونه: دکمه‌ی {factory_percent}% پیدا نشد")
        await factory_home(chat_id, mid)
        return False
    await safe_click(pb)
    cf = await wait_msg(chat_id, mid, lambda x: "اطمینان" in _clean(x.raw_text) and _pick_btn(x, contains="شروع") is not None, 8)
    if not cf:
        print("کارخونه: صفحه‌ی تأیید تولید باز نشد")
        await factory_home(chat_id, mid)
        return False
    cost = parse_unit_cost(cf.raw_text)
    market = parse_market_price(cf.raw_text)
    secs = parse_cook_seconds(cf.raw_text) or 3600
    print(f"کارخونه: هزینه‌ی ساخت هر عدد {cost} | قیمت بازار {market} | زمان تولید {secs} ثانیه")
    if factory_cost_max and cost is not None and cost > factory_cost_max:
        print(f"کارخونه: هزینه‌ی ساخت ({cost}) از حد تعیین‌شده ({factory_cost_max}) بیشتره؛ تولید شروع نشد")
        await factory_home(chat_id, mid)
        return False
    sb = _pick_btn(cf, contains="شروع")
    if not sb or not await safe_click(sb):
        await factory_home(chat_id, mid)
        return False
    await wait_msg(chat_id, mid, lambda x: "اطمینان" not in _clean(x.raw_text), 8)
    factory_busy_until = time.time() + secs + 30
    schedule_factory_check(secs + 60)
    print(f"کارخونه: تولید «{item}» از دسته‌ی «{cat_name}» شروع شد ✅")
    await factory_home(chat_id, mid)
    return True


async def factory_produce_flow(chat_id: int, mid: int) -> bool:
    """لیست اولویت: اولین «محصول از دسته» که بشه تولید میشه؛ اگه نشد (پیدا نشد / هزینه زیاد) بعدی"""
    for t in list(factory_targets):
        if await factory_produce_target(chat_id, mid, t["cat"], t["item"]):
            return True
    return False


def _factory_target_chat():
    return factory_chat_id or farm_chat_id


async def factory_session(force: bool = False):
    chat = _factory_target_chat()
    if chat is None:
        print("کارخونه: گروه تنظیم نشده؛ توی گروه بنویس: factory on")
        return
    async with factory_lock:
        if not force and time.time() < factory_busy_until:
            print(f"کارخونه: تولید در جریانه؛ {int((factory_busy_until - time.time()) / 60)} دقیقه‌ی دیگه بررسی میشه")
            return
        sent = await client.send_message(chat, FACTORY_TRIGGER_TEXT)
        fmsg = await wait_reply_to(chat, sent.id)
        if not fmsg:
            print("کارخونه: پاسخ کارخونه نیومد")
            return
        mid = fmsg.id
        st = parse_factory_storage(fmsg.raw_text)
        if not st:
            print("کارخونه: ظرفیت انبار خونده نشد")
            return
        print(f"کارخونه: ظرفیت انبار {st[0]:,} / {st[1]:,}")
        if st[0] == st[1]:   # انبار پر
            if factory_sell_min is None:
                print("کارخونه: انبار پره ولی حد فروش تنظیم نشده (factory sell above <n>)")
                return
            await factory_sell_flow(chat, mid)
            await factory_home(chat, mid)
            m = await client.get_messages(chat, ids=mid)
            st = parse_factory_storage(m.raw_text) if m else None
            if not st or st[0] == st[1]:
                print("کارخونه: انبار هنوز پره؛ بعداً دوباره بررسی میشه")
                return
        await factory_produce_flow(chat, mid)


def schedule_factory_check(delay: float):
    global factory_timer
    if factory_timer and factory_timer is not asyncio.current_task():
        factory_timer.cancel()
    factory_timer = asyncio.create_task(_factory_timer(delay))


async def _factory_timer(delay: float):
    try:
        await asyncio.sleep(delay)
        if factory_enabled:
            await factory_session()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"کارخونه (تایمر): {e}")


async def factory_loop():
    try:
        while True:
            if factory_enabled and _factory_target_chat() is not None:
                try:
                    await factory_session()
                except Exception as e:
                    print(f"خطا توی کارخونه: {e}")
            await asyncio.sleep(factory_interval_seconds)
    except asyncio.CancelledError:
        pass


def start_factory_loop():
    global factory_task
    if factory_task:
        factory_task.cancel()
    factory_task = asyncio.create_task(factory_loop())


def stop_factory_loop():
    global factory_task, factory_timer
    if factory_task:
        factory_task.cancel()
        factory_task = None
    if factory_timer:
        factory_timer.cancel()
        factory_timer = None


def factory_status_text() -> str:
    sell = f"قیمت بازار {factory_sell_min:,} یا بیشتر" if factory_sell_min is not None else "خاموش (factory sell above <n>)"
    cost = f"حداکثر {factory_cost_max:,}" if factory_cost_max else "بدون محدودیت"
    on = "روشن ✅" if factory_enabled else "خاموش ❌"
    return (f"🏭 کارخونه میویی: {on}\n• فروش محصول: {sell}\n• هزینه‌ی ساخت هر عدد: {cost}\n"
            f"• تولید (به ترتیب اولویت): " + "، ".join(f"{t['item']} از {t['cat']}" for t in factory_targets) + f" | {factory_percent}%\n"
            f"• بررسی هر {factory_interval_seconds/60:g} دقیقه")


def _resolve_category(arg: str):
    arg = arg.strip()
    name = FACTORY_CATEGORIES.get(arg)
    if not name:
        key = _fa(arg).replace("تولیدی", "").replace(" ", "")
        name = next((v for v in FACTORY_CATEGORIES.values() if v.replace(" ", "") == key), None)
    return name


def _parse_item(arg: str):
    arg = arg.strip()
    if not arg:
        return None
    return int(arg) if arg.isdigit() and 1 <= int(arg) <= 9 else arg


def _parse_factory_target(arg: str):
    """«ستاره از تکنولوژی پیشرفته» ، «⭐ 6» ، «2 تکنولوژی پیشرفته»"""
    item_txt = cat_txt = None
    for sep in (" از ", " in "):
        if sep in arg:
            item_txt, cat_txt = arg.split(sep, 1)
            break
    if item_txt is None:
        parts = arg.split(None, 1)
        if len(parts) < 2:
            return None
        item_txt, cat_txt = parts
    cat = _resolve_category(cat_txt)
    item = _parse_item(item_txt)
    return {"cat": cat, "item": item} if cat and item is not None else None


def apply_factory_command(sub: str):
    """تنظیم‌های کارخونه (بدون نیاز به چت)؛ متن پاسخ فارسی یا None اگه دستور شناخته نشد"""
    global factory_sell_min, factory_cost_max, factory_targets, factory_percent, factory_interval_seconds, factory_chat_id
    sub = sub.strip()
    if sub.startswith("chat"):
        raw = sub[len("chat"):].strip()
        if not raw.lstrip("-").isdigit():
            return "مثال: factory chat -1001234567890   (آیدی عددی گروهی که میویی توشه)"
        factory_chat_id = int(raw)
        return f"گروه کارخونه روی {factory_chat_id} تنظیم شد ✅"
    if sub == "sell off":
        factory_sell_min = None
        return "فروش محصول کارخونه غیرفعال شد ❌"
    if sub.startswith("sell above"):
        n = parse_int(sub[len("sell above"):].strip())
        if n is None:
            return "مثال: factory sell above 70   (قیمت بازار)"
        factory_sell_min = n
        return f"فروش محصول فعال شد ✅ — وقتی انبار پره و قیمت بازار {n:,} یا بیشتر باشه محصول فروخته میشه"
    if sub == "cost off":
        factory_cost_max = 0
        return "محدودیت هزینه‌ی ساخت برداشته شد ✅"
    if sub.startswith("cost below"):
        n = parse_int(sub[len("cost below"):].strip())
        if n is None or n <= 0:
            return "مثال: factory cost below 50   (هزینه‌ی ساخت هر عدد)"
        factory_cost_max = n
        return f"حد هزینه‌ی ساخت تنظیم شد ✅ — فقط وقتی هزینه‌ی هر عدد {n:,} یا کمتر باشه تولید شروع میشه"
    if sub.startswith("make"):
        arg = sub[len("make"):].strip()
        if arg in ("list", ""):
            return "اولویت تولید:\n" + "\n".join(f"{i + 1}. {t['item']} از {t['cat']}" for i, t in enumerate(factory_targets)) + "\n\nمثال: factory make ستاره از تکنولوژی پیشرفته"
        if arg in ("clear", "reset"):
            factory_targets = [{"cat": "تکنولوژی پیشرفته", "item": 1}]
            return "لیست تولید به حالت پیش‌فرض برگشت ✅ (اولین محصول از تکنولوژی پیشرفته)"
        add = False
        if arg.startswith("add "):
            add, arg = True, arg[4:].strip()
        t = _parse_factory_target(arg)
        if not t:
            return ("مثال: factory make ستاره از تکنولوژی پیشرفته\nیا: factory make ⭐ 6\nیا: factory make 2 تکنولوژی پیشرفته\n"
                    "برای چند اولویت: factory make add موشک از هواپیما")
        if add:
            factory_targets.append(t)
        else:
            factory_targets = [t]
        return ("به لیست اولویت اضافه شد ✅" if add else "تولید تنظیم شد ✅") + f" — {t['item']} از دسته‌ی «{t['cat']}»"
    if sub.startswith("category"):
        name = _resolve_category(sub[len("category"):].strip())
        if not name:
            return "دسته‌ها: 1 آبنبات | 2 کیک | 3 تکنولوژی | 4 خودرو | 5 هواپیما | 6 تکنولوژی پیشرفته\nمثال: factory category 6"
        factory_targets[0]["cat"] = name
        return f"دسته‌ی تولید روی «{name}» تنظیم شد ✅"
    if sub.startswith("item"):
        item = _parse_item(sub[len("item"):].strip())
        if item is None:
            return "مثال: factory item ستاره   یا   factory item 1   (شماره از سمت راست)"
        factory_targets[0]["item"] = item
        return f"محصول «{item}» از دسته‌ی «{factory_targets[0]['cat']}» انتخاب میشه ✅"
    if sub.startswith("percent"):
        n = parse_int(sub[len("percent"):].strip().rstrip("%"))
        if n not in (25, 50, 75, 100):
            return "مثال: factory percent 100   (فقط 25 / 50 / 75 / 100)"
        factory_percent = n
        return f"درصد تولید روی {n}% تنظیم شد ✅"
    if sub.startswith("interval"):
        seconds = parse_duration_seconds(sub[len("interval"):].strip())
        if seconds is None or seconds < 300:
            return "مثال: factory interval 60  (دقیقه)  یا  factory interval 2h  (حداقل ۵ دقیقه)"
        factory_interval_seconds = seconds
        return f"کارخونه هر {seconds/60:g} دقیقه بررسی میشه ✅"
    return None


def factory_settings_dict() -> dict:
    return {"factory_enabled": factory_enabled, "factory_chat_id": factory_chat_id, "factory_sell_min": factory_sell_min,
            "factory_cost_max": factory_cost_max, "factory_targets": factory_targets,
            "factory_percent": factory_percent, "factory_interval_seconds": factory_interval_seconds,
            "factory_busy_until": factory_busy_until}


def apply_factory_settings(d: dict):
    global factory_enabled, factory_chat_id, factory_sell_min, factory_cost_max, factory_targets
    global factory_percent, factory_interval_seconds, factory_busy_until
    factory_enabled = d.get("factory_enabled", factory_enabled)
    factory_chat_id = d.get("factory_chat_id", factory_chat_id)
    factory_sell_min = d.get("factory_sell_min", factory_sell_min)
    factory_cost_max = d.get("factory_cost_max", factory_cost_max)
    if d.get("factory_targets"):
        factory_targets = d["factory_targets"]
    factory_percent = d.get("factory_percent", factory_percent)
    factory_interval_seconds = d.get("factory_interval_seconds", factory_interval_seconds)
    factory_busy_until = d.get("factory_busy_until", factory_busy_until)


# ---------- ماینر میویی + بانک میویی ----------
MINER_TRIGGER_TEXT = "ماینر میو"
BANK_TRIGGER_TEXT = "بانک میویی"
MINER_CURS = ("USDT", "TON", "BTC", "ETH", "SOL")
miner_cfg = {"enabled": False, "chat": None, "interval": 3600, "convert_cur": "USDT", "convert_pct": 100,
             "sell_enabled": True, "sell_cur": "USDT", "sell_pct": 100}
bank_cfg = {"enabled": False, "chat": None, "min": None, "margin": 1000}
miner_lock = asyncio.Lock()
bank_lock = asyncio.Lock()
miner_task = None
miner_sell_timer = None
bank_last = 0.0
_CANCEL_SYMS = ("❌", "✖", "✕", "×", "✗", "❎", "🚫")


def _tofloat(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def parse_fa_duration(text: str):
    """«1 ساعت 13 دقیقه 51 ثانیه» → ثانیه (یا None)"""
    t = _clean(text)
    tot, found = 0, False
    for unit, mult in (("ساعت", 3600), ("دقیقه", 60), ("ثانیه", 1)):
        m = re.search(r"(\d+)\s*" + unit, t) or re.search(unit + r"\s*(\d+)", t)
        if m:
            tot += int(m.group(1)) * mult
            found = True
    return tot if found else None


def _miner_chat():
    return miner_cfg["chat"] or farm_chat_id


def _miner_is_main(m) -> bool:
    return any(_fa(b.text) in ("تبدیل توکن", "مدیریت برق", "کیف پول") for b in _flat_buttons(m))


def _cur_btn(m, cur):
    return next((b for b in _flat_buttons(m) if (b.text or "").strip().upper() == cur), None)


def _has_cur_buttons(m) -> bool:
    return any((b.text or "").strip().upper() in MINER_CURS for b in _flat_buttons(m))


def _pct_btn(m, pct):
    for b in _flat_buttons(m):
        t = _clean(b.text or "")
        if "توکن" in t:
            continue
        if re.sub(r"\D", "", t) == str(pct) and re.sub(r"[\d%\s]", "", t) == "" or (re.sub(r"\D", "", t) == str(pct) and "%" in t):
            return b
    return None


def _first_confirm(m):
    btns = _flat_buttons(m)
    good = [b for b in btns if not any(c in (b.text or "") for c in _CANCEL_SYMS)]
    return (good or btns or [None])[0]


async def miner_home(chat_id: int, mid: int) -> bool:
    for _ in range(6):
        m = await client.get_messages(chat_id, ids=mid)
        if m and _miner_is_main(m):
            return True
        if not await click_back(chat_id, mid):
            return False
        await asyncio.sleep(0.8)
    m = await client.get_messages(chat_id, ids=mid)
    return bool(m and _miner_is_main(m))


async def miner_convert_flow(chat_id: int, mid: int) -> bool:
    """تبدیل توکن → ارز → درصد → تأیید ✓ → BK"""
    cur, pct = miner_cfg["convert_cur"], miner_cfg["convert_pct"]
    m = await client.get_messages(chat_id, ids=mid)
    if not m or not _miner_is_main(m):
        if not await miner_home(chat_id, mid):
            return False
        m = await client.get_messages(chat_id, ids=mid)
    b = next((x for x in _flat_buttons(m) if _fa(x.text) == "تبدیل توکن"), None)
    if not b or not await safe_click(b):
        print("ماینر: دکمه‌ی تبدیل توکن پیدا نشد")
        return False
    pg = await wait_msg(chat_id, mid, lambda x: not _miner_is_main(x), 8)
    if not pg:
        print("ماینر: صفحه‌ی تبدیل باز نشد")
        return False
    t = _clean(pg.raw_text)
    if "در حال آپلود" in t or "باقی مانده" in t:
        secs = parse_fa_duration(t) or 3600
        print(f"ماینر: تبدیل قبلی در جریانه؛ {int(secs / 60)} دقیقه‌ی دیگه تموم میشه")
        schedule_miner_sell(secs + 120)
        await miner_home(chat_id, mid)
        return False
    cb = _cur_btn(pg, cur) or None
    if not cb:
        pg = await wait_msg(chat_id, mid, _has_cur_buttons, 6) or pg
        cb = _cur_btn(pg, cur)
    if not cb:
        print(f"ماینر: دکمه‌ی {cur} پیدا نشد")
        await miner_home(chat_id, mid)
        return False
    await safe_click(cb)
    pp = await wait_msg(chat_id, mid, lambda x: "موجودی" in _clean(x.raw_text) and _pct_btn(x, pct) is not None, 8)
    if not pp:
        print(f"ماینر: صفحه‌ی درصد باز نشد یا دکمه‌ی {pct}% نبود")
        await miner_home(chat_id, mid)
        return False
    tt = _clean(pp.raw_text)
    bal = _tofloat((re.search(r"موجودی[^\d\n]*(\d[\d,]*\.?\d*)", tt) or [None, None])[1])
    mn = _tofloat((re.search(r"حداقل[^\d\n]*(\d[\d,]*\.?\d*)", tt) or [None, None])[1])
    if bal is not None and mn is not None and bal * pct / 100 < mn:
        print(f"ماینر: موجودی {bal:,.0f} توکن برای تبدیل {pct}% کافی نیست (حداقل {mn:,.0f})")
        await miner_home(chat_id, mid)
        return False
    await safe_click(_pct_btn(pp, pct))
    cf = await wait_msg(chat_id, mid, lambda x: "اطمینان" in _clean(x.raw_text) and bool(x.buttons), 8)
    if not cf:
        print("ماینر: صفحه‌ی تأیید تبدیل باز نشد")
        await miner_home(chat_id, mid)
        return False
    secs = parse_fa_duration(cf.raw_text) or 3600
    ok = _first_confirm(cf)
    if not ok or not await safe_click(ok):
        await miner_home(chat_id, mid)
        return False
    await wait_msg(chat_id, mid, lambda x: "اطمینان" not in _clean(x.raw_text), 8)
    print(f"ماینر: تبدیل {pct}% توکن به {cur} شروع شد ✅ (حدود {int(secs / 60)} دقیقه)")
    schedule_miner_sell(secs + 120)
    await miner_home(chat_id, mid)
    return True


async def miner_sell_flow(chat_id: int, mid: int) -> bool:
    """بازار ارز → ارز → درصد فروش → تأیید ✓ → صبر برای «فروخته شد» → BK"""
    cur, pct = miner_cfg["sell_cur"], miner_cfg["sell_pct"]
    m = await client.get_messages(chat_id, ids=mid)
    if not m or not _miner_is_main(m):
        if not await miner_home(chat_id, mid):
            return False
        m = await client.get_messages(chat_id, ids=mid)
    b = next((x for x in _flat_buttons(m) if _fa(x.text) == "بازار ارز"), None)
    if not b or not await safe_click(b):
        print("ماینر: دکمه‌ی بازار ارز پیدا نشد")
        return False
    pg = await wait_msg(chat_id, mid, _has_cur_buttons, 8)
    cb = _cur_btn(pg, cur) if pg else None
    if not cb:
        print(f"ماینر: دکمه‌ی {cur} توی بازار پیدا نشد")
        await miner_home(chat_id, mid)
        return False
    await safe_click(cb)
    pp = await wait_msg(chat_id, mid, lambda x: "موجودی" in _clean(x.raw_text) and _pct_btn(x, pct) is not None, 8)
    if not pp:
        print(f"ماینر: صفحه‌ی درصد فروش باز نشد یا دکمه‌ی {pct}% نبود")
        await miner_home(chat_id, mid)
        return False
    tt = _clean(pp.raw_text)
    bal = _tofloat((re.search(r"موجودی[^\d\n]*(\d[\d,]*\.?\d*)", tt) or [None, None])[1])
    mn = _tofloat((re.search(r"حداقل[^\d\n]*(\d[\d,]*\.?\d*)", tt) or [None, None])[1])
    print(f"ماینر: موجودی کیف پول {bal} {cur} | حداقل فروش {mn} | درصد فروش {pct}")
    if bal is not None and mn is not None and bal * pct / 100 < mn:
        print("ماینر: موجودی برای فروش کافی نیست")
        await miner_home(chat_id, mid)
        return False
    await safe_click(_pct_btn(pp, pct))
    cf = await wait_msg(chat_id, mid, lambda x: "اطمینان" in _clean(x.raw_text) and bool(x.buttons), 8)
    if not cf:
        print("ماینر: صفحه‌ی تأیید فروش باز نشد")
        await miner_home(chat_id, mid)
        return False
    ok = _first_confirm(cf)
    if not ok or not await safe_click(ok):
        await miner_home(chat_id, mid)
        return False
    done = await wait_msg(chat_id, mid, lambda x: "فروخته" in _clean(x.raw_text), 10)
    print("ماینر: ارز فروخته شد ✅" if done else "ماینر: تأیید فروش ارسال شد (پیام «فروخته شد» دیده نشد)")
    await wait_msg(chat_id, mid, lambda x: "فروخته" not in _clean(x.raw_text) and bool(x.buttons), 12)
    await miner_home(chat_id, mid)
    return True


async def _miner_open(chat: int):
    sent = await client.send_message(chat, MINER_TRIGGER_TEXT)
    fmsg = await wait_reply_to(chat, sent.id)
    if not fmsg:
        print("ماینر: پاسخ ماینر نیومد")
        return None
    return fmsg.id


async def miner_session():
    chat = _miner_chat()
    if chat is None:
        print("ماینر: گروه تنظیم نشده؛ توی گروه بنویس: miner on")
        return
    async with miner_lock:
        mid = await _miner_open(chat)
        if mid:
            await miner_convert_flow(chat, mid)


async def miner_sell_session():
    chat = _miner_chat()
    if chat is None:
        print("ماینر: گروه تنظیم نشده")
        return
    if not miner_cfg["sell_enabled"]:
        print("ماینر: فروش خاموشه (miner sell on)")
        return
    async with miner_lock:
        mid = await _miner_open(chat)
        if mid:
            await miner_sell_flow(chat, mid)


def schedule_miner_sell(delay: float):
    global miner_sell_timer
    if miner_sell_timer and miner_sell_timer is not asyncio.current_task():
        miner_sell_timer.cancel()
    miner_sell_timer = asyncio.create_task(_miner_sell_timer(delay))


async def _miner_sell_timer(delay: float):
    try:
        await asyncio.sleep(delay)
        if miner_cfg["enabled"]:
            await miner_sell_session()
            await miner_session()   # بعد از فروش، تبدیل بعدی
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"ماینر (تایمر): {e}")


async def miner_loop():
    try:
        while True:
            if miner_cfg["enabled"] and _miner_chat() is not None:
                try:
                    await miner_session()
                except Exception as e:
                    print(f"خطا توی ماینر: {e}")
            await asyncio.sleep(miner_cfg["interval"])
    except asyncio.CancelledError:
        pass


def start_miner_loop():
    global miner_task
    if miner_task:
        miner_task.cancel()
    miner_task = asyncio.create_task(miner_loop())


def stop_miner_loop():
    global miner_task, miner_sell_timer
    for t in (miner_task, miner_sell_timer):
        if t:
            t.cancel()
    miner_task = miner_sell_timer = None


def miner_status_text() -> str:
    c = miner_cfg
    sell = f"{c['sell_cur']} با {c['sell_pct']}%" if c["sell_enabled"] else "خاموش"
    return (f"⛏ ماینر میویی: {'روشن ✅' if c['enabled'] else 'خاموش ❌'}\\n• تبدیل توکن: {c['convert_cur']} با {c['convert_pct']}%\\n"
            f"• فروش ارز: {sell}\\n• بررسی هر {c['interval'] / 60:g} دقیقه\\n• گروه: {_miner_chat()}")


def apply_miner_command(sub: str):
    """تنظیم‌های ماینر؛ متن پاسخ فارسی یا None"""
    toks = sub.strip().lower().split()
    if not toks:
        return None
    c = miner_cfg

    def pct_of(ts):
        for x in ts:
            if x.rstrip("%").isdigit():
                return int(x.rstrip("%"))
        return None
    up = [x.upper() for x in toks]
    if toks[0] == "sell":
        rest, rup = toks[1:], up[1:]
        if rest == ["off"]:
            c["sell_enabled"] = False
            return "فروش ارز ماینر غیرفعال شد ❌"
        if rest == ["on"]:
            c["sell_enabled"] = True
            return f"فروش ارز ماینر فعال شد ✅ ({c['sell_cur']} با {c['sell_pct']}%)"
        cur = next((x for x in rup if x in MINER_CURS), None)
        pct = pct_of(rest)
        if cur is None and pct is None:
            return "مثال: miner sell usdt 100   (ارز + درصد فروش)   یا   miner sell 50   یا   miner sell off"
        if pct is not None and pct not in (25, 50, 75, 100):
            return "درصد فقط 25 / 50 / 75 / 100 میشه"
        if cur:
            c["sell_cur"] = cur
        if pct is not None:
            c["sell_pct"] = pct
        c["sell_enabled"] = True
        return f"فروش ارز تنظیم شد ✅ — {c['sell_cur']} با {c['sell_pct']}%"
    if toks[0] == "percent":
        pct = pct_of(toks[1:])
        if pct not in (25, 50, 75, 100):
            return "مثال: miner percent 100   (فقط 25 / 50 / 75 / 100)"
        c["convert_pct"] = pct
        return f"درصد تبدیل توکن روی {pct}% تنظیم شد ✅"
    if toks[0] == "chat":
        raw = toks[1] if len(toks) > 1 else ""
        if not raw.lstrip("-").isdigit():
            return "مثال: miner chat -1001234567890"
        c["chat"] = int(raw)
        return f"گروه ماینر روی {c['chat']} تنظیم شد ✅"
    if toks[0] == "interval":
        seconds = parse_duration_seconds(" ".join(toks[1:]))
        if seconds is None or seconds < 300:
            return "مثال: miner interval 60  (دقیقه)  یا  miner interval 2h   (حداقل ۵ دقیقه)"
        c["interval"] = seconds
        return f"ماینر هر {seconds / 60:g} دقیقه بررسی میشه ✅"
    if toks[0] == "convert":
        toks, up = toks[1:], up[1:]
    cur = next((x for x in up if x in MINER_CURS), None)
    if cur is None and toks[:1] != ["percent"]:
        return None
    pct = pct_of(toks)
    if pct is not None and pct not in (25, 50, 75, 100):
        return "درصد فقط 25 / 50 / 75 / 100 میشه"
    if cur:
        c["convert_cur"] = cur
    if pct is not None:
        c["convert_pct"] = pct
    return f"تبدیل توکن روی {c['convert_cur']} با {c['convert_pct']}% تنظیم شد ✅"


# ---- بانک ----
async def bank_session(balance: int):
    """میوپوینت‌ها از حد بیشتره: بانک میویی → واریز → ارسال مبلغ (ریپلای) → ✓ → BK"""
    global bank_last
    chat = bank_cfg["chat"] or farm_chat_id
    if chat is None:
        print("بانک: گروه تنظیم نشده؛ bank chat <id>")
        return
    amount = ((balance - bank_cfg["margin"]) // 1000) * 1000
    if amount <= 0:
        return
    async with bank_lock:
        if time.time() - bank_last < 90:
            return
        bank_last = time.time()
        sent = await client.send_message(chat, BANK_TRIGGER_TEXT)
        pm = await wait_reply_to(chat, sent.id)
        if not pm:
            print("بانک: پاسخ بانک نیومد")
            return
        mid = pm.id
        b = next((x for x in _flat_buttons(pm) if _fa(x.text) == "واریز"), None)
        if not b or not await safe_click(b):
            print("بانک: دکمه‌ی واریز پیدا نشد")
            return
        pg = await wait_msg(chat, mid, lambda x: "ارسال" in _clean(x.raw_text) or "جواب" in _clean(x.raw_text), 8)
        if not pg:
            print("بانک: صفحه‌ی واریز باز نشد")
            return
        amsg = await client.send_message(chat, str(amount), reply_to=mid)
        cid, cmsg = mid, None
        for _ in range(12):
            await asyncio.sleep(0.8)
            m = await client.get_messages(chat, ids=mid)
            if m and "اطمینان" in _clean(m.raw_text) and m.buttons:
                cmsg = m
                break
            async for x in client.iter_messages(chat, limit=15):
                if x.id > mid and not x.out and x.buttons and "اطمینان" in _clean(x.raw_text) and "واریز" in _clean(x.raw_text):
                    cmsg = x
                    break
            if cmsg:
                break
        if not cmsg:
            print("بانک: صفحه‌ی تأیید واریز نیومد")
            return
        cid = cmsg.id
        ok = _first_confirm(cmsg)
        if not ok or not await safe_click(ok):
            return
        done = await wait_msg(chat, cid, lambda x: "با موفقیت" in _clean(x.raw_text), 10)
        print(f"بانک: {amount:,} میو پوینت واریز شد ✅" if done else "بانک: تأیید واریز ارسال شد (پیام موفقیت دیده نشد)")
        await click_back(chat, cid)


def bank_status_text() -> str:
    c = bank_cfg
    return (f"🏦 بانک میویی: {'روشن ✅' if c['enabled'] else 'خاموش ❌'}\\n"
            f"• واریز وقتی میو پوینت هات از {c['min']:,} بیشتر باشه" if c["min"] else f"🏦 بانک میویی: {'روشن' if c['enabled'] else 'خاموش'} — حد واریز تنظیم نشده (bank above <n>)") + \
           f"\\n• کم‌کردن از موجودی: {c['margin']:,}\\n• گروه: {c['chat'] or farm_chat_id}"


def apply_bank_command(sub: str):
    toks = sub.strip().lower().split()
    c = bank_cfg
    if toks[:1] == ["above"] or toks[:1] == ["min"]:
        n = parse_int(" ".join(toks[1:]))
        if not n:
            return "مثال: bank above 3000000   (یا 3m)"
        c["min"] = n
        c["enabled"] = True
        return f"بانک فعال شد ✅ — وقتی میو پوینت هات از {n:,} بیشتر باشه، واریز به بانک انجام میشه"
    if toks[:1] == ["margin"]:
        n = parse_int(" ".join(toks[1:]))
        if n is None:
            return "مثال: bank margin 1000   (چقدر کمتر از موجودی واریز بشه)"
        c["margin"] = n
        return f"مقدار کم‌کردن از موجودی روی {n:,} تنظیم شد ✅"
    if toks[:1] == ["chat"]:
        raw = toks[1] if len(toks) > 1 else ""
        if not raw.lstrip("-").isdigit():
            return "مثال: bank chat -1001234567890"
        c["chat"] = int(raw)
        return f"گروه بانک روی {c['chat']} تنظیم شد ✅"
    if toks == ["on"]:
        c["enabled"] = True
        return "واریز خودکار به بانک فعال شد ✅" if c["min"] else "فعال شد ✅ ولی حد واریز تنظیم نشده: bank above <n>"
    if toks == ["off"]:
        c["enabled"] = False
        return "واریز خودکار به بانک غیرفعال شد ❌"
    if toks == ["status"]:
        return bank_status_text()
    return None


@client.on(events.NewMessage(incoming=True))
async def meow_balance_watcher(event):
    """بعد از «میو» اگه «میو پوینت هات» از حد بانک بیشتر بود → واریز به بانک"""
    if not bank_cfg["enabled"] or not bank_cfg["min"]:
        return
    t = _clean(event.raw_text or "")
    m = re.search(r"میو\s*پوینت\s*هات[^\d\n]*(\d[\d,]*)", t)
    if not m or "گرفتی" not in t:
        return
    try:
        sender = await event.get_sender()
        if not getattr(sender, "bot", False):
            return
        rep = await event.get_reply_message()
        if not rep or not rep.out:
            return
    except Exception:
        return
    bal = int(m.group(1).replace(",", ""))
    if bal >= bank_cfg["min"]:
        print(f"بانک: موجودی {bal:,} از حد {bank_cfg['min']:,} بیشتره → واریز")
        asyncio.create_task(bank_session(bal))


@client.on(events.NewMessage(incoming=True))
async def meowie_miner_pm(event):
    """وقتی ربات میویی توی پیوی میگه تبدیل توکن تموم شد → فروش ارز توی بازار"""
    if not event.is_private or not miner_cfg["enabled"]:
        return
    t = _clean(normalize(event.raw_text or ""))
    if "ماینر" not in t or not any(w in t for w in ("تبدیل", "آپلود")) or not any(
            w in t for w in ("به پایان رسید", "تکمیل", "انجام شد", "موفقیت", "کامل")):
        return
    try:
        sender = await event.get_sender()
        if not getattr(sender, "bot", False):
            return
    except Exception:
        return
    print("پیام پایان تبدیل توکن از میویی رسید → فروش ارز")
    global miner_sell_timer
    if miner_sell_timer and miner_sell_timer is not asyncio.current_task():
        miner_sell_timer.cancel()
    try:
        await asyncio.sleep(3)
        await miner_sell_session()
        await miner_session()
    except Exception as e:
        print(f"ماینر (پیام): {e}")


SETTINGS_FILE = f"{session_name}_settings.json"


def save_settings():
    try:
        data = {
            "feed_rules": {str(k): v for k, v in feed_rules.items()},
            "fish_sell_min": fish_sell_min, "fish_sell_enabled": fish_sell_enabled,
            "fish_feed_max": fish_feed_max, "fish_cook_enabled": fish_cook_enabled,
            "fish_cook_min": fish_cook_min, "feed_enabled": feed_enabled,
            "rescue_enabled": rescue_enabled, "rescue_max_tries": rescue_max_tries,
            "farm_chat_id": farm_chat_id, "feed_hunger_texts": feed_hunger_texts, "v": 2,
        }
        data.update(factory_settings_dict())
        data["miner"] = miner_cfg
        data["bank"] = bank_cfg
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f"ذخیره‌ی تنظیمات: {e}")


def load_settings():
    global fish_sell_min, fish_sell_enabled, fish_feed_max, fish_cook_enabled, fish_cook_min
    global feed_enabled, rescue_enabled, rescue_max_tries, farm_chat_id
    if not os.path.exists(SETTINGS_FILE):
        return
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        apply_factory_settings(d)
        miner_cfg.update(d.get("miner", {}))
        bank_cfg.update(d.get("bank", {}))
        feed_rules.clear()
        feed_rules.update({int(k): int(v) for k, v in d.get("feed_rules", {}).items()})
        fish_sell_min = d.get("fish_sell_min", fish_sell_min)
        fish_sell_enabled = d.get("fish_sell_enabled", fish_sell_enabled)
        if d.get("v", 1) >= 2:   # نسخه‌های قبلی حد ۲۰۰۰ رو ذخیره کرده بودن؛ نادیده گرفته میشه
            fish_feed_max = d.get("fish_feed_max", fish_feed_max)
        fish_cook_enabled = d.get("fish_cook_enabled", fish_cook_enabled)
        fish_cook_min = d.get("fish_cook_min", fish_cook_min)
        feed_enabled = d.get("feed_enabled", feed_enabled)
        rescue_enabled = d.get("rescue_enabled", rescue_enabled)
        rescue_max_tries = d.get("rescue_max_tries", rescue_max_tries)
        if d.get("feed_hunger_texts"):
            feed_hunger_texts[:] = d["feed_hunger_texts"]
        if farm_chat_id is None and d.get("farm_chat_id"):
            farm_chat_id = d["farm_chat_id"]
        print(f"تنظیمات ذخیره‌شده خونده شد (قانون‌های غذادهی: {feed_rules})")
    except Exception as e:
        print(f"خواندن تنظیمات: {e}")


async def settings_saver_loop():
    """هر ۱۵ ثانیه تنظیمات رو ذخیره می‌کنه تا بعد از ری‌استارت از دست نره"""
    while True:
        await asyncio.sleep(15)
        save_settings()



async def feed_loop():
    """هر feed_interval_seconds یک بار «پیشی» می‌فرسته، اگه گرسنه بود فلوی غذا دادن رو اجرا می‌کنه"""
    try:
        while True:
            try:
                if farm_chat_id is not None and feed_enabled:
                    sent = await client.send_message(farm_chat_id, MEOWIE_TRIGGER_TEXT)
                    reply = await wait_reply_to(farm_chat_id, sent.id, need_buttons=False)
                    if reply:
                        need, room = feed_decision(reply.raw_text)
                        if need:
                            await feed_cat_flow(farm_chat_id, room)
            except Exception as e:
                print(f"خطا توی چک غذا: {e}")
            await asyncio.sleep(feed_interval_seconds or 3600)
    except asyncio.CancelledError:
        pass


def start_feed_loop():
    global feed_task
    if feed_task:
        feed_task.cancel()
    feed_task = asyncio.create_task(feed_loop())


def stop_feed_loop():
    global feed_task
    if feed_task:
        feed_task.cancel()
        feed_task = None


async def meowie_farm_once(chat_id: int | None = None):
    target = chat_id if chat_id is not None else farm_chat_id
    if target is None:
        return
    sent = await client.send_message(target, MEOWIE_TRIGGER_TEXT)
    await click_farm_button(target, sent.id)


async def farm_loop():
    try:
        while True:
            try:
                await meowie_farm_once()
            except Exception as e:
                print(f"خطا توی فارم میویی: {e}")
            await asyncio.sleep(farm_interval_seconds)
    except asyncio.CancelledError:
        pass


async def toggle_farm() -> str:
    global farm_task
    if farm_task:
        return "فارم میویی فعال می‌باشد 🐱 (از قبل روشن بود)"
    farm_task = asyncio.create_task(farm_loop())
    return f"فارم میویی فعال شد ✅ (هر {farm_interval_seconds/60:g} دقیقه، توی گروه {farm_chat_id})"


async def untoggle_farm() -> str:
    global farm_task
    if farm_task:
        farm_task.cancel()
        farm_task = None
        return "فارم میویی غیرفعال شد ❌"
    return "فارم میویی فعال نبود"


# ---------- ابزار حذف همه‌ی پیام‌های خودِ اکانت در یک چت ----------
async def resolve_entity(raw: str):
    """آیدی عددی، یوزرنیم یا لینک کانال/چت رو به entity تبدیل می‌کنه"""
    raw = raw.strip()
    if raw.lstrip("-").isdigit():
        n = int(raw)
        try:
            return await client.get_entity(n)
        except Exception:
            if str(n).startswith("-100"):
                return await client.get_entity(PeerChannel(int(str(n)[4:])))
            return await client.get_entity(PeerChannel(abs(n)))
    return await client.get_entity(raw)


async def resolve_chat_id(raw: str) -> int:
    """آیدی عددی، یوزرنیم یا لینک رو به chat_id تبدیل می‌کنه"""
    raw = raw.strip()
    if raw.lstrip("-").isdigit():
        return int(raw)
    entity = await client.get_entity(raw)
    return entity.id


async def delete_all_my_messages(chat_id: int) -> int:
    ids = []
    async for m in client.iter_messages(chat_id, from_user="me"):
        ids.append(m.id)
    if ids:
        await client.delete_messages(chat_id, ids)
    return len(ids)


HELP_TEXT = """📖 راهنمای کامل سلف‌بات
(دستورها انگلیسی‌اند، توضیح‌ها فارسی. دستورها رو از خودِ اکانت سلف بفرست.)

🐱 میو
meow on — فعال‌سازی میو توی همین چت (پیش‌فرض هر ۱۰ دقیقه)
meow on 5 — میو هر ۵ دقیقه
meow off — خاموش کردن میو توی همین چت
meow +5 — پنج دقیقه به زمان پیش‌فرض میو اضافه می‌کنه
meow -5 — پنج دقیقه از زمان پیش‌فرض کم می‌کنه

🕐 ساعت خودکار
clock bio on / clock bio off — ساعت و تاریخ شمسی روی بیو
clock bio reverse on / off — فقط اگه ساعت بیو بعد از آپدیت هنوز برعکس بود: ساعت رو از قبل برعکس می‌نویسه تا درست دیده بشه
clock bio style — نمایش سبک‌های بیو؛ clock bio style 3 — انتخاب سبک (۱ تا ۵)
clock name on / clock name off — ساعت روی نام خانوادگی
clock font list — نمایش همه‌ی فونت‌های ساعت
clock bio font <name> — فونت ساعت بیو، مثلاً: clock bio font keycap
clock name font <name> — فونت ساعت نام خانوادگی، مثلاً: clock name font circled
(فونت بیو و نام جدا از هم تنظیم میشن)

🌙 افک (پاسخ خودکار)
afk on — روشن کردن با پیام پیش‌فرض
afk on <message> — روشن کردن با پیام دلخواه، مثلاً: afk on خوابم
afk off — خاموش کردن
(فقط توی پیوی و فقط یک بار به هر نفر جواب میده؛ به ربات‌ها جواب نمیده)

🐾 فارم خودکار میویی
farm on — روشن کردن؛ اگه گروهی تنظیم نشده باشه آیدی عددی یا لینک گروه رو می‌پرسه
farm off — خاموش کردن
farm now — همین الان یک بار فارم کن
farm +5 / farm -5 — پنج دقیقه به فاصله‌ی فارم اضافه/کم می‌کنه
farm interval 30 — فاصله‌ی فارم برحسب دقیقه
farm interval 2h — فاصله‌ی فارم برحسب ساعت
(هر دور «پیشی» می‌فرسته، حداکثر ۱۵ ثانیه منتظر جواب میویی می‌مونه
و روی دکمه‌ی «برداشت میو پوینت ها» می‌زنه)
توجه: فارم باید خودِ اکانت سلف بفرسته؛ پیام اکانت مدیر توی گروه، خودش فارم نمی‌کنه.

🐈 نجات، غذا دادن، پخت و فروش ماهی
rescue on / rescue off — کلیک خودکار روی «نجات پیشی خیابونی» توی همه‌ی گروه‌هایی که عضوی، با فاصله‌ی ۳ ثانیه بین کلیک‌ها (پیش‌فرض روشن)
rescue tries 10 — حداکثر تعداد کلیک روی هر پیام نجات
feed on / feed off — غذا دادن خودکار (پیش‌فرض روشن)
feed interval 30 — هر ۳۰ دقیقه گرسنگی رو چک کن (feed interval 2h = هر ۲ ساعت)
feed interval off — برگشت به حالت «چک بعد از هر فارم»

سلف وقتی غذا میده که جلوی «شکم» یکی از متن‌های گرسنگیِ تنظیم‌شده باشه (پیش‌فرض: گشنمیو و دیگه کار نمیکنمیو)؛ عددها فقط برای تعیین جای خالی شکم و انتخاب ماهیِ مناسب خونده میشن. بعد از هر کار با دکمه‌ی BK به یخچال برمیگرده و دوباره بررسی میکنه:
  ۱) ماهی پخته با ارزش ≥ حد فروش → «فروش ماهی» (هر چی بالاتر از حد باشه فروخته میشه)
  ۲) اگه باید غذا بده → ماهی پخته‌ای که ارزش غذاییش تو جای خالی شکم جا بشه (مثلاً ۴ جا خالی → ماهی با ارزش غذایی ۴) → «بده پیشی بخوره» → «پیشی خوردش» → BK
  ۳) همه‌ی ماهی‌های خام بدون استثنا → «بپوخش» → دکمه‌ی سبز ✓ → BK؛ وقتی ربات میویی توی پیوی پیام «ماهی شما پخید» رو فرستاد، سلف توی گروه فارم یخچال رو چک میکنه (غذا دادن یا فروش)
  ۴) اگه یخچال پر نیست (مثلاً 2 / 5) → «ماهی» می‌فرسته و «بندازش تو یخچال» رو میزنه

feed text add من گشنمیووو — متن گرسنگی اضافه میکنه: اگه ربات میویی بعد از «پیشی» جلوی «شکم» این متن (یا متن‌های شبیهش، مثلاً با «و» و «.» اضافه) رو نوشت، سلف به پیشی غذا میده
feed text del <text> — حذف یک متن / feed text list — نمایش متن‌ها / feed text reset — برگشت به پیش‌فرض (گشنمیو ، دیگه کار نمیکنمیو)
(اختیاری) feed 12/7 — قانون عددی هم میشه گذاشت؛ ولی ملاک اصلی همون متن‌هاست
feed rules — نمایش قانون‌ها / feed reset — پاک کردن قانون‌ها

fish sell above 50000 — ماهی پخته‌ی با ارزش ≥ این عدد فروخته میشه (50k هم قبوله)
fish sell off / fish sell on — خاموش/روشن کردن فروش
fish feed below 2000 — ماهی پخته‌ی ارزش < این عدد به پیشی داده میشه (و ماهی خام زیر این عدد پخته میشه)
fish cook on / fish cook off — پخت همه‌ی ماهی‌های خام (پیش‌فرض روشن)
fish cook above 5000 — فقط ماهی خام با ارزش ≥ این عدد پخته بشه (fish cook above 0 = همه)
fish status — نمایش قوانین فعلی
(ماهی‌هایی که ارزششون بین این دو عدده، نه فروخته میشن نه خورانده میشن)

🔒 ذخیره‌ی عکس/ویدیوی نابودشونده
ttl on / ttl off — هر عکس/ویدیو/ویس سکرت (تایمردار یا یک‌بار‌مصرف) که کسی توی پیوی برات بفرسته، خودکار توی Saved Messages ذخیره میشه (پیش‌فرض روشن)

⛏ ماینر میویی
miner on — توی گروهی که میویی توشه بنویس؛ هر ساعت «ماینر میو» می‌فرسته و: تبدیل توکن → ارز انتخابی (دکمه) → درصد تبدیل → تأیید ✓ → BK
miner usdt (یا ton / btc / eth / sol) — ارزی که توکن‌ها بهش تبدیل بشن (میتونی با درصد: miner convert usdt 50)
miner percent 100 — چند درصد از توکن‌ها تبدیل بشه (25 / 50 / 75 / 100)
وقتی تبدیل تموم بشه (پیام ربات توی پیوی، یا بعد از زمان تقریبیِ خودِ ربات) سلف «ماینر میو» می‌فرسته → بازار ارز → ارز → درصد فروش → تأیید ✓ → صبر برای «فروخته شد» → BK
miner sell usdt 100 — ارز و درصد فروش (پیش‌فرض: USDT و 100٪) / miner sell off — خاموش کردن فروش / miner sell on / miner sell now — همین الان بفروش
miner now — همین الان تبدیل توکن / miner status — نمایش تنظیم‌ها / miner interval 60 — فاصله‌ی بررسی / miner chat -100... — گروه با آیدی عددی / miner off

🏦 بانک میویی
bank above 3000000 — بعد از «میو»، اگه «میو پوینت هات» از این عدد بیشتر بود سلف «بانک میویی» می‌فرسته → واریز → مبلغ (موجودی منهای ۱۰۰۰، رُند شده به هزار؛ مثلاً 3,878,685 → 3,877,000) با ریپلای → تأیید ✓ → BK
bank margin 1000 — چقدر کمتر از موجودی واریز بشه / bank chat -100... — گروه بانک (پیش‌فرض: گروه فارم) / bank on / bank off / bank status

🏭 کارخونه میویی
factory on — توی گروهی که میویی توشه بنویس تا فعال بشه؛ هر ساعت (قابل تغییر) «کارخونه میویی» می‌فرسته و:
  • اگه ظرفیت انبار پره (دو عدد برابر، مثل 75,000 / 75,000) → دکمه‌ی انبار → هر محصول → اگه قیمت بازار ≥ حد فروش بود «فروش محصول» (و تیک سبز، اگه خواست) → BK تا صفحه‌ی اول؛ اگه نبود فقط BK
  • اگه انبار پر نیست (مثلاً 0 / 75,000) → تولید → دسته (پیش‌فرض: تکنولوژی پیشرفته) → محصول → درصد (پیش‌فرض 100%) → اگه هزینه‌ی ساخت هر عدد از حد تو بیشتر نبود «شروع تولید»؛ بعد از تموم شدن زمان تولید دوباره بررسی میکنه
factory chat -1001234567890 — گروه کارخونه رو با آیدی عددی تعیین کن (پیش‌فرض: گروهی که factory on توش نوشته شد یا گروه فارم)
وقتی ربات میویی توی پیوی بنویسه «تولید ... به پایان رسید و به انبار منتقل شد»، سلف توی همون گروه «کارخونه میویی» می‌فرسته، انبار رو چک می‌کنه و اگه قیمت بازار به حد فروش رسیده بود می‌فروشه (و بعد دوباره تولید رو شروع میکنه)
factory off — خاموش / factory now — همین الان یه بار بررسی کن / factory status — نمایش تنظیم‌ها
factory sell above 70 — وقتی قیمت بازار ۷۰ یا بیشتر بود محصول فروخته بشه (تا این رو نذاری فروش خاموشه) / factory sell off
factory cost below 50 — فقط وقتی هزینه‌ی ساخت هر عدد ۵۰ یا کمتره تولید کن / factory cost off
factory make ستاره از تکنولوژی پیشرفته — محصول رو با شکل/اسمش از یه دسته انتخاب کن (دکمه‌های محصول اسم ندارن، شکل دارن). مثال‌ها: factory make ⭐ 6 ، factory make موشک از هواپیما ، factory make 2 تکنولوژی پیشرفته (شماره از سمت راست)
factory make add موشک از هواپیما — اضافه کردن به لیست اولویت؛ اگه اولی نشد (پیدا نشد یا هزینه زیاد بود) بعدی امتحان میشه
factory make list — نمایش اولویت‌ها / factory make clear — برگشت به پیش‌فرض (تکنولوژی پیشرفته، اولین محصول)
دسته‌ها: 1 آبنبات | 2 کیک | 3 تکنولوژی | 4 خودرو | 5 هواپیما | 6 تکنولوژی پیشرفته
شکل‌ها برای هر دسته (از راست): آبنبات 🍫🍭🎊 | کیک 🎂🍰🧁 | تکنولوژی 🤖💻📱 | خودرو 🏎🚕🚗 | هواپیما 🚀🛩✈️ | تکنولوژی پیشرفته ⭐ AI HPC
factory percent 100 — درصد پر کردن انبار: 25 / 50 / 75 / 100
factory interval 60 — هر چند دقیقه بررسی بشه (factory interval 2h = هر ۲ ساعت)

📥 ذخیره‌ی پیام‌های پیوی توی کانال
log channel <id|link> — کانال مقصد رو تنظیم و روشن می‌کنه (اکانت باید عضو/ادمین کانال باشه)
log on / log off — روشن/خاموش
(هر چیزی که کسی توی پیوی برات بفرسته — متن، ویس، عکس، ویدیو، فایل، استیکر، و حتی مدیای نابودشونده — اول خودش توی اون کانال فرستاده میشه و زیرش «پیام از:» با اسم، یوزرنیم، آیدی عددی و ساعت ارسال. هر پیوی‌ای ذخیره میشه، حتی از اکانت‌های پرمیوم، تیک‌دار و ربات‌ها؛ فقط پیام‌هایی که خودِ تلگرام می‌فرسته (مثل کدهای ورود) نادیده گرفته میشن)

🗑 حذف پیام‌ها
clean all — روی یکی از پیام‌های خودت ریپلای کن و بنویس؛ همه‌ی پیام‌های خودت توی اون چت پاک میشه
delete messages — ربات می‌پرسه: group یا private
  • group → آیدی عددی یا لینک گروه رو بفرست، پیام‌های خودت اونجا پاک میشه
  • private → آیدی عددی یا یوزرنیم طرف رو بفرست، پیام‌های خودت توی اون پیوی پاک میشه

❓ راهنما
help — فقط فهرست دستورها (بدون توضیح)
guide — همین راهنمای کامل با توضیح هر دستور

━━━━━━━━━━━━━━━━━━━━
📡 دستورهای مدیر (ADMIN)
(آیدی عددی مدیر باید توی ADMIN_IDS باشه. دستورها رو مدیر توی پیوی همین اکانت می‌فرسته)

همه‌ی دستورهای بالا (meow, afk, clock, farm, delete messages, help) توی پیوی مدیر هم کار می‌کنن.

ping — جواب میده و زمان پاسخ رو برحسب میلی‌ثانیه نشون میده
farm now — توی پیوی: فارم توی گروه تنظیم‌شده. توی یک گروه: خودِ اکانت سلف همون‌جا «پیشی» می‌فرسته و دکمه رو می‌زنه
mio online is gp — ربات آیدی عددی یا لینک گروه رو می‌پرسه (اختیاری: فاصله و عدد دقیقه، مثلاً -1001234567890 5)؛ میو توی اون گروه فعال میشه
rmg <text> — توی هر چتی که اکانت سلف هم هست بفرست؛ اکانت سلف همون متن رو توی همون چت می‌فرسته
  اگه متن یه دستور تنظیمی باشه (rescue on/off ، feed on/off ، fish sell above 28000 ، fish cook ... ، feed 15/5) متن ارسال نمیشه و فقط همون دستور اجرا میشه. مثال: rmg rescue on
  مدیر دستورهای دیگه (meow on 5 ، meow off ، clock ... ، afk ... ، farm off/+5/-5/interval ، feed interval ...) رو هم با rmg یا بدون اون می‌تونه بنویسه؛ سلف خودش اجراشون می‌کنه و پیام تأیید رو بعد ۳۰ ثانیه پاک می‌کنه.
  این دستورها رو مدیر بدون rmg هم می‌تونه بنویسه (مثلاً فقط rescue off توی گروه)؛ همه‌ی سلف‌ها اجراش می‌کنن، پیام تأیید فارسی می‌فرستن و بعد ۳۰ ثانیه پاکش می‌کنن
  اگه مدیر روی پیام یه نفر ریپلای بزنه و rmg سلام بفرسته، سلف هم روی همون پیامِ اون شخص ریپلای می‌زنه و «سلام» می‌فرسته
  مثال: rmg hi ← سلف «hi» می‌فرسته
  مثال: rmg پیشی ← سلف «پیشی» می‌فرسته و دکمه‌ی برداشت رو هم می‌زنه
پاک یا delete — روی پیامی که خودِ اکانت سلف فرستاده ریپلای کن تا همون یک پیام پاک بشه

━━━━━━━━━━━━━━
ساخته شده توسط :
@MRZverse
"""

COMMANDS_TEXT = """📖 Commands

meow on | meow on <min> | meow off | meow +5 | meow -5
clock bio on | clock bio off | clock name on | clock name off
clock bio style [1-5] | clock bio font <name> | clock name font <name>
clock font list | clock bio reverse on|off
afk on | afk on <message> | afk off
farm on | farm off | farm now | farm +5 | farm -5
farm interval <30 | 2h>
feed on | feed off | feed interval <30 | 2h> | feed interval off
feed text add <text> | feed text del <text> | feed text list | feed text reset
fish sell above <n> | fish sell on | fish sell off
fish cook on | fish cook off | fish cook above <n>
miner on | miner off | miner now | miner status | miner chat <id>
miner usdt|ton|btc|eth|sol | miner percent <25|50|75|100>
miner sell <cur> <percent> | miner sell off | miner sell now | miner interval <60 | 2h>
bank above <n> | bank on | bank off | bank margin <n> | bank chat <id> | bank status
factory on | factory off | factory now | factory status | factory chat <id>
factory sell above <n> | factory sell off
factory cost below <n> | factory cost off
factory make <shape|n> <category> | factory make add ... | factory make list\nfactory category <1-6 | name> | factory item <n | shape>
factory percent <25|50|75|100> | factory interval <30 | 2h>
fish feed below <n> | fish feed off | fish status
rescue on | rescue off | rescue tries <n>
log channel <id|link> | log on | log off
ttl on | ttl off
clean all | delete messages
help | guide

📡 Admin (DM)
ping | farm now | mio online is gp
rmg <text>
(reply) پاک / delete

توضیح کامل هر دستور: guide

ساخته شده توسط :
@MRZverse"""


async def send_help(event, edit, text=None):
    """متن راهنما از حد ۴۰۹۶ کاراکتر تلگرام بلندتره؛ تکه‌تکه می‌فرستیم"""
    chunks, cur = [], ""
    for block in (text or COMMANDS_TEXT).split("\n\n"):
        if len(cur) + len(block) + 2 > 3500 and cur:
            chunks.append(cur); cur = block
        else:
            cur = cur + "\n\n" + block if cur else block
    if cur:
        chunks.append(cur)
    if edit:
        await event.edit(chunks[0])
    else:
        await event.reply(chunks[0])
    for c in chunks[1:]:
        await client.send_message(event.chat_id, c)




# ---------- هندلر اصلی (پیام‌های خودِ اکانت) ----------
_seen_cmd: set = set()


@client.on(events.NewMessage(outgoing=True))
async def handler(event):
    global awaiting_farm_group, farm_chat_id, farm_interval_seconds, meow_default_seconds
    global delete_flow_stage, bio_digit_font, name_digit_font, rescue_enabled, feed_enabled, bio_style, bio_reverse, ttl_save_enabled, feed_interval_seconds, rescue_max_tries, dm_log_enabled, dm_log_target, fish_sell_min, fish_sell_enabled, fish_feed_max, fish_cook_min, fish_cook_enabled, feed_setup_stage, feed_setup_cap, factory_enabled, factory_chat_id

    # هر پیام فقط یک بار پردازش میشه (هم رویداد واقعی تلگرام هم اجرای مستقیمِ دستورِ مدیر)
    _key = (event.chat_id, event.id)
    if _key in _seen_cmd:
        return
    if len(_seen_cmd) > 500:
        _seen_cmd.clear()
    _seen_cmd.add(_key)

    text = normalize(event.raw_text)
    lower = text.lower()
    chat_id = event.chat_id

    # --- فلوی گفتگویی «delete messages» ---
    if delete_flow_stage == "await_type":
        delete_flow_stage = None
        if lower in ("group", "گروه"):
            delete_flow_stage = "await_group"
            await event.edit("آیدی عددی یا لینک گروه رو بفرست.")
        elif lower in ("private", "pv", "پیوی"):
            delete_flow_stage = "await_private"
            await event.edit("آیدی عددی یا یوزرنیم اون شخص رو بفرست.")
        else:
            delete_flow_stage = "await_type"
            await event.edit("لطفاً بنویس: group  یا  private")
        return

    if delete_flow_stage == "await_group":
        delete_flow_stage = None
        try:
            target_chat_id = await resolve_chat_id(text)
            count = await delete_all_my_messages(target_chat_id)
            await event.edit(f"{count} پیام تو اون گروه پاک شد ✅")
        except Exception:
            await event.edit("گروه پیدا نشد. دوباره بنویس: delete messages")
        return

    if delete_flow_stage == "await_private":
        delete_flow_stage = None
        try:
            target_chat_id = await resolve_chat_id(text)
            count = await delete_all_my_messages(target_chat_id)
            await event.edit(f"{count} پیام تو اون چت پاک شد ✅")
        except Exception:
            await event.edit("کاربر پیدا نشد. دوباره بنویس: delete messages")
        return

    if lower == "delete messages":
        delete_flow_stage = "await_type"
        await event.edit("پیام‌ها از کجا پاک بشن؟ بنویس: group  یا  private")
        return

    # --- گام دوم فلوی «farm on»: منتظر آیدی گروه بودیم ---
    if awaiting_farm_group:
        awaiting_farm_group = False
        parts = text.split()
        target = parts[0] if parts else ""
        minutes = None
        if len(parts) >= 2:
            try:
                minutes = float(parts[1])
            except ValueError:
                minutes = None
        if target.lstrip("-").isdigit():
            farm_chat_id = int(target)
            if minutes:
                farm_interval_seconds = minutes * 60
            msg = await toggle_farm()
            await event.edit(f"گروه فارم تنظیم شد ✅ (chat_id: {farm_chat_id})\n{msg}")
        else:
            await event.edit("آیدی نامعتبر بود. دوباره بنویس: farm on")
        return

    # --- فلوی گفتگویی «feed»: ظرفیت شکم، بعد حد غذادهی ---
    if feed_setup_stage:
        digits = text.translate(_DIGITS).strip()
        if digits.isdigit() and int(digits) > 0:
            n = int(digits)
            if feed_setup_stage == "cap":
                feed_setup_cap = n
                feed_setup_stage = "need"
                await event.edit("🍖 ظرفیتی که می‌خواید با دیدن اون به گربه غذا داده بشه وارد کنید\n(وقتی عدد دوم شکم این عدد یا کمتر شد غذا بده؛ مثلاً 8)")
            else:
                cap_v = feed_setup_cap
                feed_setup_stage = None
                feed_rules[cap_v] = n
                await event.edit(f"✅ فعال سازی غذادهی به پیشی با ظرفیت {cap_v} و {n} با موفقیت انجام شد\nوقتی شکم گربه {cap_v}/{n} یا کمتر شد، سلف بهش غذا میده.")
            return
        feed_setup_stage = None

    if lower.startswith("meow on"):
        rest = text[len("meow on"):].strip()
        minutes = None
        if rest:
            try:
                minutes = float(rest)
            except ValueError:
                await event.edit("عدد دقیقه نامعتبره. مثال: meow on 5")
                return
        await event.edit(await toggle_meow(chat_id, minutes))

    elif lower == "meow off":
        await event.edit(await untoggle_meow(chat_id))

    elif lower == "clock bio on":
        await event.edit(await toggle_clock_bio())

    elif lower == "clock bio style" or lower.startswith("clock bio style "):
        arg = lower[len("clock bio style"):].strip()
        if arg in BIO_STYLES:
            bio_style = arg
            await event.edit(f"استایل بیو {arg} فعال شد ✅ پیش‌نمایش:\n{fancy_bio_text()}")
        else:
            prev = "\n".join(
                f"{k}: {v.format(d='1405/07/26', t=fancy_time(bio_digit_font), gd=_local_now().day, gm=_local_now().strftime('%b'))}" for k, v in BIO_STYLES.items()
            )
            await event.edit(f"استایل‌های بیو (دستور: clock bio style <عدد>):\n{prev}\n\nفعلی: {bio_style}")

    elif lower == "clock bio reverse on":
        bio_reverse = True
        await event.edit(f"حالت معکوس بیو فعال شد ✅ (فقط اگه ساعت بیو هنوز برعکس نمایش داده میشه)\npreview: {fancy_bio_text()}")

    elif lower == "clock bio reverse off":
        bio_reverse = False
        await event.edit("حالت معکوس بیو غیرفعال شد ❌ (حالت عادی)")

    elif lower == "clock bio off":
        await event.edit(await untoggle_clock_bio())

    elif lower == "clock name on":
        await event.edit(await toggle_clock_name())

    elif lower == "clock name off":
        await event.edit(await untoggle_clock_name())

    elif lower in ("clock font list", "clock bio font list", "clock name font list"):
        preview = "\n".join(
            f"{name}: {fancy_digits_preview(name)}" for name in DIGIT_FONTS
        )
        await event.edit(
            f"Available clock fonts:\n{preview}\n\nBio font: {bio_digit_font}\nName font: {name_digit_font}\n\n"
            "Set bio font:  clock bio font <name>\nSet name font: clock name font <name>"
        )

    elif lower.startswith("clock bio font"):
        name = lower[len("clock bio font"):].strip()
        if name in DIGIT_FONTS:
            bio_digit_font = name
            await event.edit(f"فونت ساعت بیو روی '{name}' تنظیم شد ✅ پیش‌نمایش: {fancy_time(name)}")
        else:
            await event.edit("فونت نامعتبره. لیست: clock font list")

    elif lower.startswith("clock name font"):
        name = lower[len("clock name font"):].strip()
        if name in DIGIT_FONTS:
            name_digit_font = name
            await event.edit(f"فونت ساعت اسم روی '{name}' تنظیم شد ✅ پیش‌نمایش: {fancy_time(name)}")
        else:
            await event.edit("Unknown font. See the list with: clock font list")

    elif lower.startswith("afk on"):
        custom = text[len("afk on"):].strip()
        await event.edit(await toggle_afk(custom))

    elif lower == "afk off":
        await event.edit(await untoggle_afk())

    elif lower == "farm on":
        if farm_chat_id is not None:
            await event.edit(await toggle_farm())
        else:
            awaiting_farm_group = True
            await event.edit(
                "آیدی عددی گروهی که می‌خوای فارم توش انجام بشه رو بفرست.\n"
                "مثال: -1001234567890\n"
                "اگه فاصله‌ی زمانی دلخواه (دقیقه) هم می‌خوای، بعدش با یه فاصله بنویس: "
                "-1001234567890 60"
            )

    elif lower == "farm off":
        await event.edit(await untoggle_farm())

    elif lower.startswith("log channel"):
        arg = text[len("log channel"):].strip()
        if not arg:
            await event.edit("مثال: log channel -1001234567890   (یا لینک / @یوزرنیم کانال)")
        else:
            try:
                dm_log_target = await resolve_entity(arg)
                dm_log_enabled = True
                await event.edit("ذخیره‌ی پیوی‌ها فعال شد ✅ — پیام‌های جدید پیوی توی اون کانال ذخیره میشن.")
            except Exception:
                await event.edit("کانال پیدا نشد. مطمئن شو این اکانت عضو/ادمین کانال هست.")

    elif lower == "log on":
        if dm_log_target is None:
            await event.edit("اول کانال رو تنظیم کن: log channel <آیدی یا لینک>")
        elif dm_log_enabled:
            await event.edit("ذخیره‌ی پیوی فعال می‌باشد ✅ (از قبل روشن بود)")
        else:
            dm_log_enabled = True
            await event.edit("ذخیره‌ی پیوی فعال شد ✅")

    elif lower == "log off":
        if not dm_log_enabled:
            await event.edit("ذخیره‌ی پیوی غیرفعال می‌باشد ❌ (از قبل خاموش بود)")
        else:
            dm_log_enabled = False
            await event.edit("ذخیره‌ی پیوی غیرفعال شد ❌")

    elif lower == "ttl on":
        if ttl_save_enabled:
            await event.edit("ذخیره‌ی فایل نابودشونده فعال می‌باشد ✅ (از قبل روشن بود)")
        else:
            ttl_save_enabled = True
            await event.edit("ذخیره‌ی فایل نابودشونده فعال شد ✅")

    elif lower == "ttl off":
        if not ttl_save_enabled:
            await event.edit("ذخیره‌ی فایل نابودشونده غیرفعال می‌باشد ❌ (از قبل خاموش بود)")
        else:
            ttl_save_enabled = False
            await event.edit("ذخیره‌ی فایل نابودشونده غیرفعال شد ❌")

    elif lower.startswith("miner") or lower.startswith("main "):
        sub = lower.split(None, 1)[1] if " " in lower else ""
        if sub == "on":
            if event.is_group or event.is_channel:
                miner_cfg["chat"] = chat_id
            elif _miner_chat() is None:
                await event.edit("این دستور رو توی گروهی که میویی توشه بنویس (یا اول farm on رو تنظیم کن)")
                return
            miner_cfg["enabled"] = True
            start_miner_loop()
            await event.edit(f"ماینر میویی فعال شد ✅ — هر {miner_cfg['interval'] / 60:g} دقیقه بررسی میشه")
        elif sub == "off":
            miner_cfg["enabled"] = False
            stop_miner_loop()
            await event.edit("ماینر میویی غیرفعال شد ❌")
        elif sub == "now":
            if miner_cfg["chat"] is None and (event.is_group or event.is_channel):
                miner_cfg["chat"] = chat_id
            await event.edit("تبدیل توکن شروع شد ⏳")
            asyncio.create_task(miner_session())
        elif sub == "sell now":
            if miner_cfg["chat"] is None and (event.is_group or event.is_channel):
                miner_cfg["chat"] = chat_id
            await event.edit("فروش ارز شروع شد ⏳")
            asyncio.create_task(miner_sell_session())
        elif sub in ("status", ""):
            await event.edit(miner_status_text())
        else:
            res = apply_miner_command(sub)
            await event.edit(res or "دستور نامعتبر. نمونه‌ها: miner on | miner usdt | miner percent 100 | miner sell usdt 100 | miner sell off | miner status")

    elif lower.startswith("bank"):
        sub = lower[len("bank"):].strip()
        if sub == "on" and (event.is_group or event.is_channel) and bank_cfg["chat"] is None:
            bank_cfg["chat"] = chat_id
        res = apply_bank_command(sub) if sub else bank_status_text()
        await event.edit(res or "دستور نامعتبر. نمونه‌ها: bank above 3000000 | bank margin 1000 | bank chat -100123 | bank on | bank off | bank status")

    elif lower.startswith("factory"):
        sub = lower[len("factory"):].strip()
        if sub == "on":
            if event.is_group or event.is_channel:
                factory_chat_id = chat_id
            elif farm_chat_id is None and factory_chat_id is None:
                await event.edit("این دستور رو توی گروهی که میویی توشه بنویس (یا اول farm on رو تنظیم کن)")
                return
            factory_enabled = True
            start_factory_loop()
            await event.edit(f"کارخونه میویی فعال شد ✅ — هر {factory_interval_seconds/60:g} دقیقه بررسی میشه")
            asyncio.create_task(factory_session())
        elif sub == "off":
            factory_enabled = False
            stop_factory_loop()
            await event.edit("کارخونه میویی غیرفعال شد ❌")
        elif sub == "now":
            if factory_chat_id is None and (event.is_group or event.is_channel):
                factory_chat_id = chat_id
            await event.edit("بررسی کارخونه شروع شد ⏳")
            asyncio.create_task(factory_session(force=True))
        elif sub == "status":
            await event.edit(factory_status_text())
        else:
            res = apply_factory_command(sub)
            await event.edit(res or "دستور نامعتبر. نمونه‌ها: factory on | factory sell above 70 | factory cost below 50 | factory category 6 | factory item 1 | factory percent 100")

    elif lower == "fish status":
        feed_cap = "بدون محدودیت قیمت" if fish_feed_max >= 10**12 else f"فقط ماهی پخته‌ی ارزان‌تر از {fish_feed_max:,}"
        sell = f"فروش ماهی پخته با ارزش {fish_sell_min:,} و بالاتر" if fish_sell_enabled else "فروش خاموش است"
        cook = (f"پخت ماهی خام: فعال (از ارزش {fish_cook_min:,})" if fish_cook_min else "پخت ماهی خام: فعال (همه‌ی ماهی‌ها)") if fish_cook_enabled else "پخت ماهی خام: غیرفعال"
        rules = "، ".join(f"{k}/{v}" for k, v in sorted(feed_rules.items())) or "هیچ‌کدام"
        await event.edit(f"🐟 وضعیت ماهی‌ها\n• {cook}\n• {sell}\n• غذا دادن: {feed_cap}\n• قانون‌های غذادهی (ظرفیت/پُری): {rules}")

    elif lower in ("fish cook on", "fish cook off"):
        fish_cook_enabled = lower.endswith("on")
        await event.edit("پخت ماهی‌های خام فعال شد ✅ (همه‌ی ماهی‌ها بدون استثنا پخته میشن)" if fish_cook_enabled else "پخت ماهی‌های خام غیرفعال شد ❌")

    elif lower.startswith("fish cook above"):
        n = parse_int(text[len("fish cook above"):].strip())
        if n is None:
            await event.edit("مثال: fish cook above 0   (برای پخت همه‌ی ماهی‌ها) یا fish cook above 5000")
        else:
            fish_cook_min = n
            fish_cook_enabled = True
            await event.edit(f"پخت ماهی خام فعال شد ✅ — ماهی‌های 
