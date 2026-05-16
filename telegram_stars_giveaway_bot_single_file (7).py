# main.py
# -*- coding: utf-8 -*-

import os
import asyncio
import random
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# =========================
# ENV
# =========================

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

if not TOKEN:
    raise Exception("TOKEN не найден!")

# =========================
# BOT
# =========================

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())

# =========================
# DB
# =========================

db = sqlite3.connect("database.db")
sql = db.cursor()

sql.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 0,
    ref_balance INTEGER DEFAULT 0,
    invited_by INTEGER,
    created_at TEXT
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS sponsors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER,
    username TEXT
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prize INTEGER,
    sponsor TEXT,
    message_id INTEGER,
    active INTEGER DEFAULT 1,
    winner INTEGER DEFAULT 0
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS participants (
    giveaway_id INTEGER,
    user_id INTEGER
)
""")

db.commit()

# =========================
# SETTINGS DEFAULT
# =========================

defaults = {
    "ref_enabled": "1",
    "ref_reward": "10"
}

for k, v in defaults.items():
    sql.execute("SELECT * FROM settings WHERE key=?", (k,))
    if not sql.fetchone():
        sql.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            (k, v)
        )
db.commit()

# =========================
# HELPERS
# =========================

def get_setting(key):
    sql.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = sql.fetchone()
    return row[0] if row else None

def set_setting(key, value):
    sql.execute("""
    INSERT OR REPLACE INTO settings (key, value)
    VALUES (?, ?)
    """, (key, str(value)))
    db.commit()

def is_admin(user_id):
    return user_id == ADMIN_ID

def get_user(user_id):
    sql.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    return sql.fetchone()

def add_user(user_id, username, invited_by=None):
    if get_user(user_id):
        return

    sql.execute("""
    INSERT INTO users
    (user_id, username, invited_by, created_at)
    VALUES (?, ?, ?, ?)
    """, (
        user_id,
        username,
        invited_by,
        datetime.now().strftime("%d.%m.%Y %H:%M")
    ))
    db.commit()

    # реферальная система
    if invited_by and invited_by != user_id:
        if get_setting("ref_enabled") == "1":
            reward = int(get_setting("ref_reward"))
            sql.execute("""
            UPDATE users
            SET ref_balance = ref_balance + ?
            WHERE user_id=?
            """, (reward, invited_by))
            db.commit()

def add_balance(user_id, amount):
    sql.execute("""
    UPDATE users
    SET balance = balance + ?
    WHERE user_id=?
    """, (amount, user_id))
    db.commit()

def add_ref_balance(user_id, amount):
    sql.execute("""
    UPDATE users
    SET ref_balance = ref_balance + ?
    WHERE user_id=?
    """, (amount, user_id))
    db.commit()

def remove_balance(user_id, amount):
    sql.execute("""
    UPDATE users
    SET balance = balance - ?
    WHERE user_id=?
    """, (amount, user_id))
    db.commit()

def remove_ref_balance(user_id, amount):
    sql.execute("""
    UPDATE users
    SET ref_balance = ref_balance - ?
    WHERE user_id=?
    """, (amount, user_id))
    db.commit()

async def check_sub(user_id):
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        if member.status in [
            ChatMemberStatus.LEFT,
            ChatMemberStatus.KICKED
        ]:
            return False

        sql.execute("SELECT * FROM sponsors")
        sponsors = sql.fetchall()

        for sponsor in sponsors:
            sponsor_id = sponsor[1]

            try:
                m = await bot.get_chat_member(
                    sponsor_id,
                    user_id
                )

                if m.status in [
                    ChatMemberStatus.LEFT,
                    ChatMemberStatus.KICKED
                ]:
                    return False

            except:
                return False

        return True

    except:
        return False

# =========================
# KEYBOARDS
# =========================

def main_menu():
    kb = InlineKeyboardBuilder()

    kb.row(
        InlineKeyboardButton(
            text="👤 Профиль",
            callback_data="profile"
        )
    )

    kb.row(
        InlineKeyboardButton(
            text="💸 Вывод",
            callback_data="withdraw"
        ),
        InlineKeyboardButton(
            text="🎁 Вывод реф",
            callback_data="withdraw_ref"
        )
    )

    return kb.as_markup()

def admin_menu():
    kb = InlineKeyboardBuilder()

    kb.row(
        InlineKeyboardButton(
            text="🎉 Создать розыгрыш",
            callback_data="create_giveaway"
        )
    )

    kb.row(
        InlineKeyboardButton(
            text="⭐ Выдать звезды",
            callback_data="give_balance"
        )
    )

    kb.row(
        InlineKeyboardButton(
            text="👥 Реф система",
            callback_data="ref_system"
        )
    )

    kb.row(
        InlineKeyboardButton(
            text="📢 Спонсоры",
            callback_data="sponsors"
        )
    )

    kb.row(
        InlineKeyboardButton(
            text="📨 Рассылка",
            callback_data="broadcast"
        )
    )

    return kb.as_markup()

# =========================
# STATES
# =========================

class GiveawayState(StatesGroup):
    waiting_prize = State()

class BroadcastState(StatesGroup):
    waiting_text = State()

class BalanceState(StatesGroup):
    waiting_data = State()

# =========================
# START
# =========================

@dp.message(CommandStart())
async def start(message: Message):

    args = message.text.split()

    ref_id = None

    if len(args) > 1:
        if args[1].startswith("ref_"):
            try:
                ref_id = int(args[1].replace("ref_", ""))
            except:
                pass

    add_user(
        message.from_user.id,
        message.from_user.username,
        ref_id
    )

    text = f"""
