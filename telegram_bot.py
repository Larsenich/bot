"""
Telegram Bot на aiogram 3.x
Установка: pip install aiogram
Запуск:    python telegram_bot.py
"""

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.methods import DeleteWebhook

logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────────
#                   CONFIG
# ─────────────────────────────────────────────
BOT_TOKEN         = "8729598129:AAHY-YIOuJwGcf-WanBxd-R1aSdtJKKivo8"
OWNER_CHAT_ID     = 8377792182
REMINDER_HOURS_BEFORE = 6

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
    """Фабрика кнопок с цветом и опциональным кастомным эмодзи."""
    kwargs = dict(text=text, style=style)
    if callback_data:
        kwargs["callback_data"] = callback_data
    if url:
        kwargs["url"] = url
    if emoji_key:
        kwargs["icon_custom_emoji_id"] = eb(emoji_key)
    return types.InlineKeyboardButton(**kwargs)


# ─────────────────────────────────────────────
#                   ТЕКСТЫ
# ─────────────────────────────────────────────
TIME_SLOTS = [
    "10:00 – 12:00",
    "12:00 – 14:00",
    "14:00 – 16:00",
    "16:00 – 18:00",
]

PRICES_TEXT = (
    f"{e('money')} <b>Прайс-лист</b>\n\n"
    "• Наращивание ресниц (2D эффект) — 3 200 ₽\n"
    "• Долговременная укладка бровей — 1 700 ₽\n"
    "• Архитектура и окрашивание бровей — 1 200 ₽\n"
    "• Коррекция бровей воском — 600 ₽\n"
    "• Сложное окрашивание волос (декапирование + тон) — от 5 500 ₽\n"
    "• Ламинирование ресниц — 1 900 ₽\n\n"
    f"{e('sparkle')} При записи на 2 услуги — скидка 10%"
)

FAQ_TEXT = (
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

# ─────────────────────────────────────────────
#               ХРАНИЛИЩЕ ДАННЫХ
# ─────────────────────────────────────────────
# user_id -> {"date": "YYYY-MM-DD", "slot": "HH:MM – HH:MM", "comment": "..."}
BOOKINGS: dict = {}

# date_str -> set of booked slots на эту дату (все пользователи)
# Пример: {"2026-03-05": {"10:00 – 12:00", "14:00 – 16:00"}}
BOOKED_SLOTS: dict[str, set] = {}

# user_id -> {"date": ..., "slot": ...}
PENDING_BOOKINGS: dict = {}

# user_id -> True
REMINDERS_SENT: dict = {}

# ─────────────────────────────────────────────
#          УПРАВЛЕНИЕ ЗАНЯТЫМИ СЛОТАМИ
# ─────────────────────────────────────────────

def book_slot(date_str: str, slot: str):
    """Пометить слот как занятый."""
    BOOKED_SLOTS.setdefault(date_str, set()).add(slot)


def free_slot(date_str: str, slot: str):
    """Освободить слот."""
    if date_str in BOOKED_SLOTS:
        BOOKED_SLOTS[date_str].discard(slot)


def available_slots(date_str: str) -> list[str]:
    """Вернуть список свободных слотов на дату."""
    booked = BOOKED_SLOTS.get(date_str, set())
    return [s for s in TIME_SLOTS if s not in booked]


# ─────────────────────────────────────────────
#                  КЛАВИАТУРЫ
# ─────────────────────────────────────────────

def kb_main_menu() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("Часто задаваемые вопросы", callback_data="faq",        style="danger", emoji_key="question")],
        [btn("Цены",                     callback_data="prices",      style="primary", emoji_key="money")],
        [btn("Записаться",               callback_data="book_start",  style="success", emoji_key="calendar")],
    ])


def kb_back() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("Назад", callback_data="back_main", style="default", emoji_key="back")],
    ])


