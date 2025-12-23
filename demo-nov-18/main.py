from elasticsearch import Elasticsearch
import json
import time

# Connect to Elasticsearch
client = Elasticsearch("http://localhost:9200")

def wait_for_elasticsearch():
    for _ in range(60):
        try:
            if client.ping():
                print("Elasticsearch is ready.")
                return
        except Exception as e:
            print(f"Waiting for Elasticsearch... {e}")
            time.sleep(1)
    raise Exception("Elasticsearch not ready after 60 seconds")

def create_index_with_similarity(index_name, similarity_type, k1=None, b=None):
    """Create index with specified similarity"""
    settings = {
        "settings": {
            "number_of_shards": 1,
            "analysis": {
                "analyzer": {
                    "vietnamese_text": {
                        "tokenizer": "icu_tokenizer",
                        "filter": ["lowercase", "icu_folding"]
                    }
                }
            }
        },
        "mappings": {
            "properties": {
                "title": {
                    "type": "text",
                    "analyzer": "vietnamese_text",
                    "term_vector": "with_positions_offsets_payloads"  # Needed for script scoring
                },
                "content": {
                    "type": "text",
                    "analyzer": "vietnamese_text",
                    "term_vector": "with_positions_offsets_payloads"  # Needed for script scoring
                }
            }
        }
    }

    if similarity_type == "vsm":
        settings["settings"]["index"] = {
            "similarity": {
                "default": {
                    "type": "classic"
                }
            }
        }
    elif similarity_type == "bm25":
        settings["settings"]["index"] = {
            "similarity": {
                "default": {
                    "type": "BM25",
                    "k1": k1 or 1.2,
                    "b": b or 0.75
                }
            }
        }

    if client.indices.exists(index=index_name):
        client.indices.delete(index=index_name)

    client.indices.create(index=index_name, body=settings)
    print(f"Index '{index_name}' created with {similarity_type} similarity.")

def index_documents(index_name, documents):
    """Index documents into Elasticsearch"""
    for doc in documents:
        client.index(index=index_name, id=doc["id"], body={
            "title": doc["title"],
            "content": doc["content"]
        })
    print(f"Indexed {len(documents)} documents into '{index_name}'.")

def tokenize_query(query):
    """Tokenize query using Vietnamese analyzer"""
    response = client.indices.analyze(
        index="temp_index",  # Need an index for analysis
        body={
            "analyzer": "vietnamese_text",
            "text": query
        }
    )
    tokens = [token["token"] for token in response["tokens"]]
    print(f"Query: '{query}'")
    print(f"Tokens: {tokens}")
    return tokens

def search_top_n(index_name, query, n=5, similarity_type="bm25"):
    """Search and return top N results"""
    body = {
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["title^2", "content"]
            }
        },
        "size": n
    }

    response = client.search(index=index_name, body=body)
    results = []
    for hit in response["hits"]["hits"]:
        results.append({
            "id": hit["_id"],
            "score": hit["_score"],
            "title": hit["_source"]["title"],
            "content": hit["_source"]["content"][:200] + "..." if len(hit["_source"]["content"]) > 200 else hit["_source"]["content"]
        })
    return results

def merge_results(vsm_results, bm25_results, method="score_combination"):
    """Merge results from VSM and BM25 using different methods"""
    if method == "score_combination":
        # Combine scores with weights
        combined = {}
        for result in vsm_results:
            combined[result["id"]] = {
                "doc": result,
                "vsm_score": result["score"],
                "bm25_score": 0
            }

        for result in bm25_results:
            if result["id"] in combined:
                combined[result["id"]]["bm25_score"] = result["score"]
            else:
                combined[result["id"]] = {
                    "doc": result,
                    "vsm_score": 0,
                    "bm25_score": result["score"]
                }

        # Calculate combined score (weighted average)
        for doc_id, data in combined.items():
            data["combined_score"] = 0.5 * data["vsm_score"] + 0.5 * data["bm25_score"]

        # Sort by combined score and return top 5
        sorted_results = sorted(combined.values(), key=lambda x: x["combined_score"], reverse=True)[:5]
        return [{"id": item["doc"]["id"], "vsm_score": item["vsm_score"], "bm25_score": item["bm25_score"], "title": item["doc"]["title"], "content": item["doc"]["content"]} for item in sorted_results]

    elif method == "rank_combination":
        # Use Reciprocal Rank Fusion (RRF)
        combined = {}
        for i, result in enumerate(vsm_results):
            rank = i + 1
            combined[result["id"]] = {
                "doc": result,
                "vsm_score": result["score"],
                "bm25_score": 0,
                "rrf_score": 1.0 / (60 + rank)  # RRF formula
            }

        for i, result in enumerate(bm25_results):
            rank = i + 1
            if result["id"] in combined:
                combined[result["id"]]["bm25_score"] = result["score"]
                combined[result["id"]]["rrf_score"] += 1.0 / (60 + rank)
            else:
                combined[result["id"]] = {
                    "doc": result,
                    "vsm_score": 0,
                    "bm25_score": result["score"],
                    "rrf_score": 1.0 / (60 + rank)
                }

        # Sort by RRF score
        sorted_results = sorted(combined.values(), key=lambda x: x["rrf_score"], reverse=True)[:5]
        return [{"id": item["doc"]["id"], "vsm_score": item["vsm_score"], "bm25_score": item["bm25_score"], "title": item["doc"]["title"], "content": item["doc"]["content"]} for item in sorted_results]

def main():
    # Wait for Elasticsearch
    wait_for_elasticsearch()

    # Load test data
    with open("test-data.json", "r", encoding="utf-8") as f:
        documents = json.load(f)

    # Create temporary index for tokenization
    create_index_with_similarity("temp_index", "bm25")

    # Test query
    query = "Kế hoạch học tập"

    print("=== TÁCH TỪ TRUY VẤN ===")
    tokens = tokenize_query(query)

    # Create indices with different similarities
    print("\n=== TẠO CHỈ MỤC ===")
    create_index_with_similarity("vsm_index", "vsm")
    create_index_with_similarity("bm25_index", "bm25", k1=1, b=0.8)

    # Index documents
    print("\n=== INDEXING DOCUMENTS ===")
    index_documents("vsm_index", documents)
    index_documents("bm25_index", documents)

    # Wait for indexing
    time.sleep(2)

    # Search with VSM
    print("\n=== TOP 5 THEO VSM ===")
    vsm_results = search_top_n("vsm_index", query, 5, similarity_type="vsm")
    for i, result in enumerate(vsm_results, 1):
        print(f"{i}. ID: {result['id']}, Score: {result['score']:.4f}")
        print(f"   Title: {result['title']}")
        print(f"   Content: {result['content']}")
        print()

    # Search with BM25
    print("=== TOP 5 THEO BM25 (k=1, b=0.8) ===")
    bm25_results = search_top_n("bm25_index", query, 5, similarity_type="bm25")
    for i, result in enumerate(bm25_results, 1):
        print(f"{i}. ID: {result['id']}, Score: {result['score']:.4f}")
        print(f"   Title: {result['title']}")
        print(f"   Content: {result['content']}")
        print()

    # Merge results
    print("=== HỢP NHẤT KẾT QUẢ (Score Combination) ===")
    merged_results = merge_results(vsm_results, bm25_results, method="score_combination")
    for i, result in enumerate(merged_results, 1):
        print(f"{i}. ID: {result['id']}, VSM: {result['vsm_score']:.4f}, BM25: {result['bm25_score']:.4f}")
        print(f"   Title: {result['title']}")
        print(f"   Content: {result['content']}")
        print()

if __name__ == "__main__":
    main()

