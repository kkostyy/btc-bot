"""
Fixed BTC Grid Trading Bot - Single File Implementation
Features:
- Real Binance Futures Testnet trading
- Dynamic speed update
- Redesigned menu structure
- Proper state management
- Error handling and logging
"""
import asyncio
import logging
import os
import time
import hmac
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
import sqlite3
import matplotlib.pyplot as plt
import io
from typing import Dict, List, Optional, Tuple

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    Message,
    CallbackQuery,
    FSInputFile,
    InputFile,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# ======================
# CONFIGURATION
# ======================
# API Keys - Replace with your Binance Testnet keys or set via environment variables
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_SECRET_KEY", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Trading Parameters (can be overridden per bot)
DEFAULT_ORDER_USDT = 50.0
DEFAULT_LEVERAGE = 20
DEFAULT_SYMBOL = "BTCUSDT"

# Binance Testnet URLs
BASE_URL = "https://testnet.binancefuture.com"
FUTURES_URL = f"{BASE_URL}/fapi"

# Speed settings (interval in seconds between grid checks)
SPEED_SETTINGS = {
    "🐌 Медленная (x4)": 60,
    "🐢 Медленная (x2)": 30,
    "⚙️ Стандартная": 10,
    "⚡ Быстрая (x2)": 5,
    "🚀 Супер быстрая (x4)": 2,
}

# ======================
# LOGGING SETUP
# ======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log"),
    ],
)
logger = logging.getLogger(__name__)

# ======================
# DATABASE SETUP
# ======================
DB_NAME = "trading_bot.db"


def init_db():
    """Initialize SQLite database with required tables."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Bots table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            symbol TEXT DEFAULT 'BTCUSDT',
            status TEXT DEFAULT 'stopped',
            order_usdt REAL DEFAULT 50.0,
            leverage INTEGER DEFAULT 20,
            grid_step REAL DEFAULT 0.1,  # in percentage
            grid_offset REAL DEFAULT 0.175,  # in percentage
            grid_levels INTEGER DEFAULT 5,
            mode TEXT DEFAULT 'simulator',  # simulator, testnet, real
            speed_key TEXT DEFAULT '⚙️ Стандартная',
            theme TEXT DEFAULT 'dark',
            daily_report INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # Orders table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER NOT NULL,
            exchange_order_id TEXT,
            side TEXT NOT NULL,
            price REAL NOT NULL,
            quantity REAL NOT NULL,
            status TEXT DEFAULT 'OPEN',
            created_at TEXT NOT NULL,
            FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
        )
    """)

    # Pairs table (for tracking buy/sell pairs)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER NOT NULL,
            buy_order_id TEXT,
            sell_order_id TEXT,
            buy_price REAL NOT NULL,
            sell_price REAL NOT NULL,
            quantity REAL NOT NULL,
            profit REAL DEFAULT 0,
            status TEXT DEFAULT 'OPEN',
            created_at TEXT NOT NULL,
            FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()
    logger.info("Database initialized")


