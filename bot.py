"""
Main Telegram bot - v3.
New features:
- Reset stats & orders (with confirmation)
- Mode selector: Simulator / Binance Testnet / Real Binance
- Order amount setting (USDT per order)
"""
import os
import logging
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

from database import DatabaseManager
from binance_client import BinanceTestnetClient, MockBinanceClient
from simulator.trading_simulator import TradingSimulator

load_dotenv()
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set")
# На Railway используем /data для постоянного хранения (Railway Volume).
# Локально — текущая директория.
_default_db = os.path.join(os.getenv("DATA_DIR", "."), "telegram_bot.db")
DATABASE_PATH = os.getenv("DATABASE_PATH", _default_db)
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET = os.getenv("BINANCE_SECRET_KEY", "")

# Режимы работы
MODE_SIMULATOR = "simulator"
MODE_TESTNET   = "testnet"
MODE_REAL      = "real"

MODE_LABELS = {
    MODE_SIMULATOR: "🔵 Симулятор",
    MODE_TESTNET:   "🟡 Binance Testnet",
    MODE_REAL:      "🔴 Реальный Binance",
}

# ─── KEYBOARDS ────────────────────────────────────────────────────────────────

def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🤖 Мои боты"), KeyboardButton("➕ Добавить бота")],
        [KeyboardButton("📊 Общая статистика"), KeyboardButton("💰 Вывод средств")]
    ], resize_keyboard=True)

def bot_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("▶️ Запустить"), KeyboardButton("⏸ Остановить")],
        [KeyboardButton("💵 Добавить деньги"), KeyboardButton("📋 Ордера и пары")],
        [KeyboardButton("📊 Статистика"), KeyboardButton("📈 График")],
        [KeyboardButton("📋 Дублировать"), KeyboardButton("⚙️ Настройки")],
        [KeyboardButton("🗑 Удалить"), KeyboardButton("⬅️ Назад")]
    ], resize_keyboard=True)

def settings_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🖥 Режим работы"), KeyboardButton("💲 Сумма ордера")],
        [KeyboardButton("📝 Переименовать"), KeyboardButton("🔗 Binance API")],
        [KeyboardButton("🎨 Тема"), KeyboardButton("⏰ Дневной отчёт")],
        [KeyboardButton("⬅️ Назад к боту")]
    ], resize_keyboard=True)

def cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ Отмена")]], resize_keyboard=True)

def deposit_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("100 USDT"), KeyboardButton("500 USDT")],
        [KeyboardButton("1000 USDT"), KeyboardButton("5000 USDT")],
        [KeyboardButton("❌ Отмена")]
    ], resize_keyboard=True)

def mode_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔵 Симулятор")],
        [KeyboardButton("🟡 Binance Testnet")],
        [KeyboardButton("🔴 Реальный Binance")],
        [KeyboardButton("❌ Отмена")]
    ], resize_keyboard=True)

def order_amount_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("10 USDT"), KeyboardButton("25 USDT")],
        [KeyboardButton("50 USDT"), KeyboardButton("100 USDT")],
        [KeyboardButton("❌ Отмена")]
    ], resize_keyboard=True)

def theme_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🌙 Тёмная"), KeyboardButton("☀️ Светлая")],
        [KeyboardButton("💜 Фиолетовая"), KeyboardButton("🌊 Синяя")],
        [KeyboardButton("❌ Отмена")]
    ], resize_keyboard=True)


# ─── BOT CLASS ────────────────────────────────────────────────────────────────

