import asyncio
import os
import sys
import numpy as np
import pandas as pd
import ccxt.async_support as ccxt
from datetime import datetime, timezone

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

INITIAL_CAPITAL = 800.0
MAX_SLOTS = 2
BASE_SLOT_USD = 400.0

async def fetch_test_data(ex, count=40):
    tickers = await ex.fetch_tickers()
    stables = {'USDC', 'FDUSD', 'TUSD', 'EUR', 'GBP', 'BUSD', 'DAI', 'PAXG', 'USDE', 'RLUSD', 'XUSD'}
    
    liquid = []
    for sym, t in tickers.items():
        if not sym.endswith('/USDT') or 'UP/' in sym or 'DOWN/' in sym:
            continue
        base = sym.split('/')[0]
        if base in stables or base in ('BTC', 'ETH'):
            continue
        vol = float(t.get('quoteVolume') or 0.0)
        pct = float(t.get('percentage') or 0.0)
        if vol >= 3_000_000:
            liquid.append({'symbol': sym, 'pct': pct, 'vol': vol})
            
    gainers = sorted(liquid, key=lambda x: x['pct'], reverse=True)[:15]
    losers = sorted(liquid, key=lambda x: x['pct'])[:15]
    spikes = sorted(liquid, key=lambda x: x['vol'], reverse=True)[:15]
    
    user_coins = [
        'BARD/USDT', 'ERA/USDT', 'ONE/USDT', 'BMT/USDT', 'SOPH/USDT',
        'HOT/USDT', 'CYBER/USDT', 'PEPE/USDT', 'ARB/USDT', 'XTZ/USDT',
        'POWR/USDT', 'LSK/USDT', 'FET/USDT', 'ZIL/USDT', 'ALGO/USDT'
    ]
    
    all_syms = list(dict.fromkeys([x['symbol'] for x in gainers + losers + spikes] + user_coins))
    print(f"[*] Fetching multi-timeframe data for {len(all_syms)} coins...")
    
    datasets = {}
    for sym in all_syms:
        try:
            t_1d, t_4h, t_1h = await asyncio.gather(
                ex.fetch_ohlcv(sym, '1d', limit=60),
                ex.fetch_ohlcv(sym, '4h', limit=150),
                ex.fetch_ohlcv(sym, '1h', limit=1000)
            )
            if t_1h and len(t_1h) >= 150:
                df_1d = pd.DataFrame(t_1d, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                df_4h = pd.DataFrame(t_4h, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                df_1h = pd.DataFrame(t_1h, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                for d in (df_1d, df_4h, df_1h):
                    for c in ['open', 'high', 'low', 'close', 'vol']:
                        d[c] = d[c].astype(float)
                datasets[sym] = {'1d': df_1d, '4h': df_4h, '1h': df_1h}
        except Exception:
            pass
            
    print(f"[+] Loaded {len(datasets)} datasets.")
    return datasets

def simulate_trade_stress(
    highs, lows, opens, closes, i, n, entry_p, sl_p, tp_0438, risk_dist,
    worst_case_intrabar=True,
    slippage_pct=0.0015
):
    """
    Stress-tested execution:
    1. Entry Slippage: buy fills at entry_p * (1 + slippage_pct).
    2. Same-bar SL check: if lows[i] <= sl_p on the entry bar, INSTANT STOP LOSS LOSS!
    3. Worst-Case Intra-Bar Rule: if a candle touches both SL and TP/high, assume LOW HIT FIRST (Loss takes priority).
    4. Exit Slippage: stop loss exits at sl_p * (1 - slippage_pct).
    """
    actual_entry = entry_p * (1.0 + slippage_pct)
    actual_sl = sl_p * (1.0 - slippage_pct)
    
    # 1. Did the entry candle itself crash through SL?
    if lows[i] <= actual_sl:
        return actual_sl, i, "SL_ON_ENTRY_BAR", actual_entry
        
    current_sl = actual_sl
    highest_p = max(actual_entry, closes[i])
    half_banked = False
    half_banked_price = None

    for j in range(i + 1, min(i + 150, n)):
        c_high = highs[j]
        c_low = lows[j]
        c_open = opens[j]
        c_close = closes[j]

        # Worst-Case Intra-bar: Check SL first!
        if worst_case_intrabar:
            if c_low <= current_sl:
                if half_banked:
                    blended = 0.5 * half_banked_price + 0.5 * current_sl
                    return blended, j, "HYBRID_TRAIL_WORST_CASE", actual_entry
                return current_sl, j, "SL_WORST_CASE", actual_entry
                
        if c_high > highest_p:
            highest_p = c_high

        # Step 1: Move to Break-Even at +1R
        if highest_p >= actual_entry + 1.0 * risk_dist and current_sl < actual_entry + 0.20 * risk_dist:
            current_sl = actual_entry + 0.20 * risk_dist

        # Step 2: Bank 50% at +2R
        if highest_p >= tp_0438 and not half_banked:
            half_banked = True
            half_banked_price = tp_0438 * (1.0 - slippage_pct) # slippage on limit/market

        # Step 3: Trail remaining 50%
        if half_banked:
            trail_sl = max(actual_entry + 1.0 * risk_dist, highest_p - 0.75 * risk_dist)
            if trail_sl > current_sl:
                current_sl = trail_sl

        # Normal SL check if not already checked
        if not worst_case_intrabar:
            if c_low <= current_sl:
                if half_banked:
                    blended = 0.5 * half_banked_price + 0.5 * current_sl
                    return blended, j, "HYBRID_TRAIL", actual_entry
                return current_sl, j, "SL", actual_entry

    last_idx = min(i + 149, n - 1)
    final_p = closes[last_idx] * (1.0 - slippage_pct)
    if half_banked:
        final_p = 0.5 * half_banked_price + 0.5 * final_p
    return final_p, last_idx, "TIME_EXIT", actual_entry

def run_stress_backtest(
    datasets,
    min_impulse=6.0,
    use_htf=True,
    htf_low_buffer=1.08,
    htf_ema_buffer=0.95,
    worst_case_intrabar=True,
    slippage_pct=0.0015,
    commission_pct=0.001  # Full 0.1% per side (0.2% round-trip, no BNB discount assumed)
):
    all_trades = []
    
    for sym, m_data in datasets.items():
        df_1h = m_data['1h']
        df_4h = m_data['4h']
        df_1d = m_data['1d']

        n = len(df_1h)
        highs = df_1h['high'].values
        lows = df_1h['low'].values
        opens = df_1h['open'].values
        closes = df_1h['close'].values
        ts = df_1h['ts'].values

        lookback = 40
        max_impulse_bars = 15
        consumed = set()

        for i in range(lookback + 3, n - 1):
            win_start = max(0, i - lookback)
            peak_start = win_start + 4
            if peak_start >= i - 1:
                continue

            high_idx = peak_start + int(np.argmax(highs[peak_start:i]))
            swing_high = highs[high_idx]
            if high_idx >= i - 1:
                continue

            imp_start = max(0, high_idx - max_impulse_bars)
            raw_low_idx = imp_start + int(np.argmin(lows[imp_start:high_idx]))
            raw_low = lows[raw_low_idx]
            raw_rng = swing_high - raw_low
            if raw_low <= 0 or raw_rng <= 0:
                continue

            low_idx = raw_low_idx
            base_ceil = raw_low + 0.08 * raw_rng
            for k in range(raw_low_idx + 1, high_idx):
                if lows[k] <= base_ceil and closes[k] <= raw_low + 0.20 * raw_rng:
                    low_idx = k
                else:
                    break
            swing_low = lows[low_idx]
            rng = swing_high - swing_low
            if swing_low <= 0 or rng <= 0:
                continue

            imp_pct = (rng / swing_low) * 100.0
            if imp_pct < min_impulse:
                continue

            key = (int(ts[low_idx]), int(ts[high_idx]))
            if key in consumed:
                continue

            fib_0 = swing_low
            fib_0146 = swing_low + 0.146 * rng
            fib_0438 = swing_low + 0.438 * rng
            fib_1 = swing_high

            if high_idx + 1 < i:
                if np.max(highs[high_idx + 1 : i]) > fib_1:
                    continue
                if np.min(lows[high_idx + 1 : i]) <= fib_0146:
                    consumed.add(key)
                    continue

            # Strict touch
            touched = (lows[i] <= fib_0146 and opens[i] >= fib_0146 and closes[i - 1] > fib_0146)
            if not touched:
                continue

            # Strict buyer rejection
            rng_bar = highs[i] - lows[i]
            lower_wick = min(opens[i], closes[i]) - lows[i]
            is_green = closes[i] >= opens[i]
            has_wick = (lower_wick / rng_bar >= 0.30) if rng_bar > 0 else False
            if not (is_green or has_wick):
                continue

            # HTF Check
            if use_htf:
                closes_1d = df_1d['close'].values
                lows_1d = df_1d['low'].values
                if len(lows_1d) >= 30 and closes_1d[-1] < np.min(lows_1d[-30:]) * htf_low_buffer:
                    continue
                closes_4h = df_4h['close'].values
                if len(closes_4h) >= 50:
                    ema50 = pd.Series(closes_4h).ewm(span=50, adjust=False).mean().iloc[-1]
                    if closes_4h[-1] < ema50 * htf_ema_buffer:
                        continue

            consumed.add(key)
            risk_dist = fib_0146 - fib_0
            if risk_dist <= 0:
                continue

            exit_p, exit_idx, reason, actual_entry = simulate_trade_stress(
                highs, lows, opens, closes, i, n, fib_0146, fib_0, fib_0438, risk_dist,
                worst_case_intrabar=worst_case_intrabar,
                slippage_pct=slippage_pct
            )

            pct_return = (exit_p - actual_entry) / actual_entry
            r_mult = (exit_p - actual_entry) / risk_dist

            all_trades.append({
                'symbol': sym,
                'entry_ts': int(ts[i]),
                'exit_ts': int(ts[exit_idx]),
                'pct_return': pct_return,
                'r_mult': r_mult,
                'reason': reason
            })

    # Portfolio simulation
    if not all_trades:
        return {'trades': 0, 'win_rate': 0.0, 'pf': 0.0, 'net_profit': 0.0, 'roi_pct': 0.0, 'max_dd_pct': 0.0}

    sorted_trades = sorted(all_trades, key=lambda x: x['entry_ts'])
    cash = INITIAL_CAPITAL
    open_slots = []
    executed = []
    peak_equity = INITIAL_CAPITAL
    max_dd_pct = 0.0

    for t in sorted_trades:
        entry_ts = t['entry_ts']
        still_open = []
        for p in open_slots:
            if p['exit_ts'] <= entry_ts:
                cash += p['payout']
                executed.append(p)
            else:
                still_open.append(p)
        open_slots = still_open

        equity = cash + sum(p['invested'] for p in open_slots)
        if equity > peak_equity:
            peak_equity = equity
        dd_pct = ((peak_equity - equity) / peak_equity) * 100.0 if peak_equity > 0 else 0.0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

        if len(open_slots) >= MAX_SLOTS:
            continue

        free_slots = MAX_SLOTS - len(open_slots)
        slot_usd = min(BASE_SLOT_USD, cash / free_slots)
        if slot_usd < 25.0:
            continue

        cash -= slot_usd
        gross_pnl = slot_usd * t['pct_return']
        fees = slot_usd * (commission_pct * 2) # round-trip fee
        net_pnl = gross_pnl - fees
        payout = slot_usd + net_pnl

        open_slots.append({
            'symbol': t['symbol'],
            'entry_ts': entry_ts,
            'exit_ts': t['exit_ts'],
            'invested': slot_usd,
            'payout': payout,
            'net_pnl': net_pnl,
            'r_mult': t['r_mult']
        })

    for p in open_slots:
        cash += p['payout']
        executed.append(p)

    final_equity = cash
    net_profit = final_equity - INITIAL_CAPITAL
    roi_pct = (net_profit / INITIAL_CAPITAL) * 100.0

    wins = [x for x in executed if x['net_pnl'] > 0]
    losses = [x for x in executed if x['net_pnl'] <= 0]
    gw = sum(x['net_pnl'] for x in wins)
    gl = abs(sum(x['net_pnl'] for x in losses)) if losses else 0.0
    pf = (gw / gl) if gl > 0 else (99.0 if gw > 0 else 0.0)
    wr = (len(wins) / len(executed)) * 100.0 if executed else 0.0

    return {
        'trades': len(executed),
        'win_rate': wr,
        'pf': pf,
        'net_profit': net_profit,
        'roi_pct': roi_pct,
        'max_dd_pct': max_dd_pct
    }

async def main():
    ex = ccxt.binance({'enableRateLimit': True})
    try:
        datasets = await fetch_test_data(ex)
        
        print("\n" + "="*115)
        print("🧪 RIGOROUS OVERFITTING AUDIT & BRUTAL REALITY STRESS-TEST MATRIX")
        print("="*115)
        
        stress_tests = [
            ("1. Baseline Master System (Standard Binance Conditions)", 6.0, True, 1.08, 0.95, False, 0.0, 0.00075),
            ("2. Slippage Stress (0.15% Entry + 0.15% Exit Slippage)", 6.0, True, 1.08, 0.95, False, 0.0015, 0.00075),
            ("3. Fee Drag Stress (Full 0.10% Taker / 0.20% Round-trip, No BNB Discount)", 6.0, True, 1.08, 0.95, False, 0.0, 0.001),
            ("4. Worst-Case Intra-Bar Execution (Low Hits First on Ambiguous Candles)", 6.0, True, 1.08, 0.95, True, 0.0, 0.00075),
            ("5. Triple Nightmare: Slippage (0.15%) + Full Fees (0.2%) + Worst-Case Intra-Bar", 6.0, True, 1.08, 0.95, True, 0.0015, 0.001),
            ("6. Impulse Parameter Sensitivity: 5.0% Min Impulse (More Aggressive)", 5.0, True, 1.08, 0.95, True, 0.001, 0.00075),
            ("7. Impulse Parameter Sensitivity: 7.0% Min Impulse (More Conservative)", 7.0, True, 1.08, 0.95, True, 0.001, 0.00075),
            ("8. Impulse Parameter Sensitivity: 8.0% Min Impulse (Power Breakout Only)", 8.0, True, 1.08, 0.95, True, 0.001, 0.00075),
            ("9. HTF Strictness Sensitivity: Strict 4H EMA 50 (1.00x instead of 0.95x)", 6.0, True, 1.08, 1.00, True, 0.001, 0.00075),
            ("10. HTF Strictness Sensitivity: Loose 4H EMA 50 (0.90x instead of 0.95x)", 6.0, True, 1.08, 0.90, True, 0.001, 0.00075),
        ]
        
        rows = []
        for name, imp, htf, low_b, ema_b, intrabar, slip, fee in stress_tests:
            res = run_stress_backtest(
                datasets,
                min_impulse=imp,
                use_htf=htf,
                htf_low_buffer=low_b,
                htf_ema_buffer=ema_b,
                worst_case_intrabar=intrabar,
                slippage_pct=slip,
                commission_pct=fee
            )
            rows.append({
                "Stress-Test Scenario": name,
                "Trades": res['trades'],
                "Win Rate": f"{res['win_rate']:.1f}%",
                "Profit Factor": f"{res['pf']:.2f}",
                "Max DD": f"-{res['max_dd_pct']:.1f}%",
                "Net Profit ($)": f"${res['net_profit']:+.2f}",
                "Return (%)": f"{res['roi_pct']:+.1f}%",
                "Status": "✅ PASS" if res['net_profit'] > 0 else "❌ FAIL"
            })
            
        df_audit = pd.DataFrame(rows)
        print(df_audit.to_string(index=False))
        print("="*115)
        df_audit.to_csv("stress_test_overfitting_audit.csv", index=False)
        print("\n✅ Saved audit results to stress_test_overfitting_audit.csv")
        
    finally:
        await ex.close()

if __name__ == '__main__':
    asyncio.run(main())

