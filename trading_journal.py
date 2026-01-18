import argparse
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd


DEFAULT_LOG_PATH = "trade_log.csv"


@dataclass
class JournalScope:
    scope: str
    label: str


def load_trade_log(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"]).copy()
    df["Trade_Date"] = df["Timestamp"].dt.date
    df["Trade_Month"] = df["Timestamp"].dt.to_period("M").astype(str)
    df["Trade_Year"] = df["Timestamp"].dt.year.astype(str)
    return df


def scope_filter(
    df: pd.DataFrame,
    scope: str,
    day: str | None,
    month: str | None,
    year: str | None,
) -> tuple[JournalScope, pd.DataFrame]:
    if df.empty:
        return JournalScope(scope, "(no trades)"), df

    scope = scope.lower()
    if scope == "day":
        target = day or df["Trade_Date"].max().isoformat()
        filtered = df[df["Trade_Date"].astype(str) == target]
        return JournalScope("day", target), filtered
    if scope == "month":
        target = month or df["Trade_Month"].max()
        filtered = df[df["Trade_Month"] == target]
        return JournalScope("month", target), filtered
    if scope == "year":
        target = year or df["Trade_Year"].max()
        filtered = df[df["Trade_Year"] == target]
        return JournalScope("year", target), filtered
    return JournalScope("all", "all"), df


def calculate_drawdown(pnl_series: pd.Series) -> float:
    if pnl_series.empty:
        return 0.0
    equity = pnl_series.cumsum()
    peak = equity.cummax()
    drawdown = equity - peak
    return drawdown.min()


def compute_metrics(df: pd.DataFrame) -> dict:
    closed = df[df["Side"].str.upper() != "BUY"].copy()
    if closed.empty:
        return {
            "total_trades": 0,
            "net_pnl": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "payoff_ratio": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_drawdown": 0.0,
            "avg_slippage": df["Slippage"].mean() if "Slippage" in df else 0.0,
            "avg_mfe": 0.0,
            "avg_mae": 0.0,
            "mfe_mae_ratio": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "median_pnl": 0.0,
        }

    wins = closed[closed["PnL"] > 0]
    losses = closed[closed["PnL"] <= 0]
    win_rate = len(wins) / len(closed)
    avg_win = wins["PnL"].mean() if not wins.empty else 0.0
    avg_loss = losses["PnL"].mean() if not losses.empty else 0.0
    payoff_ratio = avg_win / abs(avg_loss) if avg_loss else 0.0
    profit_factor = wins["PnL"].sum() / abs(losses["PnL"].sum()) if not losses.empty else float("inf")
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
    pnl_std = closed["PnL"].std()
    sharpe = (closed["PnL"].mean() / pnl_std) * np.sqrt(len(closed)) if pnl_std else 0.0
    downside = closed.loc[closed["PnL"] < 0, "PnL"]
    downside_std = downside.std()
    sortino = (closed["PnL"].mean() / downside_std) * np.sqrt(len(closed)) if downside_std else 0.0

    avg_mfe = closed["MFE"].mean() if "MFE" in closed else 0.0
    avg_mae = closed["MAE"].mean() if "MAE" in closed else 0.0
    mfe_mae_ratio = avg_mfe / avg_mae if avg_mae else 0.0

    return {
        "total_trades": len(closed),
        "net_pnl": closed["PnL"].sum(),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff_ratio,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": calculate_drawdown(closed["PnL"]),
        "avg_slippage": df["Slippage"].mean() if "Slippage" in df else 0.0,
        "avg_mfe": avg_mfe,
        "avg_mae": avg_mae,
        "mfe_mae_ratio": mfe_mae_ratio,
        "best_trade": closed["PnL"].max(),
        "worst_trade": closed["PnL"].min(),
        "median_pnl": closed["PnL"].median(),
    }


def period_summary(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    closed = df[df["Side"].str.upper() != "BUY"].copy()
    if closed.empty:
        return {}

    summaries = {}
    for label, column in [("day", "Trade_Date"), ("month", "Trade_Month"), ("year", "Trade_Year")]:
        grouped = closed.groupby(column)["PnL"].agg([
            ("trades", "count"),
            ("net_pnl", "sum"),
            ("avg_pnl", "mean"),
            ("win_rate", lambda s: (s > 0).mean()),
            ("profit_factor", lambda s: s[s > 0].sum() / abs(s[s <= 0].sum()) if (s <= 0).any() else float("inf")),
        ])
        summaries[label] = grouped.sort_index().reset_index()
    return summaries


def print_metrics(metrics: dict) -> None:
    print("\n--- Trading Journal Metrics ---")
    print(f"Total Closed Trades: {metrics['total_trades']}")
    print(f"Net PnL: ${metrics['net_pnl']:.2f}")
    print(f"Win Rate: {metrics['win_rate']:.2%}")
    print(f"Profit Factor: {metrics['profit_factor']:.2f}")
    print(f"Expectancy: ${metrics['expectancy']:.2f} per trade")
    print(f"Avg Win: ${metrics['avg_win']:.2f} | Avg Loss: ${metrics['avg_loss']:.2f}")
    print(f"Payoff Ratio: {metrics['payoff_ratio']:.2f}")
    print(f"Sharpe (per trade): {metrics['sharpe']:.2f}")
    print(f"Sortino (per trade): {metrics['sortino']:.2f}")
    print(f"Max Drawdown: ${metrics['max_drawdown']:.2f}")
    print(f"Median PnL: ${metrics['median_pnl']:.2f}")
    print(f"Best/Worst Trade: ${metrics['best_trade']:.2f} / ${metrics['worst_trade']:.2f}")
    print(f"Avg Slippage: {metrics['avg_slippage']:.4f}")
    print(f"Avg MFE: ${metrics['avg_mfe']:.2f} | Avg MAE: ${metrics['avg_mae']:.2f}")
    print(f"MFE/MAE Ratio: {metrics['mfe_mae_ratio']:.2f}")


def print_period_tables(summaries: dict[str, pd.DataFrame]) -> None:
    for label, table in summaries.items():
        if table.empty:
            continue
        print(f"\n--- {label.upper()} SUMMARY ---")
        print(table.to_string(index=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trading journal report with day/month/year scoping.")
    parser.add_argument("--log", default=DEFAULT_LOG_PATH, help="Path to trade_log.csv")
    parser.add_argument("--scope", default="day", choices=["day", "month", "year", "all"], help="Scope for metrics")
    parser.add_argument("--day", help="YYYY-MM-DD")
    parser.add_argument("--month", help="YYYY-MM")
    parser.add_argument("--year", help="YYYY")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        df = load_trade_log(args.log)
    except FileNotFoundError:
        print(f"No trade log found at {args.log}.")
        return

    scope_info, scoped_df = scope_filter(df, args.scope, args.day, args.month, args.year)
    print(f"\nTrading Journal Scope: {scope_info.scope.upper()} ({scope_info.label})")
    if scoped_df.empty:
        print("No trades found in scope.")
        return

    metrics = compute_metrics(scoped_df)
    print_metrics(metrics)
    summaries = period_summary(scoped_df)
    print_period_tables(summaries)


if __name__ == "__main__":
    main()
