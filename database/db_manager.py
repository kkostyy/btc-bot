"""
Async database manager for SQLite operations.
"""
import aiosqlite
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from models import BotInstance, Trade, Withdrawal

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database operations for the trading bot."""
    
    def __init__(self, db_path: str):
        """
        Initialize database manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.connection: Optional[aiosqlite.Connection] = None
    
    async def initialize(self):
        """Initialize database connection and create tables."""
        logger.info(f"Initializing database: {self.db_path}")
        
        self.connection = await aiosqlite.connect(self.db_path)
        await self.create_tables()
        
        logger.info("Database initialized successfully")
    
    async def create_tables(self):
        """Create database tables if they don't exist."""
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS bot_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'stopped',
                center_price REAL,
                quantity INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                buy_order_id TEXT NOT NULL,
                sell_order_id TEXT NOT NULL,
                buy_price REAL NOT NULL,
                sell_price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                profit REAL NOT NULL,
                profit_percent REAL NOT NULL,
                executed_at TEXT NOT NULL,
                FOREIGN KEY (bot_id) REFERENCES bot_instances(id) ON DELETE CASCADE
            )
        """)
        
        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_trades_bot_id ON trades(bot_id)
        """)
        
        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_trades_executed_at ON trades(executed_at)
        """)
        
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER,
                amount REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                withdrawn_at TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY (bot_id) REFERENCES bot_instances(id) ON DELETE SET NULL
            )
        """)
        
        await self.connection.commit()
        logger.debug("Database tables created/verified")
    
    async def close(self):
        """Close database connection."""
        if self.connection:
            await self.connection.close()
            logger.info("Database connection closed")
    
    # Bot instance operations
    
    async def create_bot(self, bot: BotInstance) -> BotInstance:
        """Create a new bot instance."""
        cursor = await self.connection.execute("""
            INSERT INTO bot_instances (name, status, center_price, quantity, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (bot.name, bot.status, bot.center_price, bot.quantity,
              bot.created_at.isoformat(), bot.updated_at.isoformat()))
        
        await self.connection.commit()
        bot.id = cursor.lastrowid
        
        logger.info(f"Created bot: {bot.name} (ID: {bot.id})")
        return bot
    
    async def get_all_bots(self) -> List[BotInstance]:
        """Get all bot instances."""
        cursor = await self.connection.execute("""
            SELECT * FROM bot_instances ORDER BY created_at DESC
        """)
        
        rows = await cursor.fetchall()
        return [self._row_to_bot(row) for row in rows]
    
    async def get_bot_by_id(self, bot_id: int) -> Optional[BotInstance]:
        """Get a bot by ID."""
        cursor = await self.connection.execute("""
            SELECT * FROM bot_instances WHERE id = ?
        """, (bot_id,))
        
        row = await cursor.fetchone()
        return self._row_to_bot(row) if row else None
    
    async def update_bot(self, bot: BotInstance):
        """Update a bot instance."""
        await self.connection.execute("""
            UPDATE bot_instances 
            SET name = ?, status = ?, center_price = ?, quantity = ?, updated_at = ?
            WHERE id = ?
        """, (bot.name, bot.status, bot.center_price, bot.quantity,
              datetime.now().isoformat(), bot.id))
        
        await self.connection.commit()
        logger.info(f"Updated bot: {bot.name} (ID: {bot.id})")
    
    async def delete_bot(self, bot_id: int):
        """Delete a bot instance."""
        await self.connection.execute("""
            DELETE FROM bot_instances WHERE id = ?
        """, (bot_id,))
        
        await self.connection.commit()
        logger.info(f"Deleted bot ID: {bot_id}")
    
    # Trade operations
    
    async def create_trade(self, trade: Trade) -> Trade:
        """Record a trade."""
        cursor = await self.connection.execute("""
            INSERT INTO trades (bot_id, buy_order_id, sell_order_id, buy_price, sell_price,
                               quantity, profit, profit_percent, executed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (trade.bot_id, trade.buy_order_id, trade.sell_order_id, trade.buy_price,
              trade.sell_price, trade.quantity, trade.profit, trade.profit_percent,
              trade.executed_at.isoformat()))
        
        await self.connection.commit()
        trade.id = cursor.lastrowid
        
        logger.debug(f"Recorded trade for bot {trade.bot_id}: profit ${trade.profit}")
        return trade
    
    async def get_recent_trades(self, bot_id: int, limit: int = 5) -> List[Trade]:
        """Get last N trades for a bot."""
        cursor = await self.connection.execute("""
            SELECT * FROM trades 
            WHERE bot_id = ? 
            ORDER BY executed_at DESC 
            LIMIT ?
        """, (bot_id, limit))
        
        rows = await cursor.fetchall()
        return [self._row_to_trade(row) for row in rows]
    
    async def get_profit_since(self, bot_id: int, since: datetime) -> float:
        """Get profit for a bot since a specific time."""
        cursor = await self.connection.execute("""
            SELECT COALESCE(SUM(profit), 0) as total_profit
            FROM trades 
            WHERE bot_id = ? AND executed_at >= ?
        """, (bot_id, since.isoformat()))
        
        row = await cursor.fetchone()
        return row[0] if row else 0.0
    
    async def get_total_profit(self, bot_id: int) -> float:
        """Get total profit for a bot."""
        cursor = await self.connection.execute("""
            SELECT COALESCE(SUM(profit), 0) as total_profit
            FROM trades 
            WHERE bot_id = ?
        """, (bot_id,))
        
        row = await cursor.fetchone()
        return row[0] if row else 0.0
    
    # Withdrawal operations
    
    async def create_withdrawal(self, withdrawal: Withdrawal) -> Withdrawal:
        """Record a withdrawal."""
        cursor = await self.connection.execute("""
            INSERT INTO withdrawals (bot_id, amount, currency, withdrawn_at, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (withdrawal.bot_id, withdrawal.amount, withdrawal.currency,
              withdrawal.withdrawn_at.isoformat(), withdrawal.notes))
        
        await self.connection.commit()
        withdrawal.id = cursor.lastrowid
        
        logger.info(f"Recorded withdrawal: ${withdrawal.amount}")
        return withdrawal
    
    async def get_total_withdrawals(self, bot_id: Optional[int] = None) -> float:
        """Get total withdrawals for a bot (or all bots if None)."""
        if bot_id is not None:
            cursor = await self.connection.execute("""
                SELECT COALESCE(SUM(amount), 0) as total 
                FROM withdrawals 
                WHERE bot_id = ?
            """, (bot_id,))
        else:
            cursor = await self.connection.execute("""
                SELECT COALESCE(SUM(amount), 0) as total 
                FROM withdrawals
            """)
        
        row = await cursor.fetchone()
        return row[0] if row else 0.0
    
    # Helper methods
    
    def _row_to_bot(self, row) -> BotInstance:
        """Convert database row to BotInstance."""
        return BotInstance(
            id=row[0],
            name=row[1],
            status=row[2],
            center_price=row[3],
            quantity=row[4],
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6])
        )
    
    def _row_to_trade(self, row) -> Trade:
        """Convert database row to Trade."""
        return Trade(
            id=row[0],
            bot_id=row[1],
            buy_order_id=row[2],
            sell_order_id=row[3],
            buy_price=row[4],
            sell_price=row[5],
            quantity=row[6],
            profit=row[7],
            profit_percent=row[8],
            executed_at=datetime.fromisoformat(row[9])
        )
