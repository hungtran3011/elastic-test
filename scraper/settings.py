SCRAPER_SETTINGS = {
    "LOG_LEVEL": "INFO",
    "RETRY_ENABLED": True,
    "RETRY_TIMES": 5,
    "RETRY_HTTP_CODES": [500, 502, 503, 504, 522, 524, 408],
    "DOWNLOAD_TIMEOUT": 30,
    "DOWNLOAD_DELAY": 0.1,
    "RANDOMIZE_DOWNLOAD_DELAY": True,
    "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
    "CONCURRENT_REQUESTS": 8,
    "AUTOTHROTTLE_ENABLED": True,
    "AUTOTHROTTLE_START_DELAY": 0.5,
    "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.0,
    "AUTOTHROTTLE_MAX_DELAY": 60,
    "DEFAULT_REQUEST_HEADERS": {
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    },
    "USER_AGENT": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "DOWNLOADER_MIDDLEWARES": {
        "scrapy.downloadermiddlewares.retry.RetryMiddleware": 550,
        "scraper.middlewares.RespectRetryAfterMiddleware": 560,
    },
}
SCRAPER_SETTINGS["PUSH_TO_SUPABASE"] = False
SCRAPER_SETTINGS["SUPABASE_MODE"] = "chapters"
SCRAPER_SETTINGS["SUPABASE_TABLES"] = {
    "stories_table": "stories",
    "chapters_table": "chapters"
}
SCRAPER_SETTINGS["WRITE_STORY_FILES"] = True