<b>🏎 Ferrari Stars Giveaway</b>

✨ Добро пожаловать в премиальный клуб розыгрышей Telegram Stars!

💎 Участвуйте в розыгрышах
⭐ Получайте Stars
🎁 Приглашайте друзей
💸 Выводите награды

━━━━━━━━━━━━━━━
👤 Ваш ID: <code>{message.from_user.id}</code>
"""

    await message.answer(
        text,
        reply_markup=main_menu()
    )

# =========================
# PROFILE
# =========================

@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):

    user = get_user(callback.from_user.id)

    balance = user[2]
    ref_balance = user[3]

    me = await bot.get_me()

    ref_link = (
        f"https://t.me/{me.username}"
        f"?start=ref_{callback.from_user.id}"
    )

    text = f"""
<b>👤 Ваш профиль</b>

⭐ Баланс: <b>{balance}</b>
🎁 Реф баланс: <b>{ref_balance}</b>

🔗 Реферальная ссылка:
<code>{ref_link}</code>

💰 Награда за реферала:
<b>{get_setting("ref_reward")} ⭐</b>
"""

    await callback.message.edit_text(
        text,
        reply_markup=main_menu()
    )

# =========================
# WITHDRAW
# =========================

@dp.callback_query(F.data == "withdraw")
async def withdraw(callback: CallbackQuery):

    user = get_user(callback.from_user.id)

    if user[2] <= 0:
        return await callback.answer(
            "❌ Недостаточно звезд",
            show_alert=True
        )

    text = f"""
💸 <b>Заявка на вывод</b>

👤 Пользователь:
@{callback.from_user.username}

🆔 ID:
<code>{callback.from_user.id}</code>

⭐ Сумма:
<b>{user[2]} Stars</b>
"""

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"accept_{callback.from_user.id}_{user[2]}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"decline_{callback.from_user.id}"
                )
            ]
        ]
    )

    await bot.send_message(
        ADMIN_ID,
        text,
        reply_markup=kb
    )

    await callback.answer(
        "✅ Заявка отправлена админу",
        show_alert=True
    )

# =========================
# WITHDRAW REF
# =========================

@dp.callback_query(F.data == "withdraw_ref")
async def withdraw_ref(callback: CallbackQuery):

    user = get_user(callback.from_user.id)

    if user[3] < 100:
        return await callback.answer(
            "❌ Минимум 100 Stars",
            show_alert=True
        )

    text = f"""
