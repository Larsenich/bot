"""
Telegram Bot на aiogram 3.x
Установка: pip install aiogram
Запуск:    python telegram_bot.py

Админ-панель: отправьте /admin боту (только для владельца)
"""

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import DeleteWebhook

logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────────
#                   CONFIG
# ─────────────────────────────────────────────
BOT_TOKEN             = "8729598129:AAHY-YIOuJwGcf-WanBxd-R1aSdtJKKivo8"
OWNER_CHAT_ID         = 8377792182
REMINDER_HOURS_BEFORE = 6

# ─────────────────────────────────────────────
#              НАСТРОЙКИ ОПЛАТЫ
# ─────────────────────────────────────────────
PREPAYMENT_AMOUNT = 500                    # Сумма предоплаты в рублях
PAYMENT_TIMEOUT_H = 1                      # Часов на оплату
CARD_NUMBER       = "2200 7019 1411 8150"  # ← Номер карты
SBP_PHONE         = "+7 900 838-72-36"     # ← Телефон для СБП
SBP_BANK          = "Т-Банк"             # ← Банк для СБП

# ─────────────────────────────────────────────
#              КАСТОМНЫЕ ЭМОДЗИ
# ─────────────────────────────────────────────
EMOJI = {
    "wave":     ("5458904472598095631", "👋"),
    "menu":     ("5368324170671202286", "☰"),
    "back":     ("5352759161945867747", "◀️"),
    "check":    ("5206607081334906820", "✅"),
    "cross":    ("5240241223632954241", "❌"),
    "bell":     ("5285238101344544669", "🔔"),
    "warn":     ("5447644880824181073", "⚠️"),
    "clock":    ("5382194935057372936", "🕒"),
    "calendar": ("5413879192267805083", "📅"),
    "money":    ("5287231198098117669", "💰"),
    "sparkle":  ("5289722755871162900", "✨"),
    "bubble":   ("5443038326535759644", "💬"),
    "question": ("5235711188481883685", "❓"),
    "phone":    ("5285238101344544669", "📲"),
    "paw":      ("5454109785857205810", "🐾"),
    "person":   ("5280818098960611598", "👤"),
    "pray":     ("5256204109538663733", "🙏"),
    "eyes":     ("5210956306952758910", "👀"),
    "down":     ("5231102735817918643", "👇"),
    "edit":     ("5447644880824181073", "✏️"),
    "list":     ("5280818098960611598", "📋"),
    "send":     ("5206607081334906820", "📤"),
    "card":     ("5472250091332993630", "📤"),
    "cardsbp":  ("5445353829304387411", "📤"),
}


def e(key: str) -> str:
    emoji_id, fallback = EMOJI[key]
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


def eb(key: str) -> str:
    return EMOJI[key][0]


def btn(
    text: str,
    callback_data: str = None,
    url: str = None,
    style: str = "default",
    emoji_key: str = None,
) -> types.InlineKeyboardButton:
    kwargs = dict(text=text, style=style)
    if callback_data:
        kwargs["callback_data"] = callback_data
    if url:
        kwargs["url"] = url
    if emoji_key:
        kwargs["icon_custom_emoji_id"] = eb(emoji_key)
    return types.InlineKeyboardButton(**kwargs)


# ─────────────────────────────────────────────
#              FSM СОСТОЯНИЯ
# ─────────────────────────────────────────────
class AdminState(StatesGroup):
    broadcast_text    = State()
    edit_prices       = State()
    edit_faq          = State()
    broadcast_confirm = State()


# ─────────────────────────────────────────────
#               ХРАНИЛИЩЕ ДАННЫХ
# ─────────────────────────────────────────────
# user_id -> {"date": "YYYY-MM-DD", "slot": "HH:MM – HH:MM", "comment": "..."}
BOOKINGS: dict = {}

# date_str -> set of booked slots
BOOKED_SLOTS: dict = {}

# user_id -> {"date": ..., "slot": ...}
PENDING_BOOKINGS: dict = {}

# user_id -> True
REMINDERS_SENT: dict = {}

# Все пользователи кто писал боту (для рассылки)
ALL_USERS: set = set()

# user_id -> {
#   "date": str, "slot": str, "comment": str,
#   "deadline": datetime,
#   "full_name": str, "username": str
# }
PENDING_PAYMENTS: dict = {}

# Динамические тексты (редактируются через админку)
DYNAMIC: dict = {
    "prices": None,
    "faq":    None,
}

# ─────────────────────────────────────────────
#          ДЕФОЛТНЫЕ ТЕКСТЫ
# ─────────────────────────────────────────────
TIME_SLOTS = [
    "10:00 – 12:00",
    "12:00 – 14:00",
    "14:00 – 16:00",
    "16:00 – 18:00",
]

PRICES_DEFAULT = (
    f"{e('money')} <b>Прайс-лист</b>\n\n"
    "• Наращивание ресниц (2D эффект) — 3 200 ₽\n"
    "• Долговременная укладка бровей — 1 700 ₽\n"
    "• Архитектура и окрашивание бровей — 1 200 ₽\n"
    "• Коррекция бровей воском — 600 ₽\n"
    "• Сложное окрашивание волос (декапирование + тон) — от 5 500 ₽\n"
    "• Ламинирование ресниц — 1 900 ₽\n\n"
    f"{e('sparkle')} При записи на 2 услуги — скидка 10%"
)

