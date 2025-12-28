import asyncio
import sys
import os

# Add parent directory to path to import database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database

async def test_db():
    print("Testing Database...")
    db = Database("test_trades.db")
    try:
        await db.init_db()
        print("✅ DB Init success")
        
        # Test add trade
        trade = {
            "id": "test-123",
            "time": "2023-01-01T00:00:00",
            "symbol": "BTC/USDT",
            "side": "buy",
            "strategy": "test",
            "entry_price": 50000.0,
            "qty": 0.1,
            "used_usd": 5000.0,
            "status": "open",
            "pnl": 0.0,
            "sl": 49000.0,
            "tp": 55000.0,
            "exit_price": 0.0,
            "current_price": 50000.0,
            "unrealized_pnl": 0.0,
            "fees_usd": 5.0,
            "highest_price": 50000.0,
            "trail_active": False,
            "trail_sl": 0.0
        }
        await db.add_trade(trade)
        print("✅ Add Trade success")
        
        # Test get open trades
        trades = await db.get_open_trades()
        assert len(trades) == 1
        assert trades[0]['id'] == 'test-123'
        print("✅ Get Open Trades success")
        
        # Test Update
        await db.update_trade("test-123", {"current_price": 51000.0, "unrealized_pnl": 100.0})
        t = await db.get_trade("test-123")
        assert t['current_price'] == 51000.0
        print("✅ Update Trade success")
        
        # Test State
        await db.set_state_key("test_key", {"foo": "bar"})
        s = await db.get_state()
        assert s['test_key']['foo'] == 'bar'
        print("✅ State Management success")

    except Exception as e:
        print(f"❌ Test Failed: {e}")
        raise
    finally:
        # Cleanup
        if os.path.exists("test_trades.db"):
            os.remove("test_trades.db")

if __name__ == "__main__":
    asyncio.run(test_db())
