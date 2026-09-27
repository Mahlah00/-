"""
سلف‌بات تلگرام با Telethon
ساخته شده توسط @MRZverse

قابلیت‌ها (خلاصه‌شده):
  - میو دوره‌ای در یک گپ
  - ساعت خودکار روی بیو و نام خانوادگی (با فونت شیک)
  - افک (پاسخ خودکار وقتی نیستی)
  - فارم خودکار بات میویی، داخل یه گروه مشخص
  - کنترل کامل از راه دور توسط مدیر(ها) از طریق پیوی همین اکانت

نصب پیش‌نیاز:.
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
from datetime import datetime, timezone, timedelta

import jdatetime  # برای تبدیل درست تاریخ شمسی -> نصب: pip install jdatetime

from telethon import TelegramClient, events
from telethon.tl.functions.account import UpdateProfileRequest

# ====== تنظیمات ======
api_id = 123456          # <-- اینجا رو با api_id خودت جایگزین کن
api_hash = "YOUR_API_HASH"  # <-- اینجا رو با api_hash خودت جایگزین کن
session_name = "meow_session"

tz_offset_hours = 3.5            # تایم‌زون تهران (UTC+3:30)
clock_interval_seconds = 60      # فاصله‌ی آپدیت ساعت بیو/اسم

ADMIN_IDS: list[int] = [ ایدی عددی اکانت مدیریتی]        # <-- آیدی عددی اکانت‌های مدیر (از @userinfobot بگیر)

MEOWIE_TRIGGER_TEXT = "پیشی"      # پیامی که برای فارم به گروه فرستاده میشه
MEOWIE_BUTTON_KEYWORD = "برداشت میو پوینت ها"  # عبارت کامل دکمه، تا با دکمه‌های دیگه (مثلاً بانکی) اشتباه گرفته نشه
# ======================

client = TelegramClient(session_name, api_id, api_hash)

OWNER_ID: int | None = None  # موقع اجرا پر میشه

# --- وضعیت‌های سراسری ---
active_meow_tasks: dict[int, asyncio.Task] = {}
meow_default_seconds = 10 * 60

clock_bio_task: asyncio.Task | None = None
clock_name_task: asyncio.Task | None = None

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
    "digital": {str(i): chr(0x1FBF0 + i) for i in range(10)},                   # 🯰🯱🯲 (سبک ساعت دیجیتال/LCD)
    "normal": {str(i): str(i) for i in range(10)},                              # بدون تغییر
}

clock_digit_font = "circle"  # پیش‌فرض؛ با دستور «clock font <name>» قابل تغییره


def fancy_digits(s: str) -> str:
    mapping = DIGIT_FONTS.get(clock_digit_font, DIGIT_FONTS["circle"])
    return "".join(mapping.get(ch, ch) for ch in s)


def fancy_digits_preview(font_name: str) -> str:
    mapping = DIGIT_FONTS.get(font_name, DIGIT_FONTS["circle"])
    return "".join(mapping.get(ch, ch) for ch in "12:34")


def fancy_time() -> str:
    """ساعت با سبک فونت اعداد انتخاب‌شده، برای بیو/اسم"""
    return fancy_digits(now_str())


def fancy_bio_text() -> str:
    """تاریخ شمسی + ساعت، با ایموجی و فونت اعداد انتخاب‌شده، برای بیو"""
    return f"📅 {jalali_date_str()}  ⏰ {fancy_time()}"


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
        return "میو از قبل فعال بود 🐱"
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
            await client(UpdateProfileRequest(last_name=f"✨ {fancy_time()}"))
            await asyncio.sleep(clock_interval_seconds)
    except asyncio.CancelledError:
        pass


async def toggle_clock_bio() -> str:
    global clock_bio_task
    if clock_bio_task:
        return "ساعت بیو از قبل فعال بود 🕐"
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
        return "ساعت اسم از قبل فعال بود 🕐"
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
    if custom_message:
        afk_message = custom_message
    afk_enabled = True
    afk_replied_chats.clear()
    return f"حالت افک فعال شد ✅\nپیام: {afk_message}"


async def untoggle_afk() -> str:
    global afk_enabled
    afk_enabled = False
    afk_replied_chats.clear()
    return "حالت افک غیرفعال شد ❌ خوش اومدی 👋"


# ---------- فارم خودکار (داخل یه گروه مشخص) ----------
async def click_farm_button(chat_id: int, sent_msg_id: int):
    """منتظر پیامی می‌مونه که دقیقاً روی sent_msg_id ریپلای زده باشه، و دکمه‌ی برداشت رو می‌زنه"""
    for _ in range(15):  # حداکثر ۱۵ ثانیه صبر
        await asyncio.sleep(1)
        async for msg in client.iter_messages(chat_id, limit=15):
            if msg.reply_to_msg_id == sent_msg_id and not msg.out and msg.buttons:
                try:
                    await msg.click(text=lambda t: t and MEOWIE_BUTTON_KEYWORD in t)
                except Exception:
                    pass
                return


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
        return "فارم میویی از قبل فعال بود 🐱"
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


HELP_TEXT = """📖 Self-bot commands — full list

🐱 MEOW (send in any chat, from your own account)
meow on            — start meow every 10 min (default) in this chat
meow on 5          — start meow every 5 min in this chat (any number of minutes)
meow off           — stop meow in this chat

