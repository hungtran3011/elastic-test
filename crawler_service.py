from __future__ import annotations

import time

from apscheduler.schedulers.blocking import BlockingScheduler

from scraper_tool import init_index, sync_from_list
from settings import SCRAPE_INTERVAL_MINUTES


def run_once() -> None:
    init_index()
    results = sync_from_list()
    print(f"[crawler] synced {len(results)} stories")


def main() -> None:
    # One immediate sync on start (useful when deploying/restarting)
    try:
        run_once()
    except Exception as e:
        print(f"[crawler] initial sync failed: {e}")

    scheduler = BlockingScheduler()
    scheduler.add_job(run_once, "interval", minutes=SCRAPE_INTERVAL_MINUTES, id="scrape_sync", replace_existing=True)

    print(f"[crawler] running; interval={SCRAPE_INTERVAL_MINUTES} minutes")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass

    # Give stdout a moment to flush on Windows terminals
    time.sleep(0.1)


if __name__ == "__main__":
    main()
