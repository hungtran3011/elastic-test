from __future__ import annotations

import json
import unicodedata

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from apscheduler.schedulers.background import BackgroundScheduler

from elastic import client, search_documents, wait_for_elasticsearch, ensure_index, get_document_by_id, get_chapter_count
# from scraper import init_index, sync_from_list
from import_from_supabase import import_all
from settings import INDEX_NAME, SCRAPE_INTERVAL_MINUTES, INDEX_CONFIG_JSON
from supabase_helper import supabase
import os

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


_scheduler: BackgroundScheduler | None = None

def init_index() -> None:
    wait_for_elasticsearch()
    with open(INDEX_CONFIG_JSON, "r", encoding="utf-8") as f:
        index_settings = json.load(f)
    ensure_index(INDEX_NAME, index_settings)


def _has_diacritics(text: str) -> bool:
    normalized = unicodedata.normalize("NFD", text)
    return any(unicodedata.combining(ch) for ch in normalized)

def sync_from_list():
    import_all()


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
    _scheduler.add_job(
        _run_sync_job,
        "interval",
        minutes=SCRAPE_INTERVAL_MINUTES,
        id="scrape_sync",
        replace_existing=True,
    )
    _scheduler.start()


@app.on_event("shutdown")
def _shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "results": None,
            "query": "",
            "page": 1,
            "total_pages": 0,
            "total_hits": 0,
            "pages": [],
        },
    )


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, query: str, page: int = 1):
    per_page = 10
    page = max(1, int(page))
    offset = (page - 1) * per_page

    has_diacritics = _has_diacritics(query)
    should: list[dict] = []

    # Prefer exact diacritics matches when the user types diacritics.
    if has_diacritics:
        should.append(
            {
                "multi_match": {
                    "query": query,
                    "fields": [
                        "title.with_diacritics^60",
                        "content.with_diacritics^30",
                    ],
                    "type": "phrase",
                    "slop": 1,
                }
            }
        )

    # Accent-insensitive phrase match (folding) as a general fallback.
    should.append(
        {
            "multi_match": {
                "query": query,
                "fields": [
                    "title^10",
                    "content^5",
                ],
                "type": "phrase",
                "slop": 3,
            }
        }
    )

    # Require all query terms to appear, even if split across title/content.
    if has_diacritics:
        should.append(
            {
                "multi_match": {
                    "query": query,
                    "fields": [
                        "title.with_diacritics^12",
                        "content.with_diacritics^6",
                    ],
                    "type": "cross_fields",
                    "operator": "and",
                    "boost": 3,
                }
            }
        )

    should.append(
        {
            "multi_match": {
                "query": query,
                "fields": [
                    "title^4",
                    "content^2",
                ],
                "type": "cross_fields",
                "operator": "and",
                "boost": 2,
            }
        }
    )

    # Fuzzy fallback for typos, but still require all terms.
    should.append(
        {
            "multi_match": {
                "query": query,
                "fields": ["title", "content"],
                "fuzziness": "AUTO",
                "prefix_length": 1,
                "operator": "and",
                "boost": 0.3,
            }
        }
    )

    search_query = {
        "bool": {
            "should": should,
            "minimum_should_match": 1,
        }
    }

    response = search_documents(
        INDEX_NAME,
        search_query,
        highlight_fields=["content", "title"],
        from_=offset,
        size=per_page,
    )

    body = getattr(response, "body", response)
    hits_obj = body.get("hits", {}) if isinstance(body, dict) else {}
    total_obj = hits_obj.get("total", 0)
    if isinstance(total_obj, dict):
        total_hits = int(total_obj.get("value", 0))
    else:
        total_hits = int(total_obj or 0)
    results = hits_obj.get("hits", [])

    # Enrichment: Total chapters for UI
    story_counts = {}
    for hit in results:
        s = hit.get("_source", {})
        sid = s.get("story_id")
        if sid and sid not in story_counts:
            story_counts[sid] = get_chapter_count(INDEX_NAME, sid)

    for hit in results:
        sid = hit.get("_source", {}).get("story_id")
        if sid:
            hit["total_chapters"] = story_counts.get(sid, 0)

    total_pages = (total_hits + per_page - 1) // per_page if total_hits else 0
    window = 10
    start_page = max(1, page - window // 2)
    end_page = min(total_pages, start_page + window - 1)
    start_page = max(1, end_page - window + 1)
    pages = list(range(start_page, end_page + 1)) if total_pages else []

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "results": results,
            "query": query,
            "page": page,
            "total_pages": total_pages,
            "total_hits": total_hits,
            "pages": pages,
        },
    )


@app.get("/document/{doc_id}", response_class=HTMLResponse)
async def document_detail(request: Request, doc_id: str):
    doc = get_document_by_id(INDEX_NAME, doc_id)
    if not doc:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    source = doc.get("_source", {})

    # Simple logic for Prev/Next (based on chapter number if available)
    prev_id = None
    next_id = None

    if source.get("doc_type") == "chapter":
        story_id = source.get("story_id")
        chapter_num = source.get("chapter_number")

        if chapter_num is not None:
             # Look for prev/next by searching ES
             try:
                 # Search for Prev
                 prev_q = {
                     "bool": {
                         "must": [
                             {"term": {"story_id.keyword": story_id}},
                             {"term": {"chapter_number": chapter_num - 1}},
                             {"term": {"doc_type.keyword": "chapter"}}
                         ]
                     }
                 }
                 p_resp = search_documents(INDEX_NAME, prev_q, size=1)
                 p_hits = getattr(p_resp, "body", p_resp).get("hits", {}).get("hits", [])
                 if p_hits:
                     prev_id = p_hits[0]["_id"]

                 # Search for Next
                 next_q = {
                     "bool": {
                         "must": [
                             {"term": {"story_id.keyword": story_id}},
                             {"term": {"chapter_number": chapter_num + 1}},
                             {"term": {"doc_type.keyword": "chapter"}}
                         ]
                     }
                 }
                 n_resp = search_documents(INDEX_NAME, next_q, size=1)
                 n_hits = getattr(n_resp, "body", n_resp).get("hits", {}).get("hits", [])
                 if n_hits:
                     next_id = n_hits[0]["_id"]
             except Exception:
                 pass

    # Process content to handle <br> and \n
    content = source.get("content", "")
    if content:
        # Normalize: turn escaped <br> or literal <br> strings into real newlines
        content = content.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        content = content.replace("&lt;br&gt;", "\n").replace("&lt;br/&gt;", "\n")
        # Then convert double newlines to paragraphs or single to <br> for clean mapping
        content = content.replace("\n\n", "</p><p>").replace("\n", "<br>")
        source["content"] = content

    # Enrichment: Total chapters
    total_chapters = 0
    if source.get("story_id"):
        total_chapters = get_chapter_count(INDEX_NAME, source.get("story_id"))

    return templates.TemplateResponse(
        "detail.html",
        {
            "request": request,
            "doc": source,
            "doc_id": doc_id,
            "prev_id": prev_id,
            "next_id": next_id,
            "total_chapters": total_chapters
        }
    )


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
