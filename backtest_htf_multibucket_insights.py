import asyncio
import os
import sys
import numpy as np
import pandas as pd
import ccxt.async_support as ccxt
from datetime import datetime, timezone

# Ensure UTF-8 output on Windows consoles
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

INITIAL_CAPITAL = 800.0
MAX_SLOTS = 2
BASE_SLOT_USD = 400.0
COMMISSION_PCT = 0.00075  # 0.075% with BNB discount (0.15% round-trip)

USER_TRADED_COINS = [
    'BARD/USDT', 'ERA/USDT', 'ONE/USDT', 'BMT/USDT', 'SOPH/USDT',
    'HOT/USDT', 'CYBER/USDT', 'PEPE/USDT', 'ARB/USDT', 'XTZ/USDT',
    'POWR/USDT', 'LSK/USDT', 'FET/USDT', 'ZIL/USDT', 'ALGO/USDT'
]

async def fetch_universe_buckets(ex):
    """
    Fetches real-time Binance spot tickers and categorizes into:
    1. Top Gainers (> $3M Vol)
    2. Top Losers (> $3M Vol)
    3. Volume Velocity Spikes
    4. User's manual traded coins
    """
    print("[*] Fetching Binance Spot Tickers...")
    tickers = await ex.fetch_tickers()
    stables = {'USDC', 'FDUSD', 'TUSD', 'EUR', 'GBP', 'BUSD', 'DAI', 'PAXG', 'USDE', 'RLUSD', 'XUSD'}

    liquid_pairs = []
    for sym, t in tickers.items():
        if not sym.endswith('/USDT') or 'UP/' in sym or 'DOWN/' in sym:
            continue
        base = sym.split('/')[0]
        if base in stables or base in ('BTC', 'ETH'):
            continue
        vol = float(t.get('quoteVolume') or 0.0)
        pct = float(t.get('percentage') or 0.0)
        if vol >= 3_000_000:
            liquid_pairs.append({'symbol': sym, 'pct': pct, 'vol': vol})

    gainers = sorted(liquid_pairs, key=lambda x: x['pct'], reverse=True)[:15]
    losers = sorted(liquid_pairs, key=lambda x: x['pct'])[:15]
    vol_spikes = sorted(liquid_pairs, key=lambda x: x['vol'], reverse=True)[:15]

    top_gainers = [x['symbol'] for x in gainers]
    top_losers = [x['symbol'] for x in losers]
    top_vol = [x['symbol'] for x in vol_spikes]

    # Combine all unique symbols + ensure user's traded coins are included
    all_syms = list(dict.fromkeys(top_gainers + top_losers + top_vol + USER_TRADED_COINS))
    print(f"[+] Loaded {len(top_gainers)} Gainers, {len(top_losers)} Losers, {len(top_vol)} Vol Spikes. Total Unique: {len(all_syms)}")
    return top_gainers, top_losers, top_vol, all_syms

