"use client";

import { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart
} from "recharts";

type Trade = {
  entry_ts: string;
  exit_ts: string;
  symbol: string;
  entry_price: number;
  exit_price: number;
  qty: number;
  pnl: number;
  fee: number;
  type: string;
};

export default function BacktestViewer({ api = "http://localhost:8000" }) {
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${api}/backtest/results`);
      if (!res.ok) throw new Error("No results");
      const j = await res.json();
      setData(j);
    } catch (e) {
      console.warn("Backtest results not found", e);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (loading) return <div>Loading backtest...</div>;
  if (!data)
    return <div className="p-4 text-red-600 font-semibold">No backtest results. Run backtest.py first.</div>;

  const equity = data.equity_curve.map((p: any) => ({
    ts: p.ts,
    equity: Number(p.equity)
  }));

  const dd = data.drawdown_series.map((p: any) => ({
    ts: p.ts,
    dd: Number(p.dd)
  }));

  const trades: Trade[] = data.trades ?? [];

  const daily = Object.entries(data.daily_pnl ?? {}).map(([day, val]) => ({
    day,
    val
  }));

  return (
    <div className="p-6 bg-gray-50 min-h-screen text-gray-900">
      <h2 className="text-3xl font-bold mb-4">📈 Backtest Results — {data.symbol} {data.timeframe}</h2>

      {/* ==================== EQUITY + DRAWDOWN ==================== */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        
        {/* === EQUITY CURVE === */}
        <div className="bg-white p-4 rounded-xl shadow border">
          <h3 className="text-lg font-semibold mb-2">Equity Curve</h3>
          <div style={{ height: 300 }}>
            <ResponsiveContainer>
              <LineChart data={equity}>
                <CartesianGrid stroke="#e5e7eb" />
                <XAxis tick={{ fill: "#333" }} dataKey="ts" tickFormatter={(t: string) => new Date(t).toLocaleString()} />
                <YAxis tick={{ fill: "#333" }} domain={["auto", "auto"]} />
                <Tooltip />
                <Line type="monotone" dataKey="equity" stroke="#16a34a" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* === DRAWDOWN === */}
        <div className="bg-white p-4 rounded-xl shadow border">
          <h3 className="text-lg font-semibold mb-2">Drawdown</h3>
          <div style={{ height: 300 }}>
            <ResponsiveContainer>
              <AreaChart data={dd}>
                <CartesianGrid stroke="#e5e7eb" />
                <XAxis tick={{ fill: "#333" }} dataKey="ts" tickFormatter={(t: string) => new Date(t).toLocaleDateString()} />
                <YAxis tick={{ fill: "#333" }} domain={[0, "auto"]} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
                <Tooltip />
                <Area dataKey="dd" fill="#fca5a5" stroke="#ef4444" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* ==================== SUMMARY ==================== */}
      <div className="bg-white p-4 rounded-xl shadow border mt-6 backtest-summary">
        <h3 className="text-lg font-semibold mb-3">Summary</h3>
        <ul className="text-gray-900 leading-6">
          <li>Initial Balance: <b>${data.initial_balance}</b></li>
          <li>Final Equity: <b>${Number(data.final_equity).toFixed(2)}</b></li>
          <li>Total PnL: <b className={data.total_pnl >= 0 ? "text-green-600" : "text-red-600"}>${Number(data.total_pnl).toFixed(2)}</b></li>
          <li>Trades: <b>{data.n_trades}</b></li>
          <li>Win Rate: <b>{Number(data.win_rate).toFixed(2)}%</b></li>
          <li>Profit Factor: <b>{Number(data.profit_factor).toFixed(2)}</b></li>
          <li>Max Drawdown: <b>{(Number(data.max_drawdown) * 100).toFixed(2)}%</b></li>
        </ul>
      </div>

      {/* ==================== DAILY PNL ==================== */}
      <div className="bg-white p-4 rounded-xl shadow border mt-6 backtest-summary">
        <h3 className="text-lg font-semibold mb-2">Daily PnL (recent)</h3>

        <div className="overflow-auto max-h-60 border rounded-lg">
          <table className="w-full text-sm backtest-table">
            <thead className="bg-gray-100 text-gray-900 border-b">
              <tr>
                <th className="p-2 text-left">Day</th>
                <th className="p-2 text-left">PnL</th>
              </tr>
            </thead>
            <tbody>
              {daily.slice(-30).map((d: any, i: number) => (
                <tr key={i} className="border-b">
                  <td className="p-2">{d.day}</td>
                  <td className={`p-2 font-semibold ${d.val > 0 ? "text-green-600" : "text-red-600"}`}>
                    ${Number(d.val).toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ==================== TRADES ==================== */}
      <div className="bg-white p-4 rounded-xl shadow border mt-6 backtest-table">
        <h3 className="text-lg font-semibold mb-3">Trades ({trades.length})</h3>

        <div className="overflow-auto max-h-96">
          <table className="w-full text-sm text-gray-900">
            <thead className="bg-gray-100 border-b">
              <tr>
                <th className="p-2">Entry</th>
                <th className="p-2">Exit</th>
                <th className="p-2">Entry Price</th>
                <th className="p-2">Exit Price</th>
                <th className="p-2">Qty</th>
                <th className="p-2">PnL</th>
                <th className="p-2">Fee</th>
                <th className="p-2">Type</th>
              </tr>
            </thead>
            <tbody>
              {trades.slice().reverse().map((t, i) => (
                <tr key={i} className="border-b">
                  <td className="p-2">{new Date(t.entry_ts).toLocaleString()}</td>
                  <td className="p-2">{new Date(t.exit_ts).toLocaleString()}</td>
                  <td className="p-2">{Number(t.entry_price).toFixed(4)}</td>
                  <td className="p-2">{Number(t.exit_price).toFixed(4)}</td>
                  <td className="p-2">{Number(t.qty).toFixed(6)}</td>
                  <td className={`p-2 font-bold ${t.pnl > 0 ? "text-green-600" : "text-red-600"}`}>
                    ${Number(t.pnl).toFixed(2)}
                  </td>
                  <td className="p-2">${Number(t.fee).toFixed(4)}</td>
                  <td className="p-2">{t.type}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