FAQ_DEFAULT = (
    f"{e('question')} <b>Часто задаваемые вопросы</b>\n\n"
    f"{e('calendar')} <b>Вы работаете в выходные и праздники?</b>\n"
    "Да! Мы работаем ежедневно с 10:00 до 21:00, включая субботу, воскресенье и большинство праздников.\n\n"
    f"{e('clock')} <b>Что делать, если я опаздываю или не могу прийти?</b>\n"
    "Пожалуйста, предупредите нас как можно раньше по телефону или через бота (кнопка «Отменить запись»). "
    "Если вы опаздываете более чем на 15 минут — время процедуры сокращается или запись переносится.\n\n"
    f"{e('paw')} <b>Можно ли прийти с маленьким ребёнком или домашним животным?</b>\n"
    "Да, можно, если это не будет мешать работе.\n\n"
    f"{e('phone')} <b>Как записаться на процедуру?</b>\n"
    "Запись возможна прямо через этого бота (кнопка «Записаться»). "
    "Рекомендуем записываться заранее, чтобы выбрать удобное время."
)


def get_prices() -> str:
    return DYNAMIC["prices"] or PRICES_DEFAULT


def get_faq() -> str:
    return DYNAMIC["faq"] or FAQ_DEFAULT


# ─────────────────────────────────────────────
#          УПРАВЛЕНИЕ ЗАНЯТЫМИ СЛОТАМИ
# ─────────────────────────────────────────────

def book_slot(date_str: str, slot: str):
    BOOKED_SLOTS.setdefault(date_str, set()).add(slot)


def free_slot(date_str: str, slot: str):
    if date_str in BOOKED_SLOTS:
        BOOKED_SLOTS[date_str].discard(slot)


def available_slots(date_str: str) -> list:
    booked = BOOKED_SLOTS.get(date_str, set())
    return [s for s in TIME_SLOTS if s not in booked]


# ─────────────────────────────────────────────
#                  КЛАВИАТУРЫ
# ─────────────────────────────────────────────

def kb_main_menu() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("Часто задаваемые вопросы", callback_data="faq",       style="danger", emoji_key="question")],
        [btn("Цены",                     callback_data="prices",     style="primary", emoji_key="money")],
        [btn("Записаться",               callback_data="book_start", style="success", emoji_key="calendar")],
    ])


def kb_back() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("Назад", callback_data="back_main", style="default", emoji_key="back")],
    ])


def kb_to_menu() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("В главное меню", callback_data="back_main", style="default", emoji_key="back")],
    ])


def kb_days() -> types.InlineKeyboardMarkup:
    today   = datetime.now().date()
    days_ru = {"Mon": "Пн", "Tue": "Вт", "Wed": "Ср",
               "Thu": "Чт", "Fri": "Пт", "Sat": "Сб", "Sun": "Вс"}
    buttons, row = [], []
    for i in range(1, 11):
        day      = today + timedelta(days=i)
        date_str = day.isoformat()
        label    = f"{day.strftime('%d.%m')} ({days_ru.get(day.strftime('%a'), day.strftime('%a'))})"
        style    = "success" if available_slots(date_str) else "default"
        row.append(types.InlineKeyboardButton(text=label, callback_data=f"day_{date_str}", style=style))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([btn("Назад", callback_data="back_main", style="default", emoji_key="back")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_times(date_str: str) -> types.InlineKeyboardMarkup:
    free = available_slots(date_str)
    if not free:
        return kb_back()
    buttons = [
        [btn(slot, callback_data=f"time_{date_str}|{slot}", style="success", emoji_key="clock")]
        for slot in free
    ]
    buttons.append([btn("Назад", callback_data="book_start", style="default", emoji_key="back")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_after_booking(date_str: str, slot: str, date_obj: datetime) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn(f"Отменить запись {date_obj.strftime('%d.%m')} - {slot}",
             callback_data=f"cancel_{date_str}|{slot}", style="danger", emoji_key="cross")],
        [btn("В главное меню", callback_data="back_main", style="default", emoji_key="back")],
    ])


def kb_reminder(date_str: str, slot: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("Да, приду",           callback_data=f"remind_yes_{date_str}|{slot}", style="success", emoji_key="check")],
        [btn("Нет, отменяю запись", callback_data=f"remind_no_{date_str}|{slot}",  style="danger",  emoji_key="cross")],
    ])


def kb_already_booked(existing: dict) -> types.InlineKeyboardMarkup:
    existing_date_obj  = datetime.fromisoformat(existing["date"])
    existing_day_short = existing_date_obj.strftime("%d.%m")
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn(f"Отменить запись {existing_day_short} - {existing['slot']}",
             callback_data=f"cancel_{existing['date']}|{existing['slot']}",
             style="danger", emoji_key="cross")],
        [btn("В главное меню", callback_data="back_main", style="default", emoji_key="back")],
    ])


def kb_comment_prompt() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("Укажите услугу и добавьте комментарий",
             callback_data="comment_start", style="primary", emoji_key="bubble")],
        [btn("В главное меню", callback_data="back_main", style="default", emoji_key="back")],
    ])