def kb_days() -> types.InlineKeyboardMarkup:
    today   = datetime.now().date()
    days_ru = {"Mon": "Пн", "Tue": "Вт", "Wed": "Ср",
               "Thu": "Чт", "Fri": "Пт", "Sat": "Сб", "Sun": "Вс"}
    buttons, row = [], []
    for i in range(1, 11):
        day   = today + timedelta(days=i)
        label = f"{day.strftime('%d.%m')} ({days_ru.get(day.strftime('%a'), day.strftime('%a'))})"
        # Если на день ещё есть свободные слоты — кнопка зелёная, иначе серая
        date_str   = day.isoformat()
        free_count = len(available_slots(date_str))
        style      = "success" if free_count > 0 else "default"
        row.append(types.InlineKeyboardButton(
            text=label,
            callback_data=f"day_{date_str}",
            style=style,
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([btn("Назад", callback_data="back_main", style="default", emoji_key="back")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_times(date_str: str) -> types.InlineKeyboardMarkup:
    """Показывает только свободные слоты на выбранную дату."""
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
    cancel_text = f"Отменить запись {date_obj.strftime('%d.%m')} - {slot}"
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn(cancel_text,    callback_data=f"cancel_{date_str}|{slot}", style="danger",  emoji_key="cross")],
        [btn("В главное меню", callback_data="back_main",               style="default", emoji_key="back")],
    ])


def kb_reminder(date_str: str, slot: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("Да, приду",            callback_data=f"remind_yes_{date_str}|{slot}", style="success", emoji_key="check")],
        [btn("Нет, отменяю запись",  callback_data=f"remind_no_{date_str}|{slot}",  style="danger",  emoji_key="cross")],
    ])


def kb_to_menu() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("В главное меню", callback_data="back_main", style="default", emoji_key="back")],
    ])


def kb_already_booked(existing: dict) -> types.InlineKeyboardMarkup:
    existing_date_obj  = datetime.fromisoformat(existing["date"])
    existing_day_short = existing_date_obj.strftime("%d.%m")
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn(
            f"Отменить запись {existing_day_short} - {existing['slot']}",
            callback_data=f"cancel_{existing['date']}|{existing['slot']}",
            style="danger",
            emoji_key="cross",
        )],
        [btn("В главное меню", callback_data="back_main", style="default", emoji_key="back")],
    ])


def kb_comment_prompt(date_str: str, slot: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [btn("Укажите услугу и добавьте комментарий", callback_data="comment_start", style="primary", emoji_key="bubble")],
        [btn("В главное меню", callback_data="back_main", style="default", emoji_key="back")],
    ])


# ─────────────────────────────────────────────
#             ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────

def slot_start_datetime(date_str: str, slot: str) -> datetime | None:
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


# ─────────────────────────────────────────────
#           ФОНОВЫЙ ПОТОК: НАПОМИНАНИЯ
# ─────────────────────────────────────────────

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
                        f"Вы придёте?",
                        parse_mode="HTML",
                        reply_markup=kb_reminder(booking["date"], slot),
                    )
                    REMINDERS_SENT[user_id] = True
                    logging.info(f"Напоминание → {user_id}")
                except Exception as ex:
                    logging.error(f"Ошибка напоминания для {user_id}: {ex}")


# ─────────────────────────────────────────────
#                   ХЕНДЛЕРЫ
# ─────────────────────────────────────────────

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        f"{e('wave')} Здравствуйте! Выберите, что вас интересует:",
        parse_mode="HTML",
        reply_markup=kb_main_menu(),
    )


# ── Ввод комментария к записи ─────────────────
@dp.message()
async def handle_comment(message: types.Message):
    user_id = message.from_user.id
    text    = message.text or ""
    pending = PENDING_BOOKINGS.get(user_id)

    if not pending:
        await message.answer("Используйте кнопки меню 👇", reply_markup=kb_main_menu())
        return

    date_str  = pending["date"]
    slot      = pending["slot"]
    date_obj  = datetime.fromisoformat(date_str)
    day_label = date_obj.strftime("%d.%m.%Y")
    comment   = text

    PENDING_BOOKINGS.pop(user_id, None)
    BOOKINGS[user_id] = {"date": date_str, "slot": slot, "comment": comment}
    book_slot(date_str, slot)  # ← помечаем слот как занятый

    full_name = format_name(message.from_user)
    username  = format_username(message.from_user)

    await message.answer_sticker("CAACAgIAAxkBAAEQpltpo_mjDstL7sujcnc_G6-DkV4e6wACcnsAAuIs2UhRBQ42IUSVRjoE")

    await message.answer(
        f"{e('check')} <b>Запись подтверждена!</b>\n\n"
        f"{e('calendar')} Дата: <b>{day_label}</b>\n"
        f"{e('clock')} Время: <b>{slot}</b>\n"
        f"{e('bubble')} Комментарий: {comment}\n\n"
        f"{e('pray')} Пожалуйста, приходите в назначенное время без опозданий!",
        parse_mode="HTML",
        reply_markup=kb_after_booking(date_str, slot, date_obj),
    )

    await bot.send_message(
        OWNER_CHAT_ID,
        f"{e('bell')} <b>Новая запись!</b>\n\n"
        f"{e('person')} Клиент: {full_name} ({username})\n"
        f"{e('calendar')} Дата: <b>{day_label}</b>\n"
        f"{e('clock')} Время: <b>{slot}</b>\n"
        f"{e('bubble')} Комментарий: {comment}",
        parse_mode="HTML",
    )