🎁 <b>Вывод реферального баланса</b>

👤 @{callback.from_user.username}
🆔 <code>{callback.from_user.id}</code>

⭐ Сумма:
<b>{user[3]} Stars</b>
"""

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"acceptref_{callback.from_user.id}_{user[3]}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"declineref_{callback.from_user.id}"
                )
            ]
        ]
    )

    await bot.send_message(
        ADMIN_ID,
        text,
        reply_markup=kb
    )

    await callback.answer(
        "✅ Заявка отправлена",
        show_alert=True
    )

# =========================
# ACCEPT / DECLINE
# =========================

@dp.callback_query(F.data.startswith("accept_"))
async def accept(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):
        return

    data = callback.data.split("_")

    user_id = int(data[1])
    amount = int(data[2])

    remove_balance(user_id, amount)

    await bot.send_message(
        user_id,
        f"✅ Вывод {amount} Stars подтвержден!"
    )

    await callback.message.edit_text(
        "✅ Выплата подтверждена"
    )

@dp.callback_query(F.data.startswith("decline_"))
async def decline(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):
        return

    user_id = int(callback.data.split("_")[1])

    await bot.send_message(
        user_id,
        "❌ Выплата отклонена"
    )

    await callback.message.edit_text(
        "❌ Выплата отклонена"
    )

@dp.callback_query(F.data.startswith("acceptref_"))
async def accept_ref(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):
        return

    data = callback.data.split("_")

    user_id = int(data[1])
    amount = int(data[2])

    remove_ref_balance(user_id, amount)

    await bot.send_message(
        user_id,
        f"✅ Реферальный вывод {amount} Stars подтвержден!"
    )

    await callback.message.edit_text(
        "✅ Реф вывод подтвержден"
    )

# =========================
# ADMIN
# =========================

@dp.message(Command("admin"))
async def admin(message: Message):

    if not is_admin(message.from_user.id):
        return

    text = """
<b>⚙️ Админ-панель</b>

Выберите действие:
"""

    await message.answer(
        text,
        reply_markup=admin_menu()
    )

# =========================
# GIVEAWAY CREATE
# =========================

@dp.callback_query(F.data == "create_giveaway")
async def create_giveaway(callback: CallbackQuery, state: FSMContext):

    if not is_admin(callback.from_user.id):
        return

    await state.set_state(GiveawayState.waiting_prize)

    await callback.message.answer(
        "🎉 Введите сумму выигрыша:"
    )

@dp.message(GiveawayState.waiting_prize)
async def giveaway_prize(message: Message, state: FSMContext):

    if not message.text.isdigit():
        return await message.answer(
            "❌ Введите число"
        )

    prize = int(message.text)

    sql.execute("""
    INSERT INTO giveaways (prize)
    VALUES (?)
    """, (prize,))
    db.commit()

    giveaway_id = sql.lastrowid

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎉 Участвовать",
                    url=f"https://t.me/{(await bot.get_me()).username}?start=giveaway_{giveaway_id}"
                )
            ]
        ]
    )

    text = f"""
🏎 <b>Ferrari Stars Giveaway</b>

⭐ Приз:
<b>{prize} Stars</b>

👥 Максимум участников:
<b>12</b>

