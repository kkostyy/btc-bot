"""
Binance Testnet client for virtual trading.
Uses Binance Futures Testnet API.
"""
import hashlib
import hmac
import time
import requests
import logging
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# Binance Futures Testnet base URL
TESTNET_URL = "https://testnet.binancefuture.com"
SPOT_TESTNET_URL = "https://testnet.binance.vision"


class BinanceTestnetClient:
    """Client for Binance Testnet trading."""

    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = TESTNET_URL
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": api_key,
            "Content-Type": "application/json"
        })

    def _sign(self, params: dict) -> str:
        """Sign request with secret key."""
        query = urlencode(params)
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature

    def _get(self, endpoint: str, params: dict = None, signed: bool = False):
        """Make GET request."""
        params = params or {}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign(params)

        try:
            resp = self.session.get(f"{self.base_url}{endpoint}", params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"GET {endpoint} error: {e}")
            return None

    def _post(self, endpoint: str, params: dict = None):
        """Make POST request (always signed)."""
        params = params or {}
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = self._sign(params)

        try:
            resp = self.session.post(
                f"{self.base_url}{endpoint}", params=params
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"POST {endpoint} error: {e}")
            return None

    def _delete(self, endpoint: str, params: dict = None):
        """Make DELETE request (always signed)."""
        params = params or {}
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = self._sign(params)

        try:
            resp = self.session.delete(
                f"{self.base_url}{endpoint}", params=params
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"DELETE {endpoint} error: {e}")
            return None

    def get_balance(self) -> list:
        """
        Get account balance from testnet.
        Returns list of assets with balance > 0.
        """
        data = self._get("/fapi/v2/balance", signed=True)
        if not data:
            return []

        # Filter assets with balance
        return [
            asset for asset in data
            if float(asset.get("balance", 0)) > 0
        ]

    def get_usdt_balance(self) -> float:
        """Get USDT balance."""
        balances = self.get_balance()
        for asset in balances:
            if asset.get("asset") == "USDT":
                return float(asset.get("balance", 0))
        return 0.0

    def get_current_price(self, symbol: str = "BTCUSDT") -> float:
        """Get current market price."""
        data = self._get("/fapi/v1/ticker/price", {"symbol": symbol})
        if data:
            return float(data.get("price", 0))
        return 0.0

    def get_open_orders(self, symbol: str = "BTCUSDT") -> list:
        """Get all open orders for a symbol."""
        data = self._get(
            "/fapi/v1/openOrders",
            {"symbol": symbol},
            signed=True
        )
        return data if data else []

    def get_all_orders(self, symbol: str = "BTCUSDT", limit: int = 20) -> list:
        """Get recent orders for a symbol."""
        data = self._get(
            "/fapi/v1/allOrders",
            {"symbol": symbol, "limit": limit},
            signed=True
        )
        return data if data else []

    def place_limit_buy(self, symbol: str, price: float,
                        quantity: float) -> dict:
        """Place a limit buy order."""
        params = {
            "symbol": symbol,
            "side": "BUY",
            "positionSide": "BOTH",  # Required for Futures
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": f"{quantity:.3f}",
            "price": f"{price:.2f}"
        }
        result = self._post("/fapi/v1/order", params)
        if result:
            logger.info(f"BUY order placed: {symbol} @ {price}")
        else:
            logger.error(f"Failed to place BUY order: {symbol} @ {price}")
        return result or {}

    def place_limit_sell(self, symbol: str, price: float,
                         quantity: float) -> dict:
        """Place a limit sell order."""
        params = {
            "symbol": symbol,
            "side": "SELL",
            "positionSide": "BOTH",  # Required for Futures
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": f"{quantity:.3f}",
            "price": f"{price:.2f}"
        }
        result = self._post("/fapi/v1/order", params)
        if result:
            logger.info(f"SELL order placed: {symbol} @ {price}")
        else:
            logger.error(f"Failed to place SELL order: {symbol} @ {price}")
        return result or {}

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """Cancel an order."""
        params = {"symbol": symbol, "orderId": order_id}
        result = self._delete("/fapi/v1/order", params)
        return result or {}

    def get_position(self, symbol: str = "BTCUSDT") -> dict:
        """Get current position for a symbol."""
        data = self._get(
            "/fapi/v2/positionRisk",
            {"symbol": symbol},
            signed=True
        )
        if data and len(data) > 0:
            return data[0]
        return {}

    def is_connected(self) -> bool:
        """Check if API connection works."""
        data = self._get("/fapi/v1/ping")
        return data is not None


class MockBinanceClient:
    """
    Mock client for testing without real API keys.
    Simulates Binance Testnet responses.
    """

    def __init__(self):
        self.mock_balance = 10000.0  # 10,000 USDT virtual
        self.mock_price = 100000.0
        self.mock_orders = []
        self.order_counter = 1000
        logger.info("Using MOCK Binance client (no API keys)")

    def get_usdt_balance(self) -> float:
        return self.mock_balance

    def get_balance(self) -> list:
        return [{"asset": "USDT", "balance": str(self.mock_balance)}]

    def get_current_price(self, symbol: str = "BTCUSDT") -> float:
        # Simulate small price movement
        import random
        self.mock_price += random.uniform(-100, 100)
        return self.mock_price

    def get_open_orders(self, symbol: str = "BTCUSDT") -> list:
        return [o for o in self.mock_orders if o["status"] == "NEW"]

    def get_all_orders(self, symbol: str = "BTCUSDT",
                       limit: int = 20) -> list:
        return self.mock_orders[-limit:]

    def place_limit_buy(self, symbol: str, price: float,
                        quantity: float) -> dict:
        order = {
            "orderId": self.order_counter,
            "symbol": symbol,
            "side": "BUY",
            "type": "LIMIT",
            "price": str(price),
            "origQty": str(quantity),
            "status": "NEW",
            "time": int(time.time() * 1000)
        }
        self.mock_orders.append(order)
        self.order_counter += 1
        return order

    def place_limit_sell(self, symbol: str, price: float,
                         quantity: float) -> dict:
        order = {
            "orderId": self.order_counter,
            "symbol": symbol,
            "side": "SELL",
            "type": "LIMIT",
            "price": str(price),
            "origQty": str(quantity),
            "status": "NEW",
            "time": int(time.time() * 1000)
        }
        self.mock_orders.append(order)
        self.order_counter += 1
        return order

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        for o in self.mock_orders:
            if o["orderId"] == order_id:
                o["status"] = "CANCELED"
        return {"orderId": order_id}

    def get_position(self, symbol: str = "BTCUSDT") -> dict:
        return {"positionAmt": "0", "entryPrice": "0", "unRealizedProfit": "0"}

    def is_connected(self) -> bool:
        return True
