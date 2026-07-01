"""Long-only timing backtest engine."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from alphapilot.systems.run_workspace import runs_root
from alphapilot.systems.timing.base import PortfolioState, TimingBacktestRequest, TimingBacktestResult


class TimingBacktestEngine:
    """Execute target-percent timing signals with next-bar open fills."""

    def run(
        self,
        *,
        bars: pd.DataFrame,
        signals: pd.DataFrame,
        request: TimingBacktestRequest,
    ) -> TimingBacktestResult:
        bars = bars.sort_values(["instrument", "datetime"]).reset_index(drop=True)
        signals = signals.sort_values(["instrument", "datetime"]).reset_index(drop=True)
        merged = bars.merge(
            signals[["datetime", "instrument", "signal", "target_percent", "score", "reason"]],
            on=["datetime", "instrument"],
            how="left",
        )
        merged["signal"] = pd.to_numeric(merged["signal"], errors="coerce").fillna(0).astype(int)
        merged["target_percent"] = pd.to_numeric(
            merged["target_percent"], errors="coerce"
        ).fillna(0.0).clip(lower=0.0, upper=1.0)
        merged["signal_datetime"] = merged["datetime"]
        for col in ("signal", "target_percent", "reason", "signal_datetime"):
            merged[f"exec_{col}"] = merged.groupby("instrument")[col].shift(1)

        state = PortfolioState(cash=float(request.cash))
        trades: list[dict[str, Any]] = []
        equity_rows: list[dict[str, Any]] = []
        position_rows: list[dict[str, Any]] = []
        prev_equity = float(request.cash)
        last_prices: dict[str, float] = {}

        for dt, group in merged.sort_values("datetime").groupby("datetime", sort=True):
            for _, row in group.iterrows():
                if pd.isna(row.get("exec_target_percent")):
                    continue
                self._rebalance_one(
                    state=state,
                    execution_row=row,
                    trades=trades,
                    request=request,
                )

            for _, row in group.iterrows():
                last_prices[str(row["instrument"])] = float(row["close"])

            equity = state.cash + sum(
                float(amount) * float(last_prices.get(inst, 0.0))
                for inst, amount in state.positions.items()
            )
            for _, row in group.iterrows():
                instrument = str(row["instrument"])
                close_price = float(row["close"])
                amount = float(state.positions.get(instrument, 0.0))
                equity_rows.append(
                    {
                        "datetime": pd.Timestamp(dt),
                        "instrument": instrument,
                        "cash": state.cash,
                        "position_amount": amount,
                        "close": close_price,
                        "equity": equity,
                        "return": equity / prev_equity - 1 if prev_equity else 0.0,
                    }
                )
                position_rows.append(
                    {
                        "datetime": pd.Timestamp(dt),
                        "instrument": instrument,
                        "amount": amount,
                        "close": close_price,
                        "market_value": amount * close_price,
                    }
                )
            prev_equity = equity

        equity_curve = pd.DataFrame(equity_rows).sort_values(["datetime", "instrument"])
        trades_df = pd.DataFrame(trades)
        positions_df = pd.DataFrame(position_rows).sort_values(["datetime", "instrument"])
        summary = self._summary(equity_curve, trades_df, request)
        artifact_dir = self._write_artifacts(
            request=request,
            summary=summary,
            signals=signals,
            trades=trades_df,
            equity_curve=equity_curve,
            positions=positions_df,
        )
        return TimingBacktestResult(
            summary=summary,
            equity_curve=equity_curve,
            trades=trades_df,
            positions=positions_df,
            signals=signals,
            artifact_dir=artifact_dir,
        )

    def _rebalance_one(
        self,
        *,
        state: PortfolioState,
        execution_row: pd.Series,
        trades: list[dict[str, Any]],
        request: TimingBacktestRequest,
    ) -> None:
        instrument = str(execution_row["instrument"])
        target_percent = float(execution_row["exec_target_percent"])
        open_price = float(execution_row["open"])
        if not math.isfinite(open_price) or open_price <= 0:
            return
        current_amount = float(state.positions.get(instrument, 0.0))
        current_value = current_amount * open_price
        equity = state.cash + current_value
        target_value = equity * target_percent
        delta_value = target_value - current_value
        unit = max(0, int(request.trade_unit or 0))

        if delta_value > open_price:
            fill_price = open_price * (1 + float(request.slippage))
            raw_amount = delta_value / fill_price
            amount = self._floor_unit(raw_amount, unit)
            if amount <= 0:
                return
            amount = self._affordable_amount(amount, fill_price, state.cash, request)
            if amount <= 0:
                return
            fee = self._fee(amount * fill_price, request.open_cost, request.min_cost)
            cash_delta = amount * fill_price + fee
            state.cash -= cash_delta
            new_amount = current_amount + amount
            state.positions[instrument] = new_amount
            old_cost = state.cost_basis.get(instrument, 0.0) * current_amount
            state.cost_basis[instrument] = (old_cost + amount * fill_price) / new_amount
            self._record_trade(trades, execution_row, instrument, "buy", amount, fill_price, fee, request)
            return

        if delta_value < -open_price and current_amount > 0:
            fill_price = open_price * (1 - float(request.slippage))
            desired = min(current_amount, abs(delta_value) / fill_price)
            amount = self._floor_unit(desired, unit)
            if amount <= 0 and target_percent == 0:
                amount = self._floor_unit(current_amount, unit) if unit else current_amount
            amount = min(amount, current_amount)
            if amount <= 0:
                return
            fee = self._fee(amount * fill_price, request.close_cost, request.min_cost)
            state.cash += amount * fill_price - fee
            remaining = current_amount - amount
            if remaining <= 1e-9:
                state.positions.pop(instrument, None)
                state.cost_basis.pop(instrument, None)
            else:
                state.positions[instrument] = remaining
            state.realized_pnl += (fill_price - state.cost_basis.get(instrument, fill_price)) * amount - fee
            self._record_trade(trades, execution_row, instrument, "sell", amount, fill_price, fee, request)

    @staticmethod
    def _floor_unit(amount: float, unit: int) -> float:
        if unit > 0:
            return float(math.floor(amount / unit) * unit)
        return float(max(amount, 0.0))

    def _affordable_amount(
        self,
        amount: float,
        price: float,
        cash: float,
        request: TimingBacktestRequest,
    ) -> float:
        unit = max(0, int(request.trade_unit or 0))
        candidate = amount
        while candidate > 0:
            fee = self._fee(candidate * price, request.open_cost, request.min_cost)
            if candidate * price + fee <= cash + 1e-9:
                return candidate
            candidate = candidate - unit if unit > 0 else candidate - 1
        return 0.0

    @staticmethod
    def _fee(value: float, rate: float, min_cost: float) -> float:
        if value <= 0:
            return 0.0
        return max(float(value) * float(rate), float(min_cost))

    @staticmethod
    def _record_trade(
        trades: list[dict[str, Any]],
        execution_row: pd.Series,
        instrument: str,
        side: str,
        amount: float,
        price: float,
        fee: float,
        request: TimingBacktestRequest,
    ) -> None:
        trades.append(
            {
                "signal_datetime": pd.Timestamp(execution_row["exec_signal_datetime"]),
                "datetime": pd.Timestamp(execution_row["datetime"]),
                "instrument": instrument,
                "side": side,
                "amount": float(amount),
                "price": float(price),
                "value": float(amount * price),
                "fee": float(fee),
                "reason": execution_row.get("exec_reason", ""),
                "strategy": request.strategy_name,
            }
        )

    @staticmethod
    def _summary(
        equity_curve: pd.DataFrame,
        trades: pd.DataFrame,
        request: TimingBacktestRequest,
    ) -> dict[str, Any]:
        if equity_curve.empty:
            return {"strategy": request.strategy_name, "total_return": 0.0, "n_trades": 0}
        by_time = equity_curve.groupby("datetime", as_index=True)["equity"].sum().sort_index()
        start_equity = float(request.cash)
        final_equity = float(by_time.iloc[-1])
        running_max = by_time.cummax()
        drawdown = by_time / running_max - 1
        days = max((by_time.index[-1] - by_time.index[0]).days, 1)
        total_return = final_equity / start_equity - 1 if start_equity else 0.0
        annual_return = (1 + total_return) ** (365 / days) - 1 if total_return > -1 else -1.0
        return {
            "strategy": request.strategy_name,
            "start": str(by_time.index[0]),
            "end": str(by_time.index[-1]),
            "initial_cash": start_equity,
            "final_equity": final_equity,
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": float(drawdown.min()),
            "n_trades": int(len(trades)),
            "n_buys": int((trades["side"] == "buy").sum()) if not trades.empty else 0,
            "n_sells": int((trades["side"] == "sell").sum()) if not trades.empty else 0,
            "win_rate": None,
            "total_fee": float(trades["fee"].sum()) if not trades.empty else 0.0,
            "artifact_dir": None,
        }

    @staticmethod
    def _artifact_root(request: TimingBacktestRequest) -> Path:
        if request.output_dir:
            return Path(request.output_dir).expanduser()
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        return runs_root() / "timing" / f"{ts}__{request.strategy_name}"

    def _write_artifacts(
        self,
        *,
        request: TimingBacktestRequest,
        summary: dict[str, Any],
        signals: pd.DataFrame,
        trades: pd.DataFrame,
        equity_curve: pd.DataFrame,
        positions: pd.DataFrame,
    ) -> Path:
        root = self._artifact_root(request)
        root.mkdir(parents=True, exist_ok=True)
        signals.to_csv(root / "signals.csv", index=False)
        trades.to_csv(root / "trades.csv", index=False)
        equity_curve.to_csv(root / "equity_curve.csv", index=False)
        positions.to_csv(root / "positions.csv", index=False)
        summary["artifact_dir"] = str(root)
        (root / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return root
