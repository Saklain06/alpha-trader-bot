raw_csv = """Time,OrderNo,Pair,Type¹,Side,Order Price,Order Amount,Time,Executed²,Average Price,Trading total³,Status
2026-11-14 12:51:09,392062098,BARDUSDT,LIMIT,BUY,0.123,3329.5BARD,2026-11-14 12:51:09,3329.5BARD,0.123,409.5285USDT,Filled,
2026-11-14 12:44:57,353982805,ERAUSDT,LIMIT,BUY,0.0753,5335.7ERA,2026-11-14 12:48:46,5335.7ERA,0.0753,401.77821USDT,Filled,
2026-11-13 12:13:49,2197419225,ONEUSDT,LIMIT_MAKER,SELL,0.001584,299500.2ONE,2026-11-14 00:45:32,0ONE,0,0USDT,Expired,
2026-11-13 12:13:49,2197419224,ONEUSDT,STOP_LOSS_LIMIT,SELL,0.001425,299500.2ONE,2026-11-14 00:45:32,299500.2ONE,0.001425,426.787785USDT,Filled,
2026-11-13 12:13:49,2197419223,ONEUSDT,LIMIT,BUY,0.001499,299800.1ONE,2026-11-13 12:15:10,299800.1ONE,0.001499,449.4003499USDT,Filled,
2026-11-12 20:01:20,67145886,OPGUSDT,MARKET,SELL,0,5549.4OPG,2026-11-12 20:01:20,5549.4OPG,0.1404,779.2892USDT,Filled,
2026-11-12 10:44:25,66884499,OPGUSDT,MARKET,BUY,0,2664.4OPG,2026-11-12 10:44:25,2664.4OPG,0.1343,357.82892USDT,Filled,
2026-11-12 09:49:00,2195655241,ONEUSDT,LIMIT_MAKER,SELL,0.00167,276940.4ONE,2026-11-12 13:04:04,276940.4ONE,0.00167,462.490468USDT,Filled,
2026-11-12 09:49:00,2195655240,ONEUSDT,STOP_LOSS_LIMIT,SELL,0.001351,276940.4ONE,2026-11-12 13:04:04,0ONE,0,0USDT,Expired,
2026-11-12 09:47:18,66842286,OPGUSDT,MARKET,BUY,0,2890.6OPG,2026-11-12 09:47:18,2890.6OPG,0.1383,399.9884USDT,Filled,
2026-11-12 09:45:19,2195652279,ONEUSDT,MARKET,BUY,0,277202.9ONE,2026-11-12 09:45:19,277202.9ONE,0.001442,399.9999697USDT,Filled,
2026-11-12 02:36:08,649577827,INITUSDT,Stop-Limit,SELL,0.11752,2777.8INIT,2026-11-12 08:30:04,2777.8INIT,0.11752,326.447056USDT,FILLED
2026-11-12 02:36:08,649577828,INITUSDT,Limit-Maker,SELL,0.23906,2777.8INIT,2026-11-12 07:43:10,0INIT,0,0USDT,EXPIRED
2026-11-11 18:17:17,647600057,INITUSDT,Limit,BUY,0.15803,2780.6INIT,2026-11-11 20:04:57,2780.6INIT,0.15803,439.418218USDT,FILLED
2026-11-11 11:14:30,1135416854,CYBERUSDT,Limit,BUY,0.266,1651.96CYBER,2026-11-11 11:30:04,1651.96CYBER,0.266,439.42136USDT,FILLED
2026-11-11 11:14:30,1135416855,CYBERUSDT,Stop-Limit,SELL,0.253,1650.3CYBER,2026-11-12 03:42:12,1650.3CYBER,0.253,417.5259USDT,FILLED
2026-11-11 11:14:30,1135416856,CYBERUSDT,Limit-Maker,SELL,0.292,1650.3CYBER,2026-11-12 03:42:12,0CYBER,0,0USDT,EXPIRED
2026-11-10 22:29:18,408751724,QIUSDT,Limit,BUY,0.001792,241469QI,2026-11-11 01:05:09,0QI,0,0USDT,CANCELED
2026-11-10 21:28:40,5486178758,PEPEUSDT,Stop-Limit,SELL,0.00000506,84101336PEPE,2026-11-10 22:32:05,0PEPE,0,0USDT,EXPIRED
2026-11-10 21:28:40,5486178759,PEPEUSDT,Limit-Maker,SELL,0.00000531,84101336PEPE,2026-11-10 22:32:05,84101336PEPE,0.000005,446.57809416USDT,FILLED
2026-11-10 21:27:12,5486173700,PEPEUSDT,Market,BUY,0,84185522PEPE,2026-11-10 21:27:12,84185522PEPE,0.000005,432.71358308USDT,FILLED
2026-11-10 16:19:32,236550824,HAEDALUSDT,Limit-Maker,SELL,0.02567,16167.1HAEDAL,2026-11-11 19:13:10,16167.1HAEDAL,0.02567,415.009457USDT,FILLED
2026-11-10 16:19:32,236550823,HAEDALUSDT,Stop-Limit,SELL,0.02337,16167.1HAEDAL,2026-11-11 19:13:10,0HAEDAL,0,0USDT,EXPIRED
2026-11-10 16:18:27,3776277281,ARBUSDT,Stop-Limit,SELL,0.1598,2438ARB,2026-11-10 20:42:20,2438ARB,0.1598,389.5924USDT,FILLED
2026-11-10 16:18:27,3776277282,ARBUSDT,Limit-Maker,SELL,0.1721,2438ARB,2026-11-10 20:42:20,0ARB,0,0USDT,EXPIRED
2026-11-10 13:28:05,236510505,HAEDALUSDT,Limit,BUY,0.02372,16183.3HAEDAL,2026-11-10 13:28:05,16183.3HAEDAL,0.02371,383.767876USDT,FILLED
2026-11-10 13:15:21,3776157814,ARBUSDT,Limit,BUY,0.1639,2440.5ARB,2026-11-10 16:11:16,2440.5ARB,0.1639,399.99795USDT,FILLED
2026-11-09 20:09:23,1938297318,ZILUSDT,Stop-Limit,SELL,0.001604,237961.9ZIL,2026-11-10 11:55:32,237961.9ZIL,0.001604,381.6908876USDT,FILLED
2026-11-09 20:09:23,1938297319,ZILUSDT,Limit-Maker,SELL,0.001862,237961.9ZIL,2026-11-10 11:55:32,0ZIL,0,0USDT,EXPIRED
2026-11-09 18:46:07,631199336,INITUSDT,Limit,BUY,0.12388,3249.5INIT,2026-11-09 19:21:09,0INIT,0,0USDT,CANCELED
2026-11-09 18:44:58,1938260372,ZILUSDT,Limit,BUY,0.00169,238200.2ZIL,2026-11-09 20:00:56,238200.2ZIL,0.00169,402.558338USDT,FILLED
2026-11-09 17:15:23,1407424642,HOTUSDT,Limit,BUY,0.000409,1968500HOT,2026-11-09 18:34:11,0HOT,0,0USDT,CANCELED
2026-11-09 13:00:35,3131684601,ALGOUSDT,Limit-Maker,SELL,0.0908,8875ALGO,2026-11-09 13:24:25,8875ALGO,0.0908,805.85USDT,FILLED
2026-11-09 13:00:35,3131684600,ALGOUSDT,Stop-Limit,SELL,0.0889,8875ALGO,2026-11-09 13:24:25,0ALGO,0,0USDT,EXPIRED
2026-11-09 12:59:04,3131684172,ALGOUSDT,Market,BUY,0,8884ALGO,2026-11-09 12:59:04,8884ALGO,0.0896,796.0064USDT,FILLED
2026-11-09 12:39:23,1134279390,CYBERUSDT,Stop-Limit,SELL,0.23,1542.34CYBER,2026-11-10 16:45:17,0CYBER,0,0USDT,EXPIRED
2026-11-09 12:39:23,1134279391,CYBERUSDT,Limit-Maker,SELL,0.309,1542.34CYBER,2026-11-10 16:45:19,1542.34CYBER,0.309,476.58306USDT,FILLED
2026-11-09 12:37:55,1134278926,CYBERUSDT,Market,BUY,0,1543.85CYBER,2026-11-09 12:37:55,1543.85CYBER,0.259,399.99743USDT,FILLED
2026-11-09 12:12:23,3737813416,FETUSDT,Market,SELL,0,2832.9FET,2026-11-09 12:12:23,2832.9FET,0.1388,393.20652USDT,FILLED
2026-11-09 09:52:42,245612713,GNSUSDT,Limit,BUY,0.344,1167.53GNS,2026-11-09 12:58:15,0GNS,0,0USDT,CANCELED
2026-11-09 01:37:54,3737333964,FETUSDT,Stop-Limit,SELL,0.1192,2832.9FET,2026-11-09 12:12:14,0FET,0,0USDT,CANCELED
2026-11-09 01:37:54,3737333965,FETUSDT,Limit-Maker,SELL,0.1863,2832.9FET,2026-11-09 12:12:14,0FET,0,0USDT,CANCELED
2026-11-09 01:24:41,3737330033,FETUSDT,Market,BUY,0,2835.8FET,2026-11-09 01:24:41,2835.8FET,0.1422,403.25076USDT,FILLED
2026-11-09 00:04:23,412144000,BMTUSDT,Limit,BUY,0.02318,17256.2BMT,2026-11-09 01:25:58,0BMT,0,0USDT,CANCELED
2026-11-08 14:06:55,1406312948,HOTUSDT,Limit-Maker,SELL,0.000433,1101644HOT,2026-11-08 15:20:40,1101644HOT,0.000433,477.011852USDT,FILLED
2026-11-08 14:06:55,1406312947,HOTUSDT,Stop-Limit,SELL,0.000305,1101644HOT,2026-11-08 15:20:40,0HOT,0,0USDT,EXPIRED
2026-11-08 12:14:07,299682322,MITOUSDT,Stop-Limit,SELL,0.00729,100234.5MITO,2026-11-08 15:31:43,100234.5MITO,0.00729,730.709505USDT,FILLED
2026-11-08 12:14:07,299682323,MITOUSDT,Limit-Maker,SELL,0.00797,100234.5MITO,2026-11-08 15:31:43,0MITO,0,0USDT,EXPIRED
2026-11-08 12:10:20,299680939,MITOUSDT,Market,BUY,0,100333.9MITO,2026-11-08 12:10:20,100333.9MITO,0.00761,764.000498USDT,FILLED
2026-11-08 00:58:05,942350688,LSKUSDT,Market,SELL,0,2133.5LSK,2026-11-08 00:58:05,2133.5LSK,0.1784,380.6164USDT,FILLED
2026-11-08 00:56:37,410765679,BMTUSDT,Limit,BUY,0.02226,17239.3BMT,2026-11-08 11:38:21,0BMT,0,0USDT,CANCELED
2026-11-08 00:56:19,1406279637,HOTUSDT,Limit,BUY,0.000348,1102720HOT,2026-11-08 02:10:23,1102720HOT,0.000348,383.74656USDT,FILLED
2026-11-08 00:55:29,3552845734,ENAUSDT,Market,SELL,0,2141.95ENA,2026-11-08 00:55:29,2141.95ENA,0.1574,337.14293USDT,FILLED
2026-11-06 20:47:59,2077365607,XTZUSDT,Market,SELL,0,1605.1XTZ,2026-11-06 20:47:59,1605.1XTZ,0.2685,431.11779USDT,FILLED
2026-11-06 14:06:25,3550325885,ENAUSDT,Market,BUY,0,2144.1ENA,2026-11-06 14:06:25,2144.1ENA,0.1638,351.20358USDT,FILLED
2026-11-06 03:26:06,3736234032,FETUSDT,Limit,BUY,0.1412,2487.2FET,2026-11-06 14:06:11,0FET,0,0USDT,CANCELED
2026-11-06 00:52:27,488654982,BABYUSDT,Market,SELL,0,29944BABY,2026-11-06 00:52:27,29944BABY,0.01174,351.54256USDT,FILLED
2026-11-05 20:56:15,2076999708,XTZUSDT,Limit-Maker,SELL,0.2733,1605.1XTZ,2026-11-06 20:47:44,0XTZ,0,0USDT,CANCELED
2026-11-05 20:56:15,2076999707,XTZUSDT,Stop-Limit,SELL,0.239,1605.1XTZ,2026-11-06 20:47:44,0XTZ,0,0USDT,CANCELED
2026-11-05 20:55:25,488614282,BABYUSDT,Limit-Maker,SELL,0.01179,29944BABY,2026-11-06 00:50:15,0BABY,0,0USDT,CANCELED
2026-11-05 20:55:25,488614281,BABYUSDT,Stop-Limit,SELL,0.01123,29944BABY,2026-11-06 00:50:15,0BABY,0,0USDT,CANCELED
2026-11-05 20:51:36,488610705,BABYUSDT,Market,BUY,0,29974BABY,2026-11-05 20:51:36,29974BABY,0.01144,342.90256USDT,FILLED
2026-11-05 20:49:30,2076993915,XTZUSDT,Limit,BUY,0.2505,1606.8XTZ,2026-11-05 20:51:45,1606.8XTZ,0.2505,402.5034USDT,FILLED
2026-11-03 18:17:07,405642436,BMTUSDT,Stop-Limit,SELL,0.02308,19476.1BMT,2026-11-04 06:26:06,0BMT,0,0USDT,EXPIRED
2026-11-03 18:17:07,405642437,BMTUSDT,Limit-Maker,SELL,0.03132,19476.1BMT,2026-11-04 06:26:06,19476.1BMT,0.03132,609.991452USDT,FILLED
2026-11-02 15:07:36,404160168,BMTUSDT,Market,BUY,0,19474BMT,2026-11-02 15:07:36,19474BMT,0.02095,408.09706USDT,FILLED
2026-11-02 14:19:24,937801198,LSKUSDT,Limit-Maker,SELL,0.2337,2133.5LSK,2026-11-08 00:57:50,0LSK,0,0USDT,CANCELED
2026-11-02 14:19:24,937801197,LSKUSDT,Stop-Limit,SELL,0.1674,2133.5LSK,2026-11-08 00:57:50,0LSK,0,0USDT,CANCELED
2026-11-02 14:17:19,404150361,BMTUSDT,Limit,BUY,0.02087,19570.4BMT,2026-11-02 15:02:30,21.6BMT,0.02087,0.450792USDT,PARTIALLY_FILLED
2026-11-02 10:47:50,937648703,LSKUSDT,Market,BUY,0,2135.6LSK,2026-11-02 10:47:50,2135.6LSK,0.1873,399.99788USDT,FILLED
2026-11-01 20:35:53,733767404,POWRUSDT,Limit-Maker,SELL,0.0632,7204POWR,2026-11-02 06:56:56,0POWR,0,0USDT,EXPIRED
2026-11-01 20:35:53,733767403,POWRUSDT,Stop-Limit,SELL,0.0556,7204POWR,2026-11-02 06:56:56,7204POWR,0.0556,400.5424USDT,FILLED
2026-11-01 20:34:40,733767098,POWRUSDT,Market,BUY,0,7211POWR,2026-11-01 20:34:40,7211POWR,0.0584,421.2217USDT,FILLED
2026-11-01 18:48:08,281064441,SOPHUSDT,Stop-Limit,SELL,0.00118,302752SOPH,2026-11-02 08:29:52,0SOPH,0,0USDT,EXPIRED
2026-11-01 18:48:08,281064442,SOPHUSDT,Limit-Maker,SELL,0.0018,302752SOPH,2026-11-02 08:29:52,302752SOPH,0.0018,544.9536USDT,FILLED
2026-11-01 18:46:38,281064337,SOPHUSDT,Market,BUY,0,303056SOPH,2026-11-01 18:46:38,303056SOPH,0.00139,421.24784USDT,FILLED
2026-11-01 13:16:00,936243128,LSKUSDT,Stop-Limit,SELL,0.2158,1857.9LSK,2026-11-01 17:15:18,1857.9LSK,0.2158,400.93482USDT,FILLED
2026-11-01 13:16:00,936243129,LSKUSDT,Limit-Maker,SELL,0.261,1857.9LSK,2026-11-01 17:15:18,0LSK,0,0USDT,EXPIRED
2026-11-01 12:10:17,936104663,LSKUSDT,Market,BUY,0,1859.8LSK,2026-11-01 12:10:17,1859.8LSK,0.2312,429.98576USDT,FILLED
2026-11-01 12:03:46,231145021,HAEDALUSDT,Market,SELL,0,262.9HAEDAL,2026-11-01 12:03:46,262.9HAEDAL,0.02417,6.354293USDT,FILLED
2026-11-01 12:02:16,231144401,HAEDALUSDT,Stop-Limit,SELL,0.024,262.9HAEDAL,2026-11-01 12:03:35,0HAEDAL,0,0USDT,CANCELED
2026-11-01 11:57:33,231143456,HAEDALUSDT,Stop-Limit,SELL,0.024,262.9HAEDAL,2026-11-01 12:01:53,0HAEDAL,0,0USDT,CANCELED
2026-11-01 02:49:48,231010237,HAEDALUSDT,Limit,BUY,0.02399,262.9HAEDAL,2026-11-01 02:49:48,262.9HAEDAL,0.02397,6.301713USDT,FILLED
2026-11-01 01:12:20,230988665,HAEDALUSDT,Market,SELL,0,18072.1HAEDAL,2026-11-01 01:12:20,18072.1HAEDAL,0.02388,431.693224USDT,FILLED
"""

