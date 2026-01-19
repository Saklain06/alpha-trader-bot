
// Deployment Verified: 2026-01-19 (Force Sync)
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

// Helper: Fetch with timeout protection
const fetchWithTimeout = async (url: string, options: RequestInit = {}, timeout = 20000) => {
   const controller = new AbortController();
   const id = setTimeout(() => controller.abort(), timeout);
   try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      clearTimeout(id);
      return response;
   } catch (error) {
      clearTimeout(id);
      throw error;
   }
};

const InfoTooltip = ({ text }: { text: string }) => (
   <div className="group relative inline-flex ml-1.5 cursor-help transform translate-y-0.5">
      <div className="w-4 h-4 rounded-full border-1 border-current flex items-center justify-center text-xs opacity-90 hover:opacity-100 transition-opacity">?</div>
      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-48 p-2.5 bg-slate-800 text-white text-[10px] leading-tight rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-20 pointer-events-none text-center border border-white/10">
         {text}
         <div className="absolute top-full left-1/2 -translate-x-1/2 -mt-1 border-4 border-transparent border-t-slate-800"></div>
      </div>
   </div>
);

// [COMPONENT] Smart Chart (Lightweight Charts)
import { createChart, ColorType, CandlestickSeries, LineSeries } from 'lightweight-charts';

