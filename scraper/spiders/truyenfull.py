from __future__ import annotations

import re
from datetime import datetime
from typing import List, Set, Optional, Dict, Any, Iterator
import scrapy
from scrapy.http import Response, Request
from settings import SCRAPE_BASE_URL
from scraper.utils import ProgressTracker

class TruyenfullSpider(scrapy.Spider):
    name = "truyenfull"
    custom_settings = {"LOG_LEVEL": "INFO"}
    MAX_CHAPTERS_PER_STORY = 200

    def __init__(
            self,
            start_url: Optional[str] = None,
            category_path: str = "the-loai/tien-hiep",
            chapters_limit: int = 5,
            resume_mode: bool = False,
            job_id: Optional[str] = None,
            max_stories: int = 10,
            listing_pages: Optional[int] = None,
            category_slug: Optional[str] = None,
            *args,
            **kwargs
    ):
        super().__init__(*args, **kwargs)
        if start_url:
            self.start_urls = [start_url.strip()]
        else:
            self.start_urls = [f"{SCRAPE_BASE_URL}/{category_path.strip().strip('/')}/"]
        self.chapters_limit = int(chapters_limit)
        self.max_stories = int(max_stories) if max_stories else 10
        self.listing_pages = int(listing_pages) if listing_pages else None
        self._collected_story_urls: List[str] = []
        self._pages_crawled = 0
        self.resume_mode = resume_mode
        self.job_id = job_id or "default"
        self.category_slug = category_slug or self._extract_category(start_url or "")
        self.progress_tracker = ProgressTracker() if resume_mode else None

    def parse(self, response: Response) -> Iterator[Request]:
        if self._is_story_page(response):
            yield from self.parse_story(response)
        else:
            yield from self._parse_listing(response)

    def _parse_listing(self, response: Response) -> Iterator[Request]:
        self._pages_crawled += 1
        if self.listing_pages and self._pages_crawled > self.listing_pages:
            self.logger.info("Reached page limit (%d)", self.listing_pages)
            return
        links = (
                response.css("h3.truyen-title a::attr(href)").getall()
                or response.css("h3.title a::attr(href)").getall()
                or response.xpath('//h3[contains(@class,"title")]//a/@href').getall()
        )
        for href in links:
            if self.max_stories and len(self._collected_story_urls) >= self.max_stories:
                break
            url = response.urljoin(href)
            if url in self._collected_story_urls:
                continue
            self._collected_story_urls.append(url)
            if self._is_crawled(url):
                self.logger.info("Skipping completed: %s", url)
                continue
            yield response.follow(url, callback=self.parse_story)
        if not self.max_stories or len(self._collected_story_urls) < self.max_stories:
            next_url = self._find_next_page(response)
            if next_url:
                self.logger.info("Next page: %s", next_url)
                yield response.follow(next_url, callback=self.parse)

    def parse_story(self, response: Response) -> Iterator[Request]:
        if self._is_crawled(response.url):
            return
        story = {
            "source_url": response.url,
            "title": (response.css("h3.title::text, h3.truyen-title::text").get() or "").strip(),
            "author": (response.css('a[itemprop="author"]::text').get() or "").strip(),
            "image_url": response.css('img[itemprop="image"]::attr(src)').get() or "",
            "description": self._extract_desc(response),
            "category": self.category_slug,
            "genres": self._extract_genres(response),
        }
        chapter_links = self._extract_chapter_links(response)
        pagination_urls = self._get_pagination_urls(response)
        if pagination_urls:
            yield from self._handle_paginated_chapters(response, story, chapter_links, pagination_urls)
        else:
            yield from self._request_chapters(story, chapter_links)

    def parse_chapter(self, response: Response) -> Iterator[Dict[str, Any]]:
        story = response.meta["story"]
        chapters = response.meta["chapters"]
        expected = response.meta["expected_count"]
        ch_num = self._extract_num(response.url)
        ch_title = self._extract_chapter_title(response, story)
        content = "\n".join(
            t.strip() for t in (
                    response.css("div.chapter-c *::text").getall()
                    or response.css("#chapter-c *::text").getall()
                    or response.css(".chapter-content *::text").getall()
            ) if t.strip()
        )
        chapter = {
            "chapter_number": ch_num,
            "chapter_title": ch_title,
            "content": content,
            "source_url": response.url
        }
        chapters.append(chapter)
        self.logger.info("fetched chapter %d: %s", ch_num, response.url)
        if self.resume_mode:
            self.progress_tracker.mark_chapter_completed(
                self.job_id, story["source_url"], response.url
            )
        if len(chapters) >= expected:
            yield self._finalize_story(story, chapters)

    def parse_chapter_list_page(self, response: Response) -> Iterator[Request]:
        story = response.meta["story"]
        state = response.meta["collector_state"]
        chapters_acc = response.meta["chapters_acc"]
        new_links = self._extract_chapter_links(response)
        existing = {link["url"] for link in state["anchors"]}
        for link in new_links:
            if link["url"] not in existing:
                state["anchors"].append(link)
        state["remaining"] -= 1
        if state["remaining"] <= 0:
            all_links = [l for l in state["anchors"] if "/chuong-" in l["url"]]
            all_links.sort(key=lambda x: self._extract_num(x["url"]))
            yield from self._request_chapters(story, all_links)

    def _is_story_page(self, response: Response) -> bool:
        return bool(
            response.css("#list-chapter")
            or response.css(".list-chapter")
            or response.css('h3.title[itemprop="name"]')
        )

    def _extract_desc(self, response: Response) -> str:
        texts = (
                response.css('div[itemprop="description"] *::text').getall()
                or response.css(".info-holder *::text, .book-intro *::text").getall()
        )
        return "\n".join(t.strip() for t in texts if t.strip())

    def _extract_genres(self, response: Response) -> List[str]:
        raw = response.css("a[itemprop='genre']::text").getall()
        seen = set()
        genres = []
        for g in raw:
            g = g.strip()
            if g and g not in seen:
                seen.add(g)
                genres.append(g)
        return genres

    def _extract_chapter_links(self, response: Response) -> List[Dict[str, str]]:
        anchors = (
                response.css("#list-chapter a[href*='chuong-']")
                or response.css(".list-chapter a[href*='chuong-']")
                or response.xpath('//a[contains(@href,"/chuong-")]')
        )
        seen = set()
        links = []
        for a in anchors:
            href = a.xpath("@href").get() or a.css("::attr(href)").get()
            if not href:
                continue
            url = response.urljoin(href)
            if url in seen:
                continue
            seen.add(url)
            title = (
                    a.xpath("@title").get()
                    or a.xpath("normalize-space(string(.))").get()
                    or a.css("::text").get()
                    or ""
            ).strip()
            links.append({"url": url, "title": title})
        return sorted(links, key=lambda x: self._extract_num(x["url"]))

    def _get_pagination_urls(self, response: Response) -> Dict[int, str]:
        hrefs = (
                response.css("#list-chapter a[href*='trang-']::attr(href)").getall()
                or response.css(".list-chapter a[href*='trang-']::attr(href)").getall()
        )
        # if not hrefs:
        #     return {}
        urls = {}
        for href in hrefs:
            m = re.search(r"trang-?(\d+)", href)
            if m:
                try:
                    urls[int(m.group(1))] = response.urljoin(href)
                except ValueError:
                    pass
        return urls

    def _handle_paginated_chapters(
            self,
            response: Response,
            story: Dict[str, Any],
            initial_links: List[Dict[str, str]],
            pagination_urls: Dict[int, str]
    ) -> Iterator[Request]:
        state = {
            "anchors": initial_links[:],
            "remaining": max(pagination_urls.keys()) - 1
        }
        chapters_acc = []

        for page_num in sorted(pagination_urls.keys()):
            yield scrapy.Request(
                url=pagination_urls[page_num],
                callback=self.parse_chapter_list_page,
                meta={"story": story, "collector_state": state, "chapters_acc": chapters_acc}
            )

    def _request_chapters(
            self,
            story: Dict[str, Any],
            chapter_links: List[Dict[str, str]]
    ) -> Iterator[Request]:
        # Apply limit
        limit = self.chapters_limit if self.chapters_limit > 0 else self.MAX_CHAPTERS_PER_STORY
        limit = min(limit, self.MAX_CHAPTERS_PER_STORY)
        selected = chapter_links[:limit]
        if not selected:
            self.logger.info("No chapters: %s", story["source_url"])
            return
        if self.resume_mode:
            completed = self.progress_tracker.get_completed_chapters(
                self.job_id, story["source_url"]
            )
            selected = [l for l in selected if l["url"] not in completed]

            if not selected:
                self.logger.info("All chapters done: %s", story["source_url"])
                self.progress_tracker.mark_story_completed(self.job_id, story["source_url"])
                return
        chapters_acc = []
        expected = len(selected)

        for link in selected:
            yield scrapy.Request(
                url=link["url"],
                callback=self.parse_chapter,
                meta={
                    "story": story,
                    "chapters": chapters_acc,
                    "expected_count": expected,
                    "chapter_title": link["title"]
                }
            )

    def _extract_chapter_title(self, response: Response, story: Dict[str, Any]) -> str:
        title = response.meta.get("chapter_title", "").strip()
        if not title:
            title = (
                    response.css("h1.chapter-title::text, h2.chapter-title::text").get()
                    or response.css(".chapter-title::text").get()
                    or response.css('meta[property="og:title"]::attr(content)').get()
                    or ""
            ).strip()
        title = re.sub(r'^\s*Chương\s*\d+\s*[:\-\–\—]\s*', "", title, flags=re.I)
        story_title = story.get("title", "").strip()
        if story_title and title.lower().startswith(story_title.lower()):
            title = title[len(story_title):].lstrip(" -:–—").strip()
        return title

    def _finalize_story(
            self,
            story: Dict[str, Any],
            chapters: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        valid = [
            c for c in chapters
            if "/trang-" not in c.get("source_url", "").lower()
               and not (c.get("chapter_title", "").isdigit() and c.get("chapter_number", 0) == 0)
        ]
        valid.sort(key=lambda c: c.get("chapter_number", 0))
        story["chapters"] = valid
        story["last_updated"] = datetime.utcnow().isoformat()
        if self.resume_mode:
            self.progress_tracker.mark_story_completed(self.job_id, story["source_url"])
        return story

    def _find_next_page(self, response: Response) -> Optional[str]:
        links = response.css("ul.pagination a::attr(href)").getall()
        if not links:
            return self._find_next_fallback(response)
        cat_pattern = f"/the-loai/{self.category_slug}"
        cat_links = [response.urljoin(l) for l in links if cat_pattern in response.urljoin(l)]
        #
        # if not cat_links:
        #     cat_links = [response.urljoin(l) for l in links if "/the-loai/" in response.urljoin(l)]
        #
        # if not cat_links:
        #     return self._find_next_fallback(response)

        # Find next sequential page
        cur_match = re.search(r"trang-?(\d+)", response.url)
        cur_page = int(cur_match.group(1)) if cur_match else 1
        candidates = []
        for url in cat_links:
            m = re.search(r"trang-?(\d+)", url)
            if m:
                try:
                    candidates.append((int(m.group(1)), url))
                except ValueError:
                    pass
        if not candidates:
            return cat_links[0] if cat_links else None
        next_pages = [(n, u) for n, u in candidates if n > cur_page]
        if next_pages:
            next_pages.sort(key=lambda x: x[0])
            return next_pages[0][1]
        return None

    @staticmethod
    def _find_next_fallback(response: Response) -> Optional[str]:
        return (response.css("a.next::attr(href)").get() or response.css("li.next a::attr(href)").get()or response.xpath('//a[contains(text(),"Sau") or contains(@rel,"next")]/@href').get())

    @staticmethod
    def _extract_num(url: str) -> int:
        m = re.search(r"chuong-?(\d+)", url)
        return int(m.group(1)) if m else 0

    @staticmethod
    def _extract_category(url: str) -> str:
        if "/the-loai/" in url:
            parts = url.split("/the-loai/")
            if len(parts) > 1:
                return parts[1].split("/")[0]
        return "unknown"

    def _is_crawled(self, url: str) -> bool:
        return self.resume_mode and self.progress_tracker.is_story_crawled(self.job_id, url)