#!/bin/bash
# Installation and run script for Python Telegram Bot

set -e

echo "=================================="
echo "Telegram Trading Bot (Python)"
echo "=================================="

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed!"
    exit 1
fi

echo ""
echo "Python version:"
python3 --version

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo ""
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo ""
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Check if .env exists
if [ ! -f ".env" ]; then
    echo ""
    echo "Warning: .env file not found!"
    echo "Creating from template..."
    echo "BOT_TOKEN=8503569913:AAEapWqYKVt14kBVnKGLC1WHk2GYym8Jd0A" > .env
    echo "DATABASE_PATH=telegram_bot.db" >> .env
    echo "ALLOWED_USERS=" >> .env
fi

echo ""
echo "=================================="
echo "Starting bot..."
echo "=================================="
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run the bot
python3 main.py