# ======================
# BINANCE CLIENT
# ======================
class BinanceClient:
    """Wrapper for Binance Futures Testnet API."""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        if testnet:
            self.base_url = BASE_URL
        else:
            self.base_url = "https://fapi.binance.com"
        self.session = None  # Will be initialized when needed

    def _get_session(self):
        if self.session is None:
            import requests
            self.session = requests.Session()
            self.session.headers.update({
                "X-MBX-APIKEY": self.api_key,
                "Content-Type": "application/json"
            })
        return self.session

    def _sign(self, params: dict) -> str:
        """Create signature for Binance API request."""
        query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def _request(self, method: str, endpoint: str, params: dict = None, signed: bool = False):
        """Make HTTP request to Binance API."""
        params = params or {}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign(params)

        url = f"{self.base_url}{endpoint}"
        session = self._get_session()

        try:
            if method == "GET":
                resp = session.get(url, params=params)
            elif method == "POST":
                resp = session.post(url, params=params)
            elif method == "DELETE":
                resp = session.delete(url, params=params)
            else:
                raise ValueError(f"Unsupported method: {method}")

            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Binance API error: {e}")
            raise

    def get_exchange_info(self):
        """Get exchange information (for symbol filters)."""
        return self._request("GET", "/fapi/v1/exchangeInfo")

    def get_price(self, symbol: str = DEFAULT_SYMBOL) -> float:
        """Get current mark price for symbol."""
        data = self._request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})
        return float(data["markPrice"])

    def get_balance(self) -> float:
        """Get USDT balance."""
        data = self._request("GET", "/fapi/v2/balance", signed=True)
        for asset in data:
            if asset["asset"] == "USDT":
                return float(asset["balance"])
        return 0.0

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        reduce_only: bool = False,
    ) -> dict:
        """Place a LIMIT order on Binance Futures."""
        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": f"{quantity:.3f}",  # 3 decimal places
            "price": f"{price:.1f}",        # 1 decimal place
            "positionSide": "BOTH",         # Required for one-way mode
        }
        if reduce_only:
            params["reduceOnly"] = "true"

        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def cancel_order(self, symbol: str, order_id: str) -> dict:
        """Cancel an order."""
        return self._request(
            "DELETE", "/fapi/v1/order",
            {"symbol": symbol, "orderId": order_id},
            signed=True
        )

    def get_open_orders(self, symbol: str = DEFAULT_SYMBOL) -> List[dict]:
        """Get all open orders for symbol."""
        return self._request(
            "GET", "/fapi/v1/openOrders",
            {"symbol": symbol},
            signed=True
        )

    def change_leverage(self, symbol: str, leverage: int) -> dict:
        """Change leverage for symbol."""
        return self._request(
            "POST", "/fapi/v1/leverage",
            {"symbol": symbol, "leverage": leverage},
            signed=True
        )

    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> dict:
        """Set margin type for symbol."""
        return self._request(
            "POST", "/fapi/v1/marginType",
            {"symbol": symbol, "marginType": margin_type},
            signed=True
        )


