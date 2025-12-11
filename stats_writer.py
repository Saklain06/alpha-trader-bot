import json

def write_stats(balance, trades):
    wins = [t for t in trades if t.get('pnl', 0) > 0]
    losses = [t for t in trades if t.get('pnl', 0) < 0]

    total_profit = sum(t.get('pnl', 0) for t in wins)
    total_loss = abs(sum(t.get('pnl', 0) for t in losses))

    data = {
        "balance": round(balance, 2),
        "total_trades": len(trades),
        "win_rate": round((len(wins) / len(trades)) * 100, 2) if trades else 0,
        "total_pnl": round(sum(t.get('pnl', 0) for t in trades), 2),
        "profit_factor": round(
            total_profit / total_loss, 2
        ) if total_loss > 0 else 0
    }

    with open("stats.json", "w") as f:
        json.dump(data, f, indent=2)