import csv
import io
from collections import defaultdict

lines = raw_csv.strip().split("\n")
reader = csv.reader(lines)
header = next(reader)

orders = []
for row in reader:
    if not row or len(row) < 11:
        continue
    time_created = row[0].strip()
    order_no = row[1].strip()
    pair = row[2].strip()
    order_type = row[3].strip()
    side = row[4].strip().upper()
    order_price = float(row[5].strip()) if row[5].strip() else 0.0
    order_amt = row[6].strip()
    exec_time = row[7].strip()
    exec_amt = row[8].strip()
    avg_price = float(row[9].strip()) if row[9].strip() else 0.0
    trading_total = row[10].strip()
    status = row[11].strip().upper() if len(row) > 11 else ""

    # Parse trading total
    total_usd = 0.0
    if trading_total.endswith("USDT"):
        try:
            total_usd = float(trading_total[:-4].strip())
        except:
            pass

    # Parse executed quantity
    exec_qty = 0.0
    for char_idx in range(len(exec_amt)):
        if exec_amt[char_idx].isalpha():
            try:
                exec_qty = float(exec_amt[:char_idx])
            except:
                pass
            break

    orders.append({
        "time_created": time_created,
        "exec_time": exec_time,
        "pair": pair,
        "type": order_type,
        "side": side,
        "price": avg_price if avg_price > 0 else order_price,
        "qty": exec_qty,
        "total_usd": total_usd,
        "status": status
    })

