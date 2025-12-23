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
    # Heavily prioritize phrase matches, individual words have minimal impact
    search_query = {
        "bool": {
            "should": [
                # Phrase matches get very high priority (whole phrase together)
                {"match_phrase": {"content": {"query": query, "boost": 20.0}}},
                {"match_phrase": {"title": {"query": query, "boost": 30.0}}},
                {"match_phrase": {"content.with_diacritics": {"query": query, "boost": 25.0}}},
                {"match_phrase": {"title.with_diacritics": {"query": query, "boost": 35.0}}},
                # Individual word matches (very low priority, scattered words)
                {"match": {"content": {"query": query, "boost": 0.1}}},
                {"match": {"title": {"query": query, "boost": 0.3}}},
                {"match": {"content.with_diacritics": {"query": query, "boost": 0.15}}},
                {"match": {"title.with_diacritics": {"query": query, "boost": 0.4}}},
            ],
            "minimum_should_match": 1
        }
    }
    response = search_documents(INDEX_NAME, search_query, highlight_fields=["content", "title"])
    results = response.body['hits']['hits']
    return templates.TemplateResponse("index.html", {"request": request, "results": results, "query": query})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)