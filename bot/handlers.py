import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Config
from bot.orders import OrderError, STATUSES, money, order_text, parse_order
from bot.storage import TRANSITIONS, Storage

log = logging.getLogger(__name__)
router = Router()

BTN_MY = "📦 Мои заказы"
BTN_CONTACTS = "📍 Контакты"

# Что пишем клиенту при смене статуса
CLIENT_MESSAGES = {
    "accepted": "👨‍🍳 Заказ №{id} принят и уже готовится!",
    "delivering": "🛵 Заказ №{id} передан курьеру. Скоро будем у вас!",
    "ready": "📦 Заказ №{id} готов — ждём вас по адресу {address}.",
    "done": "✅ Заказ №{id} выполнен. Приятного аппетита! Будем рады видеть вас снова 🔥",
    "cancelled": "😔 Заказ №{id} отменён. Если это ошибка — позвоните нам: +7 (999) 000-00-00.",
}


class OrderCb(CallbackData, prefix="ord"):
    id: int
    action: str


def main_keyboard(config: Config) -> ReplyKeyboardMarkup:
    # sendData работает только из кнопки обычной клавиатуры, поэтому меню открываем отсюда
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍔 Открыть меню", web_app=WebAppInfo(url=config.webapp_url))],
            [KeyboardButton(text=BTN_MY), KeyboardButton(text=BTN_CONTACTS)],
        ],
        resize_keyboard=True,
    )


def admin_keyboard(order_id: int, status: str, order_type: str) -> InlineKeyboardMarkup | None:
    kb = InlineKeyboardBuilder()
    if status == "new":
        kb.button(text="✅ Принять", callback_data=OrderCb(id=order_id, action="accept"))
    if status == "accepted":
        if order_type == "delivery":
            kb.button(text="🛵 Передан курьеру", callback_data=OrderCb(id=order_id, action="deliver"))
        else:
            kb.button(text="📦 Готов к выдаче", callback_data=OrderCb(id=order_id, action="ready"))
    if status in ("delivering", "ready"):
        kb.button(text="✔️ Выполнен", callback_data=OrderCb(id=order_id, action="done"))
    if status in ("new", "accepted"):
        kb.button(text="❌ Отменить", callback_data=OrderCb(id=order_id, action="cancel"))
    kb.adjust(1)
    return kb.as_markup() if list(kb.buttons) else None  # у выполненного/отменённого заказа кнопок нет


@router.message(CommandStart())
async def start(message: Message, config: Config, menu: dict):
    cafe = menu["cafe"]
    await message.answer(
        f"Привет! Это <b>{cafe['name']}</b> — {cafe['tagline'].lower()} 🔥\n\n"
        "Нажмите «🍔 Открыть меню» внизу, соберите заказ — и мы привезём его горячим.\n"
        f"Доставка бесплатно от {money(cafe['free_delivery_from'])}.",
        reply_markup=main_keyboard(config),
    )


@router.message(F.text == BTN_CONTACTS)
async def contacts(message: Message, menu: dict):
    cafe = menu["cafe"]
    await message.answer(f"📍 {cafe['address']}\n🕙 {cafe['hours']}\n📞 +7 (999) 000-00-00")


@router.message(F.text == BTN_MY)
async def my_orders(message: Message, orders_db: Storage):
    orders = await orders_db.user_orders(message.from_user.id)
    if not orders:
        await message.answer("Заказов пока нет. Откройте меню и выберите что-нибудь вкусное 🍔")
        return
    lines = ["<b>Ваши последние заказы</b>\n"]
    for row, order in orders:
        lines.append(f"№{row['id']} от {row['created_at'][:16]} · {money(order.total)} · {STATUSES[row['status']]}")
    await message.answer("\n".join(lines))


@router.message(F.web_app_data)
async def new_order(message: Message, bot: Bot, config: Config, orders_db: Storage, menu: dict):
    try:
        order = parse_order(message.web_app_data.data, menu)
    except OrderError as e:
        await message.answer(f"⚠️ {e}", reply_markup=main_keyboard(config))
        return

    user = message.from_user
    order_id = await orders_db.create(user.id, user.full_name, order)
    await message.answer(
        order_text(order, order_id, "new") + "\n\nСпасибо! Мы получили заказ и скоро подтвердим его.",
        reply_markup=main_keyboard(config),
    )

    admin_text = order_text(order, order_id, "new", client=user.full_name)
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=admin_keyboard(order_id, "new", order.type))
        except TelegramAPIError:
            log.warning("Не удалось уведомить администратора %s", admin_id)


@router.callback_query(OrderCb.filter())
async def change_status(callback: CallbackQuery, callback_data: OrderCb, bot: Bot,
                        config: Config, orders_db: Storage, menu: dict):
    if callback.from_user.id not in config.admin_ids:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    if callback_data.action not in TRANSITIONS:
        await callback.answer()
        return

    new_status = await orders_db.apply(callback_data.id, callback_data.action)
    found = await orders_db.get(callback_data.id)
    if not found:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    row, order = found

    if not new_status:
        await callback.answer(f"Статус уже изменён: {STATUSES[row['status']]}", show_alert=True)
    else:
        await callback.answer(STATUSES[new_status])
        try:
            await bot.send_message(
                row["user_id"],
                CLIENT_MESSAGES[new_status].format(id=row["id"], address=menu["cafe"]["address"]),
            )
        except TelegramAPIError:
            log.warning("Не удалось уведомить клиента по заказу %s", row["id"])

    await callback.message.edit_text(
        order_text(order, row["id"], row["status"], client=row["user_name"]),
        reply_markup=admin_keyboard(row["id"], row["status"], order.type),
    )


@router.message(Command("help"))
@router.message()
async def fallback(message: Message, config: Config):
    await message.answer("Чтобы сделать заказ, нажмите «🍔 Открыть меню» внизу экрана.",
                         reply_markup=main_keyboard(config))