def kb_payment(user_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("Я оплатил",      callback_data=f"paid_{user_id}",          style="success", emoji_key="check")],
        [btn("Отменить запись", callback_data=f"cancel_payment_{user_id}", style="danger",  emoji_key="cross")],
    ])


def kb_payment_confirm(user_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("Подтвердить оплату", callback_data=f"pay_confirm_{user_id}", style="success", emoji_key="check")],
        [btn("Отклонить оплату",   callback_data=f"pay_reject_{user_id}",  style="danger",  emoji_key="cross")],
    ])


# ── Клавиатуры админки ───────────────────────

def kb_admin_menu() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("Рассылка",           callback_data="admin_broadcast", style="success", emoji_key="send")],
        [btn("Редактировать цены", callback_data="admin_prices",    style="primary", emoji_key="money")],
        [btn("Редактировать FAQ",  callback_data="admin_faq",       style="primary", emoji_key="question")],
        [btn("Все записи",         callback_data="admin_bookings",  style="default", emoji_key="list")],
        [btn("Закрыть",            callback_data="admin_close",     style="danger",  emoji_key="cross")],
    ])


def kb_admin_back() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("Назад в админку", callback_data="admin_menu", style="default", emoji_key="back")],
    ])


def kb_broadcast_confirm() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("Отправить всем", callback_data="admin_broadcast_send",   style="success", emoji_key="send")],
        [btn("Отменить",       callback_data="admin_broadcast_cancel", style="danger",  emoji_key="cross")],
    ])


