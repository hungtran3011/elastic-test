from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from apscheduler.schedulers.background import BackgroundScheduler

from elastic import client, search_documents, wait_for_elasticsearch
from scraper import init_index, sync_from_list
from settings import INDEX_NAME, SCRAPE_INTERVAL_MINUTES
from supabase import supabase

app = FastAPI()
templates = Jinja2Templates(directory="templates")


_scheduler: BackgroundScheduler | None = None


def _run_sync_job() -> None:
    # best-effort background sync
    try:
        init_index()
        sync_from_list()
    except Exception as e:
        print(f"[sync] error: {e}")


@app.on_event("startup")
def _startup() -> None:
    # Ensure ES + index exist before serving.
    try:
        wait_for_elasticsearch()
        init_index()
    except Exception as e:
        print(f"[startup] elastic init error: {e}")

    global _scheduler
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(_run_sync_job, "interval", minutes=SCRAPE_INTERVAL_MINUTES, id="scrape_sync", replace_existing=True)
    _scheduler.start()


@app.on_event("shutdown")
def _shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "results": None, "query": ""})

@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, query: str):
    # Improved Query Processing
    search_query = {
        "bool": {
            "should": [
                # 1. HIGH PRIORITY: Phrase Match with Slop
                # Matches "kinh tế" or "kinh tế học" when user types "kinh tế"
                {
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "title^10", 
                            "title.with_diacritics^10", 
                            "content^5", 
                            "content.with_diacritics^5"
                        ],
                        "type": "phrase",
                        "slop": 3
                    }
                },
                
                # 2. MEDIUM PRIORITY: All Terms Present (AND)
                # Matches documents containing ALL words, even if scattered
                {
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "title^4", 
                            "title.with_diacritics^4", 
                            "content^2", 
                            "content.with_diacritics^2"
                        ],
                        "type": "best_fields",
                        "operator": "and", 
                        "boost": 2
                    }
                },
                
                # 3. LOW PRIORITY: Partial Match (Recall Fallback)
                # Catches documents with at least 75% of the words
                {
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "title", 
                            "title.with_diacritics", 
                            "content", 
                            "content.with_diacritics"
                        ],
                        "type": "best_fields",
                        "minimum_should_match": "75%"
                    }
                },

                # 4. LOWEST PRIORITY: Fuzzy Match (Typo Tolerance)
                # Catches "elstic" -> "elastic" or "viet nam" -> "viet nam"
                {
                    "multi_match": {
                        "query": query,
                        # Target only the base fields (folded/no-accents) for best fuzzy performance
                        "fields": ["title", "content"], 
                        "fuzziness": "AUTO",
                        "prefix_length": 1,  # Assume the first letter is correct for speed
                        "boost": 0.5         # Very low boost; only changes ranking if nothing else matches well
                    }
                }
            ],
            "minimum_should_match": 1
        }
    }
    
    response = search_documents(INDEX_NAME, search_query, highlight_fields=["content", "title"])
    results = response.body['hits']['hits']
    return templates.TemplateResponse("index.html", {"request": request, "results": results, "query": query})


@app.get("/healthz")
async def healthz():
    es_ok = False
    try:
        es_ok = bool(client.ping())
    except Exception:
        es_ok = False

    db_ok = supabase is not None
    return JSONResponse({"ok": es_ok and db_ok, "elasticsearch": es_ok, "supabase_configured": db_ok, "index": INDEX_NAME})


@app.post("/admin/sync")
async def admin_sync():
    # synchronous trigger; good for demos
    init_index()
    results = sync_from_list()
    return JSONResponse({"synced": len(results), "results": results})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)