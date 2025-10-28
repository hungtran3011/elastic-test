from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from elastic import client, search_documents
import json

app = FastAPI()
templates = Jinja2Templates(directory="templates")

INDEX_NAME = "demonstration-1"

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "results": None})

@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, query: str):
    # Complex bool query with both diacritic-aware and diacritic-insensitive matching
    search_query = {
        "bool": {
            "must": [
                {"match": {"content": {"query": query}}},
            ],
            "should": [
                # Regular matching (without diacritics)
                {"match": {"title": {"query": query, "boost": 2.0}}},
                {"match_phrase": {"content": {"query": query, "boost": 3.0}}},
                {"match_phrase": {"title": {"query": query, "boost": 5.0}}},
                # Exact diacritic matching (higher boost for precision)
                {"match": {"content.with_diacritics": {"query": query, "boost": 4.0}}},
                {"match": {"title.with_diacritics": {"query": query, "boost": 6.0}}},
                {"match_phrase": {"content.with_diacritics": {"query": query, "boost": 8.0}}},
                {"match_phrase": {"title.with_diacritics": {"query": query, "boost": 10.0}}},
            ]
        }
    }
    response = search_documents(INDEX_NAME, search_query, highlight_fields=["content", "title"])
    results = response.body['hits']['hits']
    return templates.TemplateResponse("index.html", {"request": request, "results": results, "query": query})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)