"use client";

import { useState } from "react";
import BacktestViewer from "../../components/BacktestViewer";

export default function CompareStrategiesPage() {
  const API = "/api";

  const strategies = [
    { name: "EMA 8/21", ema_fast: 8, ema_slow: 21 },
    { name: "EMA 13/34", ema_fast: 13, ema_slow: 34 },
    { name: "EMA 21/55", ema_fast: 21, ema_slow: 55 },
  ];

  const [running, setRunning] = useState(false);

  const runAll = async () => {
    setRunning(true);
    for (const s of strategies) {
      await fetch(
        `${API}/backtest/run?symbol=BTC/USDT&timeframe=1m&ema_fast=${s.ema_fast}&ema_slow=${s.ema_slow}`,
        { method: "POST" }
      );
      await new Promise((r) => setTimeout(r, 3000));
    }
    setRunning(false);
    alert("All strategies tested. Reload viewer.");
  };

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-3xl font-bold">Multi-Strategy Comparison</h1>

      <button
        onClick={runAll}
        className="px-4 py-2 bg-purple-600 text-white rounded-lg"
        disabled={running}
      >
        {running ? "Running..." : "▶ Run Comparisons"}
      </button>

      <p className="text-gray-600">After running, swap strategies in parameter panel and re-open viewer.</p>

      <BacktestViewer key={lastUpdated} api={API} />
    </div>
  );
}
