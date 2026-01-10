import json
import os
import re
from typing import Set, Dict, Any, Iterable

def slugify(title: str) -> str:
    slug = (title or "story").lower()
    slug = re.sub(r"\s+", "-", slug)  # Replace whitespace with hyphens
    slug = re.sub(r"[^a-z0-9\-]", "", slug)  # Remove non-alphanumeric chars
    return slug or "story"


def load_seen(path: str) -> Set[str]:
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data)
    except (json.JSONDecodeError, IOError):
        return set()


def save_seen(path: str, seen: Iterable[str]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False, indent=2)


class ProgressTracker:
    def __init__(self, progress_dir: str = "data/progress"):
        self.progress_dir = progress_dir
        os.makedirs(progress_dir, exist_ok=True)

    def get_progress_file(self, job_id: str) -> str:
        return os.path.join(self.progress_dir, f"{job_id}.json")

    def load_progress(self, job_id: str) -> Dict[str, Any]:
        progress_file = self.get_progress_file(job_id)
        if not os.path.exists(progress_file):
            return {}
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def save_progress(self, job_id: str, progress: Dict[str, Any]) -> None:
        progress_file = self.get_progress_file(job_id)
        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)

    def is_story_crawled(self, job_id: str, story_url: str) -> bool:
        progress = self.load_progress(job_id)
        return story_url in progress.get("completed_stories", [])

    def mark_story_completed(self, job_id: str, story_url: str) -> None:
        progress = self.load_progress(job_id)
        if "completed_stories" not in progress:
            progress["completed_stories"] = []
        if story_url not in progress["completed_stories"]:
            progress["completed_stories"].append(story_url)
        self.save_progress(job_id, progress)

    def is_chapter_crawled(self, job_id: str, story_url: str, chapter_url: str) -> bool:
        progress = self.load_progress(job_id)
        story_progress = progress.get("stories", {}).get(story_url, {})
        return chapter_url in story_progress.get("completed_chapters", [])

    def mark_chapter_completed(self, job_id: str, story_url: str, chapter_url: str) -> None:
        progress = self.load_progress(job_id)
        if "stories" not in progress:
            progress["stories"] = {}
        if story_url not in progress["stories"]:
            progress["stories"][story_url] = {"completed_chapters": []}
        completed_chapters = progress["stories"][story_url]["completed_chapters"]
        if chapter_url not in completed_chapters:
            completed_chapters.append(chapter_url)
        self.save_progress(job_id, progress)

    def get_completed_chapters(self, job_id: str, story_url: str) -> Set[str]:
        progress = self.load_progress(job_id)
        story_progress = progress.get("stories", {}).get(story_url, {})
        return set(story_progress.get("completed_chapters", []))