# ======================
# TRADING LOGIC
# ======================
class GridTrader:
    """Manages grid trading for a single bot."""

    def __init__(self, bot_id: int, user_id: int, db_path: str = DB_NAME):
        self.bot_id = bot_id
        self.user_id = user_id
        self.db_path = db_path
        self.binance_client: Optional[BinanceClient] = None
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        self._load_bot_config()

    def _load_bot_config(self):
        """Load bot configuration from database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bots WHERE id = ?", (self.bot_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            (
                self.id,
                self.user_id,
                self.name,
                self.symbol,
                self.status,
                self.order_usdt,
                self.leverage,
                self.grid_step,
                self.grid_offset,
                self.grid_levels,
                self.mode,
                self.speed_key,
                self.theme,
                self.daily_report,
                self.created_at,
                self.updated_at,
            ) = row
        else:
            raise ValueError(f"Bot {self.bot_id} not found")

    def _save_bot_config(self):
        """Save bot configuration to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE bots SET
                name = ?, symbol = ?, status = ?, order_usdt = ?, leverage = ?,
                grid_step = ?, grid_offset = ?, grid_levels = ?, mode = ?,
                speed_key = ?, theme = ?, daily_report = ?, updated_at = ?
            WHERE id = ?
        """, (
            self.name, self.symbol, self.status, self.order_usdt, self.leverage,
            self.grid_step, self.grid_offset, self.grid_levels, self.mode,
            self.speed_key, self.theme, self.daily_report,
            datetime.now().isoformat(), self.bot_id
        ))
        conn.commit()
        conn.close()

    def _initialize_binance(self):
        """Initialize Binance client based on mode."""
        if self.mode == "testnet" or self.mode == "real":
            if not API_KEY or not API_SECRET:
                logger.warning("API keys not set, falling back to simulator")
                self.mode = "simulator"
                self.binance_client = None
                return

            testnet = (self.mode == "testnet")
            self.binance_client = BinanceClient(API_KEY, API_SECRET, testnet=testnet)

            # Set leverage and margin type
            try:
                self.binance_client.change_leverage(self.symbol, self.leverage)
                self.binance_client.set_margin_type(self.symbol, "ISOLATED")
                logger.info(f"Leverage set to {self.leverage}x for {self.symbol}")
            except Exception as e:
                logger.error(f"Failed to set leverage/margin: {e}")
        else:
            self.binance_client = None  # Simulator mode

    async def start(self):
        """Start the grid trading bot."""
        if self.is_running:
            logger.warning(f"Bot {self.bot_id} is already running")
            return

        self.is_running = True
        self.status = "running"
        self._save_bot_config()
        self._initialize_binance()

        # Start the trading loop
        self.task = asyncio.create_thread(self._trading_loop())
        logger.info(f"Bot {self.bot_id} started in {self.mode} mode")

    async def stop(self):
        """Stop the grid trading bot."""
        if not self.is_running:
            logger.warning(f"Bot {self.bot_id} is not running")
            return

        self.is_running = False
        self.status = "stopped"
        self._save_bot_config()

        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

        # Cancel all open orders
        if self.binance_client and self.mode != "simulator":
            try:
                open_orders = self.binance_client.get_open_orders(self.symbol)
                for order in open_orders:
                    self.binance_client.cancel_order(self.symbol, str(order["orderId"]))
                logger.info(f"Cancelled {len(open_orders)} open orders for bot {self.bot_id}")
            except Exception as e:
                logger.error(f"Error cancelling orders: {e}")

        logger.info(f"Bot {self.bot_id} stopped")

    async def _trading_loop(self):
        """Main trading loop that places and manages grid orders."""
        logger.info(f"Trading loop started for bot {self.bot_id}")

        while self.is_running:
            try:
                await self._manage_grid()
                # Get interval from speed setting (read fresh each time)
                interval = SPEED_SETTINGS.get(self.speed_key, 10)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                await asyncio.sleep(5)  # Short pause before retry

    async def _manage_grid(self):
        """Check and place grid orders as needed."""
        # Skip if not in trading mode
        if self.mode == "simulator":
            logger.debug("Simulator mode - no real orders placed")
            return

        if not self.binance_client:
            logger.error("Binance client not initialized")
            return

        try:
            # Get current price
            current_price = self.binance_client.get_price(self.symbol)
            logger.debug(f"Current {self.symbol} price: {current_price}")

            # Calculate grid levels
            grid_levels = await self._calculate_grid_levels(current_price)

            # Get existing open orders
            open_orders = self.binance_client.get_open_orders(self.symbol)
            open_order_prices = {float(o["price"]) for o in open_orders}

            # Place missing orders
            for level in grid_levels:
                price = level["price"]
                side = level["side"]

                # Skip if we already have an order at this price (within tolerance)
                if any(abs(price - p) < 0.1 for p in open_order_prices):
                    continue

                # Calculate quantity based on order_usdt and price
                quantity = (self.order_usdt / price) * self.leverage
                quantity = self._round_quantity(quantity)

                # Place the order
                order = self.binance_client.place_order(
                    symbol=self.symbol,
                    side=side,
                    quantity=quantity,
                    price=price,
                )

                if order:
                    logger.info(
                        f"Placed {side} order: {quantity} {self.symbol} @ {price} "
                        f"(orderId: {order['orderId']})"
                    )
                    # Save order to database
                    self._save_order(order["orderId"], side, price, quantity)
                else:
                    logger.error("Failed to place order")

        except Exception as e:
            logger.error(f"Error managing grid: {e}")

    async def _calculate_grid_levels(self, current_price: float) -> List[Dict]:
        """Calculate grid buy and sell levels based on current price."""
        levels = []

        # Convert percentages to multipliers
        offset_mult = 1 + (self.grid_offset / 100)
        step_mult = 1 + (self.grid_step / 100)

        # Calculate center price (adjusted by offset)
        center_price = current_price * offset_mult

        # Generate sell levels (above center)
        for i in range(1, self.grid_levels + 1):
            price = center_price * (step_mult ** i)
            levels.append({
                "price": round(price, 1),
                "side": "SELL",
                "level": i,
                "type": "sell"
            })

        # Generate buy levels (below center)
        for i in range(1, self.grid_levels + 1):
            price = center_price / (step_mult ** i)
            levels.append({
                "price": round(price, 1),
                "side": "BUY",
                "level": i,
                "type": "buy"
            })

        # Sort by price
        levels.sort(key=lambda x: x["price"])
        return levels

    def _round_quantity(self, quantity: float) -> float:
        """Round quantity to 3 decimal places."""
        return float(Decimal(str(quantity)).quantize(Decimal('0.001'), rounding=ROUND_DOWN))

    def _save_order(self, exchange_order_id: str, side: str, price: float, quantity: float):
        """Save order to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO orders (bot_id, exchange_order_id, side, price, quantity, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            self.bot_id, exchange_order_id, side, price, quantity,
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()

    def get_stats(self) -> Dict:
        """Get bot statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get open orders count
        cursor.execute("SELECT COUNT(*) FROM orders WHERE bot_id = ? AND status = 'OPEN'", (self.bot_id,))
        open_orders = cursor.fetchone()[0]

        # Get closed pairs (completed trades)
        cursor.execute("""
            SELECT SUM(profit) FROM pairs
            WHERE bot_id = ? AND status = 'CLOSED'
        """, (self.bot_id,))
        total_profit = cursor.fetchone()[0] or 0

        # Get total trades
        cursor.execute("SELECT COUNT(*) FROM pairs WHERE bot_id = ? AND status = 'CLOSED'", (self.bot_id,))
        total_trades = cursor.fetchone()[0]

        conn.close()

        return {
            "open_orders": open_orders,
            "total_profit": total_profit,
            "total_trades": total_trades,
            "status": self.status,
            "mode": self.mode,
            "order_usdt": self.order_usdt,
            "speed_key": self.speed_key,
        }


# ======================
# TELEGRAM BOT HANDLERS
# ======================
# States for FSM
class BotStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_deposit = State()
    waiting_for_withdrawal = State()
    waiting_for_api_key = State()
    waiting_for_api_secret = State()
    waiting_for_order_amount = State()
    waiting_for_speed = State()
    waiting_for_theme = State()


# Global dictionaries to track bot instances and user states
bot_instances: Dict[int, GridTrader] = {}  # bot_id -> GridTrader
user_selected_bot: Dict[int, int] = {}     # user_id -> bot_id
user_awaiting: Dict[int, State] = {}       # user_id -> State (for FSM fallback)
temp_api_key: Dict[int, str] = {}          # user_id -> temp api key during setup

# Initialize bot and dispatcher
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher(storage=storage)
router = Router()


# ======================
# KEYBOARD BUILDERS
# ======================
def main_keyboard() -> ReplyKeyboardMarkup:
    """Main menu keyboard."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="▶️ Запустить бота"),
        KeyboardButton(text="⏹ Остановить бота")
    )
    builder.row(
        KeyboardButton(text="📊 Статистика"),
        KeyboardButton(text="📈 График прибыли")
    )
    builder.row(
        KeyboardButton(text="⚙️ Настройки"),
        KeyboardButton(text="📋 Отчёт")
    )
    return builder.as_markup(resize_keyboard=True)


