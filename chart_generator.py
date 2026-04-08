"""
Profit chart generator using matplotlib.
Generates beautiful profit charts for bots.
"""
import matplotlib
matplotlib.use('Agg')  # Non-GUI backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from io import BytesIO
import logging

logger = logging.getLogger(__name__)


class ChartGenerator:
    """Generate profit charts."""

    def __init__(self):
        # Set style
        plt.style.use('dark_background')
        
    def generate_profit_chart(self, trades: list, bot_name: str, 
                             period_days: int = 7) -> BytesIO:
        """
        Generate profit chart from trades.
        
        Args:
            trades: List of trade dicts with executed_at and profit
            bot_name: Name of the bot
            period_days: Number of days to show
            
        Returns:
            BytesIO with PNG image
        """
        if not trades:
            return self._generate_empty_chart(bot_name)
        
        # Group trades by date
        date_profits = {}
        cumulative_profit = 0
        
        for trade in sorted(trades, key=lambda t: t.get('executed_at', '')):
            executed = trade.get('executed_at')
            if not executed:
                continue
                
            try:
                if isinstance(executed, str):
                    dt = datetime.fromisoformat(executed.replace('Z', '+00:00'))
                else:
                    dt = executed
                    
                date_key = dt.date()
                profit = float(trade.get('profit', 0))
                
                if date_key not in date_profits:
                    date_profits[date_key] = 0
                date_profits[date_key] += profit
                
            except Exception as e:
                logger.error(f"Error parsing trade date: {e}")
                continue
        
        # Calculate cumulative
        dates = sorted(date_profits.keys())
        cumulative_data = []
        daily_data = []
        
        for date in dates:
            cumulative_profit += date_profits[date]
            cumulative_data.append(cumulative_profit)
            daily_data.append(date_profits[date])
        
        # Create figure
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), 
                                        facecolor='#1a1a1a')
        
        # Plot 1: Cumulative profit
        ax1.plot(dates, cumulative_data, color='#00ff88', 
                linewidth=2.5, label='Cumulative Profit')
        ax1.fill_between(dates, cumulative_data, alpha=0.3, color='#00ff88')
        ax1.set_title(f'📈 {bot_name} - Profit Chart', 
                     fontsize=16, color='white', pad=20)
        ax1.set_ylabel('Cumulative Profit (USDT)', fontsize=12, color='white')
        ax1.grid(True, alpha=0.2)
        ax1.legend(loc='upper left')
        
        # Format y-axis
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(
            lambda x, p: f'${x:,.0f}'
        ))
        
        # Plot 2: Daily profit bars
        colors = ['#00ff88' if x >= 0 else '#ff3366' for x in daily_data]
        ax2.bar(dates, daily_data, color=colors, alpha=0.8)
        ax2.set_ylabel('Daily Profit (USDT)', fontsize=12, color='white')
        ax2.set_xlabel('Date', fontsize=12, color='white')
        ax2.grid(True, alpha=0.2)
        ax2.axhline(y=0, color='white', linestyle='-', linewidth=0.5)
        
        # Format x-axis dates
        for ax in [ax1, ax2]:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            ax.tick_params(colors='white')
            ax.set_facecolor('#2a2a2a')
            for spine in ax.spines.values():
                spine.set_color('#444444')
        
        plt.tight_layout()
        
        # Save to BytesIO
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=100, facecolor='#1a1a1a')
        buf.seek(0)
        plt.close()
        
        return buf
    
    def _generate_empty_chart(self, bot_name: str) -> BytesIO:
        """Generate empty chart when no trades."""
        fig, ax = plt.subplots(figsize=(10, 6), facecolor='#1a1a1a')
        
        ax.text(0.5, 0.5, 'No trades yet\n\n💹 Start trading to see chart!',
                ha='center', va='center', fontsize=20, color='#888888')
        ax.set_facecolor('#2a2a2a')
        ax.set_title(f'📈 {bot_name} - Profit Chart', 
                    fontsize=16, color='white', pad=20)
        ax.axis('off')
        
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=100, facecolor='#1a1a1a')
        buf.seek(0)
        plt.close()
        
        return buf
    
    def generate_comparison_chart(self, bots_data: dict) -> BytesIO:
        """
        Generate comparison chart for multiple bots.
        
        Args:
            bots_data: Dict of {bot_name: total_profit}
            
        Returns:
            BytesIO with PNG image
        """
        if not bots_data:
            return self._generate_empty_chart("All Bots")
        
        fig, ax = plt.subplots(figsize=(10, 6), facecolor='#1a1a1a')
        
        names = list(bots_data.keys())
        profits = list(bots_data.values())
        colors = ['#00ff88' if p >= 0 else '#ff3366' for p in profits]
        
        bars = ax.barh(names, profits, color=colors, alpha=0.8)
        
        # Add value labels
        for i, (bar, profit) in enumerate(zip(bars, profits)):
            width = bar.get_width()
            label_x = width + (max(profits) * 0.02 if width >= 0 else min(profits) * 0.02)
            ax.text(label_x, i, f'${profit:.2f}', 
                   va='center', fontsize=10, color='white')
        
        ax.set_xlabel('Profit (USDT)', fontsize=12, color='white')
        ax.set_title('📊 Bots Comparison', fontsize=16, color='white', pad=20)
        ax.grid(True, axis='x', alpha=0.2)
        ax.axvline(x=0, color='white', linestyle='-', linewidth=0.5)
        ax.set_facecolor('#2a2a2a')
        ax.tick_params(colors='white')
        
        for spine in ax.spines.values():
            spine.set_color('#444444')
        
        plt.tight_layout()
        
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=100, facecolor='#1a1a1a')
        buf.seek(0)
        plt.close()
        
        return buf
