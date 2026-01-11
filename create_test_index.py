#!/usr/bin/env python
"""Create a test index with ~50 story documents for evaluation."""

import json
import requests
from settings import ELASTICSEARCH_URL, INDEX_CONFIG_JSON

# Test index name
TEST_INDEX_NAME = "test-stories-50"
SOURCE_INDEX = "demonstration-2"


def create_index_with_config():
    """Create test index with same configuration as main index."""
    print(f"Creating index: {TEST_INDEX_NAME}")
    
    with open(INDEX_CONFIG_JSON, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Create index
    resp = requests.put(
        f"{ELASTICSEARCH_URL}/{TEST_INDEX_NAME}",
        json=config,
        headers={"Content-Type": "application/json"}
    )
    
    if resp.status_code in [200, 201]:
        print(f"✅ Index created: {TEST_INDEX_NAME}")
    elif resp.status_code == 400 and "resource_already_exists" in resp.text:
        print(f"⚠️  Index already exists: {TEST_INDEX_NAME}")
    else:
        print(f"❌ Error creating index: {resp.status_code} - {resp.text}")
        return False
    
    return True


def fetch_stories(limit=50):
    """Fetch story documents from source index."""
    print(f"\nFetching {limit} stories from {SOURCE_INDEX}...")
    
    query = {
        "query": {
            "term": {"doc_type.keyword": "story"}
        },
        "size": limit,
        "_source": True
    }
    
    resp = requests.post(
        f"{ELASTICSEARCH_URL}/{SOURCE_INDEX}/_search",
        json=query,
        headers={"Content-Type": "application/json"}
    )
    
    if resp.status_code != 200:
        print(f"❌ Error fetching stories: {resp.status_code}")
        return []
    
    data = resp.json()
    hits = data.get("hits", {}).get("hits", [])
    
    stories = []
    for hit in hits:
        stories.append({
            "_id": hit["_id"],
            "_source": hit["_source"]
        })
    
    print(f"✅ Fetched {len(stories)} stories")
    return stories


def bulk_index_stories(stories):
    """Bulk index stories to test index."""
    print(f"\nIndexing {len(stories)} stories to {TEST_INDEX_NAME}...")
    
    if not stories:
        return
    
    # Build bulk request
    bulk_body = []
    for story in stories:
        bulk_body.append(json.dumps({"index": {"_index": TEST_INDEX_NAME, "_id": story["_id"]}}))
        bulk_body.append(json.dumps(story["_source"]))
    
    bulk_data = "\n".join(bulk_body) + "\n"
    
    resp = requests.post(
        f"{ELASTICSEARCH_URL}/_bulk",
        data=bulk_data,
        headers={"Content-Type": "application/x-ndjson"}
    )
    
    if resp.status_code == 200:
        result = resp.json()
        errors = result.get("errors", False)
        if errors:
            print(f"⚠️  Some documents failed to index")
        else:
            print(f"✅ Successfully indexed {len(stories)} stories")
    else:
        print(f"❌ Error bulk indexing: {resp.status_code}")


def export_story_ids(stories, output_file="test_story_ids.json"):
    """Export story IDs for reference."""
    story_ids = [s["_id"] for s in stories]
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            "index": TEST_INDEX_NAME,
            "count": len(story_ids),
            "story_ids": story_ids
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Exported story IDs to: {output_file}")


def main():
    print("=" * 60)
    print("Creating Test Index with 50 Stories")
    print("=" * 60)
    
    # Step 1: Create index
    if not create_index_with_config():
        return
    
    # Step 2: Fetch stories
    stories = fetch_stories(limit=50)
    if not stories:
        print("❌ No stories found")
        return
    
    # Step 3: Index stories
    bulk_index_stories(stories)
    
    # Step 4: Export IDs for reference
    export_story_ids(stories)
    
    print("\n" + "=" * 60)
    print(f"✅ Test index ready: {TEST_INDEX_NAME}")
    print(f"   Update evaluate_search.py to use: INDEX_NAME = '{TEST_INDEX_NAME}'")
    print("=" * 60)


if __name__ == "__main__":
    main()
