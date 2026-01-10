#!/usr/bin/env python
"""Import story JSON files to Supabase - imports both story metadata and chapters."""

import argparse
import json
import os
from pathlib import Path

try:
    from supabase import Client, create_client
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    print("❌ Missing dependencies: pip install supabase python-dotenv")
    exit(1)

# SQL Schema
SCHEMA_SQL = """
-- Stories table
CREATE TABLE IF NOT EXISTS stories (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT,
    description TEXT,
    genres TEXT[],
    source_url TEXT UNIQUE,
    image_url TEXT,
    total_chapters INTEGER DEFAULT 0,
    last_updated TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Chapters table
CREATE TABLE IF NOT EXISTS chapters (
    id SERIAL PRIMARY KEY,
    story_id INTEGER REFERENCES stories(id) ON DELETE CASCADE,
    chapter_number INTEGER NOT NULL,
    chapter_title TEXT,
    content TEXT,
    source_url TEXT UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_stories_genres ON stories USING GIN(genres);
CREATE INDEX IF NOT EXISTS idx_chapters_story_id ON chapters(story_id);
CREATE INDEX IF NOT EXISTS idx_chapters_number ON chapters(story_id, chapter_number);
"""


def get_client() -> Client | None:
    """Initialize Supabase client."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        print("❌ Missing SUPABASE_URL or SUPABASE_KEY in .env")
        return None

    return create_client(url, key)


def import_story(client: Client, json_file: Path) -> None:
    """Import story and chapters."""
    print(f"📖 Importing: {json_file.name}")

    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Upsert story
    story_record = {
        'title': data['title'],
        'author': data.get('author'),
        'description': data.get('description'),
        'genres': data.get('genres', []),
        'source_url': data['source_url'],
        'image_url': data.get('image_url'),
        'total_chapters': len(data.get('chapters', [])),
        'last_updated': data.get('last_updated')
    }

    result = client.table('stories').upsert(story_record, on_conflict='source_url').execute()

    # Get story ID
    try:
        story_id = result.data[0]['id']
    except (KeyError, IndexError):
        # Fallback: query by source_url
        query = client.table('stories').select('id').eq('source_url', data['source_url']).limit(1).execute()
        story_id = query.data[0]['id']

    # Upsert chapters
    chapters = data.get('chapters', [])
    for chapter in chapters:
        chapter_record = {
            'story_id': story_id,
            'chapter_number': chapter['chapter_number'],
            'chapter_title': chapter.get('chapter_title'),
            'content': chapter.get('content'),
            'source_url': chapter.get('source_url')
        }
        client.table('chapters').upsert(chapter_record, on_conflict='source_url').execute()

    print(f"  ✅ {data['title']} ({len(chapters)} chapters)")


def import_directory(client: Client, directory: Path) -> None:
    """Import all JSON files in directory."""
    json_files = list(directory.glob("**/*.json"))

    if not json_files:
        print(f"⚠️  No JSON files found in {directory}")
        return

    print(f"\n📚 Found {len(json_files)} files")
    print(f"{'=' * 60}\n")

    success = 0
    failed = 0

    for json_file in json_files:
        try:
            import_story(client, json_file)
            success += 1
        except Exception as e:
            print(f"  ❌ Failed: {json_file.name} - {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"📊 Summary: {success} succeeded, {failed} failed")
    print(f"{'=' * 60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Import story JSON files to Supabase"
    )

    parser.add_argument('path', help='Path to JSON file or directory')
    parser.add_argument(
        '--create-tables',
        action='store_true',
        help='Show SQL schema for creating tables'
    )

    args = parser.parse_args()

    # Show schema and exit
    if args.create_tables:
        print("\n📋 Run this SQL in Supabase SQL Editor:\n")
        print(SCHEMA_SQL)
        return

    # Get client
    client = get_client()
    if not client:
        return

    path = Path(args.path)

    # Import file or directory
    if path.is_file() and path.suffix == '.json':
        import_story(client, path)
    elif path.is_dir():
        import_directory(client, path)
    else:
        print(f"❌ Invalid path: {path}")


if __name__ == "__main__":
    main()