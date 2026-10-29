import os
import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional
import pandas as pd
import numpy as np

logger = logging.getLogger("TradingBot")


class AgentGate:
    """
    TauricResearch/TradingAgents-inspired Multi-Agent Pre-Trade Gate & Post-Trade Reflector
    adapted for low-latency Crypto execution.

    Pipeline Phases:
      1. Analyst Team (HTF 1H Structure, LTF Microstructure, Volatility/Fee-Drag Analyst)
      2. Dialectical Debate (Bullish Researcher vs. Bearish Researcher)
      3. Risk Oversight (Conservative / Aggressive / Neutral Risk Judge)
      4. Optional LLM Deep-Think Synthesis (if GEMINI_API_KEY or OPENAI_API_KEY is set)
      5. Post-Trade Reflector (Episodic memory stored in SQLite to prevent repeat mistakes)
    """

    @staticmethod
    def _analyze_1h_structure(ohlcv_1h: Optional[List[ list ]]) -> Dict[str, Any]:
        if not ohlcv_1h or len(ohlcv_1h) < 50:
            return {"valid": False, "reason": "Insufficient 1H data"}

        df = pd.DataFrame(ohlcv_1h, columns=["ts", "open", "high", "low", "close", "vol"])
        df["close"] = df["close"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["vol"] = df["vol"].astype(float)

        ema20 = df["close"].ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = df["close"].ewm(span=50, adjust=False).mean().iloc[-1]

        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, 0.0001)
        rsi_1h = float((100 - (100 / (1 + rs))).iloc[-1])

        close_now = float(df["close"].iloc[-1])
        recent_high_24h = float(df["high"].iloc[-24:].max())
        recent_low_24h = float(df["low"].iloc[-24:].min())
        dist_to_res_pct = ((recent_high_24h - close_now) / close_now) * 100 if close_now > 0 else 0.0

        return {
            "valid": True,
            "close": close_now,
            "ema20": float(ema20),
            "ema50": float(ema50),
            "rsi_1h": rsi_1h,
            "htf_uptrend": close_now >= ema50 and ema20 >= ema50 * 0.995,
            "recent_high_24h": recent_high_24h,
            "recent_low_24h": recent_low_24h,
            "dist_to_res_pct": dist_to_res_pct,
        }

    @staticmethod
    def _bull_researcher(
        symbol: str,
        trigger_type: str,
        htf: Dict[str, Any],
        ltf_df: pd.DataFrame,
        rr_ratio: float,
        recent_reflections: List[Dict[str, Any]],
    ) -> Tuple[int, List[str]]:
        """Bullish Researcher: builds the case for taking the long setup."""
        score = 50
        arguments = []

        if htf.get("valid"):
            if htf["htf_uptrend"]:
                score += 18
                arguments.append(
                    f"1H structure aligned bullish (Close {htf['close']:.4g} > EMA50 {htf['ema50']:.4g})"
                )
            if 45 <= htf["rsi_1h"] <= 68:
                score += 10
                arguments.append(f"1H RSI ({htf['rsi_1h']:.1f}) has room for continuation")
            if htf["dist_to_res_pct"] >= 1.5:
                score += 10
                arguments.append(f"Clear runway to 24h high (+{htf['dist_to_res_pct']:.2f}% overhead room)")

        if len(ltf_df) >= 20:
            last_row = ltf_df.iloc[-2]
            avg_vol = ltf_df["vol"].rolling(20).mean().iloc[-2]
            if avg_vol > 0 and last_row["vol"] >= avg_vol * 1.25:
                score += 12
                arguments.append(f"Strong institutional volume surge ({last_row['vol'] / avg_vol:.2f}x 20-bar avg)")

        if rr_ratio >= 1.9:
            score += 12
            arguments.append(f"Fibonacci 0.146->0.438 Asymmetric Risk:Reward ({rr_ratio:.2f}R) crushes 0.2% fee drag")

        wins = [r for r in recent_reflections if r.get("outcome") == "WIN"]
        if len(wins) >= 2:
            score += 8
            arguments.append(f"Reflector memory shows {len(wins)} recent winning trades on {symbol}")

        return min(score, 100), arguments

    @staticmethod
    def _bear_researcher(
        symbol: str,
        trigger_type: str,
        htf: Dict[str, Any],
        ltf_df: pd.DataFrame,
        tp_pct: float,
        sl_pct: float,
        recent_reflections: List[Dict[str, Any]],
    ) -> Tuple[int, List[str]]:
        """Bearish Researcher: stress-tests the setup for fakeouts, exhaustion, and past losses."""
        risk_score = 25
        warnings = []

        if htf.get("valid"):
            if not htf["htf_uptrend"] and trigger_type == "VWAP_Momentum_Breakout":
                risk_score += 25
                warnings.append(
                    f"Counter-trend breakout: 1H Close ({htf['close']:.4g}) is below 1H EMA50 ({htf['ema50']:.4g})"
                )
            if htf["rsi_1h"] > 74:
                risk_score += 22
                warnings.append(f"1H RSI severely overbought ({htf['rsi_1h']:.1f} > 74) — exhaustion risk")
            if htf["dist_to_res_pct"] < 0.45 and trigger_type == "VWAP_Momentum_Breakout":
                risk_score += 18
                warnings.append(
                    f"Buying directly into 24h resistance ceiling (only {htf['dist_to_res_pct']:.2f}% room)"
                )

        if len(ltf_df) >= 10:
            recent = ltf_df.iloc[-5:-1]
            # Check for repeated upper wicks (distribution)
            ranges = (recent["high"] - recent["low"]).replace(0, 1e-9)
            upper_wicks = (recent["high"] - recent[["open", "close"]].max(axis=1)) / ranges
            if float(upper_wicks.mean()) > 0.45:
                risk_score += 15
                warnings.append("Heavy upper-wick selling pressure on preceding LTF candles")

        # Fee-drag check: round-trip fee is ~0.20%, require TP >= 1.2%
        if tp_pct < 1.2:
            risk_score += 25
            warnings.append(f"Target profit ({tp_pct:.2f}%) too tight relative to 0.20% exchange fees")

        if sl_pct < 0.25:
            risk_score += 20
            warnings.append(f"Stop-loss ({sl_pct:.2f}%) inside normal LTF noise — high stop-hunt probability")

        # Episodic Memory Check (Reflector)
        recent_losses = [r for r in recent_reflections[:3] if r.get("outcome") == "LOSS"]
        if len(recent_losses) >= 2:
            risk_score += 25
            last_lesson = recent_losses[0].get("lesson", "Repeated stop-outs")
            warnings.append(
                f"Reflector Memory Warning: {len(recent_losses)} of last {min(3, len(recent_reflections))} trades on {symbol} lost ({last_lesson})"
            )

        return min(risk_score, 100), warnings

    @staticmethod
    def _optional_llm_judge(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        If GEMINI_API_KEY is present in environment, performs a fast Gemini Flash
        Risk Judge synthesis; otherwise returns None for zero-latency deterministic execution.
        """
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            return None

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
            prompt = (
                "You are the Portfolio & Risk Judge in a crypto trading firm. "
                "Review the Bullish vs Bearish Researcher debate and return ONLY valid JSON "
                'with keys: {"approved": bool, "verdict": "short 1-sentence reason"}.\n\n'
                f"Context: {json.dumps(payload)}"
            )
            req_body = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 120}
            }).encode("utf-8")

            req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                return json.loads(text)
        except Exception as e:
            logger.debug(f"[AGENT GATE] LLM judge fallback to quant judge: {e}")
            return None

    @classmethod
    async def evaluate_signal(
        cls,
        symbol: str,
        diagnostic: Dict[str, Any],
        ohlcv_entry: List[list],
        context: Optional[Dict[str, Any]],
        db,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Runs the Bull vs. Bear Debate + Risk Judge before allowing execute_buy().
        Returns (approved: bool, debate_record: dict).
        """
        trigger_type = diagnostic.get("trigger", "SMC")
        ltf_df = pd.DataFrame(ohlcv_entry, columns=["ts", "open", "high", "low", "close", "vol"])
        for col in ["open", "high", "low", "close", "vol"]:
            ltf_df[col] = ltf_df[col].astype(float)

        entry_price = float(diagnostic.get("entry_price") or ltf_df["close"].iloc[-1])
        sl_price = float(diagnostic.get("sl") or (entry_price * 0.98))
        tp_price = float(diagnostic.get("tp") or (entry_price * 1.025))

        sl_pct = max(((entry_price - sl_price) / entry_price) * 100, 0.01) if entry_price > 0 else 1.0
        tp_pct = max(((tp_price - entry_price) / entry_price) * 100, 0.01) if entry_price > 0 else 2.5
        rr_ratio = tp_pct / sl_pct if sl_pct > 0 else 0.0

        ohlcv_1h = (context or {}).get("ohlcv_1h")
        htf = cls._analyze_1h_structure(ohlcv_1h)

        # Fetch episodic memory from DB
        recent_reflections = await db.get_reflections_for_symbol(symbol, limit=5)

        bull_score, bull_args = cls._bull_researcher(
            symbol, trigger_type, htf, ltf_df, rr_ratio, recent_reflections
        )
        bear_score, bear_warnings = cls._bear_researcher(
            symbol, trigger_type, htf, ltf_df, tp_pct, sl_pct, recent_reflections
        )

        # Risk Judge synthesis
        net_edge = bull_score - bear_score
        approved = (bull_score >= 55) and (bear_score <= 65) and (net_edge >= -5)

        if approved:
            verdict = (
                f"APPROVED (Bull {bull_score} vs Bear {bear_score}): "
                + (bull_args[0] if bull_args else "Setup confirmed")
            )
        else:
            top_warning = bear_warnings[0] if bear_warnings else "Insufficient bullish conviction"
            verdict = f"VETOED (Bull {bull_score} vs Bear {bear_score}): {top_warning}"

        # Optional LLM judge override if configured
        llm_res = cls._optional_llm_judge({
            "symbol": symbol,
            "trigger": trigger_type,
            "rr_ratio": round(rr_ratio, 2),
            "bull_score": bull_score,
            "bull_arguments": bull_args,
            "bear_score": bear_score,
            "bear_warnings": bear_warnings,
        })
        if llm_res and "approved" in llm_res:
            approved = bool(llm_res["approved"])
            verdict = f"[LLM Judge] {llm_res.get('verdict', verdict)}"

        debate_record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "strategy": f"SMC_{trigger_type}",
            "approved": 1 if approved else 0,
            "bull_score": bull_score,
            "bear_score": bear_score,
            "bull_thesis": " | ".join(bull_args) if bull_args else "Standard technical entry",
            "bear_thesis": " | ".join(bear_warnings) if bear_warnings else "No major structural warnings",
            "verdict": verdict,
        }

        await db.add_agent_debate(debate_record)
        return approved, debate_record

    @classmethod
    async def reflect_on_closed_trade(
        cls,
        trade: Dict[str, Any],
        exit_price: float,
        realized_pnl: float,
        exit_reason: str,
        db,
    ) -> Dict[str, Any]:
        """
        Post-Trade Reflector: analyzes closed trade outcome and writes a lesson
        into SQLite episodic memory so future Bear Researcher debates can cite it.
        """
        symbol = trade.get("symbol", "UNKNOWN")
        strategy = trade.get("strategy", "UNKNOWN")
        entry_price = float(trade.get("entry_price") or 0.0)
        used_usd = float(trade.get("used_usd") or 0.0)

        pct_move = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0
        outcome = "WIN" if realized_pnl > 0 else "LOSS"

        hold_mins = 0.0
        try:
            start_dt = datetime.fromisoformat(str(trade.get("time", "")).replace("Z", "+00:00"))
            hold_mins = (datetime.now(timezone.utc) - start_dt).total_seconds() / 60.0
        except Exception:
            pass

        if outcome == "WIN":
            lesson = (
                f"Setup {strategy} succeeded (+{pct_move:.2f}%, +${realized_pnl:.2f} net) "
                f"via {exit_reason} in {hold_mins:.0f}m."
            )
        else:
            if hold_mins < 15:
                lesson = (
                    f"Rapid stop-out ({hold_mins:.0f}m, {pct_move:.2f}%) on {strategy} — "
                    "likely LTF fakeout or counter-HTF entry."
                )
            elif exit_reason == "time_exit":
                lesson = f"Stagnant momentum on {strategy}; closed by time_exit ({pct_move:.2f}%)."
            else:
                lesson = (
                    f"Stop-loss hit ({pct_move:.2f}%, -${abs(realized_pnl):.2f}) after {hold_mins:.0f}m "
                    f"on {strategy}."
                )

        reflection = {
            "trade_id": trade.get("id", ""),
            "time": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "strategy": strategy,
            "outcome": outcome,
            "pnl": round(realized_pnl, 4),
            "pct_move": round(pct_move, 3),
            "hold_mins": round(hold_mins, 1),
            "exit_reason": exit_reason,
            "lesson": lesson,
        }
        await db.add_trade_reflection(reflection)
        logger.info(f"🧠 [REFLECTOR] {symbol} ({outcome}): {lesson}")
        return reflection