🕐 AUTO CLOCK (send from your own account, applies to your whole account)
clock bio on       — bio updates every 60s with Jalali date + time
clock bio off
clock name on      — last name updates every 60s with time only
clock name off
clock font <name>  — choose the digit style used for the clock, options:
                     circle, bold, double, sans, mono, digital, normal
clock font list    — show a live preview of every font option

🌙 AFK (send from your own account, applies to your whole account)
afk on             — turn on AFK with the default message
afk on <message>   — turn on AFK with a custom message, e.g.: afk on sleeping now
afk off            — turn off AFK
(AFK only auto-replies once per person, only in private chats, and never to bots)

🐾 MEOWIE AUTO-FARM (send from your own account)
farm on                 — turn on; if no group is set yet, it asks:
                          "Send the group's numeric ID or link."
                          reply with the ID/link — farm turns on for that group
farm off                — turn off
farm now                — collect once immediately, without waiting for the timer
farm +5                 — increase farm interval by 5 minutes
farm -5                 — decrease farm interval by 5 minutes
farm interval 30        — set farm interval directly, in minutes
farm interval 2h        — set farm interval directly, in hours
(every cycle it sends "پیشی" in the group, waits up to 15s for Meowie's reply
 to that exact message, then clicks the button containing "برداشت")

meow +5            — increase the DEFAULT meow interval (used when you type
                     "meow on" with no number) by 5 minutes
meow -5            — decrease it by 5 minutes

🗑 DELETE MESSAGES (send from your own account)
clean all
  — reply to any of YOUR OWN messages in a chat with this text
  — deletes every message you've ever sent in that chat

delete messages
  — bot asks: "Where should I delete messages from? Reply: group or private"
  — you reply: group
      → bot asks: "Send the group's numeric ID or link."
      → you send it → all your messages in that group are deleted
  — you reply: private
      → bot asks: "Send the numeric ID or username of the person."
      → you send it → all your messages in that private chat are deleted

❓ HELP
help               — show this exact message

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📡 ADMIN-ONLY COMMANDS
(these only work when sent as a DM directly to this account,
 from an account whose numeric ID is in ADMIN_IDS)

All commands above also work the same way in the admin's DM:
meow on / meow on <minutes> / meow off
afk on / afk on <message> / afk off
clock bio on / clock bio off
clock name on / clock name off
farm +5 / farm -5 / farm interval <value>
delete messages   (same group/private flow as above)
help

Extra admin-only commands:
ping
  — replies with round-trip time in ms

farm now
  — collect the farm points immediately, on demand, without waiting for the timer

rmg <text>
  — send this in ANY chat (group or private) where this account is also present.
  — this account will send <text> as its own message in that same chat.
  — example: rmg hi  →  this account sends "hi" there.
  — example: rmg پیشی  →  this account sends "پیشی" and then automatically
    waits for Meowie's reply and clicks the "برداشت میو پوینت ها" button,
    exactly like the farm feature — useful for triggering many self-bot
    accounts in the same group at once.
  — only works if you (the sender) are in this account's ADMIN_IDS.

mio online is gp
  — bot asks: "Send the group's numeric ID or link."
  — optionally add a space and a number of minutes, e.g.: -1001234567890 5
  — activates meow in that group (default 10 min if no number given)

Reply (in ANY chat, group or private) to a message that THIS ACCOUNT sent,
with the word:
پاک   or   delete
  — deletes just that one message

━━━━━━━━━━━━━━
Made by @MRZverse
"""


# ---------- هندلر اصلی (پیام‌های خودِ اکانت) ----------
@client.on(events.NewMessage(outgoing=True))
async def handler(event):
    global awaiting_farm_group, farm_chat_id, farm_interval_seconds, meow_default_seconds
    global delete_flow_stage, clock_digit_font

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

    elif lower == "clock bio off":
        await event.edit(await untoggle_clock_bio())

    elif lower == "clock name on":
        await event.edit(await toggle_clock_name())

    elif lower == "clock name off":
        await event.edit(await untoggle_clock_name())

    elif lower == "clock font list":
        preview = "\n".join(
            f"{name}: {fancy_digits_preview(name)}" for name in DIGIT_FONTS
        )
        await event.edit(f"Available clock fonts:\n{preview}\n\nCurrent: {clock_digit_font}")

    elif lower.startswith("clock font"):
        name = lower[len("clock font"):].strip()
        if name in DIGIT_FONTS:
            clock_digit_font = name
            await event.edit(f"Clock font set to '{name}' ✅ preview: {fancy_time()}")
        else:
            options = ", ".join(DIGIT_FONTS.keys())
            await event.edit(f"Unknown font. Options: {options}")

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
        await event.edit(HELP_TEXT)

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
    global farm_interval_seconds, delete_flow_stage, clock_digit_font

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
            await event.reply(HELP_TEXT)
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
        elif lower == "clock font list":
            preview = "\n".join(
                f"{name}: {fancy_digits_preview(name)}" for name in DIGIT_FONTS
            )
            await event.reply(f"Available clock fonts:\n{preview}\n\nCurrent: {clock_digit_font}")
            return
        elif lower.startswith("clock font"):
            name = lower[len("clock font"):].strip()
            if name in DIGIT_FONTS:
                clock_digit_font = name
                await event.reply(f"Clock font set to '{name}' ✅ preview: {fancy_time()}")
            else:
                options = ", ".join(DIGIT_FONTS.keys())
                await event.reply(f"Unknown font. Options: {options}")
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
