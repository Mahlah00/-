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
import os
import re
import tempfile
from datetime import datetime, timezone, timedelta

import jdatetime  # برای تبدیل درست تاریخ شمسی -> نصب: pip install jdatetime

from telethon import TelegramClient, events
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.types import PeerChannel

# ====== تنظیمات ======
api_id = 38302455          # <-- اینجا رو با api_id خودت جایگزین کن
api_hash = "c4646ac93fcbc703948bf74e76422d5e"  # <-- اینجا رو با api_hash خودت جایگزین کن
session_name = "mohammadzadhe"

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
rescue_delay_seconds = 1.0     # فاصله‌ی بین کلیک‌ها

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

bio_digit_font = "circle"    # فونت ساعت بیو؛ با «clock bio font <name>» عوض میشه
name_digit_font = "circle"   # فونت ساعت نام خانوادگی؛ با «clock name font <name>» عوض میشه


def fancy_digits(s: str, font: str = "circle") -> str:
    mapping = DIGIT_FONTS.get(font, DIGIT_FONTS["circle"])
    return "".join(mapping.get(ch, ch) for ch in s)


def fancy_digits_preview(font_name: str) -> str:
    mapping = DIGIT_FONTS.get(font_name, DIGIT_FONTS["circle"])
    return "".join(mapping.get(ch, ch) for ch in "12:34")


def fancy_time(font: str = "circle") -> str:
    """ساعت با سبک فونت اعداد انتخاب‌شده، برای بیو/اسم"""
    # LRE ... PDF: اجبار نمایش چپ‌به‌راست تا ساعت در محیط فارسی/راست‌به‌چپ برعکس نشه
    return "\u202a" + fancy_digits(now_str(), font) + "\u202c"


BIO_STYLES = {
    "1": "🌙 {d}  ┃  🕰 {t}",
    "2": "🗓 {d}  ✦  {gd} {gm}  ✦  ⏰ {t}",
    "3": "✨ {d} ⋆ 🕐 {t} ✨",
    "4": "🌸 {d} ‹ ⏳ {t} › 🌸",
    "5": "💫 {d}  •  🕒 {t}",
}
bio_style = "1"  # با دستور «clock bio style <1-5>» عوض میشه


def fancy_bio_text() -> str:
    """تاریخ شمسی + ساعت، با ایموجی و فونت اعداد انتخاب‌شده، برای بیو"""
    d = "\u202a" + jalali_date_str() + "\u202c"
    now = _local_now()
    return BIO_STYLES.get(bio_style, BIO_STYLES["1"]).format(
        d=d, t=fancy_time(bio_digit_font), gd=now.day, gm=now.strftime("%b")  # روز و ماه میلادی، هر روز خودکار عوض میشه
    )


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
async def clock_bio_loop():
    try:
        while True:
            await client(UpdateProfileRequest(about=fancy_bio_text()))
            await asyncio.sleep(clock_interval_seconds)
    except asyncio.CancelledError:
        pass


async def clock_name_loop():
    try:
        while True:
            await client(UpdateProfileRequest(last_name=f"✨ {fancy_time(name_digit_font)}"))
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
        async for msg in client.iter_messages(chat_id, limit=15):
            if msg.reply_to_msg_id == sent_msg_id and not msg.out and msg.buttons and await _is_bot_msg(msg):
                text = msg.raw_text or ""
                try:
                    await msg.click(text=lambda t: t and MEOWIE_BUTTON_KEYWORD in t)
                except Exception:
                    pass
                hungry = is_hungry_text(text)
                if hungry and feed_enabled and feed_interval_seconds is None:
                    asyncio.create_task(feed_cat_flow(chat_id))
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
        async for msg in client.iter_messages(chat_id, limit=15):
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


def parse_fridge(msg):
    """پیام یخچال رو به لیست ماهی‌ها تبدیل می‌کنه: [{'cooked':bool,'raw':bool,'value':int}] به‌ترتیب نمایش"""
    text = (msg.raw_text or "").translate(_DIGITS)
    fish, cur = [], None
    for ln in text.splitlines():
        if "|" in ln and ("پخته" in ln or "خام" in ln):
            cur = {"emoji": ln.split("|")[0].strip(), "cooked": "پخته" in ln, "raw": "خام" in ln and "پخته" not in ln, "value": None}
            fish.append(cur)
            continue
        if cur is not None and cur["value"] is None:
            m = re.search(r"ارزش[\s\u200e\u200f]*:[\s\u200e\u200f]*([0-9][0-9,]*)", ln)
            if m:
                cur["value"] = int(m.group(1).replace(",", ""))
    return [f for f in fish if f["value"] is not None]


def is_hungry_text(text: str) -> bool:
    return any("شکم" in ln and "گشنمیو" in ln for ln in (text or "").splitlines())


