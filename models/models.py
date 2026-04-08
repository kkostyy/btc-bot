"""
Database models for the trading bot.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class BotInstance:
    """Represents a trading bot instance."""
    id: Optional[int] = None
    name: str = ""
    status: str = "stopped"  # "running" or "stopped"
    center_price: Optional[float] = None
    quantity: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def is_running(self) -> bool:
        """Check if bot is running."""
        return self.status == "running"
    
    def __post_init__(self):
        """Initialize timestamps if not provided."""
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()


@dataclass
class Trade:
    """Represents a completed trade."""
    id: Optional[int] = None
    bot_id: int = 0
    buy_order_id: str = ""
    sell_order_id: str = ""
    buy_price: float = 0.0
    sell_price: float = 0.0
    quantity: int = 0
    profit: float = 0.0
    profit_percent: float = 0.0
    executed_at: Optional[datetime] = None
    
    def calculate_profit(self):
        """Calculate profit from buy and sell prices."""
        self.profit = (self.sell_price - self.buy_price) * self.quantity
        self.profit_percent = ((self.sell_price - self.buy_price) / self.buy_price) * 100.0
    
    def __post_init__(self):
        """Initialize timestamp if not provided."""
        if self.executed_at is None:
            self.executed_at = datetime.now()


@dataclass
class Withdrawal:
    """Represents a withdrawal of funds."""
    id: Optional[int] = None
    bot_id: Optional[int] = None  # None for global withdrawals
    amount: float = 0.0
    currency: str = "USD"
    withdrawn_at: Optional[datetime] = None
    notes: Optional[str] = None
    
    def __post_init__(self):
        """Initialize timestamp if not provided."""
        if self.withdrawn_at is None:
            self.withdrawn_at = datetime.now()