def kb_admin_bookings(bookings: dict) -> types.InlineKeyboardMarkup:
    buttons = []
    for uid, b in bookings.items():
        date_obj = datetime.fromisoformat(b["date"])
        label    = f"❌ {date_obj.strftime('%d.%m')} {b['slot']} — {b.get('comment', '')[:20]}"
        buttons.append([types.InlineKeyboardButton(
            text=label,
            callback_data=f"admin_cancel_{uid}|{b['date']}|{b['slot']}",
            style="danger",
        )])
    buttons.append([btn("Назад в админку", callback_data="admin_menu", style="default", emoji_key="back")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


# ─────────────────────────────────────────────
#             ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────

def slot_start_datetime(date_str: str, slot: str):
    try:
        for sep in (" – ", " - ", "–", "-"):
            if sep in slot:
                start_time_str = slot.split(sep)[0].strip()
                break
        else:
            return None
        return datetime.strptime(f"{date_str} {start_time_str}", "%Y-%m-%d %H:%M")
    except Exception:
        return None


def format_name(user: types.User) -> str:
    name = user.first_name or ""
    if user.last_name:
        name += " " + user.last_name
    return name


def format_username(user: types.User) -> str:
    return f"@{user.username}" if user.username else "нет username"


def entities_to_html(text: str, entities: list) -> str:
    if not entities:
        return text

    utf16_offsets = []
    pos = 0
    for ch in text:
        utf16_offsets.append(pos)
        pos += 2 if ord(ch) > 0xFFFF else 1
    utf16_offsets.append(pos)
    utf16_to_char = {v: k for k, v in enumerate(utf16_offsets)}

    def to_char(utf16_off: int) -> int:
        return utf16_to_char.get(utf16_off, len(text))

    opens: dict    = {}
    closes: dict   = {}
    replaces: dict = {}

    for en in entities:
        s   = to_char(en.offset)
        end = to_char(en.offset + en.length)
        if en.type == "custom_emoji":
            fallback = text[s:end]
            replaces[s] = (end, f'<tg-emoji emoji-id="{en.custom_emoji_id}">{fallback}</tg-emoji>')
        elif en.type == "bold":
            opens.setdefault(s, []).append("<b>")
            closes.setdefault(end, []).append("</b>")
        elif en.type == "italic":
            opens.setdefault(s, []).append("<i>")
            closes.setdefault(end, []).append("</i>")
        elif en.type == "underline":
            opens.setdefault(s, []).append("<u>")
            closes.setdefault(end, []).append("</u>")
        elif en.type == "strikethrough":
            opens.setdefault(s, []).append("<s>")
            closes.setdefault(end, []).append("</s>")
        elif en.type == "code":
            opens.setdefault(s, []).append("<code>")
            closes.setdefault(end, []).append("</code>")

    result: list = []
    i = 0
    n = len(text)

    while i <= n:
        for tag in closes.get(i, []):
            result.append(tag)
        if i == n:
            break
        if i in replaces:
            end_pos, html = replaces[i]
            result.append(html)
            i = end_pos
            continue
        for tag in opens.get(i, []):
            result.append(tag)
        ch = text[i]
        if   ch == "&": result.append("&amp;")
        elif ch == "<": result.append("&lt;")
        elif ch == ">": result.append("&gt;")
        else:           result.append(ch)
        i += 1

    return "".join(result)


def is_admin(user_id: int) -> bool:
    return user_id == OWNER_CHAT_ID


# ─────────────────────────────────────────────
#        ФОНОВЫЕ ЗАДАЧИ: НАПОМИНАНИЯ И ОПЛАТА
# ─────────────────────────────────────────────

async def payment_checker(bot: Bot):
    """Каждые 60 сек проверяет дедлайн оплаты. Если истёк — отменяет запись."""
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        for user_id, pdata in list(PENDING_PAYMENTS.items()):
            if now >= pdata["deadline"]:
                PENDING_PAYMENTS.pop(user_id, None)
                free_slot(pdata["date"], pdata["slot"])
                logging.info(f"Оплата не поступила, запись отменена → {user_id}")
                day_label = datetime.fromisoformat(pdata["date"]).strftime("%d.%m.%Y")
                try:
                    await bot.send_message(
                        user_id,
                        f"{e('cross')} Время на оплату истекло.\n"
                        f"Ваша запись на <b>{day_label}</b> в <b>{pdata['slot']}</b> была отменена.\n\n"
                        f"Вы можете записаться снова через меню.",
                        parse_mode="HTML",
                        reply_markup=kb_main_menu(),
                    )
                except Exception:
                    pass
                try:
                    await bot.send_message(
                        OWNER_CHAT_ID,
                        f"{e('warn')} <b>Оплата не поступила — запись отменена</b>\n\n"
                        f"{e('person')} {pdata['full_name']} ({pdata['username']})\n"
                        f"{e('calendar')} {day_label} | {e('clock')} {pdata['slot']}",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass


async def reminder_loop(bot: Bot):
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        for user_id, booking in list(BOOKINGS.items()):
            if REMINDERS_SENT.get(user_id):
                continue
            start_dt = slot_start_datetime(booking["date"], booking["slot"])
            if start_dt is None:
                continue
            hours_left = (start_dt - now).total_seconds() / 3600
            if 0 < hours_left <= REMINDER_HOURS_BEFORE:
                date_obj  = datetime.fromisoformat(booking["date"])
                day_label = date_obj.strftime("%d.%m.%Y")
                slot      = booking["slot"]
                try:
                    await bot.send_message(
                        user_id,
                        f"{e('clock')} Ваша запись <b>{day_label}</b> в <b>{slot}</b> уже совсем скоро!\n\n"
                        "Вы придёте?",
                        parse_mode="HTML",
                        reply_markup=kb_reminder(booking["date"], slot),
                    )
                    REMINDERS_SENT[user_id] = True
                    logging.info(f"Напоминание → {user_id}")
                except Exception as ex:
                    logging.error(f"Ошибка напоминания для {user_id}: {ex}")


# ─────────────────────────────────────────────
#                 ИНИЦИАЛИЗАЦИЯ
# ─────────────────────────────────────────────

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())


# ─────────────────────────────────────────────
#           ХЕНДЛЕРЫ ПОЛЬЗОВАТЕЛЯ
# ─────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    ALL_USERS.add(message.from_user.id)
    await message.answer(
        f"{e('wave')} Здравствуйте! Выберите, что вас интересует:",
        parse_mode="HTML",
        reply_markup=kb_main_menu(),
    )


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "⚙️ <b>Админ-панель</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=kb_admin_menu(),
    )


@dp.message(AdminState.broadcast_text, F.photo)
async def handle_broadcast_photo(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    file_id      = message.photo[-1].file_id
    caption      = message.caption or ""
    caption_html = entities_to_html(caption, message.caption_entities or [])
    await state.update_data(broadcast_text=caption_html, broadcast_photo=file_id)
    await state.set_state(AdminState.broadcast_confirm)
    await message.answer_photo(
        file_id,
        caption=(
            f"📤 <b>Предпросмотр рассылки:</b>\n\n{caption_html}\n\n"
            f"Будет отправлено: <b>{len(ALL_USERS)}</b> пользователям.\nОтправить?"
        ),
        parse_mode="HTML",
        reply_markup=kb_broadcast_confirm(),
    )


@dp.message()
async def handle_text(message: types.Message, state: FSMContext):
    ALL_USERS.add(message.from_user.id)
    user_id       = message.from_user.id
    text          = message.text or ""
    current_state = await state.get_state()

    # ── Состояния FSM (только для админа) ────
    if current_state == AdminState.broadcast_text:
        await state.update_data(broadcast_text=text, broadcast_photo=None)
        await state.set_state(AdminState.broadcast_confirm)
        await message.answer(
            f"📤 <b>Предпросмотр рассылки:</b>\n\n{text}\n\n"
            f"Будет отправлено: <b>{len(ALL_USERS)}</b> пользователям.\nОтправить?",
            parse_mode="HTML",
            reply_markup=kb_broadcast_confirm(),
        )
        return

    if current_state == AdminState.edit_prices:
        new_text = entities_to_html(text, message.entities or [])
        DYNAMIC["prices"] = new_text
        await state.clear()
        await message.answer(
            f"{e('check')} <b>Цены обновлены!</b>\n\nПредпросмотр:\n\n{new_text}",
            parse_mode="HTML",
            reply_markup=kb_admin_back(),
        )
        return

    if current_state == AdminState.edit_faq:
        new_text = entities_to_html(text, message.entities or [])
        DYNAMIC["faq"] = new_text
        await state.clear()
        await message.answer(
            f"{e('check')} <b>FAQ обновлён!</b>\n\nПредпросмотр:\n\n{new_text}",
            parse_mode="HTML",
            reply_markup=kb_admin_back(),
        )
        return

    # ── Ввод комментария к записи ─────────────
    pending = PENDING_BOOKINGS.get(user_id)
    if not pending:
        await message.answer("Используйте кнопки меню 👇", reply_markup=kb_main_menu())
        return

    date_str  = pending["date"]
    slot      = pending["slot"]
    date_obj  = datetime.fromisoformat(date_str)
    day_label = date_obj.strftime("%d.%m.%Y")
    comment   = text

    full_name = format_name(message.from_user)
    username  = format_username(message.from_user)

    # Резервируем слот временно (до подтверждения оплаты)
    book_slot(date_str, slot)
    PENDING_BOOKINGS.pop(user_id, None)

    # Сохраняем в ожидание оплаты
    deadline = datetime.now() + timedelta(hours=PAYMENT_TIMEOUT_H)
    PENDING_PAYMENTS[user_id] = {
        "date":      date_str,
        "slot":      slot,
        "comment":   comment,
        "deadline":  deadline,
        "full_name": full_name,
        "username":  username,
    }

    deadline_str = deadline.strftime("%H:%M")
    await message.answer_sticker("CAACAgIAAxkBAAEQpltpo_mjDstL7sujcnc_G6-DkV4e6wACcnsAAuIs2UhRBQ42IUSVRjoE")
    await message.answer(
        f"{e('money')} <b>Для подтверждения записи внесите предоплату</b>\n\n"
        f"{e('calendar')} Дата: <b>{day_label}</b>\n"
        f"{e('clock')} Время: <b>{slot}</b>\n\n"
        f"{e('card')} <b>Карта:</b> <code>{CARD_NUMBER}</code>\n"
        f"{e('cardsbp')} <b>СБП:</b> <code>{SBP_PHONE}</code> ({SBP_BANK})\n\n"
        f"{e('money')} Сумма: <b>{PREPAYMENT_AMOUNT} ₽</b>\n\n"
        f"{e('warn')} После оплаты нажмите кнопку ниже — мы проверим поступление.\n"
        f"Оплатить нужно до <b>{deadline_str}</b>, иначе запись отменится автоматически.",
        parse_mode="HTML",
        reply_markup=kb_payment(user_id),
    )


# ─────────────────────────────────────────────
#        CALLBACK-ХЕНДЛЕРЫ: ОПЛАТА
# ─────────────────────────────────────────────

@dp.callback_query(F.data.startswith("paid_"))
async def cb_paid(query: types.CallbackQuery):
    """Пользователь нажал «Я оплатил» — уведомляем админа."""
    await query.answer()
    user_id = query.from_user.id
    pdata   = PENDING_PAYMENTS.get(user_id)

    if not pdata:
        await query.message.answer(
            f"{e('cross')} Заявка не найдена или время истекло.",
            parse_mode="HTML",
            reply_markup=kb_main_menu(),
        )
        return

    day_label = datetime.fromisoformat(pdata["date"]).strftime("%d.%m.%Y")

    await query.message.answer(
        f"{e('clock')} Запрос отправлен на проверку.\n"
        f"Как только оплата подтвердится — вы получите уведомление.",
        parse_mode="HTML",
    )

    await bot.send_message(
        OWNER_CHAT_ID,
        f"{e('bell')} <b>Клиент сообщил об оплате!</b>\n\n"
        f"{e('person')} {pdata['full_name']} ({pdata['username']})\n"
        f"{e('calendar')} Дата: <b>{day_label}</b>\n"
        f"{e('clock')} Время: <b>{pdata['slot']}</b>\n"
        f"{e('bubble')} Услуга: {pdata['comment']}\n"
        f"💰 Сумма: <b>{PREPAYMENT_AMOUNT} ₽</b>",
        parse_mode="HTML",
        reply_markup=kb_payment_confirm(user_id),
    )


@dp.callback_query(F.data.startswith("cancel_payment_"))
async def cb_cancel_payment(query: types.CallbackQuery):
    """Пользователь сам отменил во время ожидания оплаты."""
    await query.answer()
    user_id = query.from_user.id
    pdata   = PENDING_PAYMENTS.pop(user_id, None)

    if pdata:
        free_slot(pdata["date"], pdata["slot"])
        day_label = datetime.fromisoformat(pdata["date"]).strftime("%d.%m.%Y")
        await bot.send_message(
            OWNER_CHAT_ID,
            f"{e('warn')} <b>Клиент отменил запись (не оплатил)</b>\n\n"
            f"{e('person')} {pdata['full_name']} ({pdata['username']})\n"
            f"{e('calendar')} {day_label} | {e('clock')} {pdata['slot']}",
            parse_mode="HTML",
        )

    await query.message.answer(
        f"{e('cross')} Запись отменена.",
        parse_mode="HTML",
        reply_markup=kb_main_menu(),
    )


@dp.callback_query(F.data.startswith("pay_confirm_"))
async def cb_pay_confirm(query: types.CallbackQuery):
    """Админ подтвердил оплату — переводим в активные записи."""
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    await query.answer("Оплата подтверждена ✅")

    user_id = int(query.data[len("pay_confirm_"):])
    pdata   = PENDING_PAYMENTS.pop(user_id, None)

    if not pdata:
        await query.message.answer("Запись уже не актуальна (истекла или отменена).")
        return

    date_obj  = datetime.fromisoformat(pdata["date"])
    day_label = date_obj.strftime("%d.%m.%Y")

    BOOKINGS[user_id] = {
        "date":    pdata["date"],
        "slot":    pdata["slot"],
        "comment": pdata["comment"],
    }

    try:
        await bot.send_message(
            user_id,
            f"{e('check')} <b>Оплата подтверждена! Запись активна.</b>\n\n"
            f"{e('calendar')} Дата: <b>{day_label}</b>\n"
            f"{e('clock')} Время: <b>{pdata['slot']}</b>\n\n"
            f"{e('pray')} Ждём вас! Приходите в назначенное время.",
            parse_mode="HTML",
            reply_markup=kb_after_booking(pdata["date"], pdata["slot"], date_obj),
        )
    except Exception:
        pass

    await query.message.answer(
        f"{e('check')} Запись подтверждена: {pdata['full_name']} — {day_label} {pdata['slot']}.",
        parse_mode="HTML",
        reply_markup=kb_admin_back(),
    )
    await bot.send_message(
        OWNER_CHAT_ID,
        f"{e('bell')} <b>Новая запись (оплата получена)</b>\n\n"
        f"{e('person')} {pdata['full_name']} ({pdata['username']})\n"
        f"{e('calendar')} {day_label} | {e('clock')} {pdata['slot']}\n"
        f"{e('bubble')} {pdata['comment']}\n"
        f"💰 Предоплата: {PREPAYMENT_AMOUNT} ₽",
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("pay_reject_"))
async def cb_pay_reject(query: types.CallbackQuery):
    """Админ отклонил оплату."""
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    await query.answer("Оплата отклонена ❌")

    user_id = int(query.data[len("pay_reject_"):])
    pdata   = PENDING_PAYMENTS.pop(user_id, None)

    if not pdata:
        await query.message.answer("Запись уже не актуальна.")
        return

    free_slot(pdata["date"], pdata["slot"])
    day_label = datetime.fromisoformat(pdata["date"]).strftime("%d.%m.%Y")

    try:
        await bot.send_message(
            user_id,
            f"{e('cross')} <b>Оплата не подтверждена.</b>\n\n"
            "Возможно, сумма или реквизиты указаны неверно.\n"
            "Пожалуйста, свяжитесь с нами для уточнения.",
            parse_mode="HTML",
            reply_markup=kb_main_menu(),
        )
    except Exception:
        pass

    await query.message.answer(
        f"{e('cross')} Оплата отклонена. Слот освобождён.\n"
        f"{pdata['full_name']} — {day_label} {pdata['slot']}",
        parse_mode="HTML",
        reply_markup=kb_admin_back(),
    )


# ─────────────────────────────────────────────
#        CALLBACK-ХЕНДЛЕРЫ ПОЛЬЗОВАТЕЛЯ
# ─────────────────────────────────────────────

@dp.callback_query(F.data == "back_main")
async def cb_back_main(query: types.CallbackQuery):
    await query.answer()
    ALL_USERS.add(query.from_user.id)
    await query.message.answer("Главное меню:", reply_markup=kb_main_menu())


@dp.callback_query(F.data == "faq")
async def cb_faq(query: types.CallbackQuery):
    await query.answer()
    await query.message.answer(get_faq(), parse_mode="HTML", reply_markup=kb_back())


@dp.callback_query(F.data == "prices")
async def cb_prices(query: types.CallbackQuery):
    await query.answer()
    await query.message.answer(get_prices(), parse_mode="HTML", reply_markup=kb_back())


@dp.callback_query(F.data == "book_start")
async def cb_book_start(query: types.CallbackQuery):
    await query.answer()
    await query.message.answer(
        f"{e('calendar')} Выберите удобный день:",
        parse_mode="HTML",
        reply_markup=kb_days(),
    )


@dp.callback_query(F.data.startswith("day_"))
async def cb_day(query: types.CallbackQuery):
    await query.answer()
    date_str  = query.data[4:]
    date_obj  = datetime.fromisoformat(date_str)
    day_label = date_obj.strftime("%d.%m.%Y")
    free      = available_slots(date_str)
    if not free:
        await query.message.answer(
            f"{e('cross')} На <b>{day_label}</b> все слоты заняты. Выберите другой день.",
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [btn("Выбрать другой день", callback_data="book_start", style="primary", emoji_key="calendar")],
                [btn("В главное меню",      callback_data="back_main",  style="default", emoji_key="back")],
            ]),
        )
        return
    await query.message.answer(
        f"{e('clock')} Вы выбрали <b>{day_label}</b>.\nВыберите удобное время:",
        parse_mode="HTML",
        reply_markup=kb_times(date_str),
    )