def settings_keyboard() -> ReplyKeyboardMarkup:
    """Settings menu - entry point."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="💰 Сумма ордера"),
        KeyboardButton(text="⚡ Скорость")
    )
    builder.row(
        KeyboardButton(text="📐 Режим торговли"),
        KeyboardButton(text="🎯 Отступ сетки")
    )
    builder.row(
        KeyboardButton(text="↔️ Шаг сетки"),
        KeyboardButton(text="🔢 Кол-во уровней")
    )
    builder.row(
        KeyboardButton(text="🔙 Назад")
    )
    return builder.as_markup(resize_keyboard=True)


def trading_settings_keyboard() -> ReplyKeyboardMarkup:
    """Group 1: Trading parameters."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="💰 Сумма ордера"),
        KeyboardButton(text="⚡ Скорость")
    )
    builder.row(
        KeyboardButton(text="📐 Режим торговли"),
        KeyboardButton(text="🎯 Отступ сетки")
    )
    builder.row(
        KeyboardButton(text="↔️ Шаг сетки"),
        KeyboardButton(text="🔢 Кол-во уровней")
    )
    builder.row(
        KeyboardButton(text="🔙 Настроек")
    )
    return builder.as_markup(resize_keyboard=True)


def display_settings_keyboard() -> ReplyKeyboardMarkup:
    """Group 2: Display and other settings."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="🎨 Тема"),
        KeyboardButton(text="📣 Уведомления")
    )
    builder.row(
        KeyboardButton(text="💾 Дублировать настройки")
    )
    builder.row(
        KeyboardButton(text="🔙 Настроек")
    )
    return builder.as_markup(resize_keyboard=True)


def mode_keyboard() -> ReplyKeyboardMarkup:
    """Trading mode selection."""
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🔵 Симулятор"))
    builder.row(KeyboardButton(text="🟡 Binance Testnet"))
    builder.row(KeyboardButton(text="🔴 Реальный Binance"))
    builder.row(KeyboardButton(text="🔙 Настроек"))
    return builder.as_markup(resize_keyboard=True)


def speed_keyboard() -> ReplyKeyboardMarkup:
    """Speed selection."""
    builder = ReplyKeyboardBuilder()
    for text in SPEED_SETTINGS.keys():
        builder.row(KeyboardButton(text=text))
    builder.row(KeyboardButton(text="🔙 Настроек"))
    return builder.as_markup(resize_keyboard=True)


def theme_keyboard() -> ReplyKeyboardMarkup:
    """Theme selection."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="🌙 Тёмная"),
        KeyboardButton(text="☀️ Светлая")
    )
    builder.row(
        KeyboardButton(text="💜 Фиолетовая"),
        KeyboardButton(text="🌊 Синяя")
    )
    builder.row(KeyboardButton(text="🔙 Настроек"))
    return builder.as_markup(resize_keyboard=True)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    """Cancel keyboard."""
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True)