class TradingBot:

    def __init__(self):
        self.db = DatabaseManager(DATABASE_PATH)
        self.simulator = TradingSimulator(self.db)
        self.selected_bot: dict = {}
        self.awaiting: dict = {}
        self._temp_api_key: dict = {}
        self.bot_modes: dict = {}
        self.in_settings: dict = {}
        self._last_inline_msg: dict = {}  # user_id -> last inline message_id
        self._last_bot_msg: dict = {}     # user_id -> last bot message_id
        self._monitor_tasks: dict = {}    # bot_id -> asyncio.Task

    @staticmethod
    def _usd(amount) -> str:
        """Format a number as dollar string, safe for any input."""
        try:
            return "$" + "{:.2f}".format(float(amount))
        except (TypeError, ValueError):
            return "$0.00"

    def get_bot_mode(self, uid: int, bot: dict) -> str:
        """Get current mode for a bot."""
        return bot.get("mode") or self.bot_modes.get(uid, MODE_SIMULATOR)

    def get_binance_client(self, bot: dict, uid: int = None):
        mode = bot.get("mode") or (self.bot_modes.get(uid) if uid else MODE_SIMULATOR)
        if mode == MODE_SIMULATOR:
            return MockBinanceClient()
        elif mode == MODE_TESTNET:
            if bot.get("api_key") and bot.get("secret_key"):
                return BinanceTestnetClient(bot["api_key"], bot["secret_key"])
            elif BINANCE_API_KEY and BINANCE_SECRET:
                return BinanceTestnetClient(BINANCE_API_KEY, BINANCE_SECRET)
            else:
                return MockBinanceClient()
        else:  # real
            if bot.get("api_key") and bot.get("secret_key"):
                from binance_client import BinanceRealClient
                try:
                    return BinanceRealClient(bot["api_key"], bot["secret_key"])
                except Exception:
                    pass
            return MockBinanceClient()

    # ─── COMMANDS ─────────────────────────────────────────────────────────

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        name = update.effective_user.first_name
        await update.message.reply_text(
            f"👋 Привет, {name}!\n\n"
            "🤖 BTC Trading Bot\n\n"
            "Управляйте торговыми ботами прямо из Telegram.\n"
            "Работает в трёх режимах:\n"
            "🔵 Симулятор — виртуальные сделки без API\n"
            "🟡 Binance Testnet — тест с реальной биржей\n"
            "🔴 Реальный Binance — настоящая торговля\n\n"
            "Выберите действие:",
            reply_markup=main_keyboard()
        )

    # ─── MESSAGE HANDLER ──────────────────────────────────────────────────

    async def _delete_previous(self, update: Update, uid: int):
        """Delete user message and previous bot message."""
        # Delete user message
        try:
            await update.message.delete()
        except Exception:
            pass
        # Delete last bot message
        if uid in self._last_bot_msg:
            try:
                await update.effective_chat.delete_message(self._last_bot_msg[uid])
            except Exception:
                pass
            self._last_bot_msg.pop(uid, None)

    async def _send(self, update: Update, uid: int, text: str, reply_markup=None, parse_mode=None):
        """Send message and track its id for future deletion."""
        kwargs = {"text": text}
        if reply_markup:
            kwargs["reply_markup"] = reply_markup
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        msg = await update.effective_chat.send_message(**kwargs)
        self._last_bot_msg[uid] = msg.message_id
        return msg

    async def handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        uid = update.effective_user.id

        # Check quick buttons BEFORE deleting message
        if text in ["100 USDT", "500 USDT", "1000 USDT", "5000 USDT"]:
            await self._delete_previous(update, uid)
            amount = float(text.replace(" USDT", ""))
            await self._process_deposit(update, uid, amount)
            return
        
        if text in ["10 USDT", "25 USDT", "50 USDT"]:
            await self._delete_previous(update, uid)
            amount = float(text.replace(" USDT", ""))
            # Handle set_order_amount
            if uid in self.awaiting and self.awaiting[uid] == "set_order_amount":
                bot_id = self.selected_bot.get(uid)
                if bot_id:
                    await self.db.update_bot(bot_id, order_usdt=amount)
                self.awaiting.pop(uid)
                await self._send(update, uid, "✅ Сумма ордера установлена: " + TradingBot._usd(amount), reply_markup=settings_keyboard())
            else:
                await self._process_deposit(update, uid, amount)
            return

        await self._delete_previous(update, uid)

        if uid in self.awaiting:
            await self._handle_input(update, text, uid)
            return

        # Главное меню
        if text == "🤖 Мои боты":
            await self._show_bot_list(update)
        elif text == "➕ Добавить бота":
            self.awaiting[uid] = "new_bot_name"
            await update.message.reply_text("📝 Введите имя для нового бота:", reply_markup=cancel_keyboard())
        elif text == "📊 Общая статистика":
            await self._show_overall_stats(update)
        elif text == "💰 Вывод средств":
            self.awaiting[uid] = "withdrawal"
            await update.message.reply_text("💰 Введите сумму вывода в USDT:", reply_markup=cancel_keyboard())

        # Меню бота
        elif text == "▶️ Запустить":
            await self._start_bot(update, uid)
        elif text == "⏸ Остановить":
            await self._stop_bot(update, uid)
        elif text == "💵 Добавить деньги":
            await self._ask_deposit(update, uid)
        elif text == "📋 Ордера и пары":
            await self._show_orders_and_pairs(update, uid)
        elif text == "📊 Статистика":
            await self._show_bot_stats(update, uid)
        
        elif text == "📈 График":
            await self._show_profit_chart(update, uid)
        
        elif text == "🤖 AI Анализ":
            await self._show_ai_analysis(update, uid)
        
        elif text == "📋 Дублировать":
            await self._clone_bot(update, uid)
        
        elif text == "⚙️ Настройки":
            self.in_settings[uid] = True
            bot_id = self.selected_bot.get(uid)
            bot = await self.db.get_bot(bot_id) if bot_id else None
            mode = bot.get("mode") or MODE_SIMULATOR if bot else MODE_SIMULATOR
            order_usdt = bot.get("order_usdt") or 50 if bot else 50
            theme = bot.get("theme") or "dark" if bot else "dark"
            daily_report = bot.get("daily_report") or False if bot else False
            await update.message.reply_text(
                f"⚙️ *Настройки бота*\n\n"
                f"Режим: {MODE_LABELS.get(mode, mode)}\n"
                "Сумма ордера: " + TradingBot._usd(order_usdt) + " USDT\n"
                f"Тема: {theme}\n"
                f"Дневной отчёт: {'✅ Вкл' if daily_report else '❌ Выкл'}",
                parse_mode="Markdown",
                reply_markup=settings_keyboard()
            )

        # Настройки
        elif text == "🖥 Режим работы":
            self.awaiting[uid] = "set_mode"
            bot_id = self.selected_bot.get(uid)
            bot = await self.db.get_bot(bot_id) if bot_id else None
            mode = bot.get("mode") or MODE_SIMULATOR if bot else MODE_SIMULATOR
            await update.message.reply_text(
                f"🖥 *Выберите режим работы*\n\n"
                f"Текущий: {MODE_LABELS.get(mode, mode)}\n\n"
                f"🔵 *Симулятор* — работает без API, сделки виртуальные\n"
                f"🟡 *Binance Testnet* — нужны ключи от testnet.binancefuture.com\n"
                f"🔴 *Реальный Binance* — нужны ключи от binance.com ⚠️",
                parse_mode="Markdown",
                reply_markup=mode_keyboard()
            )
        elif text == "💲 Сумма ордера":
            self.awaiting[uid] = "set_order_amount"
            bot_id = self.selected_bot.get(uid)
            bot = await self.db.get_bot(bot_id) if bot_id else None
            order_usdt = bot.get("order_usdt") or 50 if bot else 50
            await update.message.reply_text(
                "💲 *Сумма одного ордера*\n\n"
                "Текущая: " + TradingBot._usd(order_usdt) + " USDT\n\nВыберите или введите сумму вручную:",
                parse_mode="Markdown",
                reply_markup=order_amount_keyboard()
            )
        
        elif text == "🎨 Тема":
            await self._change_theme(update, uid)
        
        elif text == "⏰ Дневной отчёт":
            await self._toggle_daily_report(update, uid)
        
        elif text == "🔗 Binance API":
            bot_id = self.selected_bot.get(uid)
            if not bot_id:
                await self._send(update, uid, "❌ Сначала выберите бота")
                return
            bot = await self.db.get_bot(bot_id)
            has_api = bool(bot.get("api_key") and bot.get("secret_key"))
            
            if has_api:
                # Show API management menu
                kb = [
                    [KeyboardButton("🔑 Изменить API"), KeyboardButton("👁 Показать API")],
                    [KeyboardButton("🗑 Удалить API"), KeyboardButton("⬅️ Назад к настройкам")]
                ]
                await self._send(
                    update, uid,
                    "🔗 *Binance API*\n\n"
                    "✅ API ключи настроены\n\n"
                    "Выберите действие:",
                    reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
                )
            else:
                # Ask for API keys
                self.awaiting[uid] = "binance_api_key"
                await self._send(
                    update, uid,
                    "🔗 *Подключение Binance API*\n\n"
                    "Testnet: https://testnet.binancefuture.com\n"
                    "Real: https://binance.com → Управление API\n\n"
                    "🔑 Введите API Key:",
                    reply_markup=cancel_keyboard()
                )
        
        elif text == "🔑 Изменить API":
            self.awaiting[uid] = "binance_api_key"
            await self._send(
                update, uid,
                "🔑 Введите новый API Key:",
                reply_markup=cancel_keyboard()
            )
        
        elif text == "👁 Показать API":
            bot_id = self.selected_bot.get(uid)
            if bot_id:
                bot = await self.db.get_bot(bot_id)
                api_key = bot.get("api_key", "")
                secret = bot.get("secret_key", "")
                
                # Mask secret partially
                if secret:
                    visible = secret[:8] + "..." + secret[-4:]
                else:
                    visible = "Не задан"
                
                kb = [
                    [KeyboardButton("🔑 Изменить API"), KeyboardButton("🗑 Удалить API")],
                    [KeyboardButton("⬅️ Назад к настройкам")]
                ]
                await self._send(
                    update, uid,
                    "🔗 *Binance API*\n\n"
                    f"API Key:\n`{api_key or 'Не задан'}`\n\n"
                    f"Secret Key:\n`{visible}`",
                    reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
                )
        
        elif text == "🗑 Удалить API":
            bot_id = self.selected_bot.get(uid)
            if bot_id:
                await self.db.update_bot(bot_id, api_key="", secret_key="")
                kb = [[KeyboardButton("🔗 Binance API"), KeyboardButton("⬅️ Назад к настройкам")]]
                await self._send(
                    update, uid,
                    "✅ API ключи удалены\n\nБот переключится на Mock режим",
                    reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
                )
        
        elif text == "⬅️ Назад к настройкам":
            await self._send(update, uid, "⚙️ Настройки:", reply_markup=settings_keyboard())
        
        elif text == "⬅️ Назад к боту":
            self.in_settings.pop(uid, None)
            await self._send(update, uid, "🤖 Управление ботом:", reply_markup=bot_keyboard())

        # Сброс статистики
        elif text == "🔄 Сброс":
            await self._confirm_reset(update, uid)

        # Удалить бота
        elif text == "🗑 Удалить":
            await self._confirm_delete(update, uid)

        elif text == "⬅️ Назад":
            self.selected_bot.pop(uid, None)
            self.in_settings.pop(uid, None)
            await self._send(update, uid, "🏠 Главное меню", reply_markup=main_keyboard())

        elif text == "❌ Отмена":
            self.awaiting.pop(uid, None)
            if uid in self.in_settings:
                await self._send(update, uid, "⚙️ Настройки:", reply_markup=settings_keyboard())
            elif uid in self.selected_bot:
                await self._send(update, uid, "🤖 Управление ботом:", reply_markup=bot_keyboard())
            else:
                await self._send(update, uid, "🏠 Главное меню:", reply_markup=main_keyboard())

        else:
            await self._send(update, uid, "❓ Используйте кнопки меню")

    # ─── INPUT HANDLER ────────────────────────────────────────────────────

    async def _handle_input(self, update: Update, text: str, uid: int):
        action = self.awaiting.get(uid)

        if text == "❌ Отмена":
            self.awaiting.pop(uid, None)
            if uid in self.in_settings:
                await self._send(update, uid, "⚙️ Настройки:", reply_markup=settings_keyboard())
            elif uid in self.selected_bot:
                await self._send(update, uid, "🤖 Управление ботом:", reply_markup=bot_keyboard())
            else:
                await self._send(update, uid, "🏠 Главное меню:", reply_markup=main_keyboard())
            return

        if action == "new_bot_name":
            await self._create_bot(update, uid, text)

        elif action == "rename_bot":
            bot = await self.db.get_bot(self.selected_bot[uid])
            await self.db.update_bot(bot["id"], name=text)
            self.awaiting.pop(uid)
            await update.message.reply_text(f"✅ Бот переименован в '{text}'", reply_markup=settings_keyboard())

        elif action == "deposit":
            try:
                amount = float(text.replace(",", "."))
                if amount <= 0:
                    raise ValueError
                await self._process_deposit(update, uid, amount)
            except ValueError:
                await update.message.reply_text("❌ Введите корректную сумму числом:", reply_markup=deposit_keyboard())

        elif action == "withdrawal":
            try:
                amount = float(text.replace(",", "."))
                self.awaiting.pop(uid)
                await update.message.reply_text("✅ Вывод " + TradingBot._usd(amount) + " USDT записан", reply_markup=main_keyboard())
            except ValueError:
                self.awaiting.pop(uid)
                await update.message.reply_text("❌ Некорректная сумма", reply_markup=main_keyboard())

        elif action == "binance_api_key":
            self.awaiting[uid] = "binance_secret"
            self._temp_api_key[uid] = text
            await update.message.reply_text("🔑 Теперь введите Secret Key:", reply_markup=cancel_keyboard())

        elif action == "binance_secret":
            api_key = self._temp_api_key.pop(uid, "")
            bot_id = self.selected_bot.get(uid)
            if bot_id:
                await self.db.update_bot(bot_id, api_key=api_key, secret_key=text)
            self.awaiting.pop(uid)
            await update.message.reply_text(
                "✅ API ключи сохранены!",
                reply_markup=settings_keyboard()
            )

        elif action == "set_mode":
            mode_map = {
                "🔵 Симулятор": MODE_SIMULATOR,
                "🟡 Binance Testnet": MODE_TESTNET,
                "🔴 Реальный Binance": MODE_REAL,
            }
            new_mode = mode_map.get(text)
            if new_mode:
                self.awaiting.pop(uid)
                bot_id = self.selected_bot.get(uid)
                if bot_id:
                    await self.db.update_bot(bot_id, mode=new_mode)
                    self.bot_modes[uid] = new_mode
                    label = MODE_LABELS[new_mode]
                    warn = ""
                    if new_mode == MODE_REAL:
                        warn = "\n\n⚠️ *Внимание!* Реальный режим использует настоящие деньги!"
                    await update.message.reply_text(
                        f"✅ Режим установлен: {label}{warn}",
                        parse_mode="Markdown",
                        reply_markup=settings_keyboard()
                    )
            else:
                await update.message.reply_text("❓ Выберите режим из списка:", reply_markup=mode_keyboard())

        elif action == "set_order_amount":
            # Quick buttons
            quick = {"10 USDT": 10, "25 USDT": 25, "50 USDT": 50, "100 USDT": 100}
            if text in quick:
                amount = quick[text]
            else:
                try:
                    amount = float(text.replace(",", ".").replace(" ", ""))
                    if amount <= 0:
                        raise ValueError
                except ValueError:
                    await update.message.reply_text("❌ Введите корректную сумму:", reply_markup=order_amount_keyboard())
                    return

            self.awaiting.pop(uid)
            bot_id = self.selected_bot.get(uid)
            if bot_id:
                # Convert USDT amount to BTC quantity (approximate)
                # Store order_usdt in db for display
                await self.db.update_bot(bot_id, order_usdt=amount)
            await update.message.reply_text(
                "✅ Сумма ордера установлена: " + TradingBot._usd(amount) + " USDT",
                reply_markup=settings_keyboard()
            )
        
        elif action == "select_theme":
            themes = {
                "🌙 Тёмная": "dark",
                "☀️ Светлая": "light",
                "💜 Фиолетовая": "purple",
                "🌊 Синяя": "blue"
            }
            
            if text in themes:
                theme = themes[text]
                self.awaiting.pop(uid)
                bot_id = self.selected_bot.get(uid)
                if bot_id:
                    await self.db.update_bot(bot_id, theme=theme)
                await update.message.reply_text(
                    f"✅ Тема изменена на: {text}",
                    reply_markup=settings_keyboard()
                )
            else:
                await update.message.reply_text(
                    "❌ Выберите тему из списка",
                    reply_markup=settings_keyboard()
                )

    # ─── BOT LIST ─────────────────────────────────────────────────────────

    async def _show_bot_list(self, update: Update):
        bots = await self.db.get_all_bots()
        uid = update.effective_user.id
        # Delete user message
        try:
            await update.message.delete()
        except Exception:
            pass
        if not bots:
            msg = await update.effective_chat.send_message("🤖 У вас нет ботов\n\nНажмите ➕ Добавить бота", reply_markup=main_keyboard())
            return

        text = "🤖 Ваши торговые боты:\n\n"
        keyboard = []
        for b in bots:
            emoji = "🟢" if b["status"] == "running" else "🔴"
            profit = await self.db.get_total_profit(b["id"])
            mode = b.get("mode") or MODE_SIMULATOR
            mode_icon = {"simulator": "🔵", "testnet": "🟡", "real": "🔴"}.get(mode, "🔵")
            text += "{} {} {} — ".format(emoji, b['name'], mode_icon) + TradingBot._usd(b['balance']) + " | +" + TradingBot._usd(profit) + "\n"
            keyboard.append([InlineKeyboardButton(
                "{}{} {}  |  +".format(emoji, b['name'], mode_icon) + TradingBot._usd(profit), callback_data="sel:{}".format(b['id'])
            )])

        msg = await update.effective_chat.send_message(text, reply_markup=InlineKeyboardMarkup(keyboard))
        self._last_inline_msg[uid] = msg.message_id

    # ─── CALLBACK ─────────────────────────────────────────────────────────

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        uid = query.from_user.id
        chat_id = query.message.chat_id
        data = query.data

        async def send(text, markup=None, md=False):
            """Edit current message to avoid chat clutter, fallback to new message."""
            try:
                # Try to edit the existing inline message into plain text
                await query.message.edit_text(
                    text,
                    parse_mode="Markdown" if md else None,
                    reply_markup=None
                )
            except Exception:
                pass
            # Always send new message with ReplyKeyboard
            kwargs = {"chat_id": chat_id, "text": text}
            if markup:
                kwargs["reply_markup"] = markup
            if md:
                kwargs["parse_mode"] = "Markdown"
            await ctx.bot.send_message(**kwargs)

        if data.startswith("sel:"):
            bot_id = int(data.split(":")[1])
            self.selected_bot[uid] = bot_id
            self.in_settings.pop(uid, None)
            bot = await self.db.get_bot(bot_id)
            if bot:
                emoji = "🟢" if bot["status"] == "running" else "🔴"
                profit = await self.db.get_total_profit(bot_id)
                mode = bot.get("mode") or MODE_SIMULATOR
                order_usdt = bot.get("order_usdt") or 50
                status_str = "🟢 Работает" if bot["status"] == "running" else "🔴 Остановлен"
                bal = round(bot['balance'], 2)
                prf = round(profit, 2)
                ord_u = round(order_usdt, 2)
                mode_label = MODE_LABELS.get(mode, mode)
                lines = [
                    emoji + " " + bot['name'],
                    "",
                    "Режим: " + mode_label,
                    "Баланс: $" + str(bal) + " USDT",
                    "Прибыль: $" + str(prf) + " USDT",
                    "Сумма ордера: $" + str(ord_u) + " USDT",
                    "Статус: " + status_str,
                    "",
                    "Выберите действие:",
                ]
                text = "\n".join(lines)
                # Delete inline message
                try:
                    await query.message.delete()
                except Exception:
                    pass
                # Send new message with ReplyKeyboard
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=bot_keyboard()
                )

        elif data.startswith("del:"):
            bot_id = int(data.split(":")[1])
            bot = await self.db.get_bot(bot_id)
            name = bot["name"] if bot else "?"
            await self.simulator.stop_bot_simulation(bot_id)
            await self.db.delete_bot(bot_id)
            self.selected_bot.pop(uid, None)
            try:
                await query.message.delete()
            except Exception:
                pass
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=f"🗑 Бот '{name}' удалён",
                reply_markup=main_keyboard()
            )

        elif data.startswith("reset_confirm:"):
            bot_id = int(data.split(":")[1])
            await self._do_reset(query, ctx, uid, chat_id, bot_id)

        elif data.startswith("reset_cancel:"):
            try:
                await query.message.delete()
            except Exception:
                pass
            await ctx.bot.send_message(
                chat_id=chat_id,
                text="✅ Сброс отменён",
                reply_markup=bot_keyboard()
            )

    # ─── CREATE BOT ───────────────────────────────────────────────────────

    async def _create_bot(self, update: Update, uid: int, name: str):
        self.awaiting.pop(uid)
        bot = await self.db.create_bot(name)
        self.selected_bot[uid] = bot["id"]
        await update.message.reply_text(
            f"✅ Бот *{name}* создан!\n\n"
            "Теперь:\n"
            "1️⃣ Нажмите 💵 Добавить деньги\n"
            "2️⃣ В ⚙️ Настройки выберите режим работы\n"
            "3️⃣ Нажмите ▶️ Запустить",
            parse_mode="Markdown",
            reply_markup=bot_keyboard()
        )


    # ─── ORDER MONITORING ─────────────────────────────────────────────────

    async def _monitor_orders(self, bot_id: int):
        """Background task: monitor orders on exchange and replace filled ones."""
        logger.info(f"Order monitoring started for bot {bot_id}")
        while True:
            try:
                await asyncio.sleep(15)  # Check every 15 seconds
                
                bot = await self.db.get_bot(bot_id)
                if not bot or bot["status"] != "running":
                    logger.info(f"Bot {bot_id} stopped, ending order monitoring")
                    break
                
                mode = bot.get("mode") or MODE_SIMULATOR
                if mode == MODE_SIMULATOR:
                    # Simulator doesn't need order monitoring
                    continue
                
                client = self.get_binance_client(bot)
                symbol = bot["symbol"]
                
                # Get open orders from exchange
                try:
                    live_orders = client.get_open_orders(symbol)
                except Exception as e:
                    logger.error(f"Failed to get orders for bot {bot_id}: {e}")
                    continue
                
                # Get our DB orders
                db_orders = await self.db.get_open_orders(bot_id)
                
                # Find filled orders (in DB but not on exchange)
                live_order_ids = {str(o.get("orderId")) for o in live_orders}
                for db_order in db_orders:
                    eid = db_order.get("exchange_order_id", "")
                    if not eid:
                        continue
                    
                    if eid not in live_order_ids:
                        # Order filled! Mark as closed and place new one
                        logger.info(f"Bot {bot_id}: Order {eid} filled at ${db_order['price']:.2f}")
                        await self.db.update_order_status(db_order["id"], "FILLED")
                        
                        # Place new order at same level
                        side = db_order["side"]
                        price = db_order["price"]
                        quantity = db_order["quantity"]
                        pair_id = db_order.get("pair_id", "")
                        
                        try:
                            if side == "BUY":
                                result = client.place_limit_buy(symbol, price, quantity)
                            else:
                                result = client.place_limit_sell(symbol, price, quantity)
                            
                            new_eid = str(result.get("orderId", "")) if isinstance(result, dict) else ""
                            await self.db.add_order(bot_id, side, price, quantity, new_eid, pair_id)
                            logger.info(f"Bot {bot_id}: Replaced {side} order at ${price:.2f}")
                        except Exception as e:
                            logger.error(f"Failed to replace order: {e}")
                
            except asyncio.CancelledError:
                logger.info(f"Order monitoring cancelled for bot {bot_id}")
                break
            except Exception as e:
                logger.error(f"Error in order monitoring for bot {bot_id}: {e}")
                await asyncio.sleep(5)

    async def _start_monitoring(self, bot_id: int):
        """Start order monitoring background task."""
        if bot_id not in self._monitor_tasks:
            task = asyncio.create_task(self._monitor_orders(bot_id))
            self._monitor_tasks[bot_id] = task
            logger.info(f"Started monitoring task for bot {bot_id}")

    async def _stop_monitoring(self, bot_id: int):
        """Stop order monitoring background task."""
        if bot_id in self._monitor_tasks:
            self._monitor_tasks[bot_id].cancel()
            try:
                await self._monitor_tasks[bot_id]
            except asyncio.CancelledError:
                pass
            del self._monitor_tasks[bot_id]
            logger.info(f"Stopped monitoring task for bot {bot_id}")

    # ─── START / STOP ─────────────────────────────────────────────────────

    async def _start_bot(self, update: Update, uid: int):
        bot_id = self.selected_bot.get(uid)
        if not bot_id:
            await self._send(update, uid, "❌ Сначала выберите бота")
            return
        bot = await self.db.get_bot(bot_id)

        if bot["balance"] <= 0:
            await update.message.reply_text("❌ Недостаточно средств!\n\nНажмите 💵 Добавить деньги", reply_markup=bot_keyboard())
            return

        mode = bot.get("mode") or MODE_SIMULATOR
        client = self.get_binance_client(bot, uid)
        price = client.get_current_price(bot["symbol"])

        await self.db.update_bot(bot_id, status="running", center_price=price)
        await update.message.reply_text(
            f"⏳ Запускаю бота...\n"
            f"Режим: {MODE_LABELS.get(mode, mode)}\n"
            f"Цена BTC: ${price:,.2f}"
        )

        orders_placed = await self._place_grid(bot, client, price)

        if mode == MODE_SIMULATOR:
            await self.simulator.start_bot_simulation(bot_id, price)
            sim_note = "🔄 Симулятор запущен — прибыль появится через 30-90 сек"
        else:
            # Start order monitoring for Testnet/Real
            await self._start_monitoring(bot_id)
            sim_note = "📡 Ордера выставлены | Мониторинг активен"

        await update.message.reply_text(
            f"✅ Бот *{bot['name']}* запущен!\n\n"
            f"📍 Центр сетки: ${price:,.2f}\n"
            f"📊 Ордеров выставлено: {orders_placed}\n"
            f"🖥 Режим: {MODE_LABELS.get(mode, mode)}\n"
            f"{sim_note}",
            parse_mode="Markdown",
            reply_markup=bot_keyboard()
        )

    async def _place_grid(self, bot: dict, client, center_price: float) -> int:
        symbol = bot["symbol"]
        bot_id = bot["id"]

        # Safely get order_usdt — guard against old DB returning string/None
        try:
            order_usdt = float(bot.get("order_usdt") or 50)
        except (TypeError, ValueError):
            order_usdt = 50.0

        quantity = round(order_usdt / center_price, 6)
        if quantity < 0.001:
            quantity = 0.001

        count = 0

        # BUY orders — initial 0.175%, step 0.075%
        buy_price = center_price * (1 - 0.00175)
        for i in range(5):
            try:
                result = client.place_limit_buy(symbol, round(buy_price, 2), quantity)
                eid = str(result.get("orderId", "")) if isinstance(result, dict) else ""
            except Exception:
                eid = ""
            await self.db.add_order(bot_id, "BUY", round(buy_price, 2), quantity, eid, "PAIR" + str(i+1))
            count += 1
            buy_price *= (1 - 0.00075)

        # SELL orders — initial 0.175%, step 0.095%
        sell_price = center_price * (1 + 0.00175)
        for i in range(5):
            try:
                result = client.place_limit_sell(symbol, round(sell_price, 2), quantity)
                eid = str(result.get("orderId", "")) if isinstance(result, dict) else ""
            except Exception:
                eid = ""
            await self.db.add_order(bot_id, "SELL", round(sell_price, 2), quantity, eid, "PAIR" + str(i+1))
            count += 1
            sell_price *= (1 + 0.00095)

        # Pairs — match exactly to orders above
        buy_price2 = center_price * (1 - 0.00175)
        sell_price2 = center_price * (1 + 0.00175)
        for i in range(5):
            await self.db.add_pair(bot_id, "PAIR" + str(i+1), round(buy_price2, 2), round(sell_price2, 2), quantity)
            buy_price2 *= (1 - 0.00075)
            sell_price2 *= (1 + 0.00095)

        return count

    async def _stop_bot(self, update: Update, uid: int):
        bot_id = self.selected_bot.get(uid)
        if not bot_id:
            await self._send(update, uid, "❌ Сначала выберите бота")
            return
        bot = await self.db.get_bot(bot_id)
        await self.db.update_bot(bot_id, status="stopped")
        await self.simulator.stop_bot_simulation(bot_id)
        await self._stop_monitoring(bot_id)
        await update.message.reply_text(
            bot['name'] + " остановлен",
            reply_markup=bot_keyboard()
        )

    # ─── DEPOSIT ──────────────────────────────────────────────────────────

    async def _ask_deposit(self, update: Update, uid: int):
        bot_id = self.selected_bot.get(uid)
        if not bot_id:
            await self._send(update, uid, "❌ Сначала выберите бота")
            return
        bot = await self.db.get_bot(bot_id)
        self.awaiting[uid] = "deposit"
        await update.message.reply_text(
            "💵 Пополнение " + bot['name'] + "\n\nТекущий баланс: " + TradingBot._usd(bot['balance']) + " USDT\n\nВыберите сумму:",
            parse_mode="Markdown",
            reply_markup=deposit_keyboard()
        )

    async def _process_deposit(self, update: Update, uid: int, amount: float):
        self.awaiting.pop(uid, None)
        bot_id = self.selected_bot.get(uid)
        if not bot_id:
            return
        bot = await self.db.get_bot(bot_id)
        await self.db.add_deposit(bot_id, amount)
        new_balance = (bot["balance"] or 0) + amount
        await update.message.reply_text(
            "✅ Баланс пополнен!\n\n+" + TradingBot._usd(amount) + " USDT\nНовый баланс: " + TradingBot._usd(new_balance) + " USDT",
            reply_markup=bot_keyboard()
        )

    # ─── RESET ────────────────────────────────────────────────────────────

    async def _confirm_reset(self, update: Update, uid: int):
        bot_id = self.selected_bot.get(uid)
        if not bot_id:
            return
        bot = await self.db.get_bot(bot_id)
        profit = await self.db.get_total_profit(bot_id)
        orders = await self.db.get_open_orders(bot_id)

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Да, сбросить всё", callback_data=f"reset_confirm:{bot_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"reset_cancel:{bot_id}")
        ]])
        await update.message.reply_text(
            "⚠️ Сброс статистики и ордеров\n\n"
            "Бот: " + bot['name'] + "\n\n"
            "Будет удалено:\n"
            "  • " + str(len(orders)) + " активных ордеров\n"
            "  • Вся история сделок\n"
            "  • Прибыль: " + TradingBot._usd(profit) + " USDT\n\n"
            "Баланс и настройки сохранятся.\n\n"
            "Вы уверены?",
            reply_markup=kb
        )

    async def _do_reset(self, query, ctx, uid: int, chat_id: int, bot_id: int):
        """Execute reset of orders and stats."""
        await self.simulator.stop_bot_simulation(bot_id)
        await self.db.reset_bot_stats(bot_id)
        bot = await self.db.get_bot(bot_id)
        if bot and bot["status"] == "running":
            await self.db.update_bot(bot_id, status="stopped")
        try:
            await query.message.delete()
        except Exception:
            pass
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=(
                "✅ *Сброс выполнен!*\n\n"
                "Все ордера и история сделок удалены.\n"
                "Баланс и настройки сохранены.\n\n"
                "Нажмите ▶️ Запустить чтобы начать заново."
            ),
            parse_mode="Markdown",
            reply_markup=bot_keyboard()
        )

    # ─── ORDERS AND PAIRS ─────────────────────────────────────────────────

    async def _show_orders_and_pairs(self, update: Update, uid: int):
        bot_id = self.selected_bot.get(uid)
        if not bot_id:
            await self._send(update, uid, "❌ Сначала выберите бота")
            return

        bot = await self.db.get_bot(bot_id)
        client = self.get_binance_client(bot, uid)
        orders = await self.db.get_open_orders(bot_id)
        pairs = await self.db.get_bot_pairs(bot_id)
        live_orders = []
        try:
            live_orders = client.get_open_orders(bot["symbol"])
        except Exception:
            pass

        buy_orders = [o for o in orders if o["side"] == "BUY"]
        sell_orders = [o for o in orders if o["side"] == "SELL"]
        mode = bot.get("mode") or MODE_SIMULATOR

        text = f"📋 *{bot['name']}* — Ордера\n"
        text += f"Режим: {MODE_LABELS.get(mode, mode)}\n"
        text += f"━━━━━━━━━━━━━━━━━━━━\n\n"

        if buy_orders:
            text += "🟢 *BUY ордера:*\n"
            for o in sorted(buy_orders, key=lambda x: x["price"], reverse=True):
                text += f"  📥 ${o['price']:,.1f} × {o['quantity']:.4f} BTC\n"
        else:
            text += "🟢 *BUY ордера:* нет\n"

        text += "\n"

        if sell_orders:
            text += "🔴 *SELL ордера:*\n"
            for o in sorted(sell_orders, key=lambda x: x["price"], reverse=True):
                text += f"  📤 ${o['price']:,.1f} × {o['quantity']:.4f} BTC\n"
        else:
            text += "🔴 *SELL ордера:* нет\n"

        text += "\n━━━━━━━━━━━━━━━━━━━━\n\n"

        if pairs:
            text += "🔗 *Пары:*\n"
            for p in pairs[:10]:
                status_emoji = "✅" if p["status"] == "CLOSED" else "🔄"
                profit_str = " +" + TradingBot._usd(p['profit']) if p["profit"] > 0 else ""
                text += f"  {status_emoji} {p['pair_name']}: ${p['buy_price']:,.0f} → ${p['sell_price']:,.0f}{profit_str}\n"
        else:
            text += "🔗 *Пары:* нет (запустите бота)"

        if live_orders:
            text += f"\n\n🌐 *На бирже:* {len(live_orders)} активных ордеров"

        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=bot_keyboard())

    # ─── STATS ────────────────────────────────────────────────────────────

    async def _show_bot_stats(self, update: Update, uid: int):
        bot_id = self.selected_bot.get(uid)
        if not bot_id:
            await self._send(update, uid, "❌ Сначала выберите бота")
            return

        bot = await self.db.get_bot(bot_id)
        client = self.get_binance_client(bot, uid)
        mode = bot.get("mode") or MODE_SIMULATOR

        live_balance = 0.0
        current_price = 0.0
        try:
            live_balance = client.get_usdt_balance()
            current_price = client.get_current_price(bot["symbol"])
        except Exception:
            pass

        now = datetime.now()
        orders = await self.db.get_open_orders(bot_id)
        pairs = await self.db.get_bot_pairs(bot_id)
        profit_total = await self.db.get_total_profit(bot_id)
        profit_day = await self.db.get_profit_since(bot_id, now - timedelta(days=1))
        profit_week = await self.db.get_profit_since(bot_id, now - timedelta(weeks=1))
        profit_month = await self.db.get_profit_since(bot_id, now - timedelta(days=30))
        recent_trades = await self.db.get_recent_trades(bot_id, 5)
        order_usdt = bot.get("order_usdt") or 50

        status = "🟢 Работает" if bot["status"] == "running" else "🔴 Остановлен"

        text = (
            "📊 " + bot['name'] + "\n━━━━━━━━━━━━━━━━━━━━\n\n"
            "Статус: " + status + "\n"
            "Режим: " + MODE_LABELS.get(mode, mode) + "\n"
            "Сумма ордера: " + TradingBot._usd(order_usdt) + " USDT\n\n"
            "Баланс: " + TradingBot._usd(bot['balance']) + " USDT\n"
        )
        if live_balance > 0 and mode != MODE_SIMULATOR:
            text += "  Binance: " + TradingBot._usd(live_balance) + " USDT\n"
        if current_price > 0:
            text += "📈 Цена BTC: $" + "{:,.2f}".format(current_price) + "\n"

        text += (
            "\n💵 Прибыль:\n"
            "  24ч:    " + TradingBot._usd(profit_day) + "\n"
            "  7 дней: " + TradingBot._usd(profit_week) + "\n"
            "  30 дней: " + TradingBot._usd(profit_month) + "\n"
            "  Всего:  " + TradingBot._usd(profit_total) + "\n\n"
            "Ордеров: " + str(len(orders)) + "  |  Пар: " + str(len(pairs)) + "\n"
        )
        if bot.get("center_price"):
            text += "📍 Центр: $" + "{:,.2f}".format(bot['center_price']) + "\n"

        if recent_trades:
            text += "\n📜 *Последние сделки:*\n"
            for t in recent_trades:
                dt = t.get("executed_at", "")
                if isinstance(dt, str) and dt:
                    try:
                        dt = datetime.fromisoformat(dt).strftime("%H:%M:%S")
                    except Exception:
                        dt = dt[:8]
                elif isinstance(dt, datetime):
                    dt = dt.strftime("%H:%M:%S")
                text += "  ⏰ " + str(dt) + "  +" + TradingBot._usd(t['profit']) + " ({:.2f}%)\n".format(t['profit_percent'])
        else:
            text += "\n_Сделок пока нет_"

        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=bot_keyboard())

    # ─── OVERALL STATS ────────────────────────────────────────────────────

    async def _show_overall_stats(self, update: Update):
        bots = await self.db.get_all_bots()
        if not bots:
            await update.message.reply_text("📊 Нет ботов для статистики", reply_markup=main_keyboard())
            return

        now = datetime.now()
        total_balance = sum(b["balance"] for b in bots)
        running = sum(1 for b in bots if b["status"] == "running")
        p_day = p_week = p_month = p_total = 0.0

        for b in bots:
            p_day += await self.db.get_profit_since(b["id"], now - timedelta(days=1))
            p_week += await self.db.get_profit_since(b["id"], now - timedelta(weeks=1))
            p_month += await self.db.get_profit_since(b["id"], now - timedelta(days=30))
            p_total += await self.db.get_total_profit(b["id"])

        text = (
            "📊 Общая статистика\n━━━━━━━━━━━━━━━━━━━━\n\n"
            "Ботов: " + str(len(bots)) + "  |  Работает: " + str(running) + "\n"
            "Баланс: " + TradingBot._usd(total_balance) + " USDT\n\n"
            "Прибыль:\n"
            "  24ч:    " + TradingBot._usd(p_day) + "\n"
            "  7 дней: " + TradingBot._usd(p_week) + "\n"
            "  30 дней: " + TradingBot._usd(p_month) + "\n"
            "  Всего:  " + TradingBot._usd(p_total) + "\n\n"
            "Боты:\n"
        )
        for b in bots:
            emoji = "🟢" if b["status"] == "running" else "🔴"
            mode = b.get("mode") or MODE_SIMULATOR
            mode_icon = {"simulator": "🔵", "testnet": "🟡", "real": "🔴"}.get(mode, "🔵")
            profit = await self.db.get_total_profit(b["id"])
            text += "  {} {} {}: ".format(emoji, b['name'], mode_icon) + TradingBot._usd(b['balance']) + " | +" + TradingBot._usd(profit) + "\n"

        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

    # ─── DELETE ───────────────────────────────────────────────────────────

    async def _confirm_delete(self, update: Update, uid: int):
        bot_id = self.selected_bot.get(uid)
        if not bot_id:
            return
        bot = await self.db.get_bot(bot_id)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"del:{bot_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"sel:{bot_id}")
        ]])
        await update.message.reply_text(
            f"⚠️ Удалить бота *{bot['name']}*?\nВсе данные будут потеряны!",
            parse_mode="Markdown",
            reply_markup=kb
        )

    # ─── NEW FEATURES ─────────────────────────────────────────────────────
    
    async def _show_profit_chart(self, update: Update, uid: int):
        """Show profit chart (matplotlib)."""
        bot_id = self.selected_bot.get(uid)
        if not bot_id:
            await self._send(update, uid, "❌ Сначала выберите бота")
            return
        
        bot = await self.db.get_bot(bot_id)
        
        try:
            from chart_generator import ChartGenerator
            
            # Get trades
            trades = []  # TODO: get from database
            
            chart_gen = ChartGenerator()
            image_bytes = chart_gen.generate_profit_chart(trades, bot["name"])
            
            await update.message.reply_photo(
                photo=image_bytes,
                caption=f"📈 График прибыли: *{bot['name']}*",
                parse_mode="Markdown",
                reply_markup=bot_keyboard()
            )
        except ImportError:
            await self._send(
                update, uid,
                "📈 *График прибыли*\n\n"
                "❌ Модуль matplotlib не установлен\n\n"
                "Установите:\n`pip install matplotlib`",
                reply_markup=bot_keyboard()
            )
        except Exception as e:
            logger.error(f"Chart generation error: {e}")
            await self._send(
                update, uid,
                f"❌ Ошибка генерации графика: {e}",
                reply_markup=bot_keyboard()
            )
    
    async def _show_ai_analysis(self, update: Update, uid: int):
        """Show AI analysis of bot performance."""
        bot_id = self.selected_bot.get(uid)
        if not bot_id:
            await self._send(update, uid, "❌ Сначала выберите бота")
            return
        
        bot = await self.db.get_bot(bot_id)
        
        # Show "thinking" message
        thinking_msg = await update.message.reply_text(
            "🤖 AI анализирует вашего бота...",
            reply_markup=bot_keyboard()
        )
        
        try:
            from ai_advisor import AIAdvisor
            from binance_client import MockBinanceClient
            
            advisor = AIAdvisor()
            client = MockBinanceClient()
            current_price = client.get_current_price()
            
            # Prepare bot data
            bot_data = {
                'name': bot['name'],
                'balance': bot.get('balance', 0),
                'total_profit': 0,  # TODO: calculate from trades
                'active_orders': len(await self.db.get_open_orders(bot_id)),
                'total_trades': 0,  # TODO: count trades
                'win_rate': 0.0,  # TODO: calculate
                'status': bot['status'],
                'current_price': current_price
            }
            
            # Get AI advice
            advice = await advisor.analyze_bot_performance(bot_data)
            
            await thinking_msg.edit_text(
                advice,
                parse_mode="Markdown",
                reply_markup=bot_keyboard()
            )
            
        except ImportError:
            await thinking_msg.edit_text(
                "🤖 *AI Анализ*\n\n"
                "❌ Модуль openai не установлен\n\n"
                "Установите:\n`pip install openai`\n\n"
                "Или используется MOCK режим",
                parse_mode="Markdown",
                reply_markup=bot_keyboard()
            )
        except Exception as e:
            logger.error(f"AI analysis error: {e}")
            await thinking_msg.edit_text(
                f"❌ Ошибка AI анализа: {e}\n\n"
                "Работает MOCK режим (без OpenAI API)",
                reply_markup=bot_keyboard()
            )
    
    async def _clone_bot(self, update: Update, uid: int):
        """Clone/duplicate current bot with same settings."""
        bot_id = self.selected_bot.get(uid)
        if not bot_id:
            await self._send(update, uid, "❌ Сначала выберите бота")
            return
        
        original_bot = await self.db.get_bot(bot_id)
        
        # Create new bot with same settings
        new_name = f"{original_bot['name']} (копия)"
        new_bot = await self.db.create_bot(
            name=new_name,
            symbol=original_bot.get('symbol', 'BTCUSDT')
        )
        
        # Copy settings
        await self.db.update_bot(
            new_bot['id'],
            mode=original_bot.get('mode', MODE_SIMULATOR),
            order_usdt=original_bot.get('order_usdt', 50),
            api_key=original_bot.get('api_key', ''),
            secret_key=original_bot.get('secret_key', ''),
            theme=original_bot.get('theme', 'dark'),
            daily_report=original_bot.get('daily_report', False)
        )
        
        await self._send(
            update, uid,
            f"✅ Бот *{new_name}* создан!\n\n"
            f"Скопированы все настройки:\n"
            f"• Символ: {original_bot.get('symbol', 'BTCUSDT')}\n"
            f"• Режим: {MODE_LABELS.get(original_bot.get('mode', MODE_SIMULATOR))}\n"
            f"• Сумма ордера: ${original_bot.get('order_usdt', 50):.2f}\n"
            f"• API: {'✅' if original_bot.get('api_key') else '❌'}\n\n"
            f"💵 Не забудьте добавить деньги новому боту!",
            reply_markup=bot_keyboard()
        )
    
    async def _change_theme(self, update: Update, uid: int):
        """Change bot UI theme."""
        bot_id = self.selected_bot.get(uid)
        if not bot_id:
            await self._send(update, uid, "❌ Сначала выберите бота")
            return
        
        themes = {
            "🌙 Тёмная": "dark",
            "☀️ Светлая": "light",
            "💜 Фиолетовая": "purple",
            "🌊 Синяя": "blue"
        }
        
        kb = [[KeyboardButton(theme)] for theme in themes.keys()]
        kb.append([KeyboardButton("⬅️ Назад к настройкам")])
        
        self.awaiting[uid] = "select_theme"
        await self._send(
            update, uid,
            "🎨 *Выберите тему оформления:*\n\n"
            "🌙 Тёмная - чёрный фон\n"
            "☀️ Светлая - белый фон\n"
            "💜 Фиолетовая - градиент\n"
            "🌊 Синяя - океан",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )
    
    async def _toggle_daily_report(self, update: Update, uid: int):
        """Toggle daily report on/off."""
        bot_id = self.selected_bot.get(uid)
        if not bot_id:
            await self._send(update, uid, "❌ Сначала выберите бота")
            return
        
        bot = await self.db.get_bot(bot_id)
        current = bot.get('daily_report', False)
        new_value = not current
        
        await self.db.update_bot(bot_id, daily_report=new_value)
        
        status = "✅ Включён" if new_value else "❌ Выключен"
        await self._send(
            update, uid,
            f"⏰ *Дневной отчёт*\n\n"
            f"Статус: {status}\n\n"
            + ("📊 Каждый день в 00:00 вы будете получать отчёт:\n"
               "• Прибыль за день\n"
               "• Количество сделок\n"
               "• Лучшая сделка\n"
               "• Сравнение с вчера" if new_value else 
               "Автоматические отчёты отключены"),
            reply_markup=settings_keyboard()
        )

    # ─── RUN ──────────────────────────────────────────────────────────────

    async def run(self):
        await self.db.initialize()

        running_bots = await self.db.get_all_bots()
        for bot in running_bots:
            if bot["status"] == "running" and (bot.get("mode") or MODE_SIMULATOR) == MODE_SIMULATOR:
                price = bot.get("center_price") or 100000.0
                await self.simulator.start_bot_simulation(bot["id"], price)
                logger.info(f"Resumed simulation for bot: {bot['name']}")

        app = Application.builder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CallbackQueryHandler(self.handle_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        logger.info("Bot started!")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        try:
            await asyncio.Event().wait()
        finally:
            # Stop all monitoring tasks
            for bot_id in list(self._monitor_tasks.keys()):
                await self._stop_monitoring(bot_id)
            await self.simulator.stop_all()
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
            await self.db.close()
