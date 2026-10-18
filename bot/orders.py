"""Разбор заказа из Mini App.

Данным из приложения доверять нельзя: цены и сумму пересчитываем по своему меню.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path

MENU_PATH = Path(__file__).resolve().parent.parent / "webapp" / "menu.json"

STATUSES = {
    "new": "🆕 Новый",
    "accepted": "👨‍🍳 Готовим",
    "delivering": "🛵 В пути",
    "ready": "📦 Готов к выдаче",
    "done": "✅ Выполнен",
    "cancelled": "❌ Отменён",
}
PAYMENTS = {"card": "картой при получении", "cash": "наличными"}
MAX_QTY = 20


class OrderError(ValueError):
    """Заказ некорректный — текст ошибки можно показать клиенту."""


@dataclass
class Order:
    lines: list[tuple[dict, int]]
    type: str
    address: str
    phone: str
    time: str
    payment: str
    comment: str
    subtotal: int
    delivery_fee: int
    total: int
    extra: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "items": [[it["id"], q] for it, q in self.lines], "type": self.type, "address": self.address,
            "phone": self.phone, "time": self.time, "payment": self.payment, "comment": self.comment,
        }, ensure_ascii=False)


def load_menu(path: Path = MENU_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or digits[0] not in "78":
        return None
    d = digits[1:]
    return f"+7 ({d[:3]}) {d[3:6]}-{d[6:8]}-{d[8:]}"


def parse_order(raw: str, menu: dict) -> Order:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise OrderError("Не удалось прочитать заказ")
    if not isinstance(data, dict) or data.get("v") != 1:
        raise OrderError("Устаревшая версия приложения — откройте меню заново")

    items = {it["id"]: it for it in menu["items"]}
    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items or len(raw_items) > 50:
        raise OrderError("Корзина пуста")

    qty_by_id: dict[str, int] = {}
    for entry in raw_items:
        if not (isinstance(entry, list) and len(entry) == 2 and isinstance(entry[1], int)):
            raise OrderError("Некорректный состав заказа")
        item_id, qty = entry
        if item_id not in items:
            raise OrderError("Некоторых блюд уже нет в меню — обновите корзину")
        if not 1 <= qty <= MAX_QTY:
            raise OrderError(f"Количество одного блюда — от 1 до {MAX_QTY}")
        qty_by_id[item_id] = min(qty_by_id.get(item_id, 0) + qty, MAX_QTY)

    lines = [(items[i], q) for i, q in qty_by_id.items()]
    subtotal = sum(it["price"] * q for it, q in lines)

    cafe = menu["cafe"]
    if subtotal < cafe["min_order"]:
        raise OrderError(f"Минимальная сумма заказа — {cafe['min_order']} ₽")

    order_type = data.get("type")
    if order_type not in ("delivery", "pickup"):
        raise OrderError("Выберите доставку или самовывоз")

    address = str(data.get("address") or "").strip()[:200]
    if order_type == "delivery" and len(address) < 5:
        raise OrderError("Укажите адрес доставки")
    if order_type == "pickup":
        address = ""

    phone = normalize_phone(data.get("phone", ""))
    if not phone:
        raise OrderError("Укажите корректный номер телефона")

    time = str(data.get("time") or "asap")
    if time != "asap":
        try:
            datetime.fromisoformat(time)
        except ValueError:
            raise OrderError("Некорректное время")

    payment = data.get("payment") if data.get("payment") in PAYMENTS else "card"
    comment = str(data.get("comment") or "").strip()[:300]

    fee = cafe["delivery_fee"] if order_type == "delivery" and subtotal < cafe["free_delivery_from"] else 0
    return Order(lines, order_type, address, phone, time, payment, comment, subtotal, fee, subtotal + fee)


def time_label(value: str) -> str:
    if value == "asap":
        return "как можно скорее"
    t = datetime.fromisoformat(value)
    today = datetime.now().date()
    day = "сегодня" if t.date() == today else "завтра" if (t.date() - today).days == 1 else t.strftime("%d.%m")
    return f"{day} к {t:%H:%M}"


def money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₽"


def order_text(order: Order, order_id: int, status: str, client: str | None = None) -> str:
    lines = [f"<b>Заказ №{order_id}</b> · {STATUSES[status]}", ""]
    lines += [f"{it['emoji']} {escape(it['name'])} × {q} — {money(it['price'] * q)}" for it, q in order.lines]
    lines.append("")
    if order.type == "delivery":
        fee = money(order.delivery_fee) if order.delivery_fee else "бесплатно"
        lines.append(f"🛵 Доставка ({fee}): {escape(order.address)}")
    else:
        lines.append("🏃 Самовывоз")
    lines.append(f"🕐 Время: {time_label(order.time)}")
    lines.append(f"💳 Оплата: {PAYMENTS[order.payment]}")
    if order.comment:
        lines.append(f"💬 {escape(order.comment)}")
    if client:
        lines.append(f"👤 {escape(client)}, {order.phone}")
    lines.append(f"\n<b>Итого: {money(order.total)}</b>")
    return "\n".join(lines)
