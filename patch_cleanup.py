import os
MAIN_PATH = '/opt/gitco/alpha-trader-bot/main.py'
with open(MAIN_PATH, "r") as f: content = f.read()
target_block = """            # [HARDENING] Watcher Safety Cleanup
            # If we find a trade open in DB but empty in Wallet, close it.
            try:
                bal = await ex_live.fetch_balance()
                total = bal.get('total', {})
                for t in trades:
                    coin = t['symbol'].split('/')[0]
                    real_qty = total.get(coin, 0.0)
                    if real_qty <= 1e-8 or real_qty < (t['qty'] * 0.05):
                        logger.warning(f"🧹 [WATCHER CLEANUP] {t['symbol']} found empty/dust ({real_qty}). Auto-closing.")
                        await db.update_trade(t['id'], {
                            "status": "closed",
                            "exit_time": datetime.now(timezone.utc).isoformat(),
                            "pnl": 0,
                            "exit_price": 0
                        })
                        await register_trade_close(0.0, t['symbol'])
            except Exception as e:
                logger.error(f"[WATCHER CLEANUP ERROR] {e}")"""
replacement_block = """            # [HARDENING] Watcher Safety Cleanup
            # If we find a trade open in DB but empty in Wallet, close it.
            if TRADE_MODE == "live":
                try:
                    bal = await ex_live.fetch_balance()
                    total = bal.get('total', {})
                    for t in trades:
                        coin = t['symbol'].split('/')[0]
                        real_qty = total.get(coin, 0.0)
                        if real_qty <= 1e-8 or real_qty < (t['qty'] * 0.05):
                            logger.warning(f"🧹 [WATCHER CLEANUP] {t['symbol']} found empty/dust ({real_qty}). Auto-closing.")
                            await db.update_trade(t['id'], {
                                "status": "closed",
                                "exit_time": datetime.now(timezone.utc).isoformat(),
                                "pnl": 0,
                                "exit_price": 0
                            })
                            await register_trade_close(0.0, t['symbol'])
                except Exception as e:
                    logger.error(f"[WATCHER CLEANUP ERROR] {e}")"""
if target_block in content:
    new_content = content.replace(target_block, replacement_block)
    with open(MAIN_PATH, "w") as f: f.write(new_content)
    print("Patch applied successfully.")
else:
    print("Target block not found.")
