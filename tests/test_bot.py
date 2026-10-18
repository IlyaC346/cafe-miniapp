import json
import unittest
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User, WebAppData

from bot.config import Config
from bot.handlers import router
from bot.orders import OrderError, load_menu, parse_order
from bot.storage import Storage

MENU = load_menu()
CLIENT = User(id=501, is_bot=False, first_name="Анна")
ADMIN = User(id=9, is_bot=False, first_name="Повар")


def payload(**kw):
    data = {"v": 1, "items": [["classic", 2], ["fries", 1]], "type": "delivery",
            "address": "ул. Ленина, 10", "phone": "89991234567", "time": "asap", "payment": "card", "comment": ""}
    data.update(kw)
    return json.dumps(data, ensure_ascii=False)


class ParseOrderTest(unittest.TestCase):
    def test_totals_recalculated_from_menu(self):
        # Клиент прислал заниженную сумму — она игнорируется
        o = parse_order(payload(total=1), MENU)
        self.assertEqual(o.subtotal, 390 * 2 + 160)
        self.assertEqual(o.delivery_fee, 199)  # меньше 1500 — доставка платная
        self.assertEqual(o.total, 940 + 199)
        self.assertEqual(o.phone, "+7 (999) 123-45-67")

    def test_free_delivery_and_pickup(self):
        self.assertEqual(parse_order(payload(items=[["double", 3]]), MENU).delivery_fee, 0)
        o = parse_order(payload(type="pickup", address="что угодно"), MENU)
        self.assertEqual((o.delivery_fee, o.address), (0, ""))

    def test_duplicates_merged(self):
        o = parse_order(payload(items=[["classic", 1], ["classic", 2]]), MENU)
        self.assertEqual([(it["id"], q) for it, q in o.lines], [("classic", 3)])

    def test_invalid(self):
        cases = {
            "мусор": "не json",
            "версия": payload(v=2),
            "пусто": payload(items=[]),
            "нет блюда": payload(items=[["pizza", 1]]),
            "ноль": payload(items=[["classic", 0]]),
            "много": payload(items=[["classic", 99]]),
            "дробное": payload(items=[["classic", 1.5]]),
            "минимум": payload(items=[["cola", 1]]),
            "без адреса": payload(address=""),
            "телефон": payload(phone="123"),
            "тип": payload(type="teleport"),
            "время": payload(time="вчера"),
        }
        for name, raw in cases.items():
            with self.subTest(name), self.assertRaises(OrderError):
                parse_order(raw, MENU)


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(message_id=len(self.calls), date=datetime.now(),
                           chat=Chat(id=method.chat_id or 0, type="private"), text=method.text)
        return True

    async def stream_content(self, *a, **kw):
        raise NotImplementedError

    async def close(self):
        pass


class BotFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Storage(":memory:")
        await self.db.connect()
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session, default=DefaultBotProperties(parse_mode="HTML"))
        router._parent_router = None
        self.dp = Dispatcher(config=Config("42:TEST", "https://example.com", frozenset({ADMIN.id})),
                             orders_db=self.db, menu=MENU)
        self.dp.include_router(router)
        self.n = 0

    async def asyncTearDown(self):
        await self.db.close()

    def msg(self, user, **kw):
        self.n += 1
        return Message(message_id=self.n, date=datetime.now(), chat=Chat(id=user.id, type="private"), from_user=user, **kw)

    async def feed(self, **kw):
        self.n += 1
        await self.dp.feed_update(self.bot, Update(update_id=self.n, **kw))

    async def order(self, raw=None):
        await self.feed(message=self.msg(CLIENT, web_app_data=WebAppData(data=raw or payload(), button_text="Меню")))

    async def admin_click(self, data, user=ADMIN):
        await self.feed(callback_query=CallbackQuery(id=str(self.n), from_user=user, chat_instance="x",
                                                     data=data, message=self.msg(user, text="...")))

    def sent(self, chat_id):
        return [c for c in self.session.calls if isinstance(c, SendMessage) and c.chat_id == chat_id]

    def admin_buttons(self):
        kb = [c for c in self.session.calls if isinstance(c, (SendMessage, EditMessageText)) and c.reply_markup][-1].reply_markup
        return [b.callback_data for row in kb.inline_keyboard for b in row]

    async def test_start_has_webapp_button(self):
        await self.feed(message=self.msg(CLIENT, text="/start"))
        kb = self.sent(CLIENT.id)[-1].reply_markup
        self.assertEqual(kb.keyboard[0][0].web_app.url, "https://example.com")

    async def test_delivery_order_lifecycle(self):
        await self.order()
        self.assertIn("Заказ №1", self.sent(CLIENT.id)[-1].text)
        self.assertIn("1 139 ₽", self.sent(CLIENT.id)[-1].text)
        admin_msg = self.sent(ADMIN.id)[-1]
        self.assertIn("Анна, +7 (999) 123-45-67", admin_msg.text)
        self.assertEqual(self.admin_buttons(), ["ord:1:accept", "ord:1:cancel"])

        await self.admin_click("ord:1:accept")
        self.assertIn("принят", self.sent(CLIENT.id)[-1].text)
        self.assertEqual(self.admin_buttons(), ["ord:1:deliver", "ord:1:cancel"])

        await self.admin_click("ord:1:deliver")
        self.assertIn("курьеру", self.sent(CLIENT.id)[-1].text)

        await self.admin_click("ord:1:done")
        self.assertIn("выполнен", self.sent(CLIENT.id)[-1].text)
        last_edit = [c for c in self.session.calls if isinstance(c, EditMessageText)][-1]
        self.assertIn("Выполнен", last_edit.text)
        self.assertIsNone(last_edit.reply_markup)

    async def test_pickup_has_ready_step(self):
        await self.order(payload(type="pickup"))
        await self.admin_click("ord:1:accept")
        self.assertEqual(self.admin_buttons(), ["ord:1:ready", "ord:1:cancel"])
        await self.admin_click("ord:1:ready")
        self.assertIn("ул. Примерная, 8", self.sent(CLIENT.id)[-1].text)

    async def test_invalid_transition_and_non_admin(self):
        await self.order()
        await self.admin_click("ord:1:done")  # нельзя завершить непринятый заказ
        self.assertIn("Статус уже изменён", [c for c in self.session.calls if isinstance(c, AnswerCallbackQuery)][-1].text)
        await self.admin_click("ord:1:accept", user=CLIENT)
        self.assertIn("Недостаточно прав", [c for c in self.session.calls if isinstance(c, AnswerCallbackQuery)][-1].text)
        self.assertEqual((await self.db.get(1))[0]["status"], "new")

    async def test_bad_order_rejected(self):
        await self.order(payload(items=[["cola", 1]]))
        self.assertIn("Минимальная сумма", self.sent(CLIENT.id)[-1].text)
        self.assertEqual(self.sent(ADMIN.id), [])

    async def test_my_orders(self):
        await self.order()
        await self.feed(message=self.msg(CLIENT, text="📦 Мои заказы"))
        self.assertIn("№1", self.sent(CLIENT.id)[-1].text)


if __name__ == "__main__":
    unittest.main()
