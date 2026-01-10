import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Any

try:
    from supabase_client import Client, create_client
    from dotenv import load_dotenv
    load_dotenv()
    import os
except ImportError:
    print("pip install supabase python-dotenv")
    exit(1)


def get_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None
    return create_client(url, key)


def create_tables(client: Client) -> None:
    print("""
        CREATE TABLE stories (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT,
            description TEXT,
            genres TEXT[],
            source_url TEXT UNIQUE,
            image_url TEXT,
            total_chapters INTEGER DEFAULT 0,
            last_updated TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        
        CREATE TABLE chapters (
            id SERIAL PRIMARY KEY,
            story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
            chapter_number INTEGER NOT NULL,
            chapter_title TEXT,
            content TEXT,
            source_url TEXT UNIQUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        
        CREATE INDEX idx_stories_genres ON stories USING GIN(genres);
        CREATE INDEX idx_chapters_story_id ON chapters(story_id);
        CREATE INDEX idx_chapters_number ON chapters(story_id, chapter_number);
    """)


def import_story_jsonb(client: Client, json_file: Path) -> None:
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    record = {
        'title': data['title'],
        'author': data.get('author'),
        'description': data.get('description'),
        'genres': data.get('genres', []),
        'source_url': data['source_url'],
        'image_url': data.get('image_url'),
        'total_chapters': len(data.get('chapters', [])),
        'last_updated': data.get('last_updated'),
        'data': data
    }
    result = client.table('stories').upsert(record, on_conflict='source_url').execute()

def import_story_chapters(client: Client, json_file: Path) -> None:
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
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
    story_result = client.table('stories').upsert(story_record, on_conflict='source_url').execute()
    story_id = story_result.data[0]['id']
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
def import_story_both(client: Client, json_file: Path) -> None:
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    story_record = {
        'title': data['title'],
        'author': data.get('author'),
        'description': data.get('description'),
        'genres': data.get('genres', []),
        'source_url': data['source_url'],
        'image_url': data.get('image_url'),
        'total_chapters': len(data.get('chapters', [])),
        'last_updated': data.get('last_updated'),
    }
    story_result = client.table('stories').upsert(story_record, on_conflict='source_url').execute()
    try:
        story_id = story_result.data[0]['id']
    except Exception:
        q = client.table('stories').select('id').eq('source_url', data['source_url']).limit(1).execute()
        story_id = q.data[0]['id']
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

def import_directory(client: Client, directory: Path) -> None:
    json_files = list(directory.glob("**/*.json"))
    for json_file in json_files:
        try:
            import_story_both(client, json_file)
        except Exception as e:
            continue

def main():
    parser = argparse.ArgumentParser(description="import story JSON to Supabase")
    parser.add_argument('path', help='Path to JSON file or directory')
    parser.add_argument('--create-tables', action='store_true',
                       help='Show SQL to create tables')

    args = parser.parse_args()

    client = get_supabase_client()
    if not client:
        print("Error.")
        return
    if args.create_tables:
        create_tables(client)
        return
    path = Path(args.path)
    if path.is_file() and path.suffix == '.json':
        import_story_both(client, path)
    elif path.is_dir():
        import_directory(client, path)


if __name__ == "__main__":
    main()