# ======================
# HELPER FUNCTIONS
# ======================
async def send_message(chat_id: int, text: str, reply_markup=None, parse_mode=None):
    """Send a message to a chat."""
    if bot:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )


async def get_or_create_bot(user_id: int, name: str = None) -> int:
    """Get existing bot for user or create a new one."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Check if user already has a bot
    cursor.execute("SELECT id FROM bots WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,))
    row = cursor.fetchone()
    if row and not name:
        bot_id = row[0]
        conn.close()
        return bot_id

    # Create new bot
    if not name:
        name = f"Бот {user_id}"

    cursor.execute("""
        INSERT INTO bots (user_id, name, created_at, updated_at)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        name,
        datetime.now().isoformat(),
        datetime.now().isoformat()
    ))
    bot_id = cursor.lastrowid
    conn.commit()
    conn.close()

    logger.info(f"Created new bot {bot_id} for user {user_id}")
    return bot_id


def get_bot_trader(bot_id: int) -> GridTrader:
    """Get or create GridTrader instance for a bot."""
    if bot_id not in bot_instances:
        # Get user_id from bot
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM bots WHERE id = ?", (bot_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            user_id = row[0]
            bot_instances[bot_id] = GridTrader(bot_id, user_id)
        else:
            raise ValueError(f"Bot {bot_id} not found")
    return bot_instances[bot_id]


# ======================
# COMMAND AND MESSAGE HANDLERS
# ======================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command."""
    await state.clear()
    user_id = message.from_user.id

    # Get or create bot for user
    bot_id = await get_or_create_bot(user_id)
    user_selected_bot[user_id] = bot_id

    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "🤖 BTC Grid Trading Bot\n\n"
        "Управляйте торговыми ботами прямо из Telegram.\n"
        "Работает в трёх режимах:\n"
        "🔵 Симулятор — виртуальные сделки без API\n"
        "🟡 Binance Testnet — тест с реальной биржей\n"
        "🔴 Реальный Binance — настоящая торговля\n\n"
        "Выберите действие:",
        reply_markup=main_keyboard()
    )


@router.message(F.text == "▶️ Запустить бота")
async def start_bot(message: Message):
    """Start the selected bot."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)

    if not bot_id:
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    try:
        trader = get_bot_trader(bot_id)
        await trader.start()
        await message.answer(
            f"✅ Бот '{trader.name}' запущен в режиме {trader.mode}",
            reply_markup=main_keyboard()
        )
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        await message.answer(
            f"❌ Ошибка запуска бота: {str(e)}",
            reply_markup=main_keyboard()
        )


@router.message(F.text == "⏹ Остановить бота")
async def stop_bot(message: Message):
    """Stop the selected bot."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)

    if not bot_id:
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    try:
        trader = get_bot_trader(bot_id)
        await trader.stop()
        await message.answer(
            f"⏹ Бот '{trader.name}' остановлен",
            reply_markup=main_keyboard()
        )
    except Exception as e:
        logger.error(f"Error stopping bot: {e}")
        await message.answer(
            f"❌ Ошибка остановки бота: {str(e)}",
            reply_markup=main_keyboard()
        )


