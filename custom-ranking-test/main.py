from elastic import client, create_index, delete_index, insert_document, wait_for_elasticsearch, search_documents
import json

wait_for_elasticsearch()

INDEX_NAME = "test-ranking"
DATA_JSON = "test-data.json"
CONFIG_JSON = "index-config.json"