# Chronological order
orders.sort(key=lambda x: x["exec_time"] if x["exec_time"] else x["time_created"])

# Reconstruct roundtrips
# Maintain an open inventory per pair: list of [buy_dict]
inventory = defaultdict(list)
roundtrips = []

for o in orders:
    # We only care about FILLED or PARTIALLY_FILLED trades with executed quantity > 0 and total_usd > 0
    if o["status"] not in ("FILLED", "PARTIALLY_FILLED") or o["qty"] <= 0 or o["total_usd"] <= 0:
        continue
    
    pair = o["pair"]
    if o["side"] == "BUY":
        inventory[pair].append(o)
    elif o["side"] == "SELL":
        # Match with existing buy inventory (FIFO)
        if not inventory[pair]:
            # Maybe bought before Oct 31 (e.g. early HAEDAL)
            roundtrips.append({
                "pair": pair,
                "buy_time": "Pre-history",
                "buy_usd": o["total_usd"], # rough estimate
                "buy_price": o["price"],
                "sell_time": o["exec_time"],
                "sell_usd": o["total_usd"],
                "sell_price": o["price"],
                "sell_type": o["type"],
                "pnl_usd": 0.0,
                "pnl_pct": 0.0,
                "note": "Orphan Sell without buy in log"
            })
            continue

        # Match against buy
        sell_qty = o["qty"]
        sell_usd = o["total_usd"]
        sell_price = o["price"]
        sell_time = o["exec_time"]
        sell_type = o["type"]

        # Aggregate all matching buys
        matched_buys = []
        tot_buy_usd = 0.0
        tot_buy_qty = 0.0

        while inventory[pair] and tot_buy_qty < sell_qty * 0.98:
            b = inventory[pair].pop(0)
            matched_buys.append(b)
            tot_buy_usd += b["total_usd"]
            tot_buy_qty += b["qty"]

        avg_buy_price = tot_buy_usd / tot_buy_qty if tot_buy_qty > 0 else sell_price
        pnl_usd = sell_usd - tot_buy_usd
        pnl_pct = (pnl_usd / tot_buy_usd) * 100.0 if tot_buy_usd > 0 else 0.0

        buy_time_str = matched_buys[0]["exec_time"] if matched_buys else "N/A"
        roundtrips.append({
            "pair": pair,
            "buy_time": buy_time_str,
            "buy_usd": tot_buy_usd,
            "buy_price": avg_buy_price,
            "sell_time": sell_time,
            "sell_usd": sell_usd,
            "sell_price": sell_price,
            "sell_type": sell_type,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct
        })