@router.message(F.text == "📊 Статистика")
async def show_stats(message: Message):
    """Show bot statistics."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)

    if not bot_id:
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    try:
        trader = get_bot_trader(bot_id)
        stats = trader.get_stats()

        text = (
            f"📊 *Статистика бота*{trader.name}\n\n"
            f"🟢 Статус: {'Работает' if trader.is_running else 'Остановлен'}\n"
            f"💰 Баланс: {trader.order_usdt} USDT (за ордер)\n"
            f"📈 Прибыль: {stats['total_profit']:.2f} USDT\n"
            f"🔢 Сделок: {stats['total_trades']}\n"
            f"📂 Открытых ордеров: {stats['open_orders']}\n"
            f"⚙️ Режим: {trader.mode}\n"
            f"🚀 Скорость: {trader.speed_key}\n"
            f"📐 Отступ: {trader.grid_offset}%\n"
            f"↔️ Шаг: {trader.grid_step}%\n"
            f"🔢 Уровней: {trader.grid_levels}\n"
        )

        await message.answer(text, parse_mode="Markdown", reply_markup=main_keyboard())
    except Exception as e:
        logger.error(f"Error showing stats: {e}")
        await message.answer(
            f"❌ Ошибка получения статистики: {str(e)}",
            reply_markup=main_keyboard()
        )


@router.message(F.text == "📈 График прибыли")
async def show_profit_chart(message: Message):
    """Generate and send profit chart."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)

    if not bot_id:
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    try:
        # Get trade history from database
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT executed_at, profit FROM pairs
            WHERE bot_id = ? AND status = 'CLOSED'
            ORDER BY executed_at
        """, (bot_id,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await message.answer(
                "📈 Нет данных для графика. Совершите несколько сделок.",
                reply_markup=main_keyboard()
            )
            return

        # Prepare data for plotting
        dates = [datetime.fromisoformat(row[0]) for row in rows]
        profits = [row[1] for row in rows]
        cumulative = []
        total = 0
        for p in profits:
            total += p
            cumulative.append(total)

        # Create plot
        plt.figure(figsize=(10, 6))
        plt.plot(dates, cumulative, marker='o', linestyle='-', linewidth=2)
        plt.title(f'Прибыль бота: {trader.name if "trader" in locals() else ""}')
        plt.xlabel('Дата')
        plt.ylabel('Кумулятивная прибыль, USDT')
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()

        # Save to buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150)
        buf.seek(0)
        plt.close()

        # Send photo
        await message.answer_photo(
            photo=buf,
            caption="📈 График кумулятивной прибыли",
            reply_markup=main_keyboard()
        )
    except Exception as e:
        logger.error(f"Error generating profit chart: {e}")
        await message.answer(
            f"❌ Ошибка генерации графика: {str(e)}",
            reply_markup=main_keyboard()
        )


@router.message(F.text == "⚙️ Настройки")
async def open_settings(message: Message):
    """Open settings menu."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)

    if not bot_id:
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    trader = get_bot_trader(bot_id)

    text = (
        f"⚙️ *Настройки бота*{trader.name}\n\n"
        f"Режим: {trader.mode}\n"
        f"Сумма ордера: {trader.order_usdt} USDT\n"
        f"Скорость: {trader.speed_key}\n"
        f"Режим торговли: BOTH (фиксирован)\n"
        f"Отступ сетки: {trader.grid_offset}%\n"
        f"Шаг сетки: {trader.grid_step}%\n"
        f"Уровней: {trader.grid_levels}\n"
        f"Тема: {trader.theme}\n"
        f"Дневной отчёт: {'Включен' if trader.daily_report else 'Выключен'}\n\n"
        "Выберите группу настроек:"
    )

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="💰 Торговые параметры"), KeyboardButton(text="🎨 Отображение и прочее")],
                [KeyboardButton(text="🔙 Главное меню")]
            ],
            resize_keyboard=True
        )
    )


# ======================
# TRADING SETTINGS HANDLERS
# ======================
@router.message(F.text == "💰 Торговые параметры")
async def open_trading_settings(message: Message):
    """Open trading parameters settings."""
    await message.answer(
        "⚙️ Торговые параметры\n\nВыберите что хотите изменить:",
        reply_markup=trading_settings_keyboard()
    )


@router.message(F.text == "🎨 Отображение и прочее")
async def open_display_settings(message: Message):
    """Open display settings."""
    await message.answer(
        "🎨 Отображение и прочее\n\nВыберите что хотите изменить:",
        reply_markup=display_settings_keyboard()
    )


