"""Main Telegram bot handler."""
import logging
from datetime import datetime, timedelta
from typing import Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from database import DatabaseManager
from models import BotInstance, Withdrawal
from config import is_user_allowed

logger = logging.getLogger(__name__)
user_states: Dict[int, dict] = {}

class TradingTelegramBot:
    def __init__(self, token: str, db_manager: DatabaseManager):
        self.token = token
        self.db = db_manager

    async def build_application(self) -> Application:
        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CallbackQueryHandler(self.on_button))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        return app

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_user_allowed(update.effective_user.id):
            await update.message.reply_text("Access denied.")
            return
        await self._main_menu(update, is_new=True)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("/start - главное меню")

    async def on_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        p = q.data.split(":")
        a = p[0]
        if a == "main_menu": await self._main_menu(update)
        elif a == "list_bots": await self._bot_list(update)
        elif a == "add_bot": await self._ask_name(update)
        elif a == "overall_stats": await self._overall_stats(update)
        elif a == "record_withdrawal": await self._ask_withdrawal(update)
        elif a == "view_bot": await self._bot_details(update, int(p[1]))
        elif a == "start_bot": await self._toggle(update, int(p[1]), "running")
        elif a == "stop_bot": await self._toggle(update, int(p[1]), "stopped")
        elif a == "rename_bot": await self._ask_rename(update, int(p[1]))
        elif a == "delete_bot": await self._confirm_delete(update, int(p[1]))
        elif a == "confirm_delete": await self._do_delete(update, int(p[1]))
        elif a == "bot_stats": await self._bot_stats(update, int(p[1]))
        elif a == "recent_trades": await self._recent_trades(update, int(p[1]))

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        state = user_states.pop(uid, None)
        if not state:
            await update.message.reply_text("Используйте /start")
            return
        text = update.message.text.strip()
        action = state.get("action")
        if action == "add_bot": await self._create_bot(update, text)
        elif action == "rename_bot": await self._rename_bot(update, state["bot_id"], text)
        elif action == "withdrawal": await self._process_withdrawal(update, text)

    async def _main_menu(self, update: Update, is_new: bool = False):
        bots = await self.db.get_all_bots()
        running = sum(1 for b in bots if b.is_running())
        text = f"🤖 BTC Trading Bot Manager\n\nБотов: {len(bots)} | Работает: {running} 🟢"
        kb = [
            [InlineKeyboardButton("📋 Мои боты", callback_data="list_bots"),
             InlineKeyboardButton("➕ Добавить", callback_data="add_bot")],
            [InlineKeyboardButton("📊 Общая статистика", callback_data="overall_stats")],
            [InlineKeyboardButton("💰 Записать вывод", callback_data="record_withdrawal")]
        ]
        m = InlineKeyboardMarkup(kb)
        if is_new: await update.message.reply_text(text, reply_markup=m)
        else: await update.callback_query.message.edit_text(text, reply_markup=m)

    async def _bot_list(self, update: Update):
        bots = await self.db.get_all_bots()
        if not bots:
            text = "Ботов нет. Нажмите Добавить!"
        else:
            lines = ["🤖 Ваши боты:\n"]
            for b in bots:
                e = "🟢" if b.is_running() else "🔴"
                p = await self.db.get_total_profit(b.id)
                lines.append(f"{e} {b.name} — +${p:.2f}")
            text = "\n".join(lines)
        kb = []
        for b in bots:
            e = "🟢" if b.is_running() else "🔴"
            p = await self.db.get_total_profit(b.id)
            kb.append([InlineKeyboardButton(f"{e} {b.name}  |  +${p:.2f}", callback_data=f"view_bot:{b.id}")])
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))

    async def _bot_details(self, update: Update, bot_id: int):
        bot = await self.db.get_bot_by_id(bot_id)
        if not bot: return
        now = datetime.now()
        p_today = await self.db.get_profit_since(bot_id, now - timedelta(days=1))
        p_total = await self.db.get_total_profit(bot_id)
        trades = await self.db.get_recent_trades(bot_id, 1)
        last = f"+${trades[0].profit:.2f} ({trades[0].profit_percent:.2f}%)" if trades else "нет сделок"
        status = "🟢 Работает" if bot.is_running() else "🔴 Остановлен"
        text = (f"🤖 {bot.name}\n\nСтатус: {status}\n"
                f"Прибыль сегодня: ${p_today:.2f}\n"
                f"Всего заработано: ${p_total:.2f}\n"
                f"Последняя сделка: {last}")
        kb = []
        if bot.is_running(): kb.append([InlineKeyboardButton("⏸ Остановить", callback_data=f"stop_bot:{bot_id}")])
        else: kb.append([InlineKeyboardButton("▶️ Запустить", callback_data=f"start_bot:{bot_id}")])
        kb.extend([
            [InlineKeyboardButton("📊 Статистика", callback_data=f"bot_stats:{bot_id}"),
             InlineKeyboardButton("📜 Сделки", callback_data=f"recent_trades:{bot_id}")],
            [InlineKeyboardButton("📝 Переименовать", callback_data=f"rename_bot:{bot_id}")],
            [InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_bot:{bot_id}")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="list_bots")]
        ])
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))

    async def _toggle(self, update: Update, bot_id: int, status: str):
        bot = await self.db.get_bot_by_id(bot_id)
        if not bot: return
        bot.status = status
        await self.db.update_bot(bot)
        if status == "running":
            msg = f"🟢 Бот {bot.name} запущен!\nВиртуальные сделки появятся через 30-120 секунд."
        else:
            msg = f"🔴 Бот {bot.name} остановлен."
        await update.callback_query.message.reply_text(msg)
        await self._bot_details(update, bot_id)

    async def _bot_stats(self, update: Update, bot_id: int):
        bot = await self.db.get_bot_by_id(bot_id)
        if not bot: return
        now = datetime.now()
        p_d = await self.db.get_profit_since(bot_id, now - timedelta(days=1))
        p_w = await self.db.get_profit_since(bot_id, now - timedelta(weeks=1))
        p_m = await self.db.get_profit_since(bot_id, now - timedelta(days=30))
        p_y = await self.db.get_profit_since(bot_id, now - timedelta(days=365))
        p_t = await self.db.get_total_profit(bot_id)
        wd  = await self.db.get_total_withdrawals(bot_id)
        net = p_t - wd
        trades = await self.db.get_recent_trades(bot_id, 1000)
        status = "🟢 Работает" if bot.is_running() else "🔴 Остановлен"
        text = (f"📊 Статистика — {bot.name}\nСтатус: {status}\n\n"
                f"💰 Прибыль:\n"
                f"  За 24 часа:  ${p_d:.2f}\n"
                f"  За неделю:   ${p_w:.2f}\n"
                f"  За месяц:    ${p_m:.2f}\n"
                f"  За год:      ${p_y:.2f}\n\n"
                f"📈 Всего заработано: ${p_t:.2f}\n"
                f"💸 Выводы: ${wd:.2f}\n"
                f"💵 Чистая прибыль: ${net:.2f}\n\n"
                f"🔄 Закрытых сделок: {len(trades)}")
        kb = [[InlineKeyboardButton("⬅️ Назад", callback_data=f"view_bot:{bot_id}")]]
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))

    async def _recent_trades(self, update: Update, bot_id: int):
        bot = await self.db.get_bot_by_id(bot_id)
        if not bot: return
        trades = await self.db.get_recent_trades(bot_id, 5)
        lines = [f"📜 Последние сделки — {bot.name}\n"]
        if not trades:
            lines.append("Сделок пока нет.\nЗапустите бота чтобы начать!")
        else:
            for t in trades:
                lines.append(f"⏰ {t.executed_at.strftime('%H:%M:%S')}  {t.profit_percent:.2f}%  +${t.profit:.2f}")
        kb = [[InlineKeyboardButton("⬅️ Назад", callback_data=f"view_bot:{bot_id}")]]
        await update.callback_query.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))

    async def _overall_stats(self, update: Update):
        bots = await self.db.get_all_bots()
        now = datetime.now()
        p_d = p_w = p_m = p_y = p_t = 0.0
        running = 0
        for b in bots:
            if b.is_running(): running += 1
            p_d += await self.db.get_profit_since(b.id, now - timedelta(days=1))
            p_w += await self.db.get_profit_since(b.id, now - timedelta(weeks=1))
            p_m += await self.db.get_profit_since(b.id, now - timedelta(days=30))
            p_y += await self.db.get_profit_since(b.id, now - timedelta(days=365))
            p_t += await self.db.get_total_profit(b.id)
        wd = await self.db.get_total_withdrawals()
        net = p_t - wd
        text = (f"📊 Общая статистика\n\n"
                f"🤖 Ботов: {len(bots)}  |  Работает: {running} 🟢\n\n"
                f"💰 Прибыль по всем ботам:\n"
                f"  За 24 часа:  ${p_d:.2f}\n"
                f"  За неделю:   ${p_w:.2f}\n"
                f"  За месяц:    ${p_m:.2f}\n"
                f"  За год:      ${p_y:.2f}\n\n"
                f"📈 Всего заработано: ${p_t:.2f}\n"
                f"💸 Выводы: ${wd:.2f}\n"
                f"💵 Чистая прибыль: ${net:.2f}")
        kb = [[InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]]
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))

    async def _ask_name(self, update: Update):
        user_states[update.effective_user.id] = {"action": "add_bot"}
        await update.callback_query.message.reply_text("✏️ Введите название нового бота:")

    async def _create_bot(self, update: Update, name: str):
        try:
            await self.db.create_bot(BotInstance(name=name))
            await update.message.reply_text(f"✅ Бот '{name}' создан!\nНайдите его в списке и нажмите Запустить.")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

    async def _ask_rename(self, update: Update, bot_id: int):
        user_states[update.effective_user.id] = {"action": "rename_bot", "bot_id": bot_id}
        await update.callback_query.message.reply_text("✏️ Введите новое название:")

    async def _rename_bot(self, update: Update, bot_id: int, new_name: str):
        bot = await self.db.get_bot_by_id(bot_id)
        if bot:
            old = bot.name; bot.name = new_name
            await self.db.update_bot(bot)
            await update.message.reply_text(f"✅ Переименован: {old} -> {new_name}")

    async def _confirm_delete(self, update: Update, bot_id: int):
        bot = await self.db.get_bot_by_id(bot_id)
        if not bot: return
        kb = [[InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete:{bot_id}"),
               InlineKeyboardButton("❌ Отмена", callback_data=f"view_bot:{bot_id}")]]
        await update.callback_query.message.edit_text(
            f"⚠️ Удалить бота '{bot.name}'?\nВсе данные о сделках будут удалены.",
            reply_markup=InlineKeyboardMarkup(kb))

    async def _do_delete(self, update: Update, bot_id: int):
        bot = await self.db.get_bot_by_id(bot_id)
        if not bot: return
        name = bot.name
        await self.db.delete_bot(bot_id)
        await update.callback_query.message.reply_text(f"✅ Бот '{name}' удалён.")
        await self._bot_list(update)

    async def _ask_withdrawal(self, update: Update):
        user_states[update.effective_user.id] = {"action": "withdrawal"}
        await update.callback_query.message.reply_text("💰 Введите сумму вывода в USD (например: 500):")

    async def _process_withdrawal(self, update: Update, text: str):
        try:
            amount = float(text.replace(",", "."))
            if amount <= 0: raise ValueError()
            await self.db.create_withdrawal(Withdrawal(amount=amount))
            await update.message.reply_text(f"✅ Вывод ${amount:.2f} записан!")
        except ValueError:
            await update.message.reply_text("❌ Неверная сумма. Введите число, например: 500")