@dp.callback_query(F.data.startswith("time_"))
async def cb_time(query: types.CallbackQuery):
    await query.answer()
    user_id        = query.from_user.id
    payload        = query.data[5:]
    date_str, slot = payload.split("|", 1)
    date_obj       = datetime.fromisoformat(date_str)
    day_label      = date_obj.strftime("%d.%m.%Y")

    if slot not in available_slots(date_str):
        await query.message.answer(
            f"{e('warn')} Этот слот только что заняли! Выберите другое время.",
            parse_mode="HTML",
            reply_markup=kb_times(date_str),
        )
        return

    existing = BOOKINGS.get(user_id) or PENDING_PAYMENTS.get(user_id)
    if existing:
        await query.message.answer(
            f"{e('eyes')} Вы уже записаны или ожидаете подтверждения оплаты.\n"
            "Дождитесь подтверждения или отмените текущую запись.",
            parse_mode="HTML",
            reply_markup=kb_already_booked(existing) if user_id in BOOKINGS else kb_to_menu(),
        )
        return

    PENDING_BOOKINGS[user_id] = {"date": date_str, "slot": slot}
    await query.message.answer(
        f"{e('calendar')} Вы выбрали дату <b>{day_label}</b> и время <b>{slot}</b>.\n\n"
        f"{e('bubble')} Теперь укажите услугу и добавьте комментарий\n"
        "Нажмите кнопку ниже, а затем одним сообщением опишите услугу и пожелания.",
        parse_mode="HTML",
        reply_markup=kb_comment_prompt(),
    )


