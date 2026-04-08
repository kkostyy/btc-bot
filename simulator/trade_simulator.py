"""
Trade simulator - generates virtual trades for bots.
Simulates BTC grid trading with realistic profits.
"""
import asyncio
import random
import logging
from datetime import datetime
from models import Trade
from database import DatabaseManager

logger = logging.getLogger(__name__)


class TradeSimulator:
    """Simulates virtual trades for running bots."""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.running = False
        self._task = None

        # Simulation parameters
        self.btc_price = 96000.0          # Current BTC price
        self.min_profit_pct = 0.15        # Min profit per trade %
        self.max_profit_pct = 0.53        # Max profit per trade %
        self.trade_interval_min = 30      # Min seconds between trades
        self.trade_interval_max = 120     # Max seconds between trades

    async def start(self):
        """Start the trade simulator."""
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._simulate_loop())
        logger.info("Trade simulator started")

    async def stop(self):
        """Stop the trade simulator."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Trade simulator stopped")

    async def _simulate_loop(self):
        """Main simulation loop."""
        while self.running:
            try:
                # Get all running bots
                bots = await self.db.get_all_bots()
                running_bots = [b for b in bots if b.is_running()]

                if running_bots:
                    # Simulate a trade for a random running bot
                    bot = random.choice(running_bots)
                    await self._simulate_trade(bot)

                # Wait random interval before next trade
                wait_time = random.uniform(
                    self.trade_interval_min,
                    self.trade_interval_max
                )
                await asyncio.sleep(wait_time)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in simulation loop: {e}")
                await asyncio.sleep(10)

    async def _simulate_trade(self, bot):
        """Simulate a single trade for a bot."""
        try:
            # Simulate price movement
            price_change = random.uniform(-0.005, 0.005)
            self.btc_price *= (1 + price_change)

            # Calculate buy price (slightly below current)
            buy_price = self.btc_price * (1 - random.uniform(0.001, 0.004))

            # Calculate profit percentage (grid strategy range)
            profit_pct = random.uniform(self.min_profit_pct, self.max_profit_pct)

            # Calculate sell price
            sell_price = buy_price * (1 + profit_pct / 100)

            # Quantity
            quantity = bot.quantity if bot.quantity else 1

            # Create trade
            trade = Trade(
                bot_id=bot.id,
                buy_order_id=f"BUY_{bot.id}_{int(datetime.now().timestamp())}",
                sell_order_id=f"SELL_{bot.id}_{int(datetime.now().timestamp())}",
                buy_price=round(buy_price, 2),
                sell_price=round(sell_price, 2),
                quantity=quantity,
                executed_at=datetime.now()
            )
            trade.calculate_profit()

            await self.db.create_trade(trade)

            logger.info(
                f"Simulated trade for bot '{bot.name}': "
                f"buy=${trade.buy_price:.2f}, sell=${trade.sell_price:.2f}, "
                f"profit=${trade.profit:.2f} ({trade.profit_percent:.2f}%)"
            )

        except Exception as e:
            logger.error(f"Error simulating trade for bot {bot.id}: {e}")
