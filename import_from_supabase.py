from __future__ import annotations

import sys
from typing import Any, Dict, Iterable, List

from supabase import supabase
from scraper import init_index
from elastic import bulk_insert
from settings import INDEX_NAME


def _get_data_from_resp(res: Any) -> List[dict]:
    # supabase client may return object with .data or a dict
    if res is None:
        return []
    data = None
    try:
        data = getattr(res, "data", None)
    except Exception:
        data = None
    if data is None:
        try:
            data = res["data"]
        except Exception:
            data = res
    return data or []


def fetch_stories(limit: int | None = None) -> List[dict]:
    if supabase is None:
        raise RuntimeError("Supabase client not configured; set SUPABASE_URL and SUPABASE_KEY in .env")
    q = supabase.table("stories").select("*")
    if limit:
        q = q.limit(limit)
    res = q.execute()
    return _get_data_from_resp(res)


def fetch_chapters(limit: int | None = None) -> List[dict]:
    if supabase is None:
        raise RuntimeError("Supabase client not configured; set SUPABASE_URL and SUPABASE_KEY in .env")
    q = supabase.table("chapters").select("*")
    if limit:
        q = q.limit(limit)
    res = q.execute()
    return _get_data_from_resp(res)


def transform_story(row: dict) -> Dict[str, dict]:
    story_id = str(row.get("id") or row.get("story_id") or row.get("slug"))
    doc = {
        "doc_type": "story",
        "story_id": story_id,
        "title": row.get("title"),
        "author": row.get("author"),
        "description": row.get("description"),
        "content": row.get("description") or row.get("content"),
        "tags": row.get("genres") or row.get("tags") or [],
        "popularity": row.get("popularity") or 0,
        "last_updated": row.get("last_updated"),
        "source_url": row.get("source_url"),
    }
    return {story_id: doc}


def transform_chapter(row: dict) -> Dict[str, dict]:
    story_id = str(row.get("story_id") or row.get("story") or row.get("parent_id") or "unknown")
    chapter_number = row.get("chapter_number") or row.get("chapter") or row.get("num")
    chapter_number = int(chapter_number) if chapter_number is not None else 0
    doc_id = f"{story_id}_chapter_{chapter_number}"
    doc = {
        "doc_type": "chapter",
        "story_id": story_id,
        "chapter_number": chapter_number,
        "title": row.get("title") or f"Chapter {chapter_number}",
        "author": row.get("author") or f"Chapter {chapter_number} of {story_id}",
        "description": row.get("description"),
        "content": row.get("content"),
        "tags": row.get("tags") or ["chapter"],
        "popularity": row.get("popularity") or chapter_number,
        "last_updated": row.get("last_updated"),
        "source_url": row.get("source_url"),
    }
    return {doc_id: doc}


def batch_iter(items: Iterable, batch_size: int):
    batch = []
    for it in items:
        batch.append(it)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def import_all(story_limit: int | None = None, chapter_limit: int | None = None, batch_size: int = 500, dry_run: bool = False):
    init_index()

    stories = fetch_stories(limit=story_limit)
    print(f"Fetched {len(stories)} stories from Supabase")
    total_indexed = 0

    # index stories
    for b in batch_iter(stories, batch_size):
        docs: Dict[str, dict] = {}
        for row in b:
            docs.update(transform_story(row))
        if dry_run:
            print("DRY RUN - would index stories batch of size", len(docs))
        else:
            bulk_insert(INDEX_NAME, docs)
            total_indexed += len(docs)

    chapters = fetch_chapters(limit=chapter_limit)
    print(f"Fetched {len(chapters)} chapters from Supabase")

    for b in batch_iter(chapters, batch_size):
        docs = {}
        for row in b:
            docs.update(transform_chapter(row))
        if dry_run:
            print("DRY RUN - would index chapters batch of size", len(docs))
        else:
            bulk_insert(INDEX_NAME, docs)
            total_indexed += len(docs)

    print(f"Import complete. Total documents indexed: {total_indexed}")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Import data from Supabase into Elasticsearch")
    p.add_argument("--stories", type=int, default=None, help="limit number of stories to import")
    p.add_argument("--chapters", type=int, default=None, help="limit number of chapters to import")
    p.add_argument("--batch", type=int, default=500, help="bulk batch size")
    p.add_argument("--dry-run", action="store_true", help="don't write to ES; just print counts")
    args = p.parse_args()

    try:
        import_all(story_limit=args.stories, chapter_limit=args.chapters, batch_size=args.batch, dry_run=args.dry_run)
    except Exception as e:
        print("Import failed:", e)
        sys.exit(2)
