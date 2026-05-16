# ================================
# Ferrari Giveaway Bot | aiogram 3.7+
# Single file for BotHost.ru
# ================================

import asyncio
import logging
import random
import sqlite3
import os

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from dotenv import load_dotenv

# ================================
# LOAD ENV
# ================================

load_dotenv()

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())

logging.basicConfig(level=logging.INFO)

# ================================
# DATABASE
# ================================

db = sqlite3.connect("database.db")
sql = db.cursor()

sql.execute("""
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 0,
    ref_balance INTEGER DEFAULT 0,
    invited_by INTEGER,
    invited INTEGER DEFAULT 0
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS giveaways(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prize INTEGER,
    sponsor TEXT,
    active INTEGER DEFAULT 1,
    winner INTEGER
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS participants(
    giveaway_id INTEGER,
    user_id INTEGER
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS withdraws(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    type TEXT,
    status TEXT DEFAULT 'pending'
)
""")

db.commit()

# ================================
# SETTINGS
# ================================

def get_setting(key, default=None):
    sql.execute("SELECT value FROM settings WHERE key=?", (key,))
    data = sql.fetchone()
    return data[0] if data else default

def set_setting(key, value):
    sql.execute("""
    INSERT OR REPLACE INTO settings(key, value)
    VALUES(?, ?)
    """, (key, str(value)))
    db.commit()

if get_setting("ref_enabled") is None:
    set_setting("ref_enabled", "1")

if get_setting("ref_reward") is None:
    set_setting("ref_reward", "10")

# ================================
# FSM
# ================================

class GiveawayState(StatesGroup):
    waiting_prize = State()
    waiting_sponsor = State()
    confirm = State()

class BroadcastState(StatesGroup):
    waiting_text = State()

class SponsorState(StatesGroup):
    waiting_channel = State()

class RefRewardState(StatesGroup):
    waiting_reward = State()

# ================================
# KEYBOARDS
# ================================

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile")
        ],
        [
            InlineKeyboardButton(text="💸 Вывод", callback_data="withdraw"),
            InlineKeyboardButton(text="🎁 Вывод реф", callback_data="withdraw_ref")
        ]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎉 Создать розыгрыш", callback_data="create_giveaway")
        ],
        [
            InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast")
        ],
        [
            InlineKeyboardButton(text="🎁 Реф система", callback_data="ref_system")
        ],
        [
            InlineKeyboardButton(text="🤝 Спонсор", callback_data="sponsor")
        ]
    ])

# ================================
# UTILS
# ================================

def register_user(user_id, username, ref=None):
    sql.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = sql.fetchone()

    if not user:
        sql.execute("""
        INSERT INTO users(user_id, username, invited_by)
        VALUES(?, ?, ?)
        """, (user_id, username, ref))
        db.commit()

        if ref and ref != user_id and get_setting("ref_enabled") == "1":
            reward = int(get_setting("ref_reward", 10))

            sql.execute("""
            UPDATE users
            SET ref_balance = ref_balance + ?,
                invited = invited + 1
            WHERE user_id=?
            """, (reward, ref))

            db.commit()

def get_user(user_id):
    sql.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    return sql.fetchone()

async def check_sub(user_id, channel):
    try:
        member = await bot.get_chat_member(channel, user_id)
        return member.status in [
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR
        ]
    except:
        return False

# ================================
# START
# ================================

@dp.message(CommandStart())
async def start(message: Message):

    args = message.text.split()

    ref = None

    if len(args) > 1:
        data = args[1]

        if data.startswith("ref_"):
            try:
                ref = int(data.split("_")[1])
            except:
                pass

        if data.startswith("join_"):
            giveaway_id = int(data.split("_")[1])

            await join_giveaway(message, giveaway_id)
            return

    register_user(
        message.from_user.id,
        message.from_user.username,
        ref
    )

    text = f"""
<b>🏎 FERRARI STARS GIVEAWAY</b>

Добро пожаловать, <b>{message.from_user.first_name}</b>!

🔥 Лучшие Telegram Stars розыгрыши
💎 Мгновенные выплаты
🎁 Реферальная система
⚡️ Ferrari-style дизайн

Нажми кнопку ниже 👇
"""

    await message.answer(text, reply_markup=main_menu())

