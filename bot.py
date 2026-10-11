"""Main entry point for Air Raid Alerts Telegram Bot.

Compatible with Railway, Docker, Procfile, and local execution.
"""

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.bot.interactive_bot import (
    run_live_polling,
    simulate_user_flow,
    load_env_file,
    is_valid_token,
)


def main():
    load_env_file()

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        token = token.strip().strip('"').strip("'")

    # Check CLI arguments
    if "--simulate" in sys.argv:
        reg = sys.argv[2] if len(sys.argv) > 2 else "sumy"
        hor = sys.argv[3] if len(sys.argv) > 3 else "1h"
        simulate_user_flow(region_code=reg, horizon_code=hor)
        return

    # Check if specific region passed as argument
    args_non_flags = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args_non_flags) >= 1 and not token:
        reg = args_non_flags[0]
        hor = args_non_flags[1] if len(args_non_flags) > 1 else "1h"
        simulate_user_flow(region_code=reg, horizon_code=hor)
        return

    # Live bot mode (default in Docker / Railway)
    if not is_valid_token(token):
        print("=" * 70, flush=True)
        print("[!] Помилка: Змінна середовища TELEGRAM_BOT_TOKEN не задана або некоректна.", flush=True)
        print("    Для запуску в Railway додайте TELEGRAM_BOT_TOKEN у розділі 'Variables'.", flush=True)
        print("    Для локального запуску створіть файл .env або встановіть змінну в терміналі.", flush=True)
        print("=" * 70, flush=True)
        sys.exit(1)

    print("[+] TELEGRAM_BOT_TOKEN виявлено. Запуск бота в режимі реального часу...", flush=True)
    run_live_polling(token)


if __name__ == "__main__":
    main()