const SmartChart = ({ symbol, interval, isDark, ob, position }: { symbol: string, interval: string, isDark: boolean, ob?: any, position?: any }) => {
   const chartContainerRef = useRef<HTMLDivElement>(null);
   const chartRef = useRef<any>(null);
   const seriesRef = useRef<any>(null);
   const ema5Ref = useRef<any>(null); // [NEW] EMA 5
   const ema50Ref = useRef<any>(null);
   const rsiRef = useRef<any>(null);
   const [error, setError] = useState<string | null>(null);
   const [timeLeft, setTimeLeft] = useState<string>("--:--");

   // ... (Helper & Timer unchanged)

   // 1. Initialize Chart
   useEffect(() => {
      if (!chartContainerRef.current) return;

      const chart = createChart(chartContainerRef.current, {
         layout: {
            background: { type: ColorType.Solid, color: isDark ? '#131722' : '#ffffff' },
            textColor: isDark ? '#d1d4dc' : '#334155', // slate-700
         },
         grid: {
            vertLines: { color: isDark ? 'rgba(43, 43, 67, 0.4)' : '#e2e8f0', style: 1 }, // slate-200
            horzLines: { color: isDark ? 'rgba(43, 43, 67, 0.4)' : '#e2e8f0', style: 1 },
         },
         width: chartContainerRef.current.clientWidth,
         height: chartContainerRef.current.clientHeight,
         timeScale: {
            timeVisible: true,
            secondsVisible: false,
            rightOffset: 40,
            tickMarkFormatter: (time: number) => {
               const date = new Date(time * 1000);
               return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
            }
         }
      });

      // Symbol Watermark
      chart.applyOptions({
         watermark: {
            visible: true,
            fontSize: 72,
            horzAlign: 'center',
            vertAlign: 'center',
            color: 'rgba(255, 255, 255, 0.06)',
            text: symbol,
         },
         crosshair: {
            mode: 1, // Magnet
            vertLine: {
               width: 1,
               color: 'rgba(224, 227, 235, 0.1)',
               style: 3, // Dashed
               labelBackgroundColor: '#9B7DFF',
            },
            horzLine: {
               width: 1,
               color: 'rgba(224, 227, 235, 0.1)',
               style: 3,
               labelBackgroundColor: '#9B7DFF',
            }
         }
      } as any);

      chart.priceScale('right').applyOptions({
         scaleMargins: {
            top: 0.1,
            bottom: 0.25,
         },
      });

      const candlestickSeries = chart.addSeries(CandlestickSeries, {
         upColor: '#089981',
         downColor: '#F23645',
         borderVisible: false,
         wickUpColor: '#089981',
         wickDownColor: '#F23645'
      });

      // EMA 5 (Cyan / Fast)
      const ema5 = chart.addSeries(LineSeries, { color: '#06B6D4', lineWidth: 2, crosshairMarkerVisible: false, priceScaleId: 'right', title: 'EMA 5' });
      // EMA 50 (Blue / Slow)
      const ema50 = chart.addSeries(LineSeries, { color: '#3B82F6', lineWidth: 2, crosshairMarkerVisible: false, priceScaleId: 'right', title: 'EMA 50' });

      // RSI Series (Bottom Pane)
      const rsiSeries = chart.addSeries(LineSeries, {
         color: '#A78BFA', // Purple
         lineWidth: 1,
         priceScaleId: 'rsi',
         crosshairMarkerVisible: false
      });

      chart.priceScale('rsi').applyOptions({
         scaleMargins: {
            top: 0.75, // Bottom 25%
            bottom: 0,
         },
      });

      // RSI Levels
      rsiSeries.createPriceLine({ price: 65, color: 'rgba(16, 185, 129, 0.5)', lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '65' });
      rsiSeries.createPriceLine({ price: 40, color: 'rgba(16, 185, 129, 0.5)', lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '40' });

      chartRef.current = chart;
      seriesRef.current = candlestickSeries;
      ema5Ref.current = ema5; // [NEW]
      ema50Ref.current = ema50;
      rsiRef.current = rsiSeries;

      const handleResize = () => {
         if (chartContainerRef.current) {
            chart.applyOptions({ width: chartContainerRef.current.clientWidth });
         }
      };

      window.addEventListener('resize', handleResize);

      return () => {
         window.removeEventListener('resize', handleResize);
         chart.remove();
         chartRef.current = null;
         seriesRef.current = null;
         ema5Ref.current = null; // [NEW]
         ema50Ref.current = null;
         rsiRef.current = null;
      };
   }, [isDark, symbol]);

   // 2. Fetch Data
   useEffect(() => {
      if (!seriesRef.current) return;

      let isMounted = true;
      let isFirstLoad = true;

      const fetchHistory = async () => {
         try {
            // [PROXY FIX] Use relative path /api for data fetching (goes through Nginx)
            // If localhost, fallback to direct port 8000
            const isLocal = typeof window !== 'undefined' && window.location.hostname === 'localhost';
            const apiBase = isLocal ? 'http://localhost:8000' : '/api';

            const res = await fetch(`${apiBase}/history?symbol=${symbol}&interval=${interval}`);
            const json = await res.json();
            if (!isMounted) return;

            // Handle new response structure { candles, ema20, ema50 }
            const candles = json.candles || json;

            if (Array.isArray(candles) && candles.length > 0) {
               seriesRef.current.setData(candles);

               // Handle EMA 5 data (Backend sends 'ema5' and legacy 'ema20')
               if (ema5Ref.current) {
                  const data = json.ema5 || json.ema20;
                  if (data) ema5Ref.current.setData(data);
               }
               if (ema50Ref.current && json.ema50) ema50Ref.current.setData(json.ema50);
               if (rsiRef.current && json.rsi) rsiRef.current.setData(json.rsi);

               // Only fit content on the very first load for this symbol/interval
               if (isFirstLoad) {
                  chartRef.current?.timeScale().fitContent();
                  isFirstLoad = false;
               }
            } else {
               setError("No Data");
            }
         } catch (e) {
            if (isMounted) console.error(e);
         }
      };

      fetchHistory(); // Immediate load
      const intervalId = setInterval(fetchHistory, 5000); // Poll every 5s

      return () => {
         isMounted = false;
         clearInterval(intervalId);
      };
   }, [symbol, interval]);

   // Use JSON.stringify or specific props to avoid ref-check triggering
   const obSignature = ob ? `${ob.top}-${ob.bottom}-${ob.fvg?.top}` : 'null';

   // 3. (Optional) Any specific overlays for EMA/Price actions can go here
   // Currently, lines are drawn via refs in the init effect. 
   // This effect is kept empty or removed if no dynamic overlay needed.
   // 3. Position Overlays (SL/TP)
   useEffect(() => {
      if (!seriesRef.current || !position) return;

      const lines: any[] = [];

      // ENTRY
      if (position.entry_price) {
         lines.push(seriesRef.current.createPriceLine({
            price: position.entry_price,
            color: '#3B82F6', // Blue
            lineWidth: 1,
            lineStyle: 2, // Dashed
            axisLabelVisible: true,
            title: 'ENTRY',
         }));
      }

      // STOP LOSS
      if (position.sl) {
         lines.push(seriesRef.current.createPriceLine({
            price: position.sl,
            color: '#EF4444', // Red
            lineWidth: 1,
            lineStyle: 2, // Dashed
            axisLabelVisible: true,
            title: 'SL',
         }));
      }

      // TAKE PROFIT
      if (position.tp) {
         lines.push(seriesRef.current.createPriceLine({
            price: position.tp,
            color: '#10B981', // Green
            lineWidth: 1,
            lineStyle: 2, // Dashed
            axisLabelVisible: true,
            title: 'TP',
         }));
      }

      return () => {
         if (seriesRef.current) {
            lines.forEach((l: any) => seriesRef.current.removePriceLine(l));
         }
      };
   }, [position, symbol]);

   return (
      <div className="w-full h-full relative" ref={chartContainerRef}>






         <div className="absolute bottom-8 right-[50px] z-20 bg-[#131722]/80 backdrop-blur text-white text-[10px] font-mono tabular-nums px-1.5 py-0.5 rounded border border-white/10 shadow pointer-events-none">
            {timeLeft}
         </div>
         {error && <div className="absolute inset-0 flex items-center justify-center text-red-500 font-mono text-sm">{error}</div>}
      </div>
   );
};