# ── Callback: главное меню ────────────────────
@dp.callback_query(F.data == "back_main")
async def cb_back_main(query: types.CallbackQuery):
    await query.answer()
    await query.message.answer("Главное меню:", reply_markup=kb_main_menu())


@dp.callback_query(F.data == "faq")
async def cb_faq(query: types.CallbackQuery):
    await query.answer()
    await query.message.answer(FAQ_TEXT, parse_mode="HTML", reply_markup=kb_back())


@dp.callback_query(F.data == "prices")
async def cb_prices(query: types.CallbackQuery):
    await query.answer()
    await query.message.answer(PRICES_TEXT, parse_mode="HTML", reply_markup=kb_back())


# ── Callback: выбор дня ───────────────────────
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
            f"{e('cross')} К сожалению, на <b>{day_label}</b> все слоты уже заняты.\n"
            "Пожалуйста, выберите другой день.",
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


# ── Callback: выбор времени ───────────────────
@dp.callback_query(F.data.startswith("time_"))
async def cb_time(query: types.CallbackQuery):
    await query.answer()
    user_id        = query.from_user.id
    payload        = query.data[5:]
    date_str, slot = payload.split("|", 1)
    date_obj       = datetime.fromisoformat(date_str)
    day_label      = date_obj.strftime("%d.%m.%Y")

    # Проверка: слот уже не занят (на случай гонки)
    if slot not in available_slots(date_str):
        await query.message.answer(
            f"{e('warn')} Этот слот только что заняли! Пожалуйста, выберите другое время.",
            parse_mode="HTML",
            reply_markup=kb_times(date_str),
        )
        return

    # Проверка: у пользователя уже есть своя запись
    existing = BOOKINGS.get(user_id)
    if existing:
        await query.message.answer(
            f"{e('eyes')} Вы уже записаны на другое время.\n"
            "Пожалуйста, отмените запись, если хотите изменить дату или время.",
            parse_mode="HTML",
            reply_markup=kb_already_booked(existing),
        )
        return

    PENDING_BOOKINGS[user_id] = {"date": date_str, "slot": slot}
    await query.message.answer(
        f"{e('calendar')} Вы выбрали дату <b>{day_label}</b> и время <b>{slot}</b>.\n\n"
        f"{e('bubble')} Теперь укажите услугу и добавьте комментарий\n"
        "Нажмите кнопку ниже, а затем одним сообщением опишите услугу и пожелания.",
        parse_mode="HTML",
        reply_markup=kb_comment_prompt(date_str, slot),
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


# ── Callback: отмена записи ───────────────────
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
    free_slot(date_str, slot)  # ← освобождаем слот

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


# ── Callback: ответ на напоминание: придёт ────
@dp.callback_query(F.data.startswith("remind_yes_"))
async def cb_remind_yes(query: types.CallbackQuery):
    await query.answer()
    payload        = query.data[len("remind_yes_"):]
    date_str, slot = payload.split("|", 1)
    date_obj       = datetime.fromisoformat(date_str)
    day_label      = date_obj.strftime("%d.%m.%Y")
    full_name      = format_name(query.from_user)
    username       = format_username(query.from_user)

    await query.message.answer(
        f"{e('check')} Запись подтверждена, ждём вас!",
        parse_mode="HTML",
    )
    await bot.send_message(
        OWNER_CHAT_ID,
        f"{e('check')} <b>Клиент подтвердил визит</b>\n\n"
        f"{e('person')} {full_name} ({username})\n"
        f"{e('calendar')} {day_label} | {e('clock')} {slot}",
        parse_mode="HTML",
    )


# ── Callback: ответ на напоминание: отменяет ──
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
    free_slot(date_str, slot)  # ← освобождаем слот при отмене через напоминание

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
#                   ЗАПУСК
# ─────────────────────────────────────────────

async def main():
    await bot(DeleteWebhook(drop_pending_updates=True))
    asyncio.create_task(reminder_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
