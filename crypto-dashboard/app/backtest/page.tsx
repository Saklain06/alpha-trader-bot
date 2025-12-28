"use client";

import { useEffect, useState } from "react";
import BacktestViewer from "../components/BacktestViewer";

export default function BacktestPage() {
  const API = "http://localhost:8000";

  // --------------------------
  // Load params from localStorage
  // --------------------------
  const defaultParams = {
    symbol: "BTC/USDT",
    timeframe: "1m",
    ema_fast: 8,
    ema_slow: 21,
    rsi_period: 14,
    sl_pct: 0.6,
    tp_pct: 1.2,
    size_pct: 25,
  };

  const [params, setParams] = useState(() => {
    if (typeof window === "undefined") return defaultParams;
    const saved = localStorage.getItem("backtest_params");
    return saved ? JSON.parse(saved) : defaultParams;
  });

  const [isRunning, setIsRunning] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);

  // --------------------------
  // Save params when user edits
  // --------------------------
  useEffect(() => {
    if (typeof window !== "undefined") {
      localStorage.setItem("backtest_params", JSON.stringify(params));
    }
  }, [params]);

 
  // --------------------------
  // Auto-refresh backtest results every 2 seconds
  // Detect change of backtest_results.json
  // --------------------------
  useEffect(() => {
    const interval = setInterval(async () => {
      const res = await fetch(`${API}/backtest/results`);
      const json = await res.json();

      if (json?.updated_at && json.updated_at !== lastUpdated) {
        setLastUpdated(json.updated_at);
        setIsRunning(false);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [lastUpdated]);
  

  // --------------------------
  // Run Backtest
  // --------------------------
  const runBacktest = async () => {
    setIsRunning(true);

    const query = new URLSearchParams(
      Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)]))
    );

    await fetch(`${API}/backtest/run?${query.toString()}`, {
      method: "POST",
    });

    // UI shows loader while backend runs
    setTimeout(() => setIsRunning(false), 3000);
  };

  return (
    <div className="p-6 space-y-6 bg-gray-50 min-h-screen">

      <h1 className="text-3xl font-bold text-gray-900">Backtesting Lab</h1>

      {/* PARAMETER PANEL */}
      <div className="bg-white p-4 rounded-xl shadow border grid grid-cols-2 md:grid-cols-4 gap-4 text-gray-900">

        {Object.keys(params).map((key) => (
          <div key={key} className="flex flex-col">
            <label className="text-sm font-semibold">{key}</label>
            <input
              className="border px-2 py-1 rounded"
              value={params[key as keyof typeof params]}
              onChange={(e) =>
                setParams({ ...params, [key]: e.target.value })
              }
            />
          </div>
        ))}

        <button
          onClick={runBacktest}
          disabled={isRunning}
          className={`col-span-full px-4 py-2 rounded-lg text-white ${
            isRunning ? "bg-gray-400" : "bg-blue-600 hover:bg-blue-700"
          }`}
        >
          {isRunning ? "Running…" : "▶ Run Backtest"}
        </button>
      </div>

      {/* Results Viewer */}
      <BacktestViewer key={lastUpdated} api={API} />
    </div>
  );
}
