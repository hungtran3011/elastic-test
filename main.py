from elastic import client, create_index, insert_document, wait_for_elasticsearch, search_documents
import json

wait_for_elasticsearch()

INDEX_NAME = "demonstration-1"
DATA_JSON = "test-data.json"

# Create index with custom analyzer and tokenizer
index_settings = {
  "settings": {
    "analysis": {
      "analyzer": {
        "vietnamese_text": {
          "tokenizer": "icu_tokenizer",
          "filter": ["lowercase", "icu_folding"]
        },
        "autocomplete": {
          "tokenizer": "edge_ngram_tokenizer",
          "filter": ["lowercase"]
        }
      },
      "tokenizer": {
        "edge_ngram_tokenizer": {
          "type": "edge_ngram",
          "min_gram": 2,
          "max_gram": 15,
          "token_chars": ["letter", "digit"]
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "title": {
        "type": "text",
        "analyzer": "vietnamese_text",
        "search_analyzer": "vietnamese_text",
        "fields": {
          "autocomplete": {
            "type": "text",
            "analyzer": "autocomplete",
            "search_analyzer": "standard"
          }
        }
      },
      "author": { "type": "keyword" },
      "genres": { "type": "keyword" },
      "tags": { "type": "keyword" },
      "description": {
        "type": "text",
        "analyzer": "vietnamese_text"
      },
      "popularity": { "type": "integer" },
      "last_updated": { "type": "date" }
    }
  }
}

create_index(INDEX_NAME, index_settings)

# Load documents from JSON file
with open(DATA_JSON, 'r', encoding='utf-8') as f:
    data = json.load(f)

documents = {item['id']: {'title': item['title'], 'content': item['content']} for item in data}

for doc_id, doc in documents.items():
    insert_document(INDEX_NAME, doc_id, doc)

# Test search with highlighting for excerpts and ranking
query = {
    "match": {"content": "bách khoa"}
}

response = search_documents(INDEX_NAME, query, highlight_fields=["content"])

print("Search Results:")
for hit in response['hits']['hits']:
    print(f"Document ID: {hit['_id']}")
    print(f"Score (Ranking): {hit['_score']}")
    print(f"Title: {hit['_source']['title']}")
    print(f"Content: {hit['_source']['content']}")
    if 'highlight' in hit:
        print("Excerpts:")
        for field, highlights in hit['highlight'].items():
            for highlight in highlights:
                print(f"  {field}: {highlight}")
    print("---")