from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup
from unidecode import unidecode

from elastic import ensure_index, insert_document, wait_for_elasticsearch
from settings import (
    INDEX_CONFIG_JSON,
    INDEX_NAME,
    SCRAPE_BASE_URL,
    SCRAPE_LIST_FILE,
    SUPABASE_CHAPTERS_TABLE,
    SUPABASE_STORIES_TABLE,
)
from supabase_helper import get_story_state, upsert_chapter, upsert_story


def init_index() -> None:
    wait_for_elasticsearch()
    with open(INDEX_CONFIG_JSON, "r", encoding="utf-8") as f:
        index_settings = json.load(f)
    ensure_index(INDEX_NAME, index_settings)

def slugify(text):
    text = unidecode(text).lower()
    text = re.sub(r'[^a-z0-9 ]', '', text)
    text = re.sub(r'\s+', '-', text)
    text = text.strip('-')
    return text if text else 'default-slug'

def crawl_story_metadata(url: str) -> Optional[dict]:
    """
    Crawls story metadata from the webpage.
    """
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            print(f"Failed to retrieve the page. Status code: {response.status_code}")
            return None

        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract title
        title_tag = soup.find('h3', class_='title')
        title = title_tag.text.strip() if title_tag else "Title not found"

        # Extract image URL
        image_tag = soup.find('img', itemprop='image')
        image_url = image_tag['src'] if image_tag and 'src' in image_tag.attrs else "Image URL not found"

        # Extract author
        author_tag = soup.find('a', itemprop='author')
        author_name = author_tag.text.strip() if author_tag else "Author not found"

        # Extract description
        description_div = soup.find('div', itemprop='description')
        description = "Not found"
        if description_div:
            if description_div.find(['p', 'div']):
                description = "\n".join(tag.get_text(strip=True) for tag in description_div.find_all(['p', 'div']) if tag.get_text(strip=True)).strip()
            else:
                description = description_div.decode_contents()
                description = re.sub(r'<br\s*/?>', '\n', description)
                description = re.sub(r'</?(b|i|strong)\s*/?>', '\n', description)
                description = re.sub(r'</?a[^>]*>', '', description)
                description = description.strip()

        # Extract genres
        genres = []
        infor_div = soup.find('div', class_='info')
        if infor_div:
            genre_tags = infor_div.find_all('a', itemprop='genre')
            genres = [tag.text.strip() for tag in genre_tags] if genre_tags else []

        return {
            'title': title,
            'author': author_name,
            'image_url': image_url,
            'description': description,
            'genres': genres,
            'source_url': url,
            'last_updated': datetime.now()
        }

    except Exception as e:
        print(f"Error crawling story metadata: {e}")
        return None

def crawl_chapter(story_slug: str, chapter_number: int) -> Optional[dict]:
    """
    Crawls a single chapter content.
    """
    url = f"{SCRAPE_BASE_URL}/{story_slug}/chuong-{chapter_number}/"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return None  # Chapter not found

        soup = BeautifulSoup(response.text, 'html.parser')
        title_elem = soup.find(class_='chapter-title')
        content_div = soup.find('div', class_='chapter-c')

        chapter_title = title_elem.text.strip().split(":")[-1] if title_elem else f"Chapter {chapter_number}"

        content = "Content not found"
        if content_div:
            for script in content_div(["script", "style"]):
                script.decompose()
            content = content_div.get_text(separator='\n').strip()

        if content == "Content not found":
            return None

        return {
            'chapter_title': chapter_title.strip(),
            'chapter_number': chapter_number,
            'content': content,
            'source_url': url,
            'last_updated': datetime.now()
        }

    except Exception as e:
        print(f"Error crawling chapter {chapter_number}: {e}")
        return None

def store_story_in_elasticsearch(story_data: dict, story_id: str) -> None:
    """
    Stores story data in Elasticsearch using our elastic.py functions.
    """
    # Convert to our document format
    doc = {
        'doc_type': 'story',
        'story_id': story_id,
        'title': story_data['title'],
        'author': story_data['author'],
        'description': story_data['description'],
        'content': story_data['description'],  # Use description as content for now
        'tags': story_data['genres'],
        'popularity': 0,  # Default popularity
        'last_updated': story_data['last_updated']
    }

    # client.index() acts as upsert.
    insert_document(INDEX_NAME, story_id, doc)


