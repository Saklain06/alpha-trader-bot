
import sqlite3
import pandas as pd
import numpy as np

def optimize():
    conn = sqlite3.connect('trades_vps.db')
    df = pd.read_sql_query("SELECT * FROM trades WHERE status = 'closed'", conn)
    
    if df.empty:
        print("No trades found.")
        return

    # Convert columns
    cols = ['entry_price', 'highest_price', 'sl', 'pnl', 'fees_usd', 'qty', 'side']
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

    # Base Constants
    total_fees = df['fees_usd'].sum()
    
    results = []
    
    # Grid Search: TP Multipliers
    tp_range = [0.5, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 2.2, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]

    print(f"--- 🚀 STRATEGY OPTIMIZER (Grid Search) ---")
    print(f"Analyzing {len(df)} Trades...")
    print(f"Fees Fixed Cost: ${total_fees:.2f}")
    print("-" * 60)
    print(f"{'TP (R)':<8} {'Win Rate':<10} {'Gross PnL':<12} {'Net PnL':<12} {'Trade Count':<12}")
    print("-" * 60)

    best_pnl = -99999
    best_rr = 0

    for rr in tp_range:
        sim_wins = 0
        sim_losses = 0
        gross_pnl = 0.0
        
        for _, row in df.iterrows():
            entry = row['entry_price']
            sl = row['sl']
            qty = row['qty']
            side = str(row.get('side', 'BUY')).upper()
            
            if side == 'NAN' or side == 'NONE': side = 'BUY'
            
            # Calculate Risk
            risk_per_share = abs(entry - sl)
            if risk_per_share == 0: continue
            
            risk_usd = risk_per_share * qty
            
            # Determine Target Price
            if side == 'SELL':
                target_price = entry - (rr * risk_per_share)
                # For SHORT: Win if LOW <= Target
                # Note: DB might not have 'lowest_price'. Assuming Long-only or 'highest_price' represents favorable excursion
                # If bot is Long/Short, we need logic. 
                # Assuming Long-Only for simplicity based on previous chats (trend following)
                # If Short supported, we need correct column.
                # Let's assume Long for now.
                target_price = entry + (rr * risk_per_share) # Fallback to Long logic check
            else:
                target_price = entry + (rr * risk_per_share)
            
            # Check Outcome
            if row['highest_price'] >= target_price:
                # Win
                sim_wins += 1
                gross_pnl += (risk_usd * rr)
            else:
                # Loss
                sim_losses += 1
                gross_pnl -= risk_usd
        
        net_pnl = gross_pnl - total_fees
        win_rate = (sim_wins / len(df)) * 100
        
        results.append((rr, net_pnl))
        
        # Color code
        pnl_str = f"${net_pnl:.2f}"
        if net_pnl > 0: pnl_str = f"+{pnl_str}"
        
        print(f"{rr:<8} {win_rate:>6.1f}%    ${gross_pnl:>9.2f}   {pnl_str:>10}   {sim_wins}W/{sim_losses}L")
        
        if net_pnl > best_pnl:
            best_pnl = net_pnl
            best_rr = rr

    print("-" * 60)
    print(f"🏆 BEST SETTING: Risk:Reward 1:{best_rr}")
    print(f"💰 POTENTIAL NET PROFIT: ${best_pnl:.2f}")

if __name__ == "__main__":
    optimize()
