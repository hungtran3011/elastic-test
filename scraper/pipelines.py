"""
Scrapy pipelines for processing and storing scraped story data.
"""
import json
import os
from typing import Dict, Any, Optional

from scraper.utils import slugify


class StoryJsonPipeline:
    def __init__(self, output_dir: str = "."):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    @classmethod
    def from_crawler(cls, crawler):
        output_dir = crawler.settings.get("STORY_OUTPUT_DIR", ".")
        return cls(output_dir=output_dir)

    def process_item(self, item: Dict[str, Any], spider) -> Dict[str, Any]:
        title = item.get("title") or "untitled_story"
        filename_base = slugify(title)
        category_slug = self._determine_category(item)
        category_dir = os.path.join(self.output_dir, category_slug)
        os.makedirs(category_dir, exist_ok=True)
        output_path = self._get_unique_filepath(category_dir, filename_base)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
        spider.logger.info("saved story to: %s", output_path)
        return item

    @staticmethod
    def _determine_category(item: Dict[str, Any]) -> str:
        category_slug = item.get("category")
        if category_slug and category_slug != "unknown":
            return category_slug
        genres = item.get("genres", [])
        if genres:
            return slugify(genres[0])
        return "unknown"

    @staticmethod
    def _get_unique_filepath(directory: str, base_name: str) -> str:
        output_path = os.path.join(directory, f"{base_name}.json")
        if not os.path.exists(output_path):
            return output_path
        counter = 1
        while True:
            output_path = os.path.join(directory, f"{base_name}-{counter}.json")
            if not os.path.exists(output_path):
                return output_path
            counter += 1

class SupabasePipeline:
    def __init__(self, mode: str = "chapters", tables: Optional[Dict[str, str]] = None):
        self.mode = mode
        self.tables = tables or {
            "stories_table": "stories",
            "chapters_table": "chapters"
        }
        self._supabase_helper = None
        self._client = None
        self._initialize_supabase()
    def _initialize_supabase(self) -> None:
        try:
            import supabase_client as sb
            self._supabase_helper = sb
            self._client = sb.get_supabase_client()
        except ImportError:
            pass

    @classmethod
    def from_crawler(cls, crawler):
        mode = crawler.settings.get("SUPABASE_MODE", "chapters")
        tables = crawler.settings.get("SUPABASE_TABLES")
        return cls(mode=mode, tables=tables)

    def process_item(self, item: Dict[str, Any], spider) -> Dict[str, Any]:
        try:
            if self.mode == "jsonb":
                self._push_jsonb_mode(item, spider)
            else:
                self._push_chapters_mode(item, spider)
        except Exception as e:
            spider.logger.error("failed to push to Supabase: %s", e, exc_info=True)
        return item

    def _push_jsonb_mode(self, item: Dict[str, Any], spider) -> None:
        self._supabase_helper.import_story_jsonb(self._client, item)
        spider.logger.info("Pushed story (JSONB mode): %s", item.get("title"))

    def _push_chapters_mode(self, item: Dict[str, Any], spider) -> None:
        if hasattr(self._supabase_helper, "import_story_chapters"):
            self._supabase_helper.import_story_chapters(self._client, item)
            spider.logger.info("Pushed story (chapters mode): %s", item.get("title"))
            return
        self._manual_chapters_push(item)
        spider.logger.info("Pushed story (chapters mode, manual): %s", item.get("title"))

    def _manual_chapters_push(self, item: Dict[str, Any]) -> None:
        story_id = item.get("source_url", "").strip("/").split("/")[-1]
        story_record = {
            "id": story_id,
            "title": item.get("title"),
            "author": item.get("author"),
            "description": item.get("description"),
            "genres": item.get("genres", []),
            "source_url": item.get("source_url"),
            "image_url": item.get("image_url"),
            "total_chapters": len(item.get("chapters", [])),
        }
        if hasattr(self._supabase_helper, "upsert_story"):
            stories_table = self.tables.get("stories_table", "stories")
            self._supabase_helper.upsert_story(stories_table, story_record)
        if hasattr(self._supabase_helper, "upsert_chapter"):
            chapters_table = self.tables.get("chapters_table", "chapters")
            for chapter in item.get("chapters", []):
                chapter_id = f"{story_id}-ch{chapter.get('chapter_number')}"
                chapter_record = {
                    "id": chapter_id,
                    "story_id": story_id,
                    "chapter_number": chapter.get("chapter_number"),
                    "chapter_title": chapter.get("chapter_title"),
                    "content": chapter.get("content"),
                    "source_url": chapter.get("source_url"),
                }
                self._supabase_helper.upsert_chapter(chapters_table, chapter_record)