async def feed_loop():
    """هر feed_interval_seconds یک بار «پیشی» می‌فرسته، اگه گرسنه بود فلوی غذا دادن رو اجرا می‌کنه"""
    try:
        while True:
            try:
                if farm_chat_id is not None and feed_enabled:
                    sent = await client.send_message(farm_chat_id, MEOWIE_TRIGGER_TEXT)
                    reply = await wait_reply_to(farm_chat_id, sent.id, need_buttons=False)
                    if reply and is_hungry_text(reply.raw_text):
                        await feed_cat_flow(farm_chat_id)
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


async def catch_and_store_fish(chat_id: int) -> bool:
    """«ماهی» می‌فرسته و روی «بندازش تو یخچال» می‌زنه. اگه انجام شد True برمی‌گردونه"""
    sent = await client.send_message(chat_id, FISH_TRIGGER_TEXT)
    msg = await wait_reply_to(chat_id, sent.id)
    if not msg:
        print("fish: پاسخ ماهی نیومد")
        return False
    for b in _flat_buttons(msg):
        if b.text and FRIDGE_STORE_KEYWORD in b.text:
            await b.click()
            print("fish: ماهی توی یخچال انداخته شد")
            return True
    print("fish: دکمه‌ی «بندازش تو یخچال» پیدا نشد")
    return False


async def feed_cat_flow(chat_id: int):
    """قفل می‌گیره تا دو فلوی غذا دادن همزمان اجرا نشن"""
    async with feed_lock:
        await asyncio.sleep(3)
        await _feed_once(chat_id, allow_fish=True)


async def _feed_once(chat_id: int, allow_fish: bool):
    """یخچال رو چک می‌کنه؛ ماهی پخته‌ی ارزان رو می‌ده پیشی بخوره، وگرنه ماهی خام ارزان رو می‌پزه.
    اگه یخچال خالی بود (و allow_fish)، ماهی می‌گیره، می‌ندازه توی یخچال و دوباره چک می‌کنه"""
    if True:
        try:
            sent = await client.send_message(chat_id, FRIDGE_TRIGGER_TEXT)
            fmsg = await wait_reply_to(chat_id, sent.id, need_buttons=False)
            if not fmsg:
                print("feed: پاسخ یخچال نیومد")
                return

            fish = parse_fridge(fmsg)
            # دکمه‌های ماهی: همه‌ی دکمه‌ها به‌جز «ارتقا سطح یخچال» (به‌ترتیب همون پیام)
            fish_btns = [b for b in _flat_buttons(fmsg) if b.text and "ارتقا" not in b.text]
            if not fish and (not fish_btns or "یخچال خالی" in normalize(fmsg.raw_text or "")):
                # یخچال خالیه: ماهی بگیر، بنداز توی یخچال، و دوباره فلوی پخت/غذا رو اجرا کن
                if allow_fish and await catch_and_store_fish(chat_id):
                    await asyncio.sleep(2)
                    await _feed_once(chat_id, allow_fish=False)
                return
            if not fish or len(fish) != len(fish_btns):
                print(f"feed: تعداد ماهی‌ها ({len(fish)}) با دکمه‌ها ({len(fish_btns)}) نمی‌خونه، انجام نشد")
                return
            # اول با ایموجی گوشه‌ی هر ماهی به دکمه‌اش وصل می‌کنیم (دکمه‌ها هر بار عوض میشن)؛
            # اگه ایموجی‌ها یکتا و کامل تطبیق نکرد، به‌ترتیب نمایش برمی‌گردیم
            matched = []
            for f in fish:
                hits = [b for b in fish_btns if f["emoji"] and b.text.strip() == f["emoji"]]
                matched.append(hits[0] if len(hits) == 1 else None)
            if None not in matched and len({id(b) for b in matched}) == len(fish):
                for f, b in zip(fish, matched):
                    f["btn"] = b
            else:
                for f, b in zip(fish, fish_btns):
                    f["btn"] = b

            cooked = [f for f in fish if f["cooked"] and f["value"] < MAX_FISH_VALUE]
            raw = [f for f in fish if f["raw"] and f["value"] < MAX_FISH_VALUE]

            if cooked:
                pick = min(cooked, key=lambda f: f["value"])
                await pick["btn"].click()
                fb = await wait_button(chat_id, fmsg.id, FEED_BUTTON_KEYWORD)
                if fb:
                    await fb.click()
                    print("feed: ماهی پخته داده شد")
                return

            if raw:
                pick = min(raw, key=lambda f: f["value"])
                await pick["btn"].click()
                cb = await wait_button(chat_id, fmsg.id, COOK_BUTTON_KEYWORD)
                if not cb:
                    return
                await cb.click()
                # منوی تأیید: دکمه‌ی سبز ✓ (پخت) و دکمه‌ی قرمز ✗ (انصراف)
                await asyncio.sleep(2)
                async for m in client.iter_messages(chat_id, limit=8):
                    # فقط منوی تأییدِ مربوط به همین پیام: یا خودِ پیام ادیت‌شده، یا ریپلای ربات به پیام‌های خودمون
                    mine = m.id == fmsg.id or m.reply_to_msg_id in (fmsg.id, sent.id)
                    if mine and not m.out and m.buttons and "اطمینان" in (m.raw_text or "") and await _is_bot_msg(m):
                        btns = _flat_buttons(m)
                        bad = ("❌", "✖", "✕", "×", "✗", "❎")
                        good = [b for b in btns if b.text and not any(x in b.text for x in bad)]
                        if good:
                            await good[0].click()
                            print("feed: پخت ماهی خام تأیید شد")
                        break
        except Exception as e:
            print(f"خطا توی غذا دادن: {e}")


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

