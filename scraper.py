import json
from unidecode import unidecode
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from elastic import client, create_index, insert_document, wait_for_elasticsearch, search_documents, delete_index

# Wait for Elasticsearch to be ready
wait_for_elasticsearch()

INDEX_NAME = "demonstration-1"
CONFIG_JSON = "index-config.json"

delete_index(INDEX_NAME)

with open(CONFIG_JSON, 'r', encoding='utf-8') as f:
    index_settings = json.load(f)

create_index(INDEX_NAME, index_settings)

def slugify(text):
    text = unidecode(text).lower()
    text = re.sub(r'[^a-z0-9 ]', '', text)
    text = re.sub(r'\s+', '-', text)
    text = text.strip('-')
    return text if text else 'default-slug'

def crawl_story_metadata(url):
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

def crawl_chapter(story_slug, chapter_number):
    """
    Crawls a single chapter content.
    """
    base_url = "https://truyenfull.vision"
    url = f"{base_url}/{story_slug}/chuong-{chapter_number}/"

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
            'last_updated': datetime.now()
        }

    except Exception as e:
        print(f"Error crawling chapter {chapter_number}: {e}")
        return None

def store_story_in_elasticsearch(story_data, story_id):
    """
    Stores story data in Elasticsearch using our elastic.py functions.
    """
    # Convert to our document format
    doc = {
        'title': story_data['title'],
        'author': story_data['author'],
        'description': story_data['description'],
        'content': story_data['description'],  # Use description as content for now
        'tags': story_data['genres'],
        'popularity': 0,  # Default popularity
        'last_updated': story_data['last_updated']
    }

    insert_document(INDEX_NAME, story_id, doc)
    print(f"Successfully stored story: {story_data['title']}")
    return True

def store_chapter_in_elasticsearch(chapter_data, story_id, chapter_number):
    """
    Stores chapter data in Elasticsearch.
    """
    chapter_id = f"{story_id}_chapter_{chapter_number}"

    # Store chapter as a separate document
    doc = {
        'story_id': story_id,
        'title': chapter_data['chapter_title'],
        'author': f"Chapter {chapter_number} of {story_id}",
        'description': f"Chapter {chapter_number}",
        'content': chapter_data['content'],
        'tags': ['chapter'],
        'popularity': chapter_number,  # Use chapter number as popularity indicator
        'last_updated': chapter_data['last_updated']
    }

    insert_document(INDEX_NAME, chapter_id, doc)
    print(f"Successfully stored chapter {chapter_number}: {chapter_data['chapter_title']}")
    return True

def crawl_and_store_story(url, start_chapter=1, end_chapter=10):
    """
    Main function to crawl story and chapters, adapted for our Elasticsearch setup.
    """
    # Get story ID from URL
    try:
        story_slug = [part for part in url.split('/') if part][-1]
    except IndexError:
        print(f"Invalid URL format: {url}")
        return None

    story_id = story_slug
    print(f"Processing story ID: {story_id}")

    # Check if story already exists
    try:
        # Try to search for existing story
        query = {"match": {"title": story_slug}}
        response = search_documents(INDEX_NAME, query)
        if response['hits']['total']['value'] > 0:
            print(f"Story '{story_slug}' already exists. Checking for new chapters...")
        else:
            # Crawl and store story metadata
            print(f"Story ID {story_id} not found. Crawling new story...")
            story_data = crawl_story_metadata(url)
            if story_data:
                store_story_in_elasticsearch(story_data, story_id)
            else:
                print("Failed to crawl story metadata")
                return None
    except Exception as e:
        print(f"Error checking existing story: {e}")

    # Crawl chapters
    print(f"Starting crawl from chapter {start_chapter} to {end_chapter - 1}...")

    for chapter_number in range(start_chapter, end_chapter):
        chapter_data = crawl_chapter(story_slug, chapter_number)
        if chapter_data:
            store_chapter_in_elasticsearch(chapter_data, story_id, chapter_number)
            print(f"Successfully crawled chapter {chapter_number}")
        else:
            print(f"Stopping crawl at chapter {chapter_number} (likely end of story or error).")
            break

    return {
        'id': story_id,
        'url': url,
        'chapters_crawled': range(start_chapter, chapter_number)
    }

# Test the adapted scraper
if __name__ == "__main__":
    with open("list.txt", "r", encoding="utf-8") as f:
        story_list = [line.strip() for line in f if line.strip()]
    for story_id in story_list:
        url = f"https://truyenfull.vision/{story_id}"
        result = crawl_and_store_story(url, start_chapter=1, end_chapter=11)  # Crawl first 10 chapters

    if result:
        print(f"\nCrawl finished for story: {result['id']}")
        print(f"URL: {result['url']}")
    else:
        print("\nFailed to crawl story.")