def store_story_in_supabase(story_data: dict, story_id: str) -> None:
    story_row = {
        "id": story_id,
        "title": story_data.get("title"),
        "author": story_data.get("author"),
        "description": story_data.get("description"),
        "image_url": story_data.get("image_url"),
        "genres": story_data.get("genres"),
        "source_url": story_data.get("source_url"),
        "last_updated": story_data.get("last_updated").isoformat() if story_data.get("last_updated") else None,
        "last_crawled_at": datetime.utcnow().isoformat(),
    }
    upsert_story(SUPABASE_STORIES_TABLE, story_row)

def store_chapter_in_elasticsearch(chapter_data: dict, story_id: str, chapter_number: int) -> None:
    """
    Stores chapter data in Elasticsearch.
    """
    chapter_id = f"{story_id}_chapter_{chapter_number}"

    # Store chapter as a separate document
    doc = {
        'doc_type': 'chapter',
        'story_id': story_id,
        'title': chapter_data['chapter_title'],
        'author': f"Chapter {chapter_number} of {story_id}",
        'description': f"Chapter {chapter_number}",
        'content': chapter_data['content'],
        'tags': ['chapter'],
        'popularity': chapter_number,  # Use chapter number as popularity indicator
        'last_updated': chapter_data['last_updated'],
        'chapter_number': chapter_number,
        'source_url': chapter_data.get('source_url'),
    }
    insert_document(INDEX_NAME, chapter_id, doc)


def store_chapter_in_supabase(chapter_data: dict, story_id: str, chapter_number: int) -> None:
    chapter_id = f"{story_id}_chapter_{chapter_number}"
    row = {
        "id": chapter_id,
        "story_id": story_id,
        "chapter_number": chapter_number,
        "title": chapter_data.get("chapter_title"),
        "content": chapter_data.get("content"),
        "source_url": chapter_data.get("source_url"),
        "last_updated": chapter_data.get("last_updated").isoformat() if chapter_data.get("last_updated") else None,
    }
    upsert_chapter(SUPABASE_CHAPTERS_TABLE, row)

def sync_story(story_id: str, start_chapter: Optional[int] = None, end_chapter: int = 10_000) -> dict:
    """
    Syncs one story:
    - Ensures index exists
    - Crawls metadata (always)
    - Crawls chapters starting from last crawled chapter (if Supabase has state)
    - Upserts to Supabase (optional) + Elasticsearch

    end_chapter is an upper bound; crawl stops at first missing chapter.
    """
    init_index()

    story_slug = story_id
    url = f"{SCRAPE_BASE_URL}/{story_slug}"

    # Determine start chapter from DB state if not provided.
    if start_chapter is None:
        state = get_story_state(SUPABASE_STORIES_TABLE, story_id)
        if state and state.get("last_crawled_chapter"):
            try:
                start_chapter = int(state["last_crawled_chapter"]) + 1
            except Exception:
                start_chapter = 1
        else:
            start_chapter = 1

    story_data = crawl_story_metadata(url)
    if story_data:
        store_story_in_elasticsearch(story_data, story_id)
        store_story_in_supabase(story_data, story_id)

    chapters_added = 0
    last_ok = start_chapter - 1
    for chapter_number in range(start_chapter, end_chapter + 1):
        chapter_data = crawl_chapter(story_slug, chapter_number)
        if not chapter_data:
            break
        store_chapter_in_elasticsearch(chapter_data, story_id, chapter_number)
        store_chapter_in_supabase(chapter_data, story_id, chapter_number)
        chapters_added += 1
        last_ok = chapter_number

    # Persist crawl state to stories table (if present)
    upsert_story(
        SUPABASE_STORIES_TABLE,
        {
            "id": story_id,
            "last_crawled_chapter": last_ok if last_ok >= 1 else None,
            "last_crawled_at": datetime.utcnow().isoformat(),
        },
    )

    return {
        "id": story_id,
        "url": url,
        "start_chapter": start_chapter,
        "last_crawled_chapter": last_ok,
        "chapters_added": chapters_added,
    }


def sync_from_list(list_file: str = SCRAPE_LIST_FILE, end_chapter: int = 10_000) -> list[dict]:
    results: list[dict] = []
    with open(list_file, "r", encoding="utf-8") as f:
        story_ids = [line.strip() for line in f if line.strip()]
    for story_id in story_ids:
        results.append(sync_story(story_id, start_chapter=None, end_chapter=end_chapter))
    return results

if __name__ == "__main__":
    # CLI run: sync all stories in list.txt
    for item in sync_from_list():
        print(
            f"Synced {item['id']}: +{item['chapters_added']} chapters "
            f"(from {item['start_chapter']} to {item['last_crawled_chapter']})"
        )
