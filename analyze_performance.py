import sqlite3
from datetime import datetime, timedelta

def analyze_trades():
    conn = sqlite3.connect('trades.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    yesterday = (datetime.now() - timedelta(days=1)).isoformat()
    
    cursor.execute("SELECT * FROM trades WHERE time >= ?", (yesterday,))
    trades = [dict(row) for row in cursor.fetchall()]
    
    print(f"Total trades in last 24h: {len(trades)}")
    
    if not trades:
        print("No trades found in the last 24 hours.")
        return

    winning_trades = [t for t in trades if t['pnl'] is not None and t['pnl'] > 0]
    losing_trades = [t for t in trades if t['pnl'] is not None and t['pnl'] < 0]
    open_trades = [t for t in trades if t['status'] == 'open']
    
    total_pnl = sum(t['pnl'] for t in trades if t['pnl'] is not None)
    
    print(f"Winning trades: {len(winning_trades)}")
    print(f"Losing trades: {len(losing_trades)}")
    print(f"Open trades: {len(open_trades)}")
    print(f"Total PnL: {total_pnl:.2f}")
    
    print("\nDetailed Trade Log:")
    for t in trades:
        print(f"Time: {t['time']}, Symbol: {t['symbol']}, Strategy: {t['strategy']}, Status: {t['status']}, PnL: {t['pnl']}, Side: {t['side']}, Entry: {t['entry_price']}, Exit: {t['exit_price']}")

    # Check for common losing strategies
    strategy_perf = {}
    for t in trades:
        s = t['strategy']
        if s not in strategy_perf:
            strategy_perf[s] = {'pnl': 0, 'count': 0, 'wins': 0}
        strategy_perf[s]['count'] += 1
        if t['pnl'] is not None:
            strategy_perf[s]['pnl'] += t['pnl']
            if t['pnl'] > 0:
                strategy_perf[s]['wins'] += 1

    print("\nStrategy Performance:")
    for s, perf in strategy_perf.items():
        win_rate = (perf['wins'] / perf['count']) * 100 if perf['count'] > 0 else 0
        print(f"Strategy: {s}, Count: {perf['count']}, PnL: {perf['pnl']:.2f}, Win Rate: {win_rate:.2f}%")

if __name__ == "__main__":
    analyze_trades()
