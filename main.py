"""
BTC Trading Bot - Entry point
"""
import asyncio
import logging
import os
import sys

# На Railway файловая система эфемерная — пишем логи только в stdout
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO"),
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

logger = logging.getLogger(__name__)


async def main():
    from bot import TradingBot
    logger.info("=" * 50)
    logger.info("BTC Trading Bot Starting...")
    logger.info("=" * 50)
    bot = TradingBot()
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