🐈 نجات و غذا دادن
rescue on / rescue off — کلیک خودکار روی دکمه‌ی «نجات پیشی خیابونی» توی همه‌ی گروه‌هایی که عضوی، با فاصله‌ی ۳ ثانیه بین کلیک‌ها (پیش‌فرض روشن)
rescue tries 10 — (وقتی پیام «گربه کشته شد» یا نجات نهایی بشه، کلیک‌ها متوقف میشن) حداکثر تعداد کلیک روی هر پیام نجات (هر کلیک ممکنه شکست بخوره؛ تا موفقیت یا تموم شدن شانس‌ها تکرار میشه)
feed on / feed off — غذا دادن خودکار (پیش‌فرض روشن)
feed interval 30 — هر ۳۰ دقیقه گرسنگی رو چک کن و غذا بده (feed interval 2h = هر ۲ ساعت)
feed interval off — برگشت به حالت «چک بعد از هر فارم»
مراحل غذا دادن:
  اگه بعد از «پیشی» شکم «گشنمیو» بود، «یخچال میویی» رو می‌فرسته و
  • ماهی پخته‌ی زیر ۲۰۰۰ سکه → کلیک روی ماهی و «بده پیشی بخوره»
  • وگرنه ماهی خام زیر ۲۰۰۰ سکه → کلیک روی ماهی، «بپوخش» و دکمه‌ی سبز ✓
  • اگه یخچال خالی بود → «ماهی» می‌فرسته، «بندازش تو یخچال» رو می‌زنه و دوباره یخچال رو چک می‌کنه و مراحل پخت رو انجام میده
  (ارزان‌ترین ماهی انتخاب میشه و هیچ ماهی‌ای فروخته نمیشه)

🔒 ذخیره‌ی عکس/ویدیوی نابودشونده
ttl on / ttl off — هر عکس/ویدیو/ویس سکرت (تایمردار یا یک‌بار‌مصرف) که کسی توی پیوی برات بفرسته، خودکار توی Saved Messages ذخیره میشه (پیش‌فرض روشن)

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
help — نمایش همین راهنما

━━━━━━━━━━━━━━━━━━━━
📡 دستورهای مدیر (ADMIN)
(آیدی عددی مدیر باید توی ADMIN_IDS باشه. دستورها رو مدیر توی پیوی همین اکانت می‌فرسته)

همه‌ی دستورهای بالا (meow, afk, clock, farm, delete messages, help) توی پیوی مدیر هم کار می‌کنن.

ping — جواب میده و زمان پاسخ رو برحسب میلی‌ثانیه نشون میده
farm now — توی پیوی: فارم توی گروه تنظیم‌شده. توی یک گروه: خودِ اکانت سلف همون‌جا «پیشی» می‌فرسته و دکمه رو می‌زنه
mio online is gp — ربات آیدی عددی یا لینک گروه رو می‌پرسه (اختیاری: فاصله و عدد دقیقه، مثلاً -1001234567890 5)؛ میو توی اون گروه فعال میشه
rmg <text> — توی هر چتی که اکانت سلف هم هست بفرست؛ اکانت سلف همون متن رو توی همون چت می‌فرسته
  مثال: rmg hi ← سلف «hi» می‌فرسته
  مثال: rmg پیشی ← سلف «پیشی» می‌فرسته و دکمه‌ی برداشت رو هم می‌زنه
پاک یا delete — روی پیامی که خودِ اکانت سلف فرستاده ریپلای کن تا همون یک پیام پاک بشه