async def fetch_multi_timeframe(ex, symbol):
    """Fetches 1D, 4H, and 1H data concurrently for multi-timeframe analysis."""
    try:
        t_1d, t_4h, t_1h = await asyncio.gather(
            ex.fetch_ohlcv(symbol, '1d', limit=60),
            ex.fetch_ohlcv(symbol, '4h', limit=150),
            ex.fetch_ohlcv(symbol, '1h', limit=1000)
        )
        if not t_1h or len(t_1h) < 100:
            return None
        
        df_1d = pd.DataFrame(t_1d, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        df_4h = pd.DataFrame(t_4h, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        df_1h = pd.DataFrame(t_1h, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        for df in (df_1d, df_4h, df_1h):
            for c in ['open', 'high', 'low', 'close', 'vol']:
                df[c] = df[c].astype(float)
                
        return {'1d': df_1d, '4h': df_4h, '1h': df_1h}
    except Exception:
        return None

def compute_htf_bias(df_1d, df_4h):
    """
    Checks if coin passes Higher-Timeframe (4H/1D) Trend & Support Filter:
    1. 1D: Current price is >= 8% above the 30-day low (not making fresh death-spiral lows).
    2. 4H: Current close is >= 95% of 4H EMA 50 (macro uptrend or holding major structural support).
    """
    try:
        closes_1d = df_1d['close'].values
        lows_1d = df_1d['low'].values
        if len(lows_1d) >= 30:
            min_30d = np.min(lows_1d[-30:])
            curr_1d = closes_1d[-1]
            if curr_1d < min_30d * 1.08:
                return False, "Failed 1D Death Spiral Filter (Too close to 30D low)"
        
        closes_4h = df_4h['close'].values
        if len(closes_4h) >= 50:
            # 4H EMA 50
            ema50_4h = pd.Series(closes_4h).ewm(span=50, adjust=False).mean().iloc[-1]
            if closes_4h[-1] < ema50_4h * 0.95:
                return False, "Failed 4H Trend Filter (Below 4H EMA50)"
                
        return True, "HTF Bullish/Support Confirmed"
    except Exception:
        return True, "HTF Check OK"

def simulate_trade(highs, lows, opens, closes, i, n, entry_p, sl_p, tp_0438, risk_dist, exit_mode="hybrid"):
    """
    Simulates trade execution under:
    - Mode A: 'fixed_tp' (Fixed 1:2 TP @ 0.438 Fib, SL @ 0)
    - Mode B: 'pure_trail' (Trail SL once 0.438 hit, lock +1.6R, trail 0.5R)
    - Mode C: 'hybrid' (Break-Even @ +1R, Bank 50% @ +2R via Limit-Maker, Trail 50% with 0.75R)
    """
    current_sl = sl_p
    highest_p = max(entry_p, closes[i])
    tp_hit = False
    half_banked = False
    half_banked_price = None

    for j in range(i + 1, min(i + 150, n)):
        c_high = highs[j]
        c_low = lows[j]
        c_close = closes[j]

        if exit_mode == "fixed_tp":
            if c_low <= current_sl:
                return current_sl, j, "SL"
            if c_high >= tp_0438:
                return tp_0438, j, "TP_1_2"

        elif exit_mode == "pure_trail":
            if c_low <= current_sl:
                reason = "TRAIL_EXIT" if current_sl > sl_p else "SL"
                return current_sl, j, reason
            if c_high > highest_p:
                highest_p = c_high
            if highest_p >= tp_0438:
                new_sl = max(entry_p + 1.6 * risk_dist, highest_p - 0.5 * risk_dist)
                if new_sl > current_sl:
                    current_sl = new_sl

        elif exit_mode == "hybrid":
            # 1. Check SL
            if c_low <= current_sl:
                if half_banked:
                    blended = 0.5 * half_banked_price + 0.5 * current_sl
                    return blended, j, "HYBRID_TRAIL"
                return current_sl, j, "SL"

            if c_high > highest_p:
                highest_p = c_high

            # Step 1: At +1.0R (0.292 Fib), Move SL to Break-Even (+0.20R for fees)
            if highest_p >= entry_p + 1.0 * risk_dist and current_sl < entry_p + 0.20 * risk_dist:
                current_sl = entry_p + 0.20 * risk_dist

            # Step 2: At +2.0R (0.438 Fib), Bank 50% Profit
            if highest_p >= tp_0438 and not half_banked:
                half_banked = True
                half_banked_price = tp_0438

            # Step 3: Trail remaining 50% with 0.75R buffer behind highest_p
            if half_banked:
                trail_sl = max(entry_p + 1.0 * risk_dist, highest_p - 0.75 * risk_dist)
                if trail_sl > current_sl:
                    current_sl = trail_sl

    last_idx = min(i + 149, n - 1)
    final_p = closes[last_idx]
    if exit_mode == "hybrid" and half_banked:
        final_p = 0.5 * half_banked_price + 0.5 * final_p
    return final_p, last_idx, "TIME_EXIT"

def run_signals_on_symbol(m_data, symbol, min_impulse=6.0, use_htf_filter=True, exit_mode="hybrid"):
    """Runs 1H Big-Move Fibonacci strategy on symbol datasets with optional HTF check."""
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
    trades = []
    consumed = set()

    for i in range(lookback + 3, n - 1):
        win_start = max(0, i - lookback)
        peak_search_start = win_start + 4
        if peak_search_start >= i - 1:
            continue

        high_idx = peak_search_start + int(np.argmax(highs[peak_search_start:i]))
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

        touched = (lows[i] <= fib_0146 and opens[i] >= fib_0146 and closes[i - 1] > fib_0146)
        if not touched:
            continue

        # Buyer rejection confirmation (green candle or 30%+ lower wick)
        rng_bar = highs[i] - lows[i]
        lower_wick = min(opens[i], closes[i]) - lows[i]
        is_green = closes[i] >= opens[i]
        has_wick = (lower_wick / rng_bar >= 0.30) if rng_bar > 0 else False
        if not (is_green or has_wick):
            continue

        # HTF 4H/1D Confluence Filter
        if use_htf_filter:
            passed_htf, _ = compute_htf_bias(df_1d, df_4h)
            if not passed_htf:
                continue

        consumed.add(key)
        risk_dist = fib_0146 - fib_0
        if risk_dist <= 0:
            continue

        exit_p, exit_idx, reason = simulate_trade(
            highs, lows, opens, closes, i, n, fib_0146, fib_0, fib_0438, risk_dist, exit_mode=exit_mode
        )

        r_mult = (exit_p - fib_0146) / risk_dist
        pct_return = (exit_p - fib_0146) / fib_0146

        trades.append({
            'symbol': symbol,
            'entry_ts': int(ts[i]),
            'exit_ts': int(ts[exit_idx]),
            'imp_pct': imp_pct,
            'r_mult': r_mult,
            'pct_return': pct_return,
            'reason': reason
        })

    return trades

def simulate_portfolio(candidate_trades, step_up=True):
    """Simulates $800 balance, 2-slot capacity, and drawdown tracking."""
    if not candidate_trades:
        return {'trades': 0, 'win_rate': 0.0, 'pf': 0.0, 'net_profit': 0.0, 'roi_pct': 0.0, 'max_dd_pct': 0.0, 'avg_win_r': 0.0, 'max_win_r': 0.0, 'skipped': 0}

    sorted_trades = sorted(candidate_trades, key=lambda x: x['entry_ts'])
    cash = INITIAL_CAPITAL
    open_slots = []
    executed = []
    skipped = 0

    peak_equity = INITIAL_CAPITAL
    max_dd_pct = 0.0
    step_tier_base = INITIAL_CAPITAL

    for t in sorted_trades:
        entry_ts = t['entry_ts']

        # Settle finished trades
        still_open = []
        for p in open_slots:
            if p['exit_ts'] <= entry_ts:
                cash += p['payout']
                executed.append(p)
            else:
                still_open.append(p)
        open_slots = still_open

        # Drawdown tracking
        equity = cash + sum(p['invested'] for p in open_slots)
        if equity > peak_equity:
            peak_equity = equity
        dd_pct = ((peak_equity - equity) / peak_equity) * 100.0 if peak_equity > 0 else 0.0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

        if step_up and equity >= step_tier_base * 1.30:
            step_tier_base = equity

        # Check capacity
        if len(open_slots) >= MAX_SLOTS:
            skipped += 1
            continue

        free_slots = MAX_SLOTS - len(open_slots)
        base_slot = (step_tier_base / MAX_SLOTS) if step_up else BASE_SLOT_USD
        slot_usd = min(base_slot, cash / free_slots)
        if slot_usd < 25.0:
            skipped += 1
            continue

        cash -= slot_usd
        gross_pnl = slot_usd * t['pct_return']
        fees = slot_usd * (COMMISSION_PCT * 2)
        net_pnl = gross_pnl - fees
        payout = slot_usd + net_pnl

        open_slots.append({
            'symbol': t['symbol'],
            'entry_ts': entry_ts,
            'exit_ts': t['exit_ts'],
            'invested': slot_usd,
            'payout': payout,
            'net_pnl': net_pnl,
            'r_mult': t['r_mult'],
            'reason': t['reason']
        })

    for p in open_slots:
        cash += p['payout']
        executed.append(p)

    final_equity = cash
    net_profit = final_equity - INITIAL_CAPITAL
    roi_pct = (net_profit / INITIAL_CAPITAL) * 100.0

    if not executed:
        return {'trades': 0, 'win_rate': 0.0, 'pf': 0.0, 'net_profit': 0.0, 'roi_pct': 0.0, 'max_dd_pct': 0.0, 'avg_win_r': 0.0, 'max_win_r': 0.0, 'skipped': skipped}

    wins = [x for x in executed if x['net_pnl'] > 0]
    losses = [x for x in executed if x['net_pnl'] <= 0]
    gw = sum(x['net_pnl'] for x in wins)
    gl = abs(sum(x['net_pnl'] for x in losses)) if losses else 0.0
    pf = (gw / gl) if gl > 0 else (99.0 if gw > 0 else 0.0)
    wr = (len(wins) / len(executed)) * 100.0
    avg_win_r = float(np.mean([x['r_mult'] for x in wins])) if wins else 0.0
    max_win_r = float(max([x['r_mult'] for x in executed])) if executed else 0.0

    return {
        'trades': len(executed),
        'skipped': skipped,
        'win_rate': wr,
        'pf': pf,
        'net_profit': net_profit,
        'roi_pct': roi_pct,
        'max_dd_pct': max_dd_pct,
        'avg_win_r': avg_win_r,
        'max_win_r': max_win_r
    }

async def main():
    ex = ccxt.binance({'enableRateLimit': True})
    try:
        top_gainers, top_losers, top_vol, all_syms = await fetch_universe_buckets(ex)
        print(f"\n[*] Downloading 1D, 4H, and 1H candles for {len(all_syms)} coins...")

        datasets = {}
        for s in all_syms:
            d = await fetch_multi_timeframe(ex, s)
            if d is not None:
                datasets[s] = d
        print(f"[+] Loaded {len(datasets)} full multi-timeframe datasets.\n")

        # Configurations to test and benchmark
        experiments = [
            ("1. Old Bot Baseline: Top Gainers Only (No HTF check, Fixed TP)", top_gainers, 6.0, False, "fixed_tp", False),
            ("2. Blind Top Losers (No HTF check, Fixed TP - Why Backtest Failed)", top_losers, 6.0, False, "fixed_tp", False),
            ("3. Top Losers WITH 4H/1D Confluence Filter (The User's Edge!)", top_losers, 6.0, True, "fixed_tp", False),
            ("4. Multi-Bucket Universe (Gainers + Filtered Losers + Vol Spikes | Fixed TP)", all_syms, 6.0, True, "fixed_tp", False),
            ("5. Multi-Bucket Universe + Pure Trailing Stop (Trail @ 0.438)", all_syms, 6.0, True, "pure_trail", False),
            ("6. 🏆 THE MASTER SYSTEM: Multi-Bucket + HTF Filter + Hybrid Trailing OCO", all_syms, 6.0, True, "hybrid", False),
            ("7. 🌟 MASTER SYSTEM + +30% Step-Up Sizing Tier (Compounding Growth)", all_syms, 6.0, True, "hybrid", True),
        ]

        results = []
        for name, sym_list, imp, use_htf, exit_m, step_up in experiments:
            trades = []
            for s in sym_list:
                if s in datasets:
                    tr = run_signals_on_symbol(datasets[s], s, min_impulse=imp, use_htf_filter=use_htf, exit_mode=exit_m)
                    trades.extend(tr)

            res = simulate_portfolio(trades, step_up=step_up)
            results.append({
                "Strategy Configuration": name,
                "Trades": res['trades'],
                "Skipped": res['skipped'],
                "Win Rate": f"{res['win_rate']:.1f}%",
                "Avg Win": f"+{res['avg_win_r']:.2f}R",
                "Max Win": f"+{res['max_win_r']:.2f}R",
                "Profit Factor": f"{res['pf']:.2f}",
                "Max DD": f"-{res['max_dd_pct']:.1f}%",
                "Net Profit ($)": f"${res['net_profit']:+.2f}",
                "Return (%)": f"{res['roi_pct']:+.1f}%"
            })

        df_res = pd.DataFrame(results)
        df_res['sort_val'] = df_res['Net Profit ($)'].apply(lambda x: float(x.replace('$', '').replace('+', '')))
        df_res = df_res.sort_values(by='sort_val', ascending=False).drop(columns=['sort_val'])

        pd.set_option('display.max_columns', 15)
        pd.set_option('display.width', 1000)
        print("=" * 130)
        print("🏆 FULL BACKTEST BENCHMARK: MULTI-BUCKET + HTF 4H/1D CONFLUENCE + HYBRID TRAILING")
        print("=" * 130)
        print(df_res.to_string(index=False))
        print("=" * 130)

        df_res.to_csv("backtest_htf_multibucket_results.csv", index=False)
        print("\n✅ Results saved to backtest_htf_multibucket_results.csv")

    finally:
        await ex.close()

if __name__ == '__main__':
    asyncio.run(main())

