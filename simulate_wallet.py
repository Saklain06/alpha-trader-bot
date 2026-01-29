
import sqlite3
import pandas as pd
from datetime import datetime

def simulate_wallet():
    conn = sqlite3.connect('trades_vps.db')
    df = pd.read_sql_query("SELECT * FROM trades WHERE status = 'closed'", conn)
    
    if df.empty:
        print("No trades found.")
        return

    # parameters
    INITIAL_CASH = 120.0
    TRADE_SIZE = 80.0
    FEE_RATE = 0.0015 # 0.15% approx (Exchange Taker + Slippage)
    
    events = []
    
    for i, row in df.iterrows():
        try:
            # Parse times
            # Format in DB examples: "2026-01-19T15:56:53.109269+00:00"
            # We need to handle potential parsing errors
            t_entry = row['time'] # String format
            t_exit = row['exit_time']
            
            # Simple unique ID
            tid = row['id']
            
            # Calculate ROI of this specific trade
            entry_px = float(row['entry_price'])
            exit_px = float(row['exit_price'])
            qty = float(row['qty'])
            
            # [FIX] Handle missing exit prices (early database records)
            if exit_px == 0 and qty > 0:
                # Back-calculate from PnL
                # PnL = (Exit - Entry) * Qty
                # PnL/Qty = Exit - Entry
                # Exit = (PnL/Qty) + Entry
                pnl = float(row['pnl'])
                exit_px = (pnl / qty) + entry_px
            
            # ROI = (Exit - Entry) / Entry  (Long)
            if entry_px == 0: continue
            roi = (exit_px - entry_px) / entry_px
            
            events.append({
                'time': t_entry,
                'type': 'ENTRY',
                'id': tid,
                'roi': roi,
                'symbol': row['symbol']
            })
            
            events.append({
                'time': t_exit,
                'type': 'EXIT',
                'id': tid
            })
            
        except Exception as e:
            continue
            
    # Sort events chronologically
    events.sort(key=lambda x: x['time'])
    
    cash = INITIAL_CASH
    active_trades = {} # id -> trade_info
    
    taken_trades = 0
    skipped_trades = 0
    total_pnl = 0.0
    total_fees = 0.0
    
    print(f"--- 💼 WALLET SIMULATION ($120 Balance, $80/Trade) ---")
    
    for e in events:
        if e['type'] == 'ENTRY':
            if cash >= TRADE_SIZE:
                # Take Trade
                cash -= TRADE_SIZE
                active_trades[e['id']] = e
                taken_trades += 1
                # print(f"[ENTRY] {e['symbol']} Taken. Cash: {cash:.2f}")
            else:
                skipped_trades += 1
                # print(f"[SKIP]  {e['symbol']} Insufficient Funds.")
                
        elif e['type'] == 'EXIT':
            if e['id'] in active_trades:
                # Process Exit
                trade = active_trades.pop(e['id'])
                
                # Calculate Result
                gross_profit = TRADE_SIZE * trade['roi']
                
                # Calculate Fees (Entry + Exit) ~ 2 * Rate * Size
                fee_cost = (TRADE_SIZE * FEE_RATE) + ((TRADE_SIZE + gross_profit) * FEE_RATE)
                
                net_profit = gross_profit - fee_cost
                
                cash += (TRADE_SIZE + net_profit)
                total_pnl += net_profit
                total_fees += fee_cost
                
                # print(f"[EXIT]  {trade['symbol']} PnL: {net_profit:.2f}. Cash: {cash:.2f}")

    final_balance = cash + (len(active_trades) * TRADE_SIZE) # Add back currently locked collateral (approx)
    net_change = final_balance - INITIAL_CASH

    print(f"----------------------------------------")
    print(f"Total Trades Taken:   {taken_trades} (Skipped {skipped_trades})")
    print(f"Total Fees Paid:      ${total_fees:.2f}")
    print(f"Net PnL:              ${net_change:.2f}")
    print(f"Final Balance:        ${final_balance:.2f} (Start: ${INITIAL_CASH:.2f})")
    print(f"----------------------------------------")
    
    if net_change > 0:
        print("✅ RESULT: Profitable!")
    else:
        print("❌ RESULT: Still a loss (Fees + Losers).")

if __name__ == "__main__":
    simulate_wallet()