export default function Dashboard() {
   // Dynamic API Host (No State Trap)
   // Dynamic API Host (Relative Path for Nginx Proxy)
   // FINAL PRODUCTION FIX: Always use relative path
   // This allows Nginx to handle the proxying (Localhost -> VPS)
   const API = "/api";

   const [stats, setStats] = useState<any>({});
   const [trades, setTrades] = useState<any[]>([]);
   const [positions, setPositions] = useState<Position[]>([]);
   const [signals, setSignals] = useState<any[]>([]);
   const [smcScanner, setSmcScanner] = useState<any[]>([]);
   const [loading, setLoading] = useState(false);
   const [backendError, setBackendError] = useState<string | null>(null);
   const [apiError, setApiError] = useState<string | null>(null);

   const [slEdits, setSlEdits] = useState<Record<string, string>>({});
   const [tpEdits, setTpEdits] = useState<Record<string, string>>({});

   // [NEW] Chart Modal State
   const [selectedCoin, setSelectedCoin] = useState<string | null>(null);
   const [chartInterval, setChartInterval] = useState<string>("15m");

   const initialized = useRef(false);
   const [lastSync, setLastSync] = useState<string>("—");


   const [theme, setTheme] = useState<"dark" | "light">("dark");

   const [tradeUsd, setTradeUsd] = useState<number>(10);
   const [tradeUsdDraft, setTradeUsdDraft] = useState<string>("10");
   const isEditingTradeUsd = useRef(false);

   const [exitMenuOpen, setExitMenuOpen] = useState<string | null>(null);

   // Pagination for trade history
   const [currentPage, setCurrentPage] = useState(1);
   const tradesPerPage = 10;

   const loadData = async () => {
      // Dynamic API URL calculation to avoid closure staleness
      try {
         const [s, t, p, cfg, sigs, smc] = await Promise.all([
            fetchWithTimeout(`${API}/stats`).then(r => r.json()),
            fetchWithTimeout(`${API}/trades`).then(r => r.json()),
            fetchWithTimeout(`${API}/positions`).then(r => r.json()),
            fetchWithTimeout(`${API}/admin/trade-usd`).then(r => r.json()),
            fetchWithTimeout(`${API}/signals`).then(r => r.json()),
            fetchWithTimeout(`${API}/smc-scanner`).then(r => r.json())
         ]);
         setStats(s);
         setTrades(t);
         setPositions(p);
         setTradeUsd(cfg.trade_usd);
         // Only overwrite the draft if the user isn't currently editing it
         // Using ref here to avoid stale closure issues in the setInterval
         if (!isEditingTradeUsd.current) {
            setTradeUsdDraft(String(cfg.trade_usd));
         }
         setSignals(Array.isArray(sigs) ? sigs : []);
         setSmcScanner(Array.isArray(smc) ? smc : []);

         setLastSync(new Date().toISOString());
         setLastSync(new Date().toISOString());
         setBackendError(null); // Clear error on ANY successful load

         if (s.api_status === "error") {
            setApiError(s.api_error || "Unknown Exchange API Error");
         } else {
            setApiError(null);
         }
      } catch (e) {
         console.error("Load failed", e);
         setBackendError("Backend Offline: Check if the trading bot is running (port 8000)");
      }
   };

   useEffect(() => {
      if (initialized.current) return;
      initialized.current = true;
      loadData();
      const i = setInterval(loadData, 5000);
      return () => clearInterval(i);
   }, []);

   const autoRunning = stats?.mode === "auto";
   const isDark = theme === "dark";

   const toUSD = (usd: number) => `$${Number(usd || 0).toFixed(2)}`;
   const toPrice = (price: number) => Number(price || 0).toFixed(5);
   const formatTime = (utcTime: string) => utcTime ? new Date(utcTime).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : "--";

   const killBot = async () => {
      if (!confirm("Pause AI Agent?")) return;
      setLoading(true);
      try {
         await fetchWithTimeout(`${API_REF.current}/admin/kill`, { method: "POST" });
         await loadData();
      } finally {
         setLoading(false);
      }
   };

   const resumeBot = async () => {
      if (!confirm("Start AI Agent?")) return;
      setLoading(true);
      try {
         await fetchWithTimeout(`${API}/admin/resume`, { method: "POST" });
         await loadData();
      } finally {
         setLoading(false);
      }
   };

   const closeAllTrades = async () => {
      if (!confirm("Emergency Exit: Sell everything now?")) return;
      setLoading(true);
      try {
         // Parallel execution for speed during emergency
         await Promise.all(
            positions.map(p =>
               fetchWithTimeout(`${API}/paper-sell?trade_id=${p.id}&sell_pct=100`, { method: "POST" })
            )
         );
         await loadData();
      } catch (error) {
         console.error("Emergency exit failed", error);
         alert("⚠️ Some exits may have failed. Check positions.");
      } finally {
         setLoading(false);
      }
   };

   const closeTrade = async (id: string, pct: number) => {
      if (loading) return;
      setLoading(true);
      try {
         await fetchWithTimeout(`${API}/paper-sell?trade_id=${id}&sell_pct=${pct}`, { method: "POST" });
         await loadData();
      } finally {
         setLoading(false);
      }
   };

   const UpdateSlTp = async (p: Position) => {
      if (loading) return;
      const sl = slEdits[p.id] ?? p.sl ?? "";
      const tp = tpEdits[p.id] ?? p.tp ?? "";
      setLoading(true);
      try {
         await fetchWithTimeout(`${API}/update-sl-tp?trade_id=${p.id}&sl=${sl || 0}&tp=${tp || 0}`, { method: "POST" });
         alert(`✅ Updated for ${p.symbol}`);
         await loadData();
      } finally {
         setLoading(false);
      }
   };

   const updateTradeUsd = async () => {
      if (loading) return;
      setLoading(true);
      try {
         const v = parseFloat(tradeUsdDraft);
         if (isNaN(v) || v < 5) {
            alert("❌ Minimum investment per trade is $5");
            return;
         }
         const r = await fetchWithTimeout(`${API}/admin/set-trade-usd?amount=${v}`, {
            method: "POST",
            headers: { "Accept": "application/json" }
         });

         if (!r.ok) throw new Error("Server rejected request");

         const d = await r.json();
         if (d.status === "ok") {
            setTradeUsd(v);
            setTradeUsdDraft(String(v));
            isEditingTradeUsd.current = false;
            // Re-fetch everything to sync
            await loadData();
         }
      } catch (err) {
         console.error("Update failed", err);
         alert("❌ Failed to update. Check server connection.");
      } finally {
         setLoading(false);
      }
   };

   return (
      <main className={`min-h-screen pb-12 ${isDark ? "bg-slate-950 text-slate-100" : "bg-slate-100 text-slate-900"} font-sans transition-colors duration-300`}>
         {/* CHART MODAL OVERLAY */}
         {selectedCoin && (
            <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-200" onClick={() => setSelectedCoin(null)}>
               <div className="relative w-full max-w-6xl h-[85vh] bg-[#131722] rounded-2xl border border-white/10 shadow-2xl overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
                  <div className="flex items-center justify-between px-4 py-2 bg-white/5 border-b border-white/5">
                     <div className="flex items-center gap-4">
                        <span className="font-bold text-sm tracking-widest">{selectedCoin} SPOT</span>
                        <div className="flex bg-black/40 rounded-lg p-0.5">
                           {["5m", "15m", "1h", "4h"].map(int => (
                              <button
                                 key={int}
                                 onClick={() => setChartInterval(int)}
                                 className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${chartInterval === int ? "bg-emerald-500 text-white shadow-lg" : "text-slate-400 hover:text-white hover:bg-white/5"}`}
                              >
                                 {int.toUpperCase()}
                              </button>
                           ))}
                        </div>
                     </div>

                     <div className="flex items-center gap-4">
                        {smcScanner.find(s => s.symbol === selectedCoin) && (
                           <span className="text-xs bg-emerald-500/20 text-emerald-500 px-2 py-1 rounded border border-emerald-500/20">
                              OB: {smcScanner.find(s => s.symbol === selectedCoin).top} - {smcScanner.find(s => s.symbol === selectedCoin).bottom}
                           </span>
                        )}
                        <button
                           onClick={() => setSelectedCoin(null)}
                           className="w-8 h-8 flex items-center justify-center bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors"
                        >
                           ✕
                        </button>
                     </div>
                  </div>
                  <div className="flex-1 relative">
                     <SmartChart
                        symbol={selectedCoin}
                        interval={chartInterval}
                        isDark={true}
                        ob={smcScanner.find(s => s.symbol === selectedCoin)}
                        position={positions.find(p => p.symbol === selectedCoin)}
                     />
                  </div>
               </div>
            </div>
         )}

         <div className="w-full px-8 py-6 space-y-8">

            {/* HEADER */}
            <header className="flex flex-col md:flex-row md:items-center justify-between gap-6">
               <div>
                  <h1 className={`text-3xl font-extrabold tracking-tight ${isDark ? "text-white" : "text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 to-violet-600"} drop-shadow-sm`}>Alpha Trader</h1>
                  <p className={`text-base font-medium ${isDark ? "text-slate-400" : "text-slate-500"}`}>Autonomous Trading System</p>
               </div>
               {backendError && (
                  <div className="bg-red-500/10 border border-red-500/20 text-red-500 px-4 py-2 rounded-xl flex items-center gap-2 animate-pulse">
                     <span className="text-xl">⚠️</span>
                     <span className="text-sm font-bold">{backendError}</span>
                  </div>
               )}
               {apiError && (
                  <div className="bg-orange-500/10 border border-orange-500/20 text-orange-500 px-4 py-2 rounded-xl flex items-center gap-2 animate-pulse">
                     <span className="text-xl">⚠️</span>
                     <span className="text-sm font-bold">Exchange Error: {apiError}</span>
                  </div>
               )}
               <div className="flex items-center gap-4">
                  <div className={`flex items-center gap-2 px-5 py-2.5 rounded-full border shadow-sm ${autoRunning ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-600 dark:text-emerald-400" : "bg-red-500/10 border-red-500/20 text-red-600 dark:text-red-400"}`}>
                     <div className={`w-2.5 h-2.5 rounded-full ${autoRunning ? "bg-emerald-500 animate-pulse" : "bg-red-500"}`} />
                     <span className="text-sm font-semibold">{autoRunning ? "System Active" : "System Paused"}</span>
                  </div>
                  <button onClick={() => setTheme(t => (t === "dark" ? "light" : "dark"))} className={`p-2.5 rounded-xl border shadow-md transition-all ${isDark ? "bg-white/5 border-white/10 hover:bg-white/10 text-yellow-300" : "bg-white border-slate-200 text-indigo-600 hover:text-indigo-800 hover:shadow-lg hover:-translate-y-0.5"}`}>
                     {isDark ? "🌙" : "☀️"}
                  </button>
               </div>
            </header>

            {/* PORTFOLIO SUMMARY */}
            <section className={`p-8 rounded-3xl border shadow-xl backdrop-blur-sm ${isDark ? "bg-gradient-to-br from-slate-900 to-slate-800 border-white/10" : "bg-white border-slate-200 shadow-slate-200/50"}`}>
               <div className="flex flex-col md:flex-row items-end gap-2 mb-6">
                  <div>
                     <p className={`text-sm font-semibold uppercase tracking-wider mb-2 ${isDark ? "text-slate-400" : "text-slate-400"}`}>Total Portfolio Value (Live)</p>
                     <div className={`text-6xl font-bold ${isDark ? "text-white" : "text-slate-900"}`}>{toUSD(stats.balance)}</div>
                  </div>
                  <div className="mb-2 text-xs font-mono text-slate-500 bg-white/5 px-2 py-1 rounded">
                     Synced: {new Date(lastSync).toLocaleTimeString()} IST
                  </div>
               </div>
               <div className="grid grid-cols-2 md:grid-cols-4 gap-6 pt-6 border-t border-dashed border-white/10">
                  <div>
                     <span className="block text-sm mb-1 opacity-50 flex items-center">
                        Cash Available
                        <InfoTooltip text="Unused USDT in your wallet ready for new trades." />
                     </span>
                     <span className="text-2xl font-semibold text-emerald-500">{toUSD(stats.free)}</span>
                  </div>
                  <div>
                     <span className="block text-sm mb-1 opacity-50 flex items-center">
                        Invested Amount
                        <InfoTooltip text="Total value of assets currently held in active trades." />
                     </span>
                     <span className="text-2xl font-semibold text-blue-500">{toUSD(stats.locked)}</span>
                  </div>
                  <div>
                     <span className="block text-sm mb-1 opacity-50 flex items-center">
                        Net Earnings
                        <InfoTooltip text="Realized Profit/Loss from all closed trades (Banked)." />
                     </span>
                     <span className={`text-2xl font-semibold ${stats.realized_pnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                        {stats.realized_pnl >= 0 ? "+" : ""}{toUSD(stats.realized_pnl)}
                     </span>
                  </div>
                  <div>
                     <span className="block text-sm mb-1 opacity-50 flex items-center">
                        Current PnL
                        <InfoTooltip text="Unrealized Profit/Loss from currently open positions (Floating)." />
                     </span>
                     <span className={`text-2xl font-semibold ${stats.unrealized_pnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                        {stats.unrealized_pnl >= 0 ? "+" : ""}{toUSD(stats.unrealized_pnl)}
                     </span>
                  </div>
               </div>
            </section>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
               {/* SIDEBAR */}
               <div className="lg:col-span-1 space-y-6">
                  {/* CONTROL PANEL */}
                  <section className={`p-6 rounded-3xl border shadow-xl ${isDark ? "bg-slate-900 border-white/10" : "bg-white border-slate-200 shadow-slate-200/60"}`}>
                     <h3 className="text-lg font-bold mb-6">Control Panel</h3>
                     <div className="space-y-6">
                        <div>
                           <label className="text-xs font-bold uppercase tracking-wide block mb-3 opacity-50">Max Position Size (Safety Cap)</label>
                           <div className="flex gap-3">
                              <div className="relative flex-1">
                                 <span className="absolute left-4 top-3 text-slate-400">$</span>
                                 <input
                                    value={tradeUsdDraft}
                                    onFocus={() => { isEditingTradeUsd.current = true; }}
                                    onBlur={() => {
                                       // Small timeout to allow the "Save" button click to register first
                                       setTimeout(() => { isEditingTradeUsd.current = false; }, 200);
                                    }}
                                    onChange={e => /^\d*\.?\d*$/.test(e.target.value) && setTradeUsdDraft(e.target.value)}
                                    className={`w-full pl-8 pr-4 py-3 rounded-xl font-medium outline-none border ${isDark ? "bg-slate-800 border-slate-700 text-white" : "bg-slate-50 border-slate-200 text-slate-900 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"}`}
                                 />
                              </div>
                              <button
                                 onClick={updateTradeUsd}
                                 disabled={loading}
                                 className={`px-6 py-3 rounded-xl font-semibold ${loading
                                    ? "bg-gray-600 cursor-not-allowed opacity-50"
                                    : "bg-slate-700 hover:bg-slate-600 text-white"
                                    }`}
                              >
                                 Save
                              </button>
                           </div>
                        </div>
                        <div className="pt-4 border-t border-dashed border-white/10 space-y-3">
                           <button
                              onClick={autoRunning ? killBot : resumeBot}
                              disabled={loading}
                              className={`w-full py-4 rounded-xl font-bold shadow-lg transition-all ${loading
                                 ? "bg-gray-600 cursor-not-allowed opacity-50"
                                 : autoRunning
                                    ? "bg-red-500 hover:bg-red-600 shadow-red-500/20"
                                    : "bg-emerald-500 hover:bg-emerald-600 shadow-emerald-500/20"
                                 }`}
                           >
                              {autoRunning ? "⏸ Pause Trading" : "▶ Start Trading"}
                           </button>
                           <button
                              onClick={closeAllTrades}
                              disabled={!positions.length || loading}
                              className={`w-full py-4 rounded-xl font-bold border-2 transition-all ${!positions.length || loading
                                 ? "border-slate-700 text-slate-600 opacity-50 cursor-not-allowed"
                                 : "border-red-500 text-red-500 hover:bg-red-500/5"
                                 }`}
                           >
                              🚨 Exit All Trades
                           </button>
                        </div>
                     </div>
                  </section>

                  {/* PERFORMANCE */}
                  <section className={`p-6 rounded-3xl border shadow-xl ${isDark ? "bg-slate-900 border-white/10" : "bg-white border-slate-200 shadow-slate-200/60"}`}>
                     <h3 className="text-lg font-bold mb-4">Performance</h3>
                     <div className="space-y-4">
                        <div className={`flex justify-between items-center bg-white/5 p-3 rounded-xl ${!isDark && "bg-slate-50 border border-slate-100"}`}>
                           <span className="opacity-50">Win Rate</span>
                           <span className={`font-bold text-lg ${stats.win_rate >= 50 ? "text-emerald-500" : "text-orange-500"}`}>{stats.win_rate?.toFixed(1)}%</span>
                        </div>
                        <div className={`flex justify-between items-center bg-white/5 p-3 rounded-xl ${!isDark && "bg-slate-50 border border-slate-100"}`}>
                           <span className="opacity-50">Total Trades</span>
                           <span className="font-bold text-lg">{stats.total_trades}</span>
                        </div>
                     </div>
                  </section>

                  {/* MARKET TREND & SMC SCANNER */}
                  <section className={`p-6 rounded-3xl border shadow-xl ${isDark ? "bg-slate-900 border-white/10" : "bg-white border-slate-200 shadow-slate-200/60"}`}>
                     <div className="flex items-center justify-between mb-4">
                        <h3
                           className="text-lg font-bold cursor-pointer hover:underline decoration-dashed flex items-center gap-2 group"
                           onClick={() => setSelectedCoin("BTC/USDT")}
                        >
                           Market Trend <span className="text-sm opacity-50 group-hover:opacity-100 transition-opacity">↗</span>
                        </h3>
                        <div className={`px-3 py-1 rounded-full text-xs font-bold border ${stats.market_trend_label === 'Bullish' ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-500" :
                           stats.market_trend_label === 'Bearish' ? "bg-red-500/10 border-red-500/20 text-red-500" :
                              "bg-yellow-500/10 border-yellow-500/20 text-yellow-500"
                           }`}>
                           {stats.market_trend_label?.toUpperCase() || "NEUTRAL"} ({stats.market_trend_score ?? 50}%)
                        </div>
                     </div>

                     {/* Trend Bar or Circuit Breaker */}
                     {stats.circuit_breaker_triggered ? (
                        <div className="w-full mb-6 p-4 rounded-xl bg-red-500/10 border border-red-500/20 flex flex-col items-center justify-center text-center animate-pulse">
                           <span className="text-red-500 font-bold text-sm mb-1">🛑 Circuit Breaker Active</span>
                           <span className="text-xs opacity-70">Max Daily Losses Hit. Scanning Paused.</span>
                           <div className="mt-3 font-mono text-xl font-bold">
                              Resets in: {(() => {
                                 const now = Date.now();
                                 const diff = (stats.reset_time_ts || 0) - now;
                                 if (diff <= 0) return "00h 00m";
                                 const h = Math.floor(diff / (1000 * 60 * 60));
                                 const m = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
                                 return `${h}h ${m}m`;
                              })()}
                           </div>
                        </div>
                     ) : (
                        <div className={`w-full h-2 rounded-full overflow-hidden mb-6 ${isDark ? "bg-white/5" : "bg-slate-100 border border-slate-200"}`}>
                           <div
                              className={`h-full transition-all duration-1000 ${stats.market_trend_label === 'Bullish' ? "bg-emerald-500" :
                                 stats.market_trend_label === 'Bearish' ? "bg-red-500" :
                                    "bg-yellow-500"
                                 }`}
                              style={{ width: `${stats.market_trend_score ?? 50}%` }}
                           />
                        </div>
                     )}

                     {/* Scanner Header */}
                     <div className="flex items-center justify-between mb-2">
                        <div>
                           <h3 className="text-lg font-bold mb-2">Growth Strategy Scanner (15m-EMA)</h3>
                           <p className="text-[10px] opacity-50 mb-4">Top Assets &gt; BTC Strength (15m)</p>
                        </div>
                        <div className="flex gap-2"></div>
                     </div>
                     <div className="overflow-x-auto">
                        <table className="w-full text-[10px]">
                           <thead className="font-bold uppercase tracking-wider opacity-50">
                              <tr>
                                 <th className="px-1 py-2 text-left">Coin</th>
                                 <th className="px-1 py-2 text-right">Price</th>
                                 <th className="px-1 py-2 text-right">EMA 20</th>
                                 <th className="px-1 py-2 text-right">EMA 50</th>
                                 <th className="px-1 py-2 text-right">RSI</th>
                              </tr>
                           </thead>
                           <tbody className="divide-y divide-white/5">
                              {smcScanner.length === 0 && (
                                 <tr><td colSpan={5} className="py-4 text-center opacity-30 italic">No Setups Detected</td></tr>
                              )}
                              {smcScanner.map((s, i) => (
                                 <tr key={i} className={`transition-colors cursor-pointer ${isDark ? "hover:bg-white/5" : "hover:bg-slate-50 border-b border-slate-50"}`} onClick={() => setSelectedCoin(s.symbol)}>
                                    <td className="px-1 py-2 font-bold truncate max-w-[60px]">{s.symbol.split('/')[0]}</td>
                                    <td className="px-1 py-2 text-right font-mono">{Number(s.price).toFixed(4)}</td>
                                    <td className="px-1 py-2 text-right font-mono text-yellow-500">{Number(s.ema20).toFixed(4)}</td>
                                    <td className="px-1 py-2 text-right font-mono text-blue-500">{Number(s.ema50).toFixed(4)}</td>
                                    <td className={`px-1 py-2 text-right font-mono font-bold ${s.rsi >= 40 && s.rsi <= 65 ? "text-emerald-500" : "opacity-30"}`}>
                                       {s.rsi ? Number(s.rsi).toFixed(1) : "--"}
                                    </td>
                                 </tr>
                              ))}
                           </tbody>
                        </table>
                     </div>
                  </section>
               </div>

               {/* MAIN AREA: ACTIVE POSITIONS */}
               <div className="lg:col-span-2 space-y-6">
                  <div className="flex items-center justify-between">
                     <h2 className="text-xl font-bold">Active Positions</h2>
                     <span className={`text-sm font-bold px-3 py-1 rounded-lg ${isDark ? "bg-white/5" : "bg-white border border-slate-200 text-indigo-600 shadow-sm"}`}>{positions.length} Running</span>
                  </div>

                  {positions.length === 0 && (
                     <div className="py-20 text-center rounded-3xl border-2 border-dashed border-white/10 opacity-50">
                        <p className="text-lg font-medium">No active trades</p>
                        <p className="text-sm mt-2">AI is scanning the market for opportunities...</p>
                     </div>
                  )}

                  <div className="space-y-4">
                     {positions.map(p => (
                        <div key={p.id} className={`p-6 rounded-3xl border shadow-xl transition-all ${isDark ? "bg-slate-900 border-white/5 hover:border-white/10" : "bg-white border-slate-200 shadow-slate-200/60 hover:shadow-2xl hover:border-indigo-100"}`}>
                           <div className="flex justify-between items-start mb-6">
                              <div>
                                 <h3
                                    className="text-2xl font-bold cursor-pointer hover:underline decoration-dashed"
                                    onClick={() => setSelectedCoin(p.symbol)}
                                 >
                                    {p.symbol} ↗
                                 </h3>
                                 <div className="flex items-center gap-3 mt-1 opacity-50 text-sm">
                                    <span>Entry: {toPrice(p.entry_price)}</span>
                                    <span>|</span>
                                    <span>Invested: <span className={isDark ? "text-white" : "text-slate-900"}>{toUSD(p.used_usd || 0)}</span></span>
                                 </div>
                              </div>
                              <div className="text-right">
                                 <div className={`text-2xl font-bold ${p.unrealized_pnl! >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                                    {p.unrealized_pnl! >= 0 ? "+" : ""}{toUSD(p.unrealized_pnl!)}
                                 </div>
                                 <div className="text-xs font-bold uppercase tracking-wide mt-1 opacity-50">Profit</div>
                              </div>
                           </div>
                           <div className="grid grid-cols-2 gap-4 mb-6">
                              <div>
                                 <label className="text-xs font-bold uppercase tracking-wider mb-2 block opacity-50">Stop Loss</label>
                                 <input
                                    value={slEdits[p.id] ?? p.sl ?? ""}
                                    onChange={e => /^\d*\.?\d*$/.test(e.target.value) && setSlEdits({ ...slEdits, [p.id]: e.target.value })}
                                    className={`w-full border rounded-lg px-3 py-2 text-sm outline-none ${isDark ? "bg-slate-800 border-slate-700" : "bg-slate-50 border-slate-200 focus:border-indigo-500"}`}
                                 />
                              </div>
                              <div>
                                 <label className="text-xs font-bold uppercase tracking-wider mb-2 block opacity-50">Profit Target</label>
                                 <input
                                    value={tpEdits[p.id] ?? p.tp ?? ""}
                                    onChange={e => /^\d*\.?\d*$/.test(e.target.value) && setTpEdits({ ...tpEdits, [p.id]: e.target.value })}
                                    className={`w-full border rounded-lg px-3 py-2 text-sm outline-none ${isDark ? "bg-slate-800 border-slate-700" : "bg-slate-50 border-slate-200 focus:border-indigo-500"}`}
                                 />
                              </div>
                           </div>
                           <div className="flex justify-between items-center">
                              <button
                                 onClick={() => UpdateSlTp(p)}
                                 disabled={loading}
                                 className={`text-sm font-bold ${loading ? "text-slate-500 cursor-not-allowed" : "text-emerald-500 hover:underline"}`}
                              >
                                 Save Changes
                              </button>
                              <div className="relative">
                                 <button onClick={() => setExitMenuOpen(exitMenuOpen === p.id ? null : p.id)} className="px-4 py-2 rounded-lg bg-red-500/10 text-red-500 text-sm font-bold hover:bg-red-500/20">Close Trade ▾</button>
                                 {exitMenuOpen === p.id && (
                                    <div className={`absolute right-0 bottom-full mb-2 w-40 border rounded-xl shadow-xl overflow-hidden z-20 ${isDark ? "bg-slate-800 border-white/10" : "bg-white border-slate-200"}`}>
                                       {[25, 50, 100].map(pct => (
                                          <button key={pct} onClick={() => { setExitMenuOpen(null); closeTrade(p.id, pct); }} className="block w-full text-left px-4 py-3 text-sm font-medium hover:bg-red-500 hover:text-white transition-colors">Sell {pct}%</button>
                                       ))}
                                    </div>
                                 )}
                              </div>
                           </div>
                        </div>
                     ))}
                  </div>
               </div>
            </div>

            {/* FULL WIDTH: HISTORY */}
            <section className="mt-12">
               <div className="flex items-center justify-between mb-6">
                  <h2 className="text-xl font-bold">Trade History</h2>
                  <div className="flex items-center gap-4">
                     <span className="text-sm opacity-50">
                        Page {currentPage} of {Math.ceil(trades.length / tradesPerPage) || 1}
                     </span>
                     <div className="flex gap-2">
                        <button
                           onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                           disabled={currentPage === 1}
                           className={`px-3 py-1 rounded-lg text-sm font-medium ${currentPage === 1
                              ? "bg-slate-800 text-slate-600 cursor-not-allowed"
                              : "bg-slate-700 hover:bg-slate-600 text-white"
                              }`}
                        >
                           ← Prev
                        </button>
                        <button
                           onClick={() => setCurrentPage(p => Math.min(Math.ceil(trades.length / tradesPerPage), p + 1))}
                           disabled={currentPage >= Math.ceil(trades.length / tradesPerPage)}
                           className={`px-3 py-1 rounded-lg text-sm font-medium ${currentPage >= Math.ceil(trades.length / tradesPerPage)
                              ? "bg-slate-800 text-slate-600 cursor-not-allowed"
                              : "bg-slate-700 hover:bg-slate-600 text-white"
                              }`}
                        >
                           Next →
                        </button>
                     </div>
                  </div>
               </div>
               <div className={`rounded-3xl border overflow-hidden shadow-xl ${isDark ? "bg-slate-900 border-white/5" : "bg-white border-slate-200 shadow-slate-200/60"}`}>
                  <div className="overflow-x-auto">
                     <table className="w-full text-xs">
                        <thead className="font-bold uppercase tracking-wider bg-white/5 opacity-50">
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
                        <tbody className="divide-y divide-white/5">
                           {trades
                              .slice((currentPage - 1) * tradesPerPage, currentPage * tradesPerPage)
                              .map((t, i) => (
                                 <tr key={i} className={`transition-colors ${isDark ? "hover:bg-white/5" : "hover:bg-slate-50 border-b border-slate-50"}`}>
                                    <td className="px-4 py-3 font-bold">
                                       <button
                                          onClick={() => { setSelectedCoin(t.symbol); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
                                          className="hover:text-blue-500 hover:underline text-left"
                                       >
                                          {t.symbol}
                                       </button>
                                    </td>
                                    <td className="px-4 py-3 whitespace-nowrap">{formatTime(t.time)}</td>
                                    <td className="px-4 py-3 whitespace-nowrap">{t.exit_time ? formatTime(t.exit_time) : "--"}</td>
                                    <td className="px-4 py-3 text-right">{toPrice(t.entry_price)}</td>
                                    <td className="px-4 py-3 text-right">{t.exit_price ? toPrice(t.exit_price) : "--"}</td>
                                    <td className="px-4 py-3 text-right">
                                       {t.status === 'closed' && (!t.qty || t.qty === 0)
                                          ? Number((t.used_usd || 0) / (t.entry_price || 1)).toFixed(4)
                                          : t.qty}
                                    </td>
                                    <td className="px-4 py-3 text-right text-red-400">-{Number(t.fees_usd || 0).toFixed(4)}</td>
                                    <td className={`px-4 py-3 text-right font-bold ${t.pnl >= 0 ? "text-emerald-500" : "text-red-500"}`}>
                                       {t.pnl >= 0 ? "+" : ""}{toUSD(t.pnl)}
                                    </td>
                                    <td className="px-4 py-3 text-right">
                                       <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${t.status === 'closed' ? "bg-white/10 text-slate-500" : "bg-emerald-500/10 text-emerald-500"}`}>
                                          {t.status.toUpperCase()}
                                       </span>
                                    </td>
                                 </tr>
                              ))}
                        </tbody>
                     </table>
                  </div>
               </div>
            </section>
         </div>
      </main>
   );
}
