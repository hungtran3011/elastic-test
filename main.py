from elastic import client, create_index, delete_index, insert_document, wait_for_elasticsearch, search_documents
import json

wait_for_elasticsearch()

INDEX_NAME = "demonstration-1"

word_query = "dao duc"
query = {
  "bool": {
            "must": [
                {"match": {"content": {"query": word_query}}},
            ],
            "should": [
                # Regular matching (without diacritics)
                {"match": {"title": {"query": word_query, "boost": 2.0}}},
                {"match_phrase": {"content": {"query": word_query, "boost": 3.0}}},
                {"match_phrase": {"title": {"query": word_query, "boost": 5.0}}},
                # Exact diacritic matching (higher boost for precision)
                {"match": {"content.with_diacritics": {"query": word_query, "boost": 4.0}}},
                {"match": {"title.with_diacritics": {"query": word_query, "boost": 6.0}}},
                {"match_phrase": {"content.with_diacritics": {"query": word_query, "boost": 8.0}}},
                {"match_phrase": {"title.with_diacritics": {"query": word_query, "boost": 10.0}}},
            ]
        }
}

response = search_documents(INDEX_NAME, query, highlight_fields=["content"])
print(response)

with open("search-results.json", "w", encoding="utf-8") as f:
    json.dump(response.body, f, ensure_ascii=False, indent=2)

# print("Search Results:")
# for hit in response['hits']['hits']:
#     print(f"Document ID: {hit['_id']}")
#     print(f"Score (Ranking): {hit['_score']}")
#     print(f"Title: {hit['_source']['title']}")
#     print(f"Content: {hit['_source']['content'][:150]}...")
#     if 'highlight' in hit:
#         print("Excerpts:")
#         for field, highlights in hit['highlight'].items():
#             for highlight in highlights:  
#                 print(f"  {field}: {highlight}")
#     print("---")

# # Tokenizer test
# print("\n--- Tokenizer Test ---")
# tokenizer_test_response = client.indices.analyze(
#   index=INDEX_NAME,
#   body={
#     "analyzer": "vietnamese_text",
#     "text": "Đại học Bách khoa Hà Nội"
#   }
# )
# print("Tokens for 'Đại học Bách khoa Hà Nội':")
# for token in tokenizer_test_response['tokens']:
#     print(f"- {token['token']}")
# print("---")