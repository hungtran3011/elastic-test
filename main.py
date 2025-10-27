from elastic import client, create_index, delete_index, insert_document, wait_for_elasticsearch, search_documents
import json

wait_for_elasticsearch()

INDEX_NAME = "demonstration-1"
DATA_JSON = "test-data.json"
CONFIG_JSON = "index-config.json"

# Create index with custom analyzer and tokenizer
with open(CONFIG_JSON, 'r', encoding='utf-8') as f:
    index_settings = json.load(f)

delete_index(INDEX_NAME)
create_index(INDEX_NAME, index_settings)

# Load documents from JSON file
with open(DATA_JSON, 'r', encoding='utf-8') as f:
    data = json.load(f)

documents = {item['id']: {'title': item['title'], 'content': item['content']} for item in data}

for doc_id, doc in documents.items():
    insert_document(INDEX_NAME, doc_id, doc)

client.indices.refresh(index=INDEX_NAME)
print(f"Inserted {len(documents)} documents and refreshed index.\n")

query = {
  "bool": {
    "must": [
      {"match": {"content": "bách khoa"}},
      {"match": {"content": "chiến binh"}}
    ]
  }
}

response = search_documents(INDEX_NAME, query, highlight_fields=["content"])
# print(response)

with open("search-results.json", "w", encoding="utf-8") as f:
    json.dump(response.body, f, ensure_ascii=False, indent=2)

print("Search Results:")
for hit in response['hits']['hits']:
    print(f"Document ID: {hit['_id']}")
    print(f"Score (Ranking): {hit['_score']}")
    print(f"Title: {hit['_source']['title']}")
    print(f"Content: {hit['_source']['content'][:150]}...")
    if 'highlight' in hit:
        print("Excerpts:")
        for field, highlights in hit['highlight'].items():
            for highlight in highlights:  
                print(f"  {field}: {highlight}")
    print("---")