@dp.callback_query(F.data == "comment_start")
async def cb_comment_start(query: types.CallbackQuery):
    await query.answer()
    user_id = query.from_user.id
    if not PENDING_BOOKINGS.get(user_id):
        await query.message.answer(
            "Сначала выберите дату и время через меню «Записаться».",
            reply_markup=kb_to_menu(),
        )
        return
    await query.message.answer(
        f"{e('bubble')} Пожалуйста, одним следующим сообщением укажите услугу и добавьте комментарий",
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("cancel_"))
async def cb_cancel(query: types.CallbackQuery):
    await query.answer()
    user_id        = query.from_user.id
    payload        = query.data[7:]
    date_str, slot = payload.split("|", 1)

    if not BOOKINGS.get(user_id):
        await query.message.answer("У вас нет активной записи.", reply_markup=kb_to_menu())
        return

    BOOKINGS.pop(user_id, None)
    REMINDERS_SENT.pop(user_id, None)
    free_slot(date_str, slot)

    date_obj  = datetime.fromisoformat(date_str)
    day_label = date_obj.strftime("%d.%m.%Y")
    full_name = format_name(query.from_user)
    username  = format_username(query.from_user)

    await bot.send_message(
        OWNER_CHAT_ID,
        f"{e('warn')} <b>Отмена записи</b>\n\n"
        f"{e('person')} Клиент: {full_name} ({username})\n"
        f"{e('calendar')} Дата: <b>{day_label}</b>\n"
        f"{e('clock')} Время: <b>{slot}</b>",
        parse_mode="HTML",
    )
    await query.message.answer(
        f"{e('cross')} Запись отменена.",
        parse_mode="HTML",
        reply_markup=kb_to_menu(),
    )