# ================================
# PROFILE
# ================================

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):

    user = get_user(call.from_user.id)

    balance = user[2]
    ref_balance = user[3]
    invited = user[5]

    me = await bot.get_me()

    ref_link = f"https://t.me/{me.username}?start=ref_{call.from_user.id}"

    text = f"""
<b>👤 Ваш профиль</b>

⭐ Баланс: <b>{balance}</b>
🎁 Реф баланс: <b>{ref_balance}</b>

👥 Приглашено: <b>{invited}</b>

🔗 Реферальная ссылка:
<code>{ref_link}</code>
"""

    await call.message.edit_text(
        text,
        reply_markup=main_menu()
    )

# ================================
# WITHDRAW
# ================================

@dp.callback_query(F.data == "withdraw")
async def withdraw(call: CallbackQuery):

    user = get_user(call.from_user.id)

    if user[2] <= 0:
        return await call.answer("Недостаточно звезд", show_alert=True)

    amount = user[2]

    sql.execute("""
    INSERT INTO withdraws(user_id, amount, type)
    VALUES(?, ?, ?)
    """, (call.from_user.id, amount, "balance"))

    sql.execute("""
    UPDATE users
    SET balance = 0
    WHERE user_id=?
    """, (call.from_user.id,))

    db.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Подтвердить",
                callback_data=f"accept_{call.from_user.id}_{amount}"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"decline_{call.from_user.id}_{amount}"
            )
        ]
    ])

    await bot.send_message(
        ADMIN_ID,
        f"""
💸 Новая заявка

👤 ID: <code>{call.from_user.id}</code>
⭐ Сумма: <b>{amount}</b>
""",
        reply_markup=kb
    )

    await call.answer("Заявка отправлена")

@dp.callback_query(F.data == "withdraw_ref")
async def withdraw_ref(call: CallbackQuery):

    user = get_user(call.from_user.id)

    if user[3] < 100:
        return await call.answer(
            "Минимум 100 звезд",
            show_alert=True
        )

    amount = user[3]

    sql.execute("""
    INSERT INTO withdraws(user_id, amount, type)
    VALUES(?, ?, ?)
    """, (call.from_user.id, amount, "ref"))

    sql.execute("""
    UPDATE users
    SET ref_balance = 0
    WHERE user_id=?
    """, (call.from_user.id,))

    db.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Подтвердить",
                callback_data=f"accept_{call.from_user.id}_{amount}"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"decline_{call.from_user.id}_{amount}"
            )
        ]
    ])

    await bot.send_message(
        ADMIN_ID,
        f"""
🎁 Реферальный вывод

👤 ID: <code>{call.from_user.id}</code>
⭐ Сумма: <b>{amount}</b>
""",
        reply_markup=kb
    )

    await call.answer("Заявка отправлена")

# ================================
# ADMIN
# ================================

@dp.message(Command("admin"))
async def admin(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        "<b>⚙️ Админ панель</b>",
        reply_markup=admin_menu()
    )

# ================================
# CREATE GIVEAWAY
# ================================

@dp.callback_query(F.data == "create_giveaway")
async def create_giveaway(call: CallbackQuery, state: FSMContext):

    if call.from_user.id != ADMIN_ID:
        return

    await state.set_state(GiveawayState.waiting_prize)

    await call.message.answer(
        "Введите сумму выигрыша:"
    )

@dp.message(GiveawayState.waiting_prize)
async def giveaway_prize(message: Message, state: FSMContext):

    if not message.text.isdigit():
        return await message.answer("Введите число")

    await state.update_data(prize=int(message.text))

    await state.set_state(GiveawayState.waiting_sponsor)

    await message.answer(
        "Введите sponsor channel username или -"
    )

@dp.message(GiveawayState.waiting_sponsor)
async def giveaway_sponsor(message: Message, state: FSMContext):

    sponsor = None if message.text == "-" else message.text

    await state.update_data(sponsor=sponsor)

    data = await state.get_data()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Создать",
                callback_data="confirm_giveaway"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="cancel_giveaway"
            )
        ]
    ])

    await message.answer(
        f"""
🎉 Подтверждение

⭐ Приз: {data['prize']}
🤝 Спонсор: {sponsor}
""",
        reply_markup=kb
    )

