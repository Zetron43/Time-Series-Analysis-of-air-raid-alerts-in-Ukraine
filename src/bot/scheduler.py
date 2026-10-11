"""Autonomous Scheduler for 15-Minute Forecast Publishing.

Triggers forecasts at exact clock boundaries: :00, :15, :30, :45.
"""

from datetime import datetime, timezone
import time
from typing import Optional
from src.bot.bot_runner import AirRaidForecastBot


def seconds_until_next_quarter_hour() -> int:
    """Calculates remaining seconds until the next :00, :15, :30, :45 boundary."""
    now = datetime.now(timezone.utc)
    minute = now.minute
    second = now.second
    microsecond = now.microsecond

    # Next target minute
    next_minute = ((minute // 15) + 1) * 15
    if next_minute == 60:
        minutes_to_wait = 60 - minute
    else:
        minutes_to_wait = next_minute - minute

    total_seconds = minutes_to_wait * 60 - second - (microsecond / 1_000_000.0)
    # Add a tiny buffer (3 seconds) to ensure the target boundary has definitely begun
    return int(max(1.0, total_seconds + 3.0))


def run_scheduler_loop(
    max_cycles: Optional[int] = None,
    bot: Optional[AirRaidForecastBot] = None,
):
    """Main daemon loop running forecasts on 15-minute intervals."""
    if bot is None:
        bot = AirRaidForecastBot()

    print("[Scheduler] Starting Air Raid Forecast 15-minute daemon loop.")
    print("[Scheduler] Target boundaries: :00, :15, :30, :45 every hour.")

    cycles = 0
    while True:
        wait_sec = seconds_until_next_quarter_hour()
        next_run_dt = datetime.fromtimestamp(time.time() + wait_sec, tz=timezone.utc)
        print(f"[Scheduler] Next forecast scheduled at {next_run_dt.strftime('%H:%M:%S UTC')} (in {wait_sec}s)...")

        time.sleep(wait_sec)

        print(f"\n[Scheduler] Triggering 15-minute forecast at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}...")
        try:
            bot.publish_forecast()
        except Exception as e:
            print(f"[Scheduler] Error executing forecast cycle: {e}")

        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            print(f"[Scheduler] Reached maximum cycles ({max_cycles}). Exiting.")
            break


if __name__ == "__main__":
    import sys
    # If passed --test, run 1 cycle immediately without waiting 15 min
    if "--test" in sys.argv:
        bot = AirRaidForecastBot()
        bot.publish_forecast()
    else:
        run_scheduler_loop()