print(f"Total Closed Roundtrips: {len(roundtrips)}")
wins = [r for r in roundtrips if r.get("pnl_usd", 0) > 0.01 and "note" not in r]
losses = [r for r in roundtrips if r.get("pnl_usd", 0) < -0.01 and "note" not in r]

gross_profit = sum(r["pnl_usd"] for r in wins)
gross_loss = sum(abs(r["pnl_usd"]) for r in losses)
net_pnl = gross_profit - gross_loss
pf = gross_profit / gross_loss if gross_loss > 0 else 999.0

print("\n" + "="*85)
print(f"📊 FULL AUDIT OF ALL MANUAL TRADES (Oct 31 - Nov 14):")
print("="*85)
for i, r in enumerate(roundtrips):
    if "note" in r:
        continue
    outcome = "🟢 WIN" if r["pnl_usd"] > 0 else "🔴 LOSS"
    print(f"{i+1:2d}. {r['pair']:10s} | Buy: {r['buy_time'][5:16]} (${r['buy_usd']:.2f} @ {r['buy_price']:.5g}) -> Sell: {r['sell_time'][5:16]} (${r['sell_usd']:.2f} @ {r['sell_price']:.5g}) | PnL: ${r['pnl_usd']:+7.2f} ({r['pnl_pct']:+5.1f}%) [{r['sell_type']}] {outcome}")

print("="*85)
print(f"Total Roundtrips: {len(wins) + len(losses)}")
print(f"Wins: {len(wins)} | Losses: {len(losses)} | Win Rate: {len(wins)/(len(wins)+len(losses))*100:.1f}%")
print(f"Gross Profit: +${gross_profit:.2f}")
print(f"Gross Loss:   -${gross_loss:.2f}")
print(f"Net Profit:   +${net_pnl:.2f}")
print(f"Profit Factor: {pf:.2f}")
if wins:
    print(f"Average Win:  +${gross_profit/len(wins):.2f} (+{sum(r['pnl_pct'] for r in wins)/len(wins):.1f}%)")
if losses:
    print(f"Average Loss: -${gross_loss/len(losses):.2f} ({sum(r['pnl_pct'] for r in losses)/len(losses):.1f}%)")

print("\n📦 CURRENTLY OPEN POSITIONS:")
for pair, items in inventory.items():
    if items:
        for it in items:
            print(f"  - {pair}: Bought at {it['exec_time']} for ${it['total_usd']:.2f} @ {it['price']}")