━━━━━━━━━━━━━━
ساخته‌شده توسط @MRZverse
"""

async def send_help(event, edit):
    """HELP_TEXT از حد ۴۰۹۶ کاراکتر تلگرام بلندتره؛ تکه‌تکه می‌فرستیم"""
    chunks, cur = [], ""
    for block in HELP_TEXT.split("\n\n"):
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
@client.on(events.NewMessage(outgoing=True))
async def handler(event):
    global awaiting_farm_group, farm_chat_id, farm_interval_seconds, meow_default_seconds
    global delete_flow_stage, bio_digit_font, name_digit_font, rescue_enabled, feed_enabled, bio_style, ttl_save_enabled, feed_interval_seconds, rescue_max_tries, dm_log_enabled, dm_log_target

    text = normalize(event.raw_text)
    lower = text.lower()
    chat_id = event.chat_id

    # --- فلوی گفتگویی «delete messages» ---
    if delete_flow_stage == "await_type":
        delete_flow_stage = None
        if lower in ("group", "گروه"):
            delete_flow_stage = "await_group"
            await event.edit("Send the group's numeric ID or link.")
        elif lower in ("private", "pv", "پیوی"):
            delete_flow_stage = "await_private"
            await event.edit("Send the numeric ID or username of the person.")
        else:
            delete_flow_stage = "await_type"
            await event.edit("Please answer with: group  or  private")
        return

    if delete_flow_stage == "await_group":
        delete_flow_stage = None
        try:
            target_chat_id = await resolve_chat_id(text)
            count = await delete_all_my_messages(target_chat_id)
            await event.edit(f"Deleted {count} of your messages in that group ✅")
        except Exception:
            await event.edit("Could not resolve that group. Try again with: delete messages")
        return

    if delete_flow_stage == "await_private":
        delete_flow_stage = None
        try:
            target_chat_id = await resolve_chat_id(text)
            count = await delete_all_my_messages(target_chat_id)
            await event.edit(f"Deleted {count} of your messages in that chat ✅")
        except Exception:
            await event.edit("Could not resolve that user. Try again with: delete messages")
        return

    if lower == "delete messages":
        delete_flow_stage = "await_type"
        await event.edit("Where should I delete messages from? Reply: group  or  private")
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
            await event.edit(f"Bio style {arg} ✅ preview:\n{fancy_bio_text()}")
        else:
            prev = "\n".join(
                f"{k}: {v.format(d='1405/07/26', t=fancy_time(bio_digit_font), gd=_local_now().day, gm=_local_now().strftime('%b'))}" for k, v in BIO_STYLES.items()
            )
            await event.edit(f"Bio styles (use: clock bio style <number>):\n{prev}\n\nCurrent: {bio_style}")

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
            await event.edit(f"Bio clock font set to '{name}' ✅ preview: {fancy_time(name)}")
        else:
            await event.edit("Unknown font. See the list with: clock font list")

    elif lower.startswith("clock name font"):
        name = lower[len("clock name font"):].strip()
        if name in DIGIT_FONTS:
            name_digit_font = name
            await event.edit(f"Name clock font set to '{name}' ✅ preview: {fancy_time(name)}")
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
            await event.edit("Example: log channel -1001234567890   (or a channel link/@username)")
        else:
            try:
                dm_log_target = await resolve_entity(arg)
                dm_log_enabled = True
                await event.edit("DM logging is ON ✅ — new private messages will be saved to that channel.")
            except Exception:
                await event.edit("Could not find that channel. Make sure this account is a member/admin of it.")

    elif lower == "log on":
        if dm_log_target is None:
            await event.edit("Set the channel first: log channel <id or link>")
        elif dm_log_enabled:
            await event.edit("DM logging is already ON — فعال می‌باشد ✅")
        else:
            dm_log_enabled = True
            await event.edit("DM logging is ON ✅")

    elif lower == "log off":
        if not dm_log_enabled:
            await event.edit("DM logging is already OFF — غیرفعال می‌باشد ❌")
        else:
            dm_log_enabled = False
            await event.edit("DM logging is OFF ❌")

    elif lower == "ttl on":
        if ttl_save_enabled:
            await event.edit("Self-destruct media saving is already ON — فعال می‌باشد ✅")
        else:
            ttl_save_enabled = True
            await event.edit("Self-destruct media saving is ON ✅")

    elif lower == "ttl off":
        if not ttl_save_enabled:
            await event.edit("Self-destruct media saving is already OFF — غیرفعال می‌باشد ❌")
        else:
            ttl_save_enabled = False
            await event.edit("Self-destruct media saving is OFF ❌")

    elif lower == "rescue on":
        if rescue_enabled:
            await event.edit("Auto-rescue is already ON — فعال می‌باشد ✅")
        else:
            rescue_enabled = True
            await event.edit("Auto-rescue of stray cats is ON ✅")

    elif lower == "rescue off":
        if not rescue_enabled:
            await event.edit("Auto-rescue is already OFF — غیرفعال می‌باشد ❌")
        else:
            rescue_enabled = False
            await event.edit("Auto-rescue of stray cats is OFF ❌")

    elif lower == "feed on":
        if feed_enabled:
            await event.edit("Auto-feed is already ON — فعال می‌باشد ✅")
            return
        feed_enabled = True
        if feed_interval_seconds is not None and farm_chat_id is not None:
            start_feed_loop()
        await event.edit("Auto-feed is ON ✅" + (f" (every {feed_interval_seconds/60:g} min)" if feed_interval_seconds else " (checked after each farm)"))

    elif lower == "feed off":
        if not feed_enabled:
            await event.edit("Auto-feed is already OFF — غیرفعال می‌باشد ❌")
            return
        feed_enabled = False
        stop_feed_loop()
        await event.edit("Auto-feed is OFF ❌")

    elif lower == "feed interval off":
        feed_interval_seconds = None
        stop_feed_loop()
        await event.edit("Timed feed check stopped. Feeding is now checked after each farm.")

    elif lower.startswith("feed interval"):
        seconds = parse_duration_seconds(text[len("feed interval"):].strip())
        if seconds is None or seconds < 60:
            await event.edit("Example: feed interval 30  (minutes)  or  feed interval 2h  (hours)")
        elif farm_chat_id is None:
            await event.edit("Set the farm group first: farm on")
        else:
            feed_interval_seconds = seconds
            feed_enabled = True
            start_feed_loop()
            await event.edit(f"Feed check every {seconds/60:g} min ✅")

    elif lower.startswith("rescue tries"):
        try:
            n = int(lower[len("rescue tries"):].strip())
            if not 1 <= n <= 50:
                raise ValueError
            rescue_max_tries = n
            await event.edit(f"Rescue: up to {n} clicks per message ✅")
        except ValueError:
            await event.edit("Example: rescue tries 10   (1-50)")

    elif lower == "farm now":
        if farm_chat_id is None:
            await event.edit("No farm group set yet. Use: farm on")
        else:
            await event.edit("Collecting now...")
            await meowie_farm_once()

    elif lower == "farm +5":
        farm_interval_seconds += 5 * 60
        await event.edit(f"Farm interval: {farm_interval_seconds/60:g} min")

    elif lower == "farm -5":
        farm_interval_seconds = max(5 * 60, farm_interval_seconds - 5 * 60)
        await event.edit(f"Farm interval: {farm_interval_seconds/60:g} min")

    elif lower.startswith("farm interval"):
        raw = text[len("farm interval"):].strip()
        seconds = parse_duration_seconds(raw)
        if seconds is None or seconds < 60:
            await event.edit("Example: farm interval 30  (minutes)  or  farm interval 2h  (hours)")
        else:
            farm_interval_seconds = seconds
            await event.edit(f"Farm interval set to {farm_interval_seconds/60:g} min")

    elif lower == "meow +5":
        meow_default_seconds += 5 * 60
        await event.edit(f"Default meow interval: {meow_default_seconds/60:g} min")

    elif lower == "meow -5":
        meow_default_seconds = max(60, meow_default_seconds - 5 * 60)
        await event.edit(f"Default meow interval: {meow_default_seconds/60:g} min")

    elif lower == "help":
        await send_help(event, True)

    elif lower == "clean all":
        if not event.is_reply:
            await event.edit("Reply to one of your own messages in this chat with: clean all")
            return
        reply_msg = await event.get_reply_message()
        if not (reply_msg and reply_msg.out):
            await event.edit("You need to reply to one of your own messages.")
            return
        count = await delete_all_my_messages(chat_id)
        await client.send_message(chat_id, f"Deleted {count} of your messages in this chat ✅")


# ---------- هندلر پیام‌های ورودی: افک + کنترل مدیر ----------
@client.on(events.NewMessage(incoming=True))
async def incoming_watcher(event):
    global farm_interval_seconds, delete_flow_stage, bio_digit_font, name_digit_font, rescue_enabled, feed_enabled

    sender_id = event.sender_id
    text = normalize(event.raw_text or "")
    lower = text.lower()

    # --- حذف پیام از راه دور با ریپلای «پاک»/«delete» ---
    if event.is_reply and lower in ("پاک", "delete") and sender_id in ADMIN_IDS:
        reply_msg = await event.get_reply_message()
        if reply_msg and reply_msg.out:
            await reply_msg.delete()
            await event.delete()
        return

    # --- rmg <text>: وقتی مدیر این رو تو یه گپ می‌فرسته، این اکانت هم همون متن رو
    # توی همون گپ می‌فرسته (برای هماهنگ‌کردن چند اکانت سلف با هم). اگه متن دقیقاً
    # کلمه‌ی محرک میویی («پیشی») باشه، بعد از ارسال، دنبال دکمه‌ی برداشت هم می‌گرده.
    # --- farm now از طرف مدیر توی گروه: خودِ اکانت سلف همون‌جا «پیشی» می‌فرسته ---
    if sender_id in ADMIN_IDS and not event.is_private and lower == "farm now":
        sent = await client.send_message(event.chat_id, MEOWIE_TRIGGER_TEXT)
        await click_farm_button(event.chat_id, sent.id)
        return

    if sender_id in ADMIN_IDS and lower.startswith("rmg "):
        payload = text[len("rmg "):].strip()
        if payload:
            sent = await client.send_message(event.chat_id, payload)
            if payload == MEOWIE_TRIGGER_TEXT:
                await click_farm_button(event.chat_id, sent.id)
        return

    if event.is_private and sender_id in ADMIN_IDS:
        admin_chat_id = event.chat_id

        # --- فلوی گفتگویی «delete messages» برای مدیر ---
        if delete_flow_stage == "await_type":
            delete_flow_stage = None
            if lower in ("group", "گروه"):
                delete_flow_stage = "await_group"
                await event.reply("Send the group's numeric ID or link.")
            elif lower in ("private", "pv", "پیوی"):
                delete_flow_stage = "await_private"
                await event.reply("Send the numeric ID or username of the person.")
            else:
                delete_flow_stage = "await_type"
                await event.reply("Please answer with: group  or  private")
            return

        if delete_flow_stage == "await_group":
            delete_flow_stage = None
            try:
                target_chat_id = await resolve_chat_id(text)
                count = await delete_all_my_messages(target_chat_id)
                await event.reply(f"Deleted {count} of your messages in that group ✅")
            except Exception:
                await event.reply("Could not resolve that group. Try again with: delete messages")
            return

        if delete_flow_stage == "await_private":
            delete_flow_stage = None
            try:
                target_chat_id = await resolve_chat_id(text)
                count = await delete_all_my_messages(target_chat_id)
                await event.reply(f"Deleted {count} of your messages in that chat ✅")
            except Exception:
                await event.reply("Could not resolve that user. Try again with: delete messages")
            return

        if lower == "delete messages":
            delete_flow_stage = "await_type"
            await event.reply("Where should I delete messages from? Reply: group  or  private")
            return

        # --- گام دوم فلوی «mio online is gp» ---
        if sender_id in admin_awaiting_group:
            admin_awaiting_group.discard(sender_id)
            parts = text.split()
            target_raw = parts[0] if parts else ""
            minutes = None
            if len(parts) >= 2:
                try:
                    minutes = float(parts[1])
                except ValueError:
                    minutes = None
            try:
                if target_raw.lstrip("-").isdigit():
                    target_chat_id = int(target_raw)
                else:
                    entity = await client.get_entity(target_raw)
                    target_chat_id = entity.id
                msg = await toggle_meow(target_chat_id, minutes)
                await event.reply(f"گروه شناسایی شد ✅\n{msg}")
            except Exception:
                await event.reply(
                    "نتونستم این گروه رو شناسایی کنم. آیدی عددی یا لینک عمومی رو چک کن، "
                    "یا مطمئن شو اکانت اصلی از قبل عضو اون گروهه."
                )
            return

        if lower == "mio online is gp":
            admin_awaiting_group.add(sender_id)
            await event.reply(
                "آیدی عددی گروه یا لینک عمومی‌ش رو بفرست.\n"
                "برای فاصله‌ی زمانی دلخواه، بعدش با یه فاصله عدد دقیقه رو بنویس.\n"
                "مثال: -1001234567890 5"
            )
            return

        if lower == "help":
            await send_help(event, False)
            return

        if lower == "farm now":
            if farm_chat_id is None:
                await event.reply("No farm group set yet. Use: farm on")
            else:
                await event.reply("Collecting now...")
                await meowie_farm_once()
            return

        if lower == "farm +5":
            farm_interval_seconds += 5 * 60
            await event.reply(f"Farm interval: {farm_interval_seconds/60:g} min")
            return

        if lower == "farm -5":
            farm_interval_seconds = max(5 * 60, farm_interval_seconds - 5 * 60)
            await event.reply(f"Farm interval: {farm_interval_seconds/60:g} min")
            return

        if lower.startswith("farm interval"):
            raw = text[len("farm interval"):].strip()
            seconds = parse_duration_seconds(raw)
            if seconds is None or seconds < 60:
                await event.reply("Example: farm interval 30  (minutes)  or  farm interval 2h  (hours)")
            else:
                farm_interval_seconds = seconds
                await event.reply(f"Farm interval set to {farm_interval_seconds/60:g} min")
            return

        if lower == "ping":
            start = datetime.now()
            msg = await event.reply("در حال سنجش...")
            delta = (datetime.now() - start).total_seconds() * 1000
            await msg.edit(f"پونگ! 🏓 {delta:.0f} ms")
            return

        if lower.startswith("meow on"):
            rest = text[len("meow on"):].strip()
            minutes = None
            if rest:
                try:
                    minutes = float(rest)
                except ValueError:
                    await event.reply("عدد دقیقه نامعتبره. مثال: meow on 5")
                    return
            await event.reply(await toggle_meow(admin_chat_id, minutes))
            return
        elif lower == "meow off":
            await event.reply(await untoggle_meow(admin_chat_id))
            return
        elif lower.startswith("afk on"):
            custom = text[len("afk on"):].strip()
            await event.reply(await toggle_afk(custom))
            return
        elif lower == "afk off":
            await event.reply(await untoggle_afk())
            return
        elif lower == "clock bio on":
            await event.reply(await toggle_clock_bio())
            return
        elif lower == "clock bio off":
            await event.reply(await untoggle_clock_bio())
            return
        elif lower == "clock name on":
            await event.reply(await toggle_clock_name())
            return
        elif lower == "clock name off":
            await event.reply(await untoggle_clock_name())
            return
        elif lower in ("clock font list", "clock bio font list", "clock name font list"):
            preview = "\n".join(
                f"{name}: {fancy_digits_preview(name)}" for name in DIGIT_FONTS
            )
            await event.reply(
                f"Available clock fonts:\n{preview}\n\nBio font: {bio_digit_font}\nName font: {name_digit_font}\n\n"
                "Set bio font:  clock bio font <name>\nSet name font: clock name font <name>"
            )
            return

        elif lower.startswith("clock bio font"):
            name = lower[len("clock bio font"):].strip()
            if name in DIGIT_FONTS:
                bio_digit_font = name
                await event.reply(f"Bio clock font set to '{name}' ✅ preview: {fancy_time(name)}")
            else:
                await event.reply("Unknown font. See the list with: clock font list")
            return

        elif lower.startswith("clock name font"):
            name = lower[len("clock name font"):].strip()
            if name in DIGIT_FONTS:
                name_digit_font = name
                await event.reply(f"Name clock font set to '{name}' ✅ preview: {fancy_time(name)}")
            else:
                await event.reply("Unknown font. See the list with: clock font list")
            return

    # --- پاسخ خودکار افک (فقط پیوی، و نه به بات‌ها) ---
    if not afk_enabled:
        return
    if not event.is_private:
        return
    sender = await event.get_sender()
    if sender and getattr(sender, "bot", False):
        return
    chat_id = event.chat_id
    if chat_id in afk_replied_chats:
        return
    afk_replied_chats.add(chat_id)
    await event.reply(afk_message)


# --- نجات خودکار «پیشی خیابونی» توی گروه‌های میو/فارم ---
@client.on(events.NewMessage(incoming=True))
async def rescue_watcher(event):
    if not rescue_enabled or not event.is_group:
        return
    # توی همه‌ی گروه‌هایی که اکانت عضوشه کار می‌کنه
    cid = event.chat_id
    msg = event.message
    if not msg.buttons or (cid, msg.id) in rescued_msg_ids:
        return
    if any(b.text and RESCUE_BUTTON_KEYWORD in b.text for b in _flat_buttons(msg)) and await _is_bot_msg(msg):
        rescued_msg_ids.add((cid, msg.id))
        asyncio.create_task(rescue_loop(cid, msg.id))


async def rescue_loop(chat_id: int, msg_id: int):
    """چند بار پشت‌سرهم روی «نجات پیشی خیابونی» می‌زنه (هر بار ممکنه شکست بخوره: «گربه توسط 🐭 کشته شد»)
    تا وقتی که دکمه از پیام بره، شانس‌ها تموم بشه، یا به سقف تعداد تلاش برسه"""
    for attempt in range(1, rescue_max_tries + 1):
        try:
            m = await client.get_messages(chat_id, ids=msg_id)
            if not m or not m.buttons:
                print("rescue: دکمه دیگه نیست، تموم شد")
                return
            btn = next((x for x in _flat_buttons(m) if x.text and RESCUE_BUTTON_KEYWORD in x.text), None)
            if not btn:
                return
            body = m.raw_text or ""
            if any(w in body for w in RESCUE_DONE_WORDS):
                print("rescue: پیام نهایی شد (نجات/مرگ)، تموم شد")
                return
            chances = re.search(r"شانس[^\n:：]*[:：]\s*([0-9۰-۹]+)", (m.raw_text or ""))
            if chances and int(chances.group(1).translate(_DIGITS)) == 0:
                print("rescue: شانسی باقی نمونده")
                return
            ans = await btn.click()
            reply_text = getattr(ans, "message", None) or ""
            print(f"rescue: تلاش {attempt}/{rescue_max_tries} {reply_text[:60]}")
        except Exception as e:
            print(f"rescue: {e}")
        await asyncio.sleep(rescue_delay_seconds)


# --- ذخیره‌ی عکس/ویدیوی نابودشونده (سکرت/یک‌بار‌مصرف) توی Saved Messages ---
@client.on(events.NewMessage(incoming=True))
async def ttl_watcher(event):
    if not ttl_save_enabled or not event.is_private or not event.message.media:
        return
    ttl = getattr(event.message.media, "ttl_seconds", None)
    if not ttl:
        return
    try:
        sender = await event.get_sender()
        name = " ".join(x for x in [getattr(sender, "first_name", None), getattr(sender, "last_name", None)] if x) or "Unknown"
        uname = f"@{sender.username}" if getattr(sender, "username", None) else "no username"
        caption = f"🔒 Self-destruct media saved\nFrom: {name} ({uname}) — ID {event.sender_id}\nTimer: {ttl}s"
        tmpdir = tempfile.mkdtemp(prefix="ttl_")
        path = await event.message.download_media(file=tmpdir + os.sep)
        if not path:
            await client.send_message("me", caption + "\n⚠️ Could not download the media.")
            return
        await client.send_file("me", path, caption=caption)
        try:
            os.remove(path)
            os.rmdir(tmpdir)
        except OSError:
            pass
    except Exception as e:
        print(f"ttl: {e}")
        try:
            await client.send_message("me", f"⚠️ Failed to save a self-destruct media: {e}")
        except Exception:
            pass


# --- ذخیره‌ی پیام‌های پیوی (همه‌چیز: متن، ویس، استیکر، مدیا، ...) توی یک کانال ---
# اول خودِ پیام فرستاده میشه، و زیرش اسم، یوزرنیم، آیدی و ساعت فرستنده
@client.on(events.NewMessage(incoming=True))
async def dm_logger(event):
    if not dm_log_enabled or dm_log_target is None or not event.is_private:
        return
    # فقط پیام‌هایی که خودِ تلگرام فرستاده (کدهای ورود و ...) به کانال نمیره (امنیتی)
    if event.sender_id in TELEGRAM_SERVICE_IDS or event.sender_id == OWNER_ID:
        return
    msg = event.message
    try:
        sender = await event.get_sender()
        if sender is None:
            return
        name = " ".join(x for x in [getattr(sender, "first_name", None), getattr(sender, "last_name", None)] if x) or "Unknown"
        uname = f"@{sender.username}" if getattr(sender, "username", None) else "—"
        bot_tag = " 🤖" if getattr(sender, "bot", False) else ""
        footer = (
            f"👤 {name}{bot_tag}\n🔗 {uname}\n🆔 {event.sender_id}\n"
            f"🕐 {_local_now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        sep = "┄┄┄┄┄┄┄┄┄┄"
        info = f"{sep}\n📩 پیام از:\n{footer}"
        text = msg.message or ""

        if not msg.media:
            if text:
                await client.send_message(dm_log_target, f"{text}\n\n{info}")
            return

        # مدیا: اول خودِ فایل (با ارجاع مستقیم)، اگه نشد (مثلاً تایمردار) دانلود و آپلود
        async def send_media(caption):
            try:
                await client.send_file(dm_log_target, msg.media, caption=caption)
            except Exception:
                tmpdir = tempfile.mkdtemp(prefix="dm_")
                path = await msg.download_media(file=tmpdir + os.sep)
                if not path:
                    raise
                await client.send_file(dm_log_target, path, caption=caption)
                try:
                    os.remove(path)
                    os.rmdir(tmpdir)
                except OSError:
                    pass

        no_caption = bool(msg.sticker or msg.video_note)
        cap = (text + "\n\n" if text else "") + info
        if getattr(msg.media, "ttl_seconds", None):
            cap = f"⏱ مدیای نابودشونده ({msg.media.ttl_seconds}s)\n" + cap
        try:
            if no_caption or len(cap) > 1000:
                await send_media(None)
                await client.send_message(dm_log_target, (text + "\n\n" if text else "") + info)
            else:
                await send_media(cap)
        except Exception:
            # انواعی که با send_file نمیشن (لوکیشن، نظرسنجی، مخاطب، ...): فوروارد + اطلاعات فرستنده
            await client.forward_messages(dm_log_target, msg)
            await client.send_message(dm_log_target, info)
    except Exception as e:
        print(f"dm-log: {e}")


async def main():
    global OWNER_ID
    await client.start()
    me = await client.get_me()
    OWNER_ID = me.id
    print("سلف‌بات اجرا شد. دستورات:")
    print("  meow on [دقیقه] / meow off")
    print("  clock bio on/off | clock name on/off")
    print("  afk on <پیام> / afk off")
    print("  farm on / farm off")
    print("  help  → show full command list")
    if ADMIN_IDS:
        print(f"  کنترل مدیریتی برای {len(ADMIN_IDS)} اکانت مدیر فعاله")
    else:
        print("  ⚠️ ADMIN_IDS خالیه — قابلیت مدیریتی غیرفعاله تا آیدی مدیر رو اضافه کنی")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
