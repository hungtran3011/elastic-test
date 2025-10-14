from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
import time

client = Elasticsearch("http://localhost:9200")

def wait_for_elasticsearch():
    for _ in range(60):  # wait up to 60 seconds
        try:
            if client.ping():
                print("Elasticsearch is ready.")
                return
        except Exception as e:
            print(f"Waiting for Elasticsearch... {e}")
            time.sleep(1)
    raise Exception("Elasticsearch not ready after 60 seconds")

def create_index(index_name, settings=None):
    if not client.indices.exists(index=index_name):
        if settings is None:
            settings = {}
        client.indices.create(index=index_name, body=settings)
        print(f"Index '{index_name}' created.")
    else:
        print(f"Index '{index_name}' already exists.")

def delete_index(index_name):
    if client.indices.exists(index=index_name):
        client.indices.delete(index=index_name)
        print(f"Index '{index_name}' deleted.")
    else:
        print(f"Index '{index_name}' does not exist.")

def insert_document(index_name, doc_id, document):
    client.index(index=index_name, id=doc_id, body=document)
    print(f"Document with ID '{doc_id}' inserted into index '{index_name}'.")

def bulk(index_name, documents):
    actions = [
        {
            "_index": index_name,
            "_id": doc_id,
            "_source": doc
        }
        for doc_id, doc in documents.items()
    ]
    bulk(client, actions)
    print(f"Bulk inserted {len(documents)} documents into index '{index_name}'.")

def update_document(index_name, doc_id, document):
    client.update(index=index_name, id=doc_id, body={"doc": document})
    print(f"Document with ID '{doc_id}' updated in index '{index_name}'.")

def delete_document(index_name, doc_id):
    client.delete(index=index_name, id=doc_id)
    print(f"Document with ID '{doc_id}' deleted from index '{index_name}'.")

def search_documents(index_name, query, highlight_fields=None):
    body = {
        "query": query,
        "highlight": {
            "fields": {field: {} for field in highlight_fields} if highlight_fields else {"content": {}}
        }
    }
    response = client.search(index=index_name, body=body)
    return response
