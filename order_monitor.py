"""
Order monitoring module - checks order status on exchange and rebalances grid.
"""
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class OrderMonitor:
    """Monitors orders on exchange and maintains grid."""
    
    def __init__(self, db, get_binance_client_func):
        self.db = db
        self.get_client = get_binance_client_func
        self.running_monitors = {}  # bot_id -> task
        
    async def start_monitoring(self, bot_id: int, bot: dict, uid: int):
        """Start monitoring orders for a bot."""
        if bot_id in self.running_monitors:
            logger.info(f"Monitor already running for bot {bot_id}")
            return
            
        task = asyncio.create_task(self._monitor_loop(bot_id, bot, uid))
        self.running_monitors[bot_id] = task
        logger.info(f"Started order monitor for bot {bot_id}")
        
    async def stop_monitoring(self, bot_id: int):
        """Stop monitoring for a bot."""
        if bot_id in self.running_monitors:
            self.running_monitors[bot_id].cancel()
            del self.running_monitors[bot_id]
            logger.info(f"Stopped order monitor for bot {bot_id}")
            
    async def stop_all(self):
        """Stop all monitors."""
        for bot_id in list(self.running_monitors.keys()):
            await self.stop_monitoring(bot_id)
            
    async def _monitor_loop(self, bot_id: int, bot: dict, uid: int):
        """Main monitoring loop."""
        logger.info(f"Monitor loop started for bot {bot_id}")
        
        while True:
            try:
                # Check every 15 seconds
                await asyncio.sleep(15)
                
                # Refresh bot from DB
                bot = await self.db.get_bot(bot_id)
                if not bot or bot.get("status") != "running":
                    logger.info(f"Bot {bot_id} stopped, ending monitor")
                    break
                    
                # Skip if simulator mode (simulator handles its own trades)
                mode = bot.get("mode", "simulator")
                if mode == "simulator":
                    continue
                    
                # Get client and check orders
                client = self.get_client(bot, uid)
                await self._check_and_rebalance(bot, client)
                
            except asyncio.CancelledError:
                logger.info(f"Monitor cancelled for bot {bot_id}")
                break
            except Exception as e:
                logger.error(f"Error in monitor loop for bot {bot_id}: {e}")
                await asyncio.sleep(5)
                
    async def _check_and_rebalance(self, bot: dict, client):
        """Check order status and rebalance grid if needed."""
        bot_id = bot["id"]
        symbol = bot["symbol"]
        
        try:
            # Get open orders from exchange
            live_orders = client.get_open_orders(symbol)
            live_order_ids = {str(o.get("orderId")) for o in live_orders}
            
            # Get our DB orders
            db_orders = await self.db.get_open_orders(bot_id)
            
            # Find filled orders (in DB but not on exchange)
            filled_orders = []
            for db_order in db_orders:
                eid = db_order.get("exchange_order_id", "")
                if eid and eid not in live_order_ids:
                    filled_orders.append(db_order)
                    
            if not filled_orders:
                return
                
            logger.info(f"Bot {bot_id}: {len(filled_orders)} orders filled")
            
            # Mark filled orders as FILLED in DB
            for order in filled_orders:
                await self.db.update_order_status(order["id"], "FILLED")
                
            # Rebalance grid - place new orders
            await self._rebalance_grid(bot, client, filled_orders)
            
        except Exception as e:
            logger.error(f"Error checking orders for bot {bot_id}: {e}")
            
    async def _rebalance_grid(self, bot: dict, client, filled_orders: list):
        """Place new orders to replace filled ones."""
        bot_id = bot["id"]
        symbol = bot["symbol"]
        
        try:
            # Get order_usdt safely
            order_usdt = float(bot.get("order_usdt", 50))
        except (TypeError, ValueError):
            order_usdt = 50.0
            
        # Get current price
        current_price = client.get_current_price(symbol)
        quantity = round(order_usdt / current_price, 6)
        if quantity < 0.001:
            quantity = 0.001
            
        # Calculate grid center
        center_price = bot.get("center_price") or current_price
        
        for order in filled_orders:
            side = order["side"]
            pair_id = order.get("pair_id", "")
            
            if side == "BUY":
                # BUY filled - place new SELL above
                new_price = current_price * 1.005  # 0.5% above
                try:
                    result = client.place_limit_sell(symbol, round(new_price, 2), quantity)
                    eid = str(result.get("orderId", "")) if isinstance(result, dict) else ""
                except Exception:
                    eid = ""
                await self.db.add_order(bot_id, "SELL", round(new_price, 2), quantity, eid, pair_id)
                logger.info(f"Bot {bot_id}: Placed SELL at {new_price:.2f} (BUY filled)")
                
            elif side == "SELL":
                # SELL filled - place new BUY below
                new_price = current_price * 0.995  # 0.5% below
                try:
                    result = client.place_limit_buy(symbol, round(new_price, 2), quantity)
                    eid = str(result.get("orderId", "")) if isinstance(result, dict) else ""
                except Exception:
                    eid = ""
                await self.db.add_order(bot_id, "BUY", round(new_price, 2), quantity, eid, pair_id)
                logger.info(f"Bot {bot_id}: Placed BUY at {new_price:.2f} (SELL filled)")
                
        logger.info(f"Bot {bot_id}: Rebalanced {len(filled_orders)} orders")