@dp.callback_query(F.data.startswith("remind_yes_"))
async def cb_remind_yes(query: types.CallbackQuery):
    await query.answer()
    payload        = query.data[len("remind_yes_"):]
    date_str, slot = payload.split("|", 1)
    date_obj       = datetime.fromisoformat(date_str)
    day_label      = date_obj.strftime("%d.%m.%Y")
    full_name      = format_name(query.from_user)
    username       = format_username(query.from_user)

    await query.message.answer(f"{e('check')} Запись подтверждена, ждём вас!", parse_mode="HTML")
    await bot.send_message(
        OWNER_CHAT_ID,
        f"{e('check')} <b>Клиент подтвердил визит</b>\n\n"
        f"{e('person')} {full_name} ({username})\n"
        f"{e('calendar')} {day_label} | {e('clock')} {slot}",
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("remind_no_"))
async def cb_remind_no(query: types.CallbackQuery):
    await query.answer()
    user_id        = query.from_user.id
    payload        = query.data[len("remind_no_"):]
    date_str, slot = payload.split("|", 1)
    date_obj       = datetime.fromisoformat(date_str)
    day_label      = date_obj.strftime("%d.%m.%Y")
    full_name      = format_name(query.from_user)
    username       = format_username(query.from_user)

    BOOKINGS.pop(user_id, None)
    REMINDERS_SENT.pop(user_id, None)
    free_slot(date_str, slot)

    await query.message.answer(
        f"{e('cross')} Запись отменена\nБудем рады видеть вас в другой раз!",
        parse_mode="HTML",
        reply_markup=kb_to_menu(),
    )
    await bot.send_message(
        OWNER_CHAT_ID,
        f"{e('cross')} <b>Клиент отменил запись через напоминание</b>\n\n"
        f"{e('person')} {full_name} ({username})\n"
        f"{e('calendar')} {day_label} | {e('clock')} {slot}",
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#          CALLBACK-ХЕНДЛЕРЫ АДМИНКИ
# ─────────────────────────────────────────────

@dp.callback_query(F.data == "admin_menu")
async def cb_admin_menu(query: types.CallbackQuery, state: FSMContext):
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    await state.clear()
    await query.answer()
    await query.message.answer(
        "⚙️ <b>Админ-панель</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=kb_admin_menu(),
    )


@dp.callback_query(F.data == "admin_close")
async def cb_admin_close(query: types.CallbackQuery, state: FSMContext):
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    await state.clear()
    await query.answer("Закрыто")
    await query.message.delete()


@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(query: types.CallbackQuery, state: FSMContext):
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    await query.answer()
    await state.set_state(AdminState.broadcast_text)
    await query.message.answer(
        f"📤 <b>Рассылка</b>\n\n"
        f"Пользователей в базе: <b>{len(ALL_USERS)}</b>\n\n"
        "Отправьте <b>текст</b> или <b>фото с подписью</b> для рассылки.\n"
        "Поддерживается HTML-разметка и кастомные эмодзи.\n\n"
        "Для отмены нажмите /admin",
        parse_mode="HTML",
        reply_markup=kb_admin_back(),
    )


@dp.callback_query(F.data == "admin_broadcast_send")
async def cb_broadcast_send(query: types.CallbackQuery, state: FSMContext):
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    await query.answer()
    data     = await state.get_data()
    text     = data.get("broadcast_text", "")
    photo_id = data.get("broadcast_photo")
    await state.clear()

    sent, failed = 0, 0
    for user_id in list(ALL_USERS):
        try:
            if photo_id:
                await bot.send_photo(user_id, photo_id, caption=text, parse_mode="HTML")
            else:
                await bot.send_message(user_id, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await query.message.answer(
        f"{e('check')} <b>Рассылка завершена</b>\n\n"
        f"✅ Отправлено: <b>{sent}</b>\n"
        f"❌ Не доставлено: <b>{failed}</b>",
        parse_mode="HTML",
        reply_markup=kb_admin_back(),
    )


@dp.callback_query(F.data == "admin_broadcast_cancel")
async def cb_broadcast_cancel(query: types.CallbackQuery, state: FSMContext):
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    await state.clear()
    await query.answer("Рассылка отменена")
    await query.message.answer(
        "⚙️ <b>Админ-панель</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=kb_admin_menu(),
    )


@dp.callback_query(F.data == "admin_prices")
async def cb_admin_prices(query: types.CallbackQuery, state: FSMContext):
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    await query.answer()
    await state.set_state(AdminState.edit_prices)
    await query.message.answer(
        f"✏️ <b>Редактирование цен</b>\n\n"
        f"Текущий текст:\n{get_prices()}\n\n"
        "Отправьте новый текст прайса (поддерживается HTML и кастомные эмодзи).\n"
        "Для отмены нажмите /admin",
        parse_mode="HTML",
        reply_markup=kb_admin_back(),
    )


@dp.callback_query(F.data == "admin_faq")
async def cb_admin_faq(query: types.CallbackQuery, state: FSMContext):
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    await query.answer()
    await state.set_state(AdminState.edit_faq)
    await query.message.answer(
        f"✏️ <b>Редактирование FAQ</b>\n\n"
        f"Текущий текст:\n{get_faq()}\n\n"
        "Отправьте новый текст FAQ (поддерживается HTML и кастомные эмодзи).\n"
        "Для отмены нажмите /admin",
        parse_mode="HTML",
        reply_markup=kb_admin_back(),
    )


@dp.callback_query(F.data == "admin_bookings")
async def cb_admin_bookings(query: types.CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    await query.answer()

    if not BOOKINGS:
        await query.message.answer(
            "📋 <b>Активных записей нет</b>",
            parse_mode="HTML",
            reply_markup=kb_admin_back(),
        )
        return

    lines = [f"📋 <b>Активные записи ({len(BOOKINGS)})</b>\n"]
    for uid, b in BOOKINGS.items():
        date_obj = datetime.fromisoformat(b["date"])
        lines.append(
            f"• {date_obj.strftime('%d.%m.%Y')} {b['slot']}\n"
            f"  {e('bubble')} {b.get('comment', '—')}"
        )

    await query.message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kb_admin_bookings(BOOKINGS),
    )


@dp.callback_query(F.data.startswith("admin_cancel_"))
async def cb_admin_cancel_booking(query: types.CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    await query.answer()

    payload              = query.data[len("admin_cancel_"):]
    uid_str, date_str, slot = payload.split("|", 2)
    uid                  = int(uid_str)

    if uid not in BOOKINGS:
        await query.message.answer("Запись уже не существует.", reply_markup=kb_admin_back())
        return

    BOOKINGS.pop(uid, None)
    REMINDERS_SENT.pop(uid, None)
    free_slot(date_str, slot)

    date_obj  = datetime.fromisoformat(date_str)
    day_label = date_obj.strftime("%d.%m.%Y")

    try:
        await bot.send_message(
            uid,
            f"{e('warn')} Ваша запись на <b>{day_label}</b> в <b>{slot}</b> была отменена администратором.\n"
            "Если это ошибка, пожалуйста, свяжитесь с нами.",
            parse_mode="HTML",
            reply_markup=kb_main_menu(),
        )
    except Exception:
        pass

    await query.message.answer(
        f"{e('check')} Запись на <b>{day_label}</b> {slot} отменена.",
        parse_mode="HTML",
        reply_markup=kb_admin_back(),
    )


# ─────────────────────────────────────────────
#                   ЗАПУСК
# ─────────────────────────────────────────────

async def main():
    await bot(DeleteWebhook(drop_pending_updates=True))
    asyncio.create_task(reminder_loop(bot))
    asyncio.create_task(payment_checker(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