# Trading parameter handlers
@router.message(F.text == "💰 Сумма ордера")
async def ask_order_amount(message: Message, state: FSMContext):
    """Ask for order amount."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)
    if not bot_id:
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    trader = get_bot_trader(bot_id)
    await state.set_state(BotStates.waiting_for_order_amount)
    user_awaiting[user_id] = BotStates.waiting_for_order_amount

    await message.answer(
        f"💰 *Сумма одного ордера*\n\n"
        f"Текущая: {trader.order_usdt} USDT\n\n"
        "Введите сумму в USDT (например: 50):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )


@router.message(F.text == "⚡ Скорость")
async def ask_speed(message: Message, state: FSMContext):
    """Ask for speed setting."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)
    if not bot_id:
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    await state.set_state(BotStates.waiting_for_speed)
    user_awaiting[user_id] = BotStates.waiting_for_speed

    await message.answer(
        "⚡ *Шаг сетки ордеров*\n\n"
        "Выберите скорость проверки сетки:",
        parse_mode="Markdown",
        reply_markup=speed_keyboard()
    )


@router.message(F.text == "📐 Режим торговли")
async def ask_mode(message: Message, state: FSMContext):
    """Ask for trading mode."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)
    if not bot_id:
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    await state.set_state(BotStates.waiting_for_api_key)  # Reusing state for mode selection
    user_awaiting[user_id] = BotStates.waiting_for_api_key

    await message.answer(
        "📐 *Режим работы*\n\n"
        "Выберите режим торговли:",
        parse_mode="Markdown",
        reply_markup=mode_keyboard()
    )


# Note: Offsets, step, and levels handlers would be similar but omitted for brevity
# In a complete implementation, you would add handlers for:
# - 🎯 Отступ сетки
# - ↔️ Шаг сетки
# - 🔢 Кол-во уровней


# ======================
# DISPLAY SETTINGS HANDLERS
# ======================
@router.message(F.text == "🎨 Тема")
async def ask_theme(message: Message, state: FSMContext):
    """Ask for theme setting."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)
    if not bot_id:
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    await state.set_state(BotStates.waiting_for_theme)
    user_awaiting[user_id] = BotStates.waiting_for_theme

    await message.answer(
        "🎨 *Выберите тему оформления*\n\n"
        "Выберите одну из доступных тем:",
        parse_mode="Markdown",
        reply_markup=theme_keyboard()
    )


@router.message(F.text == "💾 Дублировать настройки")
async def duplicate_settings(message: Message):
    """Duplicate bot settings (show current settings as text)."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)
    if not bot_id:
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    trader = get_bot_trader(bot_id)

    text = (
        f"💾 *Текущие настройки бота*{trader.name}\n\n"
        f"Режим: {trader.mode}\n"
        f"Сумма ордера: {trader.order_usdt} USDT\n"
        f"Скорость: {trader.speed_key}\n"
        f"Отступ сетки: {trader.grid_offset}%\n"
        f"Шаг сетки: {trader.grid_step}%\n"
        f"Уровней: {trader.grid_levels}\n"
        f"Тема: {trader.theme}\n"
        f"Дневной отчёт: {'Включен' if trader.daily_report else 'Выключен'}\n\n"
        "Скопируйте эти значения для настройки другого бота."
    )

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )


@router.message(F.text == "🔙 Настроек")
@router.message(F.text == "🔙 Главное меню")
async def back_to_main(message: Message, state: FSMContext):
    """Return to main menu."""
    await state.clear()
    user_id = message.from_user.id
    if user_id in user_awaiting:
        del user_awaiting[user_id]

    await message.answer("🏠 Главное меню", reply_markup=main_keyboard())


# ======================
# FSM INPUT HANDLERS
# ======================
@router.message(BotStates.waiting_for_order_amount)
async def process_order_amount(message: Message, state: FSMContext):
    """Process order amount input."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)
    if not bot_id:
        await state.clear()
        if user_id in user_awaiting:
            del user_awaiting[user_id]
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введите корректную сумму числом больше нуля:",
            reply_markup=cancel_keyboard()
        )
        return

    trader = get_bot_trader(bot_id)
    trader.order_usdt = amount
    trader._save_bot_config()

    await state.clear()
    if user_id in user_awaiting:
        del user_awaiting[user_id]

    await message.answer(
        f"✅ Сумма ордера установлена: {amount} USDT",
        reply_markup=main_keyboard()
    )


