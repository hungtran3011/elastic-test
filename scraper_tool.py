from __future__ import annotations

import argparse
import os
import re
import requests

from scraper.runner import crawl_story, crawl_category_pages
from settings import SCRAPE_BASE_URL


def detect_category() -> str:
    try:
        resp = requests.get(SCRAPE_BASE_URL, timeout=10)
        m = re.search(r'href=[\'"]([^\'"]*/the-loai/([^/\'"]+)[/\'"])', resp.text, re.I)
        if m:
            category = m.group(2)
            return category
    except Exception as e:
        return "Unknown"
    return "tien-hiep"


def detect_pages(category: str, max_pages: int) -> int:
    try:
        url = f"{SCRAPE_BASE_URL}/the-loai/{category}/"
        resp = requests.get(url, timeout=10)
        nums = re.findall(r"trang-?(\d+)", resp.text, re.I)
        if nums:
            detected = max(map(int, nums))
            pages = min(detected, max_pages)
            return pages
    except Exception:
        pass
    return 1


def main():
    parser = argparse.ArgumentParser(
        description="crawl Truyenfull stories"
    )
    parser.add_argument("--story", help="Story URL (overrides category mode)")
    parser.add_argument("--category", default="tien-hiep", help="Category slug")
    parser.add_argument("--auto-category", action="store_true", help="Auto-detect category")
    parser.add_argument("--chapters", type=int, default=10, help="Chapters per story (0=all, max 200)")
    parser.add_argument("--listing-pages", type=int, default=0, help="Listing pages (0=auto)")
    parser.add_argument("--max-pages", type=int, default=10, help="Max pages limit")
    parser.add_argument("--out", default="data", help="Output directory")
    parser.add_argument("--no-files", action="store_true", help="Disable JSON output")
    parser.add_argument("--delay", type=float, default=0.1, help="Download delay (seconds)")
    parser.add_argument("--resume", action="store_true", help="Skip crawled items")
    parser.add_argument("--job-id", help="Job ID for progress tracking")
    args = parser.parse_args()
    if args.no_files:
        os.environ["SCRAPER_WRITE_STORY_FILES"] = "0"
    if args.story:
        job_id = args.job_id or args.story.split("/")[-1]
        crawl_story(url=args.story, chapters=args.chapters, output_dir=args.out, resume=args.resume, job_id=job_id, download_delay=args.delay)
        return
    category = detect_category() if args.auto_category else args.category
    if args.listing_pages == 0:
        pages = detect_pages(category, args.max_pages)
    else:
        pages = min(args.listing_pages, args.max_pages)
    job_id = args.job_id or (category if args.resume else None)
    crawl_category_pages(
        category_slug=category,
        listing_pages=pages,
        chapters=args.chapters,
        output_dir=args.out,
        resume=args.resume,
        job_id=job_id,
        download_delay=args.delay
    )

if __name__ == "__main__":
    main()