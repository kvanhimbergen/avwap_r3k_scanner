from pathlib import Path
from datetime import datetime

import pytz
from dotenv import load_dotenv

from alerts.slack import slack_alert
from config import cfg
import scan_engine


def main() -> None:
    load_dotenv()

    BASE_DIR = Path(__file__).resolve().parent
    OUT_PATH = BASE_DIR / "daily_candidates.csv"
    watchlist_path = BASE_DIR / "tradingview_watchlist.txt"

    out = scan_engine.run_scan(cfg)
    scan_engine.write_candidates_csv(out, OUT_PATH)

    # --- TradingView watchlist export ---
    n = scan_engine.write_tradingview_watchlist(out, watchlist_path)
    print(f"[watchlist] wrote {n} symbols -> {watchlist_path}")

    print(f"\nDEBUG: Scan finished. Found {len(out)} total candidates. Wrote: {OUT_PATH}")

    if not out.empty:
        out = out.sort_values(["TrendTier", "TrendScore"], ascending=[True, False]).head(
            scan_engine.ALGO_CANDIDATE_CAP
        )
        scan_engine.write_candidates_csv(out, OUT_PATH)
        print(f"Wrote candidates to: {OUT_PATH}")

        scan_date = datetime.now(pytz.timezone("America/New_York")).date()
        slack_alert(
            "INFO",
            "Scan complete",
            f"Saved {len(out)} candidates to {OUT_PATH.name}",
            component="SCAN",
            throttle_key=f"scan_complete_{scan_date}",
            throttle_seconds=3600,
        )
    else:
        scan_date = datetime.now(pytz.timezone("America/New_York")).date()
        slack_alert(
            "WARNING",
            "Scan complete (empty)",
            f"No candidates met gates; wrote empty {OUT_PATH.name} to prevent stale execution.",
            component="SCAN",
            throttle_key=f"scan_empty_{scan_date}",
            throttle_seconds=3600,
        )

    scan_engine.save_bad_tickers(scan_engine.BAD_TICKERS)


if __name__ == "__main__":
    main()
