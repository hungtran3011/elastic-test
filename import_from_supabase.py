from __future__ import annotations

import sys
from typing import Any, Dict, Iterable, List
import os
import requests

import json

from elastic import bulk_insert, ensure_index, wait_for_elasticsearch
from settings import INDEX_NAME, INDEX_CONFIG_JSON, USE_COCCOC_TOKENIZER
from tokenizer_client import tokenize


def fetch_stories(limit: int | None = None) -> List[dict]:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Supabase client not configured; set SUPABASE_URL and SUPABASE_KEY in .env")

    # Use REST API directly with pagination
    endpoint = f"{url}/rest/v1/stories"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Prefer": "count=exact",
    }

    all_data = []
    offset = 0
    page_size = 1000

    while True:
        params = {"select": "*", "offset": str(offset), "limit": str(page_size)}
        if limit and len(all_data) >= limit:
            break

        resp = requests.get(endpoint, headers=headers, params=params)
        resp.raise_for_status()
        batch = resp.json()

        if not batch:
            break

        all_data.extend(batch)
        print(f"Fetched {len(batch)} stories (total: {len(all_data)})")

        if len(batch) < page_size:
            break
        offset += page_size

    if limit:
        return all_data[:limit]
    return all_data


def fetch_chapters(limit: int | None = None) -> List[dict]:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Supabase client not configured; set SUPABASE_URL and SUPABASE_KEY in .env")

    endpoint = f"{url}/rest/v1/chapters"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Prefer": "count=exact",
    }

    all_data = []
    offset = 0
    page_size = 1000

    while True:
        params = {"select": "*", "offset": str(offset), "limit": str(page_size)}
        if limit and len(all_data) >= limit:
            break

        resp = requests.get(endpoint, headers=headers, params=params)
        resp.raise_for_status()
        batch = resp.json()

        if not batch:
            break

        all_data.extend(batch)
        print(f"Fetched {len(batch)} chapters (total: {len(all_data)})")

        if len(batch) < page_size:
            break
        offset += page_size

    if limit:
        return all_data[:limit]
    return all_data


def extract_id_from_url(source_url: str) -> str:
    """Extract document ID from source_url.
    E.g. https://truyenfull.vision/su-phu-mang-thai-con-cua-ai/chuong-3/
    becomes su-phu-mang-thai-con-cua-ai_chuong-3
    """
    if not source_url:
        return "unknown"

    # Remove https://truyenfull.vision/ prefix
    path = source_url.replace("https://truyenfull.vision/", "")
    # Remove trailing slash
    path = path.rstrip("/")
    # Replace remaining slashes with underscores
    doc_id = path.replace("/", "_")
    return doc_id if doc_id else "unknown"


def transform_story(row: dict) -> Dict[str, dict]:
    source_url = row.get("source_url") or ""
    doc_id = extract_id_from_url(source_url)
    story_id = doc_id
    
    # Tokenize text fields if Cốc Cốc tokenizer is enabled
    title = row.get("title")
    content = row.get("description") or row.get("content")
    
    if USE_COCCOC_TOKENIZER:
        if title:
            title = tokenize(title, use_coccoc=True)
        if content:
            content = tokenize(content, use_coccoc=True)
    
    doc = {
        "doc_type": "story",
        "story_id": story_id,
        "title": title,
        "author": row.get("author"),
        "description": row.get("description"),
        "content": content,
        "tags": row.get("genres") or row.get("tags") or [],
        "popularity": row.get("popularity") or 0,
        "last_updated": row.get("last_updated"),
        "source_url": row.get("source_url"),
    }
    return {doc_id: doc}


def transform_chapter(row: dict) -> Dict[str, dict]:
    source_url = row.get("source_url") or ""
    doc_id = extract_id_from_url(source_url)
    story_id = str(row.get("story_id") or row.get("story") or row.get("parent_id") or "unknown")
    chapter_number = row.get("chapter_number") or row.get("chapter") or row.get("num")
    chapter_number = int(chapter_number) if chapter_number is not None else 0
    
    # Tokenize text fields if Cốc Cốc tokenizer is enabled
    title = row.get("title") or f"Chapter {chapter_number}"
    content = row.get("content")
    
    if USE_COCCOC_TOKENIZER:
        if title:
            title = tokenize(title, use_coccoc=True)
        if content:
            content = tokenize(content, use_coccoc=True)
    
    doc = {
        "doc_type": "chapter",
        "story_id": story_id,
        "chapter_number": chapter_number,
        "title": title,
        "author": row.get("author") or f"Chapter {chapter_number} of {story_id}",
        "description": row.get("description"),
        "content": content,
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


def import_all(story_limit: int | None = None, chapter_limit: int | None = None, batch_size: int = 500,
               dry_run: bool = False):
    # IMPORTANT: ensure the index is created with the intended analyzers/mappings
    # BEFORE inserting any docs. Otherwise Elasticsearch will auto-create the index
    # with default mappings and accent-insensitive search will not work.
    wait_for_elasticsearch()
    try:
        with open(INDEX_CONFIG_JSON, "r", encoding="utf-8") as f:
            index_settings = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to load INDEX_CONFIG_JSON='{INDEX_CONFIG_JSON}': {e}")

    ensure_index(INDEX_NAME, index_settings)

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