import argparse
import os
from scrapy.crawler import CrawlerProcess
from scraper.settings import SCRAPER_SETTINGS


def _make_settings(output_dir: str = ".", download_delay: float | None = None):
    s = SCRAPER_SETTINGS.copy()
    if download_delay is not None:
        s["DOWNLOAD_DELAY"] = float(download_delay)
    pipelines: dict = {}
    env_flag = os.getenv("SCRAPER_WRITE_STORY_FILES")
    write_files = s.get("WRITE_STORY_FILES", True) if env_flag is None else bool(int(env_flag))
    if write_files:
        pipelines["scraper.pipelines.StoryJsonPipeline"] = 300
    if s.get("PUSH_TO_SUPABASE"):
        pipelines["scraper.pipelines.SupabasePipeline"] = 400
    s["ITEM_PIPELINES"] = pipelines
    s["STORY_OUTPUT_DIR"] = output_dir
    return s


def crawl_category_pages(category_slug: str, listing_pages: int = 2, chapters: int = 0, output_dir: str = ".", resume: bool = False, job_id: str | None = None, download_delay: float | None = None):
    from scraper.spiders.truyenfull import TruyenfullSpider
    settings = _make_settings(output_dir=output_dir, download_delay=download_delay)
    process = CrawlerProcess(settings=settings)
    base = f"https://truyenfull.vision/the-loai/{category_slug}/"
    process.crawl(TruyenfullSpider, start_url=base, chapters_limit=chapters, resume_mode=resume, job_id=job_id, max_stories=0, listing_pages=listing_pages, category_slug=category_slug)
    process.start()


def crawl_story(url: str, chapters: int = 0, output_dir: str = ".", resume: bool = False, job_id: str | None = None, download_delay: float | None = None):
    from scraper.spiders.truyenfull import TruyenfullSpider
    settings = _make_settings(output_dir=output_dir, download_delay=download_delay)
    process = CrawlerProcess(settings=settings)
    process.crawl(TruyenfullSpider, start_url=url, chapters_limit=chapters, resume_mode=resume, job_id=job_id)
    process.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["story", "category"], default="story")
    parser.add_argument("--url", type=str, default=None)
    parser.add_argument("--category", type=str, default="tien-hiep")
    parser.add_argument("--listing-pages", type=int, default=2)
    parser.add_argument("--chapters", type=int, default=0)
    parser.add_argument("--out", type=str, default=".")
    args = parser.parse_args()
    if args.mode == "story" and args.url:
        crawl_story(args.url, chapters=args.chapters, output_dir=args.out)
    else:
        crawl_category_pages(args.category, listing_pages=args.listing_pages, chapters=args.chapters, output_dir=args.out)


