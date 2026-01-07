from __future__ import annotations

import os
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

try:
	from supabase import Client, create_client
except Exception:  # pragma: no cover
	Client = Any  # type: ignore
	create_client = None  # type: ignore


def get_supabase_client() -> Optional[Client]:
	url = os.getenv("SUPABASE_URL")
	key = os.getenv("SUPABASE_KEY")
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