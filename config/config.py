"""
Configuration module for Telegram Trading Bot.
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN', '8503569913:AAEapWqYKVt14kBVnKGLC1WHk2GYym8Jd0A')

# Database configuration
DATABASE_PATH = os.getenv('DATABASE_PATH', 'telegram_bot.db')

# Security - allowed users (comma-separated user IDs)
ALLOWED_USERS_STR = os.getenv('ALLOWED_USERS', '')
ALLOWED_USERS = [int(uid.strip()) for uid in ALLOWED_USERS_STR.split(',') if uid.strip()] if ALLOWED_USERS_STR else []

# Logging configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', 'telegram_bot.log')

def is_user_allowed(user_id: int) -> bool:
    """
    Check if user is allowed to use the bot.
    
    Args:
        user_id: Telegram user ID
        
    Returns:
        True if user is allowed, False otherwise
    """
    if not ALLOWED_USERS:  # Empty list means all users allowed
        return True
    return user_id in ALLOWED_USERS
