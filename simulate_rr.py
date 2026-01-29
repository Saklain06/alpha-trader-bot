
import sqlite3
import pandas as pd

def simulate():
    conn = sqlite3.connect('trades_vps.db')
    df = pd.read_sql_query("SELECT * FROM trades WHERE status = 'closed'", conn)
    
    if df.empty:
        print("No trades data.")
        return

    # Convert columns
    cols = ['entry_price', 'exit_price', 'sl', 'tp', 'highest_price', 'pnl', 'fees_usd', 'qty']
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

    # Simulation Variables
    sim_wins = 0
    sim_losses = 0
    sim_pnl = 0.0
    
    total_fees = df['fees_usd'].sum()
    original_net_pnl = df['pnl'].sum() - total_fees

    print(f"--- 🎲 SIMULATION: 1:3 Risk:Reward ---")
    
    for i, row in df.iterrows():
        entry = row['entry_price']
        sl = row['sl']
        qty = row['qty']
        
        # Determine Trade Direction (Long/Short) - Assuming Long for now based on context
        # Risk Per Share
        risk_per_share = abs(entry - sl)
        if risk_per_share == 0: continue
        
        # Calculate Risk Amount ($)
        risk_usd = risk_per_share * qty
        
        # Target 1:1.5
        # Assuming LONG trades:
        target_price = entry + (1.5 * risk_per_share)
        
        # Did we hit it?
        # highest_price tracks the max price reached during the trade
        if row['highest_price'] >= target_price:
            # WIN
            sim_wins += 1
            gain = 1.5 * risk_usd # 1.5R GAIN
            sim_pnl += gain
        else:
            # LOSS (Reversed to SL)
            sim_losses += 1
            loss = risk_usd
            sim_pnl -= loss

    # Net Simulation PnL (Subtracting same fees)
    # Baseline assumed Gross PnL ~ +2.53 (from previous analysis)
    # Fees are constant ($5.09)
    sim_net_pnl = sim_pnl - total_fees
    
    # Original Net PnL (from DB)
    original_net_pnl = df['pnl'].sum()

    print(f"--- 🎲 SIMULATION: 1:1.5 Risk:Reward ---")
    print(f"Original Net PnL: ${original_net_pnl:.2f}")
    print(f"----------------------------------------")
    print(f"Simulated 1:1.5 PnL: ${sim_net_pnl:.2f}")
    print(f"Simulated Win Rate: {(sim_wins / len(df) * 100):.1f}% ({sim_wins}W / {sim_losses}L)")
    
    diff = sim_net_pnl - original_net_pnl
    print(f"----------------------------------------")
    if diff > 0:
        print(f"✅ RESULT: 1:1.5 would have earned ${diff:.2f} MORE.")
    else:
        print(f"❌ RESULT: 1:1.5 would have lost ${abs(diff):.2f} MORE.")

if __name__ == "__main__":
    simulate()