@dp.callback_query(F.data == "cancel_giveaway")
async def cancel_giveaway(call: CallbackQuery, state: FSMContext):

    await state.clear()

    await call.message.answer("Отменено")

@dp.callback_query(F.data == "confirm_giveaway")
async def confirm_giveaway(call: CallbackQuery, state: FSMContext):

    data = await state.get_data()

    prize = data["prize"]
    sponsor = data["sponsor"]

    sql.execute("""
    INSERT INTO giveaways(prize, sponsor)
    VALUES(?, ?)
    """, (prize, sponsor))

    giveaway_id = sql.lastrowid

    db.commit()

    me = await bot.get_me()

    link = f"https://t.me/{me.username}?start=join_{giveaway_id}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🎉 Участвовать",
                url=link
            )
        ]
    ])

    await bot.send_message(
        CHANNEL_ID,
        f"""
🏎 <b>FERRARI GIVEAWAY</b>

⭐ Приз: <b>{prize} Stars</b>

👥 Участников: 0/12

🔥 Успей принять участие!
""",
        reply_markup=kb
    )

    await state.clear()

    await call.message.answer("Розыгрыш создан")

# ================================
# JOIN GIVEAWAY
# ================================

async def join_giveaway(message: Message, giveaway_id):

    sql.execute("""
    SELECT * FROM giveaways
    WHERE id=? AND active=1
    """, (giveaway_id,))

    giveaway = sql.fetchone()

    if not giveaway:
        return await message.answer("Розыгрыш завершен")

    sponsor = giveaway[2]

    sub_main = await check_sub(
        message.from_user.id,
        CHANNEL_ID
    )

    if not sub_main:
        return await message.answer(
            f"Подпишитесь: https://t.me/{CHANNEL_USERNAME}"
        )

    if sponsor:
        sub_sponsor = await check_sub(
            message.from_user.id,
            sponsor
        )

        if not sub_sponsor:
            return await message.answer(
                f"Подпишитесь на спонсора: https://t.me/{sponsor.replace('@','')}"
            )

    emoji = random.choice(["🔥", "🏎", "⭐", "💎"])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=emoji,
                callback_data=f"captcha_{giveaway_id}_{emoji}"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌",
                callback_data="wrong"
            )
        ]
    ])

    await message.answer(
        f"Выберите emoji {emoji}",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("captcha_"))
async def captcha(call: CallbackQuery):

    data = call.data.split("_")

    giveaway_id = int(data[1])

    sql.execute("""
    SELECT * FROM participants
    WHERE giveaway_id=? AND user_id=?
    """, (giveaway_id, call.from_user.id))

    if sql.fetchone():
        return await call.answer("Вы уже участвуете")

    sql.execute("""
    INSERT INTO participants(giveaway_id, user_id)
    VALUES(?, ?)
    """, (giveaway_id, call.from_user.id))

    db.commit()

    sql.execute("""
    SELECT COUNT(*) FROM participants
    WHERE giveaway_id=?
    """, (giveaway_id,))

    count = sql.fetchone()[0]

    await call.message.edit_text(
        f"✅ Вы участвуете!\n\n👥 {count}/12"
    )

    if count >= 12:

        sql.execute("""
        SELECT user_id FROM participants
        WHERE giveaway_id=?
        """, (giveaway_id,))

        users = sql.fetchall()

        d1 = await bot.send_dice(CHANNEL_ID)
        d2 = await bot.send_dice(CHANNEL_ID)

        total = d1.dice.value + d2.dice.value

        winner_index = (total - 1) % 12

        winner_id = users[winner_index][0]

        sql.execute("""
        SELECT prize FROM giveaways
        WHERE id=?
        """, (giveaway_id,))

        prize = sql.fetchone()[0]

        sql.execute("""
        UPDATE users
        SET balance = balance + ?
        WHERE user_id=?
        """, (prize, winner_id))

        sql.execute("""
        UPDATE giveaways
        SET active=0,
            winner=?
        WHERE id=?
        """, (winner_id, giveaway_id))

        db.commit()

        await bot.send_message(
            CHANNEL_ID,
            f"""
🏆 Победитель определен!

👤 Победитель:
<code>{winner_id}</code>

⭐ Выигрыш:
<b>{prize} Stars</b>
"""
        )

        await bot.send_message(
            winner_id,
            f"🎉 Вы выиграли {prize} Stars!"
        )

