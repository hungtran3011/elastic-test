from __future__ import annotations

import os
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

try:
    from supabase import Client, create_client
except Exception:
    Client = Any
    create_client = None


def get_supabase_client() -> Optional[Client]:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    print(url)
    print(key)
    if not url or not key or create_client is None:
        return None
    return create_client(url, key)


supabase = get_supabase_client()


def upsert_story(table: str, story: dict) -> None:
    if supabase is None:
        return
    supabase.table(table).upsert(story).execute()


def upsert_chapter(table: str, chapter: dict) -> None:
    if supabase is None:
        return
    supabase.table(table).upsert(chapter).execute()


def get_story_state(table: str, story_id: str) -> Optional[dict]:
    if supabase is None:
        return None
    res = supabase.table(table).select("id,last_crawled_chapter,last_crawled_at").eq("id", story_id).limit(1).execute()
    data = getattr(res, "data", None)
    if not data:
        return None
    return data[0]


def import_story_jsonb(story_data: dict) -> None:
    if supabase is None:
        return
    record = {
        'title': story_data['title'],
        'author': story_data.get('author'),
        'description': story_data.get('description'),
        'genres': story_data.get('genres', []),
        'source_url': story_data['source_url'],
        'image_url': story_data.get('image_url'),
        'total_chapters': len(story_data.get('chapters', [])),
        'last_updated': story_data.get('last_updated'),
        'data': story_data
    }
    supabase.table('stories').upsert(record, on_conflict='source_url').execute()

def import_story_chapters(story_data: dict) -> None:
    if supabase is None:
        return
    story_record = {
        'title': story_data['title'],
        'author': story_data.get('author'),
        'description': story_data.get('description'),
        'genres': story_data.get('genres', []),
        'source_url': story_data['source_url'],
        'image_url': story_data.get('image_url'),
        'total_chapters': len(story_data.get('chapters', [])),
        'last_updated': story_data.get('last_updated')
    }
    story_result = supabase.table('stories').upsert(story_record, on_conflict='source_url').execute()
    story_id = story_result.data[0]['id']
    for chapter in story_data.get('chapters', []):
        chapter_record = {
            'story_id': story_id,
            'chapter_number': chapter['chapter_number'],
            'chapter_title': chapter.get('chapter_title'),
            'content': chapter.get('content'),
            'source_url': chapter.get('source_url')
        }
        supabase.table('chapters').upsert(chapter_record, on_conflict='source_url').execute()


def search_stories(query: str, limit: int = 10) -> Optional[list]:
    if supabase is None:
        return None
    res = supabase.table('stories').select('*').textSearch('title', query).limit(limit).execute()
    return getattr(res, 'data', None)

def get_story_chapters(story_id: str) -> Optional[list]:
    if supabase is None:
        return None
    res = supabase.table('chapters').select('*').eq('story_id', story_id).order('chapter_number').execute()
    return getattr(res, 'data', None)