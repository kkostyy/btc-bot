# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🚀 Development Commands

### Running the Bot
- **Start the bot**: `python main.py` or `./run.sh`
- **Dependencies**: `pip install -r requirements.txt --break-system-packages`
- **Environment**: Requires `.env` file with `BOT_TOKEN` and optional `BINANCE_API_KEY`, `BINANCE_SECRET_KEY`, `OPENAI_API_KEY`

### Testing
- No formal test suite currently exists
- Manual testing via Telegram bot interaction
- Check logs for debugging: console output or log files

### Linting/Formatting
- No configured linters or formatters
- Follow existing code style (PEP 8 with some flexibility)

## 🏗️ Code Architecture

### Core Components
1. **Entry Point**: `main.py` - Initializes and runs the TradingBot
2. **Main Bot Logic**: `bot.py` - Telegram bot interface, handles commands and callbacks
3. **Handlers**: `handlers/bot_handler.py` - Processes Telegram updates and user interactions
4. **Trading Logic**: 
   - `binance_client.py` - Binance Testnet API integration
   - `simulator/trading_simulator.py` - Trading simulation mode
   - `database.py` + `database/db_manager.py` - SQLite data persistence
   - `models/models.py` - Data models (BotInstance, Trade, Withdrawal)
5. **Utilities**:
   - `chart_generator.py` - Profit visualization with matplotlib
   - `order_monitor.py` - Monitors order status
   - `config/config.py` - Configuration utilities

### Key Features
- **Grid Trading Strategy**: Configurable BUY/SELL steps and initial offset
- **Three Trading Modes**: Simulator, Binance Testnet, Real Binance
- **Telegram Interface**: Inline keyboards for bot control
- **Data Persistence**: SQLite database for bots, trades, and withdrawals
- **Extended Features** (v2.0):
  - Profit charts (`chart_generator.py`)
  - AI Advisor (OpenAI integration)
  - Bot duplication
  - Theme customization
  - Daily reports

### Data Flow
1. User interacts via Telegram → `handlers/bot_handler.py`
2. Handler updates bot state via `DatabaseManager`
3. Trading logic executes in background loops
4. Binance/client APIs handle exchange communication
5. Results stored in SQLite and reported back to user

## 📁 Important Directories
- `config/` - Configuration utilities
- `database/` - Database management
- `handlers/` - Telegram update handlers
- `models/` - Data models
- `simulator/` - Trading simulation logic

## 🔧 Configuration
- Environment variables loaded via `python-dotenv`
- Key settings in `.env`:
  - `BOT_TOKEN` (required) - Telegram bot token
  - `BINANCE_API_KEY` / `BINANCE_SECRET_KEY` - For live/testnet trading
  - `OPENAI_API_KEY` - For AI advisor features
  - `DATA_DIR` - Custom data directory (defaults to current)
  - `DATABASE_PATH` - Override database location
  - `LOG_LEVEL` - Logging verbosity

## 📚 Documentation
- `README_V2.md` - Complete feature overview and usage guide
- `GRID_CONFIG.md` - Grid trading strategy details
- `FEATURES.md` - Feature descriptions
- `IDEAS.md` - Planned enhancements
- `CHANGELOG.md` - Version history

## 🐛 Troubleshooting
- **Bot fails to start**: Check `BOT_TOKEN` in `.env`, verify Python 3.8+
- **Graph issues**: Install matplotlib: `pip install matplotlib --break-system-packages`
- **API connection errors**: Verify Binance credentials and network connectivity
- **Database errors**: Check file permissions for SQLite database