🎯 Нажмите кнопку ниже
для участия!
"""

    msg = await bot.send_message(
        CHANNEL_ID,
        text,
        reply_markup=kb
    )

    sql.execute("""
    UPDATE giveaways
    SET message_id=?
    WHERE id=?
    """, (msg.message_id, giveaway_id))
    db.commit()

    await message.answer(
        "✅ Розыгрыш создан!"
    )

    await state.clear()

# =========================
# GIVEAWAY JOIN
# =========================

@dp.message(CommandStart(deep_link=True))
async def deep_links(message: Message):

    args = message.text.split()

    if len(args) < 2:
        return

    data = args[1]

    if data.startswith("giveaway_"):

        giveaway_id = int(
            data.replace("giveaway_", "")
        )

        if not await check_sub(message.from_user.id):

            sponsors_text = ""

            sql.execute("SELECT * FROM sponsors")
            sponsors = sql.fetchall()

            for sponsor in sponsors:
                sponsors_text += (
                    f"\n• @{sponsor[2]}"
                )

            text = f"""
❌ Для участия подпишитесь:

📢 Основной канал:
@{CHANNEL_USERNAME}

{sponsors_text}
"""

            return await message.answer(text)

        # emoji captcha
        emojis = ["🔥", "⭐", "🚀", "❤️"]

        target = random.choice(emojis)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=e,
                        callback_data=f"captcha_{giveaway_id}_{e}"
                    ) for e in emojis
                ]
            ]
        )

        await message.answer(
            f"🛡 Нажмите emoji {target}",
            reply_markup=kb
        )

# =========================
# CAPTCHA
# =========================

captcha_answers = {}

@dp.callback_query(F.data.startswith("captcha_"))
async def captcha(callback: CallbackQuery):

    data = callback.data.split("_")

    giveaway_id = int(data[1])
    emoji = data[2]

    msg = callback.message.text

    target = msg.split("emoji ")[1]

    if emoji != target:
        return await callback.answer(
            "❌ Неверно",
            show_alert=True
        )

    sql.execute("""
    SELECT * FROM participants
    WHERE giveaway_id=? AND user_id=?
    """, (
        giveaway_id,
        callback.from_user.id
    ))

    if sql.fetchone():
        return await callback.answer(
            "❌ Вы уже участвуете",
            show_alert=True
        )

    sql.execute("""
    INSERT INTO participants
    VALUES (?, ?)
    """, (
        giveaway_id,
        callback.from_user.id
    ))
    db.commit()

    sql.execute("""
    SELECT COUNT(*)
    FROM participants
    WHERE giveaway_id=?
    """, (giveaway_id,))

    count = sql.fetchone()[0]

    await callback.message.edit_text(
        f"✅ Вы участвуете!\n\n👥 Участников: {count}/12"
    )

    # финал
    if count >= 12:

        dice1 = await bot.send_dice(
            CHANNEL_ID,
            emoji="🎲"
        )

        dice2 = await bot.send_dice(
            CHANNEL_ID,
            emoji="🎲"
        )

        total = (
            dice1.dice.value +
            dice2.dice.value
        )

        if total > 12:
            total = 12

        sql.execute("""
        SELECT user_id
        FROM participants
        WHERE giveaway_id=?
        """, (giveaway_id,))

        users = sql.fetchall()

        winner_id = users[total - 1][0]

        sql.execute("""
        SELECT prize
        FROM giveaways
        WHERE id=?
        """, (giveaway_id,))

        prize = sql.fetchone()[0]

        add_balance(winner_id, prize)

        winner = await bot.get_chat(winner_id)

        await bot.send_message(
            CHANNEL_ID,
            f"""
🏆 <b>Победитель определен!</b>

🎯 Победитель:
@{winner.username}

⭐ Выигрыш:
<b>{prize} Stars</b>

🎲 Выпало число:
<b>{total}</b>
"""
        )

        await bot.send_message(
            winner_id,
            f"""
🎉 Поздравляем!

Вы выиграли
<b>{prize} Stars</b>
"""
        )

# =========================
# GIVE BALANCE
# =========================

@dp.callback_query(F.data == "give_balance")
async def give_balance(callback: CallbackQuery, state: FSMContext):

    if not is_admin(callback.from_user.id):
        return

    await state.set_state(BalanceState.waiting_data)

    await callback.message.answer(
        """
