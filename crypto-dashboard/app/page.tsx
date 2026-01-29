"use client";

import Link from "next/link";
import { ArrowRight, Shield, Activity, BarChart3 } from "lucide-react";

export default function LandingPage() {
    return (
        <div className="min-h-screen bg-slate-950 text-slate-200 selection:bg-blue-500/30">
            {/* Navigation */}
            <nav className="border-b border-white/5 bg-slate-950/50 backdrop-blur-md fixed w-full z-50">
                <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
                    <div className="text-xl font-bold bg-gradient-to-r from-blue-400 to-indigo-400 bg-clip-text text-transparent">
                        AlphaTrader
                    </div>
                    <Link
                        href="/login"
                        className="px-5 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-full text-sm font-medium transition-all"
                    >
                        Login
                    </Link>
                </div>
            </nav>

            {/* Hero Section */}
            <main className="pt-32 pb-20 px-6">
                <div className="max-w-4xl mx-auto text-center">
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-semibold mb-8">
                        <span className="relative flex h-2 w-2">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                            <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
                        </span>
                        System Operational
                    </div>

                    <h1 className="text-5xl md:text-7xl font-bold tracking-tight mb-8 bg-gradient-to-b from-white to-slate-400 bg-clip-text text-transparent">
                        Autonomous <br />
                        Quantitative Trading
                    </h1>

                    <p className="text-lg text-slate-400 max-w-2xl mx-auto mb-12 leading-relaxed">
                        A high-frequency algorithmic trading system powered by SMC (Smart Money Concepts) and statistical arbitrage.
                        Secure, efficient, and fully automated.
                    </p>

                    <div className="flex justify-center gap-4">
                        <Link
                            href="/login"
                            className="group flex items-center gap-2 px-8 py-4 bg-blue-600 hover:bg-blue-500 text-white rounded-full font-semibold transition-all shadow-lg shadow-blue-900/25"
                        >
                            Access Dashboard
                            <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
                        </Link>
                    </div>
                </div>

                {/* Features Grid */}
                <div className="max-w-6xl mx-auto mt-32 grid md:grid-cols-3 gap-8">
                    <div className="p-8 rounded-2xl bg-white/5 border border-white/5 hover:bg-white/[0.07] transition-colors">
                        <div className="w-12 h-12 rounded-xl bg-blue-500/20 flex items-center justify-center text-blue-400 mb-6">
                            <Shield className="w-6 h-6" />
                        </div>
                        <h3 className="text-xl font-semibold mb-3">Enterprise Security</h3>
                        <p className="text-slate-400 leading-relaxed">
                            Protected by JWT authentication, hardware-level firewalls, and role-based access control.
                        </p>
                    </div>

                    <div className="p-8 rounded-2xl bg-white/5 border border-white/5 hover:bg-white/[0.07] transition-colors">
                        <div className="w-12 h-12 rounded-xl bg-indigo-500/20 flex items-center justify-center text-indigo-400 mb-6">
                            <Activity className="w-6 h-6" />
                        </div>
                        <h3 className="text-xl font-semibold mb-3">Real-time Execution</h3>
                        <p className="text-slate-400 leading-relaxed">
                            Sub-second trade execution on Binance Spot/Futures with optimized networking.
                        </p>
                    </div>

                    <div className="p-8 rounded-2xl bg-white/5 border border-white/5 hover:bg-white/[0.07] transition-colors">
                        <div className="w-12 h-12 rounded-xl bg-purple-500/20 flex items-center justify-center text-purple-400 mb-6">
                            <BarChart3 className="w-6 h-6" />
                        </div>
                        <h3 className="text-xl font-semibold mb-3">Quantitative Edge</h3>
                        <p className="text-slate-400 leading-relaxed">
                            Multi-factor analysis combining internal liquidity (SMC) and global market regime models.
                        </p>
                    </div>
                </div>
            </main>

            {/* Footer */}
            <footer className="border-t border-white/5 mt-20 py-12 text-center text-slate-500 text-sm">
                <p>© 2026 AlphaTrader Systems. Restricted Access.</p>
            </footer>
        </div>
    );
}
