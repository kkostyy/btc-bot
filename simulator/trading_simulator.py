"""
Trading Simulator - generates virtual trades automatically.
Simulates real grid trading logic with BTC price movements.
"""
import asyncio
import random
import logging
from datetime import datetime
from models.models import Trade
from database import DatabaseManager

logger = logging.getLogger(__name__)


class TradingSimulator:
    """
    Simulates grid trading for virtual bots.
    Generates realistic trades based on BTC price movements.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.running_bots = {}       # bot_id -> task
        self.bot_prices = {}         # bot_id -> current BTC price
        self.order_counter = {}      # bot_id -> order counter

    async def start_bot_simulation(self, bot_id: int, center_price: float = 100000.0, speed: int = 1):
        """Start simulation for a specific bot."""
        if bot_id in self.running_bots:
            logger.info(f"Bot {bot_id} simulation already running")
            return

        self.bot_prices[bot_id] = center_price
        self.order_counter[bot_id] = 0

        task = asyncio.create_task(self._simulate_bot(bot_id, speed))
        self.running_bots[bot_id] = task
        logger.info(f"Started simulation for bot {bot_id} at price ${center_price:.2f}, speed x{speed}")

    async def stop_bot_simulation(self, bot_id: int):
        """Stop simulation for a specific bot."""
        if bot_id in self.running_bots:
            self.running_bots[bot_id].cancel()
            del self.running_bots[bot_id]
            logger.info(f"Stopped simulation for bot {bot_id}")

    async def stop_all(self):
        """Stop all running simulations."""
        for bot_id in list(self.running_bots.keys()):
            await self.stop_bot_simulation(bot_id)

    async def _simulate_bot(self, bot_id: int, speed: int = 1):
        """
        speed > 0: быстрее стандарта (x2, x4)
        speed = 1: стандарт (30-90 сек)
        speed < 0: медленнее стандарта (-2: x2 медленнее, -4: x4 медленнее)
        """
        logger.info(f"Bot {bot_id} simulation loop started, speed x{speed}")
        if speed > 0:
            base_min = max(7, 30 // speed)
            base_max = max(22, 90 // speed)
        else:
            factor = abs(speed)
            base_min = 30 * factor
            base_max = 90 * factor

        while True:
            try:
                wait_time = random.randint(base_min, base_max)
                await asyncio.sleep(wait_time)

                # Check if bot is still running in DB
                bot = await self.db.get_bot_by_id(bot_id)
                if not bot or not bot.is_running():
                    logger.info(f"Bot {bot_id} stopped, ending simulation")
                    break

                # Simulate a trade
                trade = await self._generate_trade(bot_id)
                if trade:
                    logger.info(
                        f"Bot {bot_id} generated trade: "
                        f"buy=${trade.buy_price:.2f}, "
                        f"sell=${trade.sell_price:.2f}, "
                        f"profit=${trade.profit:.2f}"
                    )

            except asyncio.CancelledError:
                logger.info(f"Bot {bot_id} simulation cancelled")
                break
            except Exception as e:
                logger.error(f"Error in bot {bot_id} simulation: {e}")
                await asyncio.sleep(10)

    async def _generate_trade(self, bot_id: int) -> Trade:
        """Generate a realistic grid trade."""
        try:
            # Get current price
            current_price = self.bot_prices.get(bot_id, 100000.0)

            # Simulate price movement (-1% to +1%)
            price_change = random.uniform(-0.01, 0.01)
            current_price = current_price * (1 + price_change)
            self.bot_prices[bot_id] = current_price

            # Calculate buy price (0.35% below current)
            buy_price = current_price * (1 - 0.0035)

            # Calculate sell price (0.35% + 0.53% above buy = ~0.88% profit)
            profit_percent = random.uniform(0.15, 0.88)
            sell_price = buy_price * (1 + profit_percent / 100)

            # Quantity
            quantity = 1

            # Create trade
            self.order_counter[bot_id] += 1
            counter = self.order_counter[bot_id]

            trade = Trade(
                bot_id=bot_id,
                buy_order_id=f"BUY_{bot_id}_{counter}",
                sell_order_id=f"SELL_{bot_id}_{counter}",
                buy_price=round(buy_price, 2),
                sell_price=round(sell_price, 2),
                quantity=quantity,
                executed_at=datetime.now()
            )
            trade.calculate_profit()

            # Save to database
            await self.db.create_trade(trade)
            return trade

        except Exception as e:
            logger.error(f"Error generating trade for bot {bot_id}: {e}")
            return None

    def is_running(self, bot_id: int) -> bool:
        """Check if simulation is running for a bot."""
        return bot_id in self.running_bots

    def get_current_price(self, bot_id: int) -> float:
        """Get current simulated price for a bot."""
        return self.bot_prices.get(bot_id, 100000.0)
