"use client";

import { useEffect, useState, useRef } from "react";

type Position = {
   id: string;
   symbol: string;
   entry_price: number;
   qty: number;
   used_usd?: number;
   sl?: number;
   tp?: number;
   current_price?: number;
   unrealized_pnl?: number;
   fees_usd?: number;
};

export default function Dashboard() {
   const API = "http://localhost:8000";

   const [stats, setStats] = useState<any>({});
   const [trades, setTrades] = useState<any[]>([]);
   const [positions, setPositions] = useState<Position[]>([]);
   const [loading, setLoading] = useState(false);

   const [slEdits, setSlEdits] = useState<Record<string, string>>({});
   const [tpEdits, setTpEdits] = useState<Record<string, string>>({});

   const initialized = useRef(false);
   const [lastSync, setLastSync] = useState<string>("—");

   const [theme, setTheme] = useState<"dark" | "light">("dark");

   const [tradeUsd, setTradeUsd] = useState<number>(10);
   const [tradeUsdDraft, setTradeUsdDraft] = useState<string>("10");
   const [editingTradeUsd, setEditingTradeUsd] = useState(false);

   const [exitMenuOpen, setExitMenuOpen] = useState<string | null>(null);

   const loadData = async () => {
      try {
         const [s, t, p, cfg] = await Promise.all([
            fetch(`${API}/stats`).then(r => r.json()),
            fetch(`${API}/trades`).then(r => r.json()),
            fetch(`${API}/positions`).then(r => r.json()),
            fetch(`${API}/admin/trade-usd`).then(r => r.json()),
         ]);

         setStats(s ?? {});
         setTrades(Array.isArray(t) ? t : []);
         setPositions(Array.isArray(p) ? p : []);

         const serverUsd = String(cfg?.trade_usd ?? 10);
         setTradeUsd(Number(serverUsd));
         if (!editingTradeUsd) setTradeUsdDraft(serverUsd);

         setLastSync(new Date().toUTCString());
      } catch { }
   };

   useEffect(() => {
      if (initialized.current) return;
      initialized.current = true;
      loadData();
      const i = setInterval(loadData, 5000);
      return () => clearInterval(i);
   }, [editingTradeUsd]);

   const autoRunning = stats?.mode === "auto";
   const isDark = theme === "dark";

   // --- HELPERS ---
   const toUSD = (usd: number) => {
      return `$${Number(usd || 0).toFixed(2)}`;
   };

   const toPrice = (price: number) => {
      return Number(price || 0).toFixed(5);
   };

   const formatTime = (utcTime: string) => {
      if (!utcTime) return "--";
      return new Date(utcTime).toLocaleString();
   };

   // --- ACTIONS ---
   const killBot = async () => {
      if (!confirm("Pause AI Agent?")) return;
      await fetch(`${API}/admin/kill`, { method: "POST" });
      await loadData();
   };

   const resumeBot = async () => {
      if (!confirm("Start AI Agent?")) return;
      await fetch(`${API}/admin/resume`, { method: "POST" });
      await loadData();
   };

   const closeAllTrades = async () => {
      if (!confirm("Emergency Exit: Sell everything now?")) return;
      setLoading(true);
      try {
         for (const p of positions) {
            await fetch(`${API}/paper-sell?trade_id=${p.id}&sell_pct=100`, { method: "POST" });
         }
         await loadData();
      } finally {
         setLoading(false);
      }
   };

   const closeTrade = async (id: string, pct: number) => {
      if (loading) return;
      setLoading(true);
      try {
         await fetch(`${API}/paper-sell?trade_id=${id}&sell_pct=${pct}`, { method: "POST" });
         await loadData();
      } finally {
         setLoading(false);
      }
   };

   const UpdateSlTp = async (p: Position) => {
      const sl = slEdits[p.id] ?? p.sl ?? "";
      const tp = tpEdits[p.id] ?? p.tp ?? "";

      if (!sl && !tp) {
         alert("⚠️ Please enter Safety Limit or Profit Target");
         return;
      }

      setLoading(true);
      try {
         await fetch(`${API}/update-sl-tp?trade_id=${p.id}&sl=${sl || 0}&tp=${tp || 0}`, { method: "POST" });
         alert(`✅ Updated for ${p.symbol}`);
         await loadData();
      } finally {
         setLoading(false);
      }
   };

   const updateTradeUsd = async () => {
      const v = Number(tradeUsdDraft);
      if (isNaN(v) || v < 5) {
         alert("❌ Minimum investment per trade is $5");
         return;
      }
      const r = await fetch(`${API}/admin/set-trade-usd?amount=${v}`, { method: "POST" });
      const d = await r.json();
      if (d.status === "ok") {
         setTradeUsd(v);
         setTradeUsdDraft(String(v));
         setEditingTradeUsd(false);
         alert(`✅ Updated! New trades will invest $${v}`);
      }
   };

   return (
      <main className={`min-h-screen ${isDark ? "bg-slate-950 text-slate-100" : "bg-gray-50 text-gray-900"} font-sans transition-colors duration-300`}>
         <div className="w-full px-8 py-6 space-y-8">

            {/* HEADER */}
            <header className="flex flex-col md:flex-row md:items-center justify-between gap-6">
               <div>
                  <h1 className={`text-3xl font-extrabold tracking-tight ${isDark ? "text-white" : "text-gray-900"}`}>
                     Alpha Trader
                  </h1>
                  <p className={`text-base ${isDark ? "text-slate-400" : "text-gray-500"}`}>
                     Autonomous Trading System
                  </p>
               </div>

               <div className="flex items-center gap-4">
                  <div className={`flex items-center gap-2 px-5 py-2.5 rounded-full border shadow-sm ${autoRunning
                     ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-600 dark:text-emerald-400"
                     : "bg-red-500/10 border-red-500/20 text-red-600 dark:text-red-400"
                     }`}>
                     <div className={`w-2.5 h-2.5 rounded-full ${autoRunning ? "bg-emerald-500 animate-pulse" : "bg-red-500"}`} />
                     <span className="text-sm font-semibold">{autoRunning ? "System Active" : "System Paused"}</span>
                  </div>

                  <button
                     onClick={() => setTheme(t => (t === "dark" ? "light" : "dark"))}
                     className={`p-2.5 rounded-xl border shadow-sm hover:shadow-md transition-all ${isDark
                        ? "bg-white/5 border-white/10 hover:bg-white/10 text-yellow-300"
                        : "bg-white border-gray-200 text-gray-600 hover:text-orange-500"
                        }`}
                  >
                     {isDark ? "🌙" : "☀️"}
                  </button>
               </div>
            </header>

            {/* PORTFOLIO SUMMARY */}
            <section className={`p-8 rounded-3xl border shadow-xl ${isDark
               ? "bg-gradient-to-br from-slate-900 to-slate-800 border-white/10 shadow-black/20"
               : "bg-white border-gray-100 shadow-gray-200/50"
               }`}>
               <div className="flex flex-col md:flex-row items-end gap-2 mb-6">
                  <div>
                     <p className={`text-sm font-semibold uppercase tracking-wider mb-2 ${isDark ? "text-slate-400" : "text-gray-400"}`}>Total Portfolio Value</p>
                     <div className={`text-6xl font-bold ${isDark ? "text-white" : "text-gray-900"}`}>
                        {toUSD(stats.balance)}
                     </div>
                  </div>
               </div>

               <div className="grid grid-cols-1 md:grid-cols-3 gap-8 pt-6 border-t border-dashed border-gray-700/20 dark:border-white/10">
                  <div>
                     <span className={`block text-sm mb-1 ${isDark ? "text-slate-500" : "text-gray-500"}`}>Cash Available</span>
                     <span className="text-2xl font-semibold text-emerald-500">{toUSD(stats.free)}</span>
                  </div>
                  <div>
                     <span className={`block text-sm mb-1 ${isDark ? "text-slate-500" : "text-gray-500"}`}>Invested Amount</span>
                     <span className="text-2xl font-semibold text-blue-500">{toUSD(stats.locked)}</span>
                  </div>
                  <div>
                     <span className={`block text-sm mb-1 ${isDark ? "text-slate-500" : "text-gray-500"}`}>Total Earnings</span>
                     <span className={`text-2xl font-semibold ${stats.total_pnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                        {stats.total_pnl >= 0 ? "+" : ""}{toUSD(stats.total_pnl)}
                     </span>
                  </div>
               </div>
            </section>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

               {/* CONTROL PANEL */}
               <section className="order-2 lg:order-1 lg:col-span-1 space-y-6">
                  <div className={`p-6 rounded-3xl border shadow-lg ${isDark ? "bg-slate-900 border-white/10" : "bg-white border-gray-100"}`}>
                     <h3 className={`text-lg font-bold mb-6 flex items-center gap-2 ${isDark ? "text-white" : "text-gray-900"}`}>
                        Control Panel
                     </h3>

                     <div className="space-y-6">
                        <div>
                           <label className={`text-xs font-bold uppercase tracking-wide block mb-3 ${isDark ? "text-slate-400" : "text-gray-500"}`}>
                              Investment Per Trade
                           </label>
                           <div className="flex gap-3">
                              <div className="relative flex-1">
                                 <span className="absolute left-4 top-3 text-gray-400 font-medium">$</span>
                                 <input
                                    value={tradeUsdDraft}
                                    onFocus={() => setEditingTradeUsd(true)}
                                    onChange={e => /^\d*$/.test(e.target.value) && setTradeUsdDraft(e.target.value)}
                                    className={`w-full pl-8 pr-4 py-3 rounded-xl font-medium outline-none transition-all ${isDark
                                       ? "bg-slate-800 border-slate-700 focus:border-emerald-500 text-white"
                                       : "bg-gray-50 border-gray-200 focus:border-emerald-500 text-gray-900 focus:bg-white"
                                       } border`}
                                 />
                              </div>
                              <button onClick={updateTradeUsd} className="px-6 py-3 bg-slate-700 hover:bg-slate-600 text-white rounded-xl font-semibold shadow-lg transition-all">
                                 Save
                              </button>
                           </div>
                        </div>

                        <div className="pt-4 border-t border-dashed border-gray-700/20 dark:border-white/10 space-y-3">
                           {autoRunning ? (
                              <button onClick={killBot} className="w-full py-4 rounded-xl bg-red-500 text-white hover:bg-red-600 font-bold shadow-lg shadow-red-500/30 transition-all flex items-center justify-center gap-2">
                                 <span className="text-xl">⏸</span> Pause Trading
                              </button>
                           ) : (
                              <button onClick={resumeBot} className="w-full py-4 rounded-xl bg-emerald-500 text-white hover:bg-emerald-600 font-bold shadow-lg shadow-emerald-500/30 transition-all flex items-center justify-center gap-2">
                                 <span className="text-xl">▶</span> Start Trading
                              </button>
                           )}

                           <button
                              onClick={closeAllTrades}
                              disabled={!positions.length}
                              className={`w-full py-4 rounded-xl font-bold transition-all flex items-center justify-center gap-2 border-2 
                                ${!positions.length
                                    ? "border-gray-300 text-gray-400 bg-transparent cursor-not-allowed opacity-50 dark:border-slate-700 dark:text-slate-600"
                                    : "border-red-500 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
                                 }`}
                           >
                              🚨 Exit All Trades
                           </button>
                        </div>
                     </div>
                  </div>

                  {/* STATS */}
                  <div className={`p-6 rounded-3xl border shadow-lg ${isDark ? "bg-slate-900 border-white/10" : "bg-white border-gray-100"}`}>
                     <h3 className={`text-lg font-bold mb-4 ${isDark ? "text-white" : "text-gray-900"}`}>Performance</h3>
                     <div className="space-y-4">
                        <div className="flex justify-between items-center bg-gray-500/5 p-3 rounded-xl">
                           <span className={isDark ? "text-slate-400" : "text-gray-500"}>Win Rate</span>
                           <span className={`font-bold text-lg ${stats.win_rate >= 50 ? "text-emerald-500" : "text-orange-500"}`}>
                              {stats.win_rate?.toFixed(1)}%
                           </span>
                        </div>
                        <div className="flex justify-between items-center bg-gray-500/5 p-3 rounded-xl">
                           <span className={isDark ? "text-slate-400" : "text-gray-500"}>Total Trades</span>
                           <span className={`font-bold text-lg ${isDark ? "text-white" : "text-gray-900"}`}>
                              {stats.total_trades}
                           </span>
                        </div>
                     </div>
                  </div>
               </section>

               {/* ACTIVE TRADES */}
               <section className="order-1 lg:order-2 lg:col-span-2 space-y-6">
                  <div className="flex items-center justify-between">
                     <h2 className={`text-xl font-bold ${isDark ? "text-white" : "text-gray-900"}`}>Active Positions</h2>
                     <span className={`text-sm font-medium px-3 py-1 rounded-lg ${isDark ? "bg-slate-800 text-slate-300" : "bg-gray-200 text-gray-600"}`}>
                        {positions.length} Running
                     </span>
                  </div>

                  {positions.length === 0 && (
                     <div className={`py-16 text-center rounded-3xl border-2 border-dashed ${isDark ? "border-slate-800 text-slate-500 bg-slate-900/50" : "border-gray-200 text-gray-400 bg-gray-50"}`}>
                        <p className="text-lg font-medium">No active trades</p>
                        <p className="text-sm mt-2 opacity-70">AI is scanning the market for opportunities...</p>
                     </div>
                  )}

                  <div className="space-y-4">
                     {positions.map(p => (
                        <div key={p.id} className={`p-6 rounded-3xl border shadow-lg relative overflow-hidden transition-all ${isDark ? "bg-slate-900 border-white/5 hover:border-white/10" : "bg-white border-gray-100 hover:shadow-xl"
                           }`}>
                           {/* HEADER */}
                           <div className="flex justify-between items-start mb-6">
                              <div>
                                 <h3 className={`text-2xl font-bold ${isDark ? "text-white" : "text-gray-900"}`}>{p.symbol}</h3>
                                 <span className="text-sm text-slate-500 font-medium">
                                    Buy Price: {toPrice(p.entry_price)}
                                 </span>
                              </div>
                              <div className="text-right">
                                 <div className={`text-2xl font-bold ${p.unrealized_pnl! >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                                    {p.unrealized_pnl! >= 0 ? "+" : ""}{toUSD(p.unrealized_pnl!)}
                                 </div>
                                 <div className={`text-xs font-bold uppercase tracking-wide mt-1 ${isDark ? "text-slate-500" : "text-gray-400"}`}>
                                    Unrealized Profit
                                 </div>
                              </div>
                           </div>

                           {/* INPUTS */}
                           <div className={`grid grid-cols-2 gap-4 mb-6 p-4 rounded-2xl ${isDark ? "bg-black/20" : "bg-gray-50"}`}>
                              <div>
                                 <label className={`text-xs font-bold uppercase tracking-wider mb-2 block ${isDark ? "text-slate-500" : "text-gray-500"}`}>Safety Stop</label>
                                 <input
                                    value={slEdits[p.id] ?? p.sl ?? ""}
                                    onChange={e => setSlEdits({ ...slEdits, [p.id]: e.target.value })}
                                    className={`w-full border rounded-lg px-3 py-2 text-sm font-medium outline-none ${isDark ? "bg-slate-800 border-slate-700 text-white" : "bg-white border-gray-200 text-gray-900"
                                       }`}
                                    placeholder="0.00"
                                 />
                              </div>
                              <div>
                                 <label className={`text-xs font-bold uppercase tracking-wider mb-2 block ${isDark ? "text-slate-500" : "text-gray-500"}`}>Profit Target</label>
                                 <input
                                    value={tpEdits[p.id] ?? p.tp ?? ""}
                                    onChange={e => setTpEdits({ ...tpEdits, [p.id]: e.target.value })}
                                    className={`w-full border rounded-lg px-3 py-2 text-sm font-medium outline-none ${isDark ? "bg-slate-800 border-slate-700 text-white" : "bg-white border-gray-200 text-gray-900"
                                       }`}
                                    placeholder="∞"
                                 />
                              </div>
                           </div>

                           <div className="flex justify-between items-center pt-2">
                              <button onClick={() => UpdateSlTp(p)} className="text-sm font-bold text-emerald-500 hover:text-emerald-400 hover:underline">
                                 Save Changes
                              </button>

                              <div className="relative">
                                 <button
                                    onClick={() => setExitMenuOpen(exitMenuOpen === p.id ? null : p.id)}
                                    className="px-4 py-2 rounded-lg bg-red-500/10 text-red-500 text-sm font-bold hover:bg-red-500/20 transition-colors"
                                 >
                                    Close Trade ▾
                                 </button>
                                 {exitMenuOpen === p.id && (
                                    <div className={`absolute right-0 bottom-full mb-2 w-40 border rounded-xl shadow-xl overflow-hidden z-20 ${isDark ? "bg-slate-800 border-white/10" : "bg-white border-gray-200"
                                       }`}>
                                       {[25, 50, 100].map(pct => (
                                          <button
                                             key={pct}
                                             onClick={() => { setExitMenuOpen(null); closeTrade(p.id, pct); }}
                                             className={`block w-full text-left px-4 py-3 text-sm font-medium hover:bg-red-500 hover:text-white transition-colors ${isDark ? "text-white" : "text-gray-900"
                                                }`}
                                          >
                                             Sell {pct}%
                                          </button>
                                       ))}
                                    </div>
                                 )}
                              </div>
                           </div>
                        </div>
                     ))}
                  </div>
               </section>
            </div>

            {/* HISTORY */}
            <section>
               <h2 className={`text-xl font-bold mb-6 ${isDark ? "text-white" : "text-gray-900"}`}>Trade History</h2>
               <div className={`rounded-3xl border overflow-hidden shadow-lg ${isDark ? "bg-slate-900 border-white/5" : "bg-white border-gray-100"}`}>
                  <div className="overflow-x-auto">
                     <table className="w-full text-xs">
                        <thead className={`font-bold uppercase tracking-wider ${isDark ? "bg-white/5 text-slate-400" : "bg-gray-50 text-gray-500"}`}>
                           <tr>
                              <th className="px-4 py-3 text-left">Symbol</th>
                              <th className="px-4 py-3 text-left">Entry Time</th>
                              <th className="px-4 py-3 text-left">Exit Time</th>
                              <th className="px-4 py-3 text-right">Entry $</th>
                              <th className="px-4 py-3 text-right">Exit $</th>
                              <th className="px-4 py-3 text-right">Qty</th>
                              <th className="px-4 py-3 text-right">Fees</th>
                              <th className="px-4 py-3 text-right">PnL</th>
                              <th className="px-4 py-3 text-right">Status</th>
                           </tr>
                        </thead>
                        <tbody className={`divide-y ${isDark ? "divide-white/5" : "divide-gray-100"}`}>
                           {trades.map((t, i) => (
                              <tr key={i} className={`transition-colors ${isDark ? "hover:bg-white/5" : "hover:bg-gray-50"}`}>
                                 <td className={`px-4 py-3 font-bold ${isDark ? "text-white" : "text-gray-900"}`}>{t.symbol}</td>
                                 <td className={`px-4 py-3 ${isDark ? "text-slate-400" : "text-gray-500"}`}>{formatTime(t.time)}</td>
                                 <td className={`px-4 py-3 ${isDark ? "text-slate-400" : "text-gray-500"}`}>{t.exit_time ? formatTime(t.exit_time) : "--"}</td>
                                 <td className="px-4 py-3 text-right">{toPrice(t.entry_price)}</td>
                                 <td className="px-4 py-3 text-right">{t.exit_price ? toPrice(t.exit_price) : "--"}</td>
                                 <td className="px-4 py-3 text-right">{t.qty}</td>
                                 <td className="px-4 py-3 text-right text-red-400">-{Number(t.fees_usd || 0).toFixed(4)}</td>
                                 <td className={`px-4 py-3 text-right font-bold ${t.pnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                                    {t.pnl >= 0 ? "+" : ""}{toUSD(t.pnl)}
                                 </td>
                                 <td className="px-4 py-3 text-right">
                                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${t.status === 'closed'
                                       ? "bg-slate-500/10 text-slate-500"
                                       : "bg-emerald-500/10 text-emerald-500"
                                       }`}>
                                       {t.status.toUpperCase()}
                                    </span>
                                 </td>
                              </tr>
                           ))}
                           {trades.length === 0 && (
                              <tr>
                                 <td colSpan={10} className="px-6 py-12 text-center text-slate-400">
                                    No history yet.
                                 </td>
                              </tr>
                           )}
                        </tbody>
                     </table>
                  </div>
               </div>
            </section>

         </div>
      </main>
   );
}