# ================================
# ACCEPT / DECLINE
# ================================

@dp.callback_query(F.data.startswith("accept_"))
async def accept(call: CallbackQuery):

    if call.from_user.id != ADMIN_ID:
        return

    user_id = int(call.data.split("_")[1])
    amount = int(call.data.split("_")[2])

    await bot.send_message(
        user_id,
        f"✅ Ваша заявка на {amount} Stars подтверждена"
    )

    await call.message.edit_text("Подтверждено")

@dp.callback_query(F.data.startswith("decline_"))
async def decline(call: CallbackQuery):

    if call.from_user.id != ADMIN_ID:
        return

    user_id = int(call.data.split("_")[1])
    amount = int(call.data.split("_")[2])

    await bot.send_message(
        user_id,
        f"❌ Ваша заявка отклонена"
    )

    await call.message.edit_text("Отклонено")

# ================================
# REF SYSTEM
# ================================

@dp.callback_query(F.data == "ref_system")
async def ref_system(call: CallbackQuery):

    if call.from_user.id != ADMIN_ID:
        return

    enabled = get_setting("ref_enabled")
    reward = get_setting("ref_reward")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="ON/OFF",
                callback_data="toggle_ref"
            )
        ],
        [
            InlineKeyboardButton(
                text="Изменить награду",
                callback_data="change_reward"
            )
        ]
    ])

    await call.message.answer(
        f"""
🎁 Реферальная система

Статус: {'ON' if enabled == '1' else 'OFF'}
Награда: {reward}
""",
        reply_markup=kb
    )

@dp.callback_query(F.data == "toggle_ref")
async def toggle_ref(call: CallbackQuery):

    current = get_setting("ref_enabled")

    set_setting("ref_enabled", "0" if current == "1" else "1")

    await call.answer("Изменено")

@dp.callback_query(F.data == "change_reward")
async def change_reward(call: CallbackQuery, state: FSMContext):

    await state.set_state(RefRewardState.waiting_reward)

    await call.message.answer("Введите новую награду")

@dp.message(RefRewardState.waiting_reward)
async def reward_input(message: Message, state: FSMContext):

    if not message.text.isdigit():
        return

    set_setting("ref_reward", message.text)

    await state.clear()

    await message.answer("Изменено")

# ================================
# SPONSOR
# ================================

@dp.callback_query(F.data == "sponsor")
async def sponsor(call: CallbackQuery, state: FSMContext):

    await state.set_state(SponsorState.waiting_channel)

    await call.message.answer(
        "Введите username канала (@channel)"
    )

@dp.message(SponsorState.waiting_channel)
async def sponsor_save(message: Message, state: FSMContext):

    set_setting("global_sponsor", message.text)

    await state.clear()

    await message.answer("Спонсор сохранен")

# ================================
# BROADCAST
# ================================

@dp.callback_query(F.data == "broadcast")
async def broadcast(call: CallbackQuery, state: FSMContext):

    await state.set_state(BroadcastState.waiting_text)

    await call.message.answer("Введите текст рассылки")

@dp.message(BroadcastState.waiting_text)
async def broadcast_send(message: Message, state: FSMContext):

    sql.execute("SELECT user_id FROM users")

    users = sql.fetchall()

    ok = 0
    bad = 0

    for user in users:
        try:
            await bot.send_message(user[0], message.text)
            ok += 1
        except:
            bad += 1

    await state.clear()

    await message.answer(
        f"""
📢 Рассылка завершена

✅ Успешно: {ok}
❌ Ошибок: {bad}
"""
    )

# ================================
# RUN
# ================================

async def main():
    print("BOT STARTED")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