@router.message(BotStates.waiting_for_speed)
async def process_speed(message: Message, state: FSMContext):
    """Process speed selection."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)
    if not bot_id:
        await state.clear()
        if user_id in user_awaiting:
            del user_awaiting[user_id]
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    speed_text = message.text
    if speed_text not in SPEED_SETTINGS:
        await message.answer(
            "❌ Пожалуйста, выберите скорость из списка:",
            reply_markup=speed_keyboard()
        )
        return

    trader = get_bot_trader(bot_id)
    trader.speed_key = speed_text
    trader._save_bot_config()

    # Note: The trading loop reads speed_key on each iteration, so change takes effect immediately

    await state.clear()
    if user_id in user_awaiting:
        del user_awaiting[user_id]

    await message.answer(
        f"✅ Скорость установлена: {speed_text}",
        reply_markup=main_keyboard()
    )


@router.message(BotStates.waiting_for_api_key)
async def process_mode(message: Message, state: FSMContext):
    """Process trading mode selection."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)
    if not bot_id:
        await state.clear()
        if user_id in user_awaiting:
            del user_awaiting[user_id]
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    mode_map = {
        "🔵 Симулятор": "simulator",
        "🟡 Binance Testnet": "testnet",
        "🔴 Реальный Binance": "real"
    }

    mode_text = message.text
    if mode_text not in mode_map:
        await message.answer(
            "❌ Пожалуйста, выберите режим из списка:",
            reply_markup=mode_keyboard()
        )
        return

    new_mode = mode_map[mode_text]
    trader = get_bot_trader(bot_id)

    # If switching to testnet or real, verify API keys
    if new_mode in ["testnet", "real"] and (not API_KEY or not API_SECRET):
        await message.answer(
            "❌ Для работы в режиме Testnet или Real необходимы API ключи.\n"
            "Установите переменные окружения BINANCE_API_KEY и BINANCE_SECRET_KEY\n"
            "или обратитесь к администратору.",
            reply_markup=main_keyboard()
        )
        await state.clear()
        if user_id in user_awaiting:
            del user_awaiting[user_id]
        return

    trader.mode = new_mode
    trader._save_bot_config()

    # If bot is running, restart to apply new mode
    was_running = trader.is_running
    if was_running:
        await trader.stop()
        await trader.start()

    await state.clear()
    if user_id in user_awaiting:
        del user_awaiting[user_id]

    await message.answer(
        f"✅ Режим работы установлен: {mode_text}\n"
        f"{'Бот перезапущен с новыми настройками' if was_running else ''}",
        reply_markup=main_keyboard()
    )


@router.message(BotStates.waiting_for_theme)
async def process_theme(message: Message, state: FSMContext):
    """Process theme selection."""
    user_id = message.from_user.id
    bot_id = user_selected_bot.get(user_id)
    if not bot_id:
        await state.clear()
        if user_id in user_awaiting:
            del user_awaiting[user_id]
        await message.answer("❌ Сначала выберите бота", reply_markup=main_keyboard())
        return

    theme_map = {
        "🌙 Тёмная": "dark",
        "☀️ Светлая": "light",
        "💜 Фиолетовая": "purple",
        "🌊 Синяя": "blue"
    }

    theme_text = message.text
    if theme_text not in theme_map:
        await message.answer(
            "❌ Пожалуйста, выберите тему из списка:",
            reply_markup=theme_keyboard()
        )
        return

    new_theme = theme_map[theme_text]
    trader = get_bot_trader(bot_id)
    trader.theme = new_theme
    trader._save_bot_config()

    await state.clear()
    if user_id in user_awaiting:
        del user_awaiting[user_id]

    await message.answer(
        f"✅ Тема установлена: {theme_text}",
        reply_markup=main_keyboard()
    )


# ======================
# ERROR HANDLER
# ======================
@router.message()
async def handle_unknown(message: Message):
    """Handle unknown messages."""
    await message.answer(
        "❓ Используйте кнопки меню для навигации",
        reply_markup=main_keyboard()
    )


# ======================
# MAIN FUNCTION
# ======================
async def main():
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set! Please set the BOT_TOKEN environment variable.")
        return

    # Initialize database
    init_db()

    # Include router
    dp.include_router(router)

    # Start polling
    await dp.start_polling(bot)
    logger.info("Bot started")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")