Введите данные:

ID СУММА

Пример:
123456789 100
"""
    )

@dp.message(BalanceState.waiting_data)
async def process_balance(message: Message, state: FSMContext):

    try:
        user_id, amount = message.text.split()

        user_id = int(user_id)
        amount = int(amount)

        add_balance(user_id, amount)

        await message.answer(
            "✅ Звезды начислены"
        )

        await bot.send_message(
            user_id,
            f"⭐ Вам начислено {amount} Stars"
        )

        await state.clear()

    except:
        await message.answer(
            "❌ Ошибка формата"
        )

# =========================
# REF SYSTEM
# =========================

@dp.callback_query(F.data == "ref_system")
async def ref_system(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):
        return

    status = (
        "ВКЛЮЧЕНА"
        if get_setting("ref_enabled") == "1"
        else "ВЫКЛЮЧЕНА"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Переключить",
                    callback_data="toggle_ref"
                )
            ]
        ]
    )

    await callback.message.answer(
        f"""
👥 Реферальная система

Статус:
<b>{status}</b>

Награда:
<b>{get_setting("ref_reward")} ⭐</b>
""",
        reply_markup=kb
    )

@dp.callback_query(F.data == "toggle_ref")
async def toggle_ref(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):
        return

    current = get_setting("ref_enabled")

    new = "0" if current == "1" else "1"

    set_setting("ref_enabled", new)

    await callback.answer(
        "✅ Статус обновлен",
        show_alert=True
    )

# =========================
# SPONSORS
# =========================

@dp.callback_query(F.data == "sponsors")
async def sponsors(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):
        return

    text = """
📢 Управление спонсорами

Добавить:
<code>/add_sponsor CHANNEL_ID USERNAME</code>

Удалить:
<code>/del_sponsor CHANNEL_ID</code>
"""

    await callback.message.answer(text)

@dp.message(Command("add_sponsor"))
async def add_sponsor_cmd(message: Message):

    if not is_admin(message.from_user.id):
        return

    try:
        _, channel_id, username = message.text.split()

        sql.execute("""
        INSERT INTO sponsors
        (channel_id, username)
        VALUES (?, ?)
        """, (
            int(channel_id),
            username.replace("@", "")
        ))

        db.commit()

        await message.answer(
            "✅ Спонсор добавлен"
        )

    except:
        await message.answer(
            "❌ Формат:\n/add_sponsor -100123456789 sponsor"
        )

@dp.message(Command("del_sponsor"))
async def del_sponsor(message: Message):

    if not is_admin(message.from_user.id):
        return

    try:
        _, channel_id = message.text.split()

        sql.execute("""
        DELETE FROM sponsors
        WHERE channel_id=?
        """, (int(channel_id),))

        db.commit()

        await message.answer(
            "✅ Спонсор удален"
        )

    except:
        await message.answer(
            "❌ Ошибка"
        )

# =========================
# BROADCAST
# =========================

@dp.callback_query(F.data == "broadcast")
async def broadcast(callback: CallbackQuery, state: FSMContext):

    if not is_admin(callback.from_user.id):
        return

    await state.set_state(BroadcastState.waiting_text)

    await callback.message.answer(
        "📨 Отправьте текст рассылки"
    )

@dp.message(BroadcastState.waiting_text)
async def process_broadcast(message: Message, state: FSMContext):

    sql.execute("SELECT user_id FROM users")
    users = sql.fetchall()

    success = 0
    failed = 0

    for user in users:

        try:
            await bot.send_message(
                user[0],
                message.text
            )
            success += 1

        except:
            failed += 1

    await message.answer(
        f"""
✅ Рассылка завершена

✔️ Успешно:
{success}

❌ Ошибок:
{failed}
"""
    )

    await state.clear()

# =========================
# RUN
# =========================

async def main():

    print("Bot started!")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
