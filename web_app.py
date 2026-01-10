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

    # Enrichment: Total chapters and Story Titles for UI
    story_info = {}
    for hit in results:
        s = hit.get("_source", {})
        hit_id = hit.get("_id", "")

        # Determine the story slug ID for fetching metadata
        if s.get("doc_type") == "chapter":
            # Extract slug from hit_id (e.g., 'story-slug_chuong-1')
            if "_chuong-" in hit_id:
                sid = hit_id.split("_chuong-")[0]
            else:
                sid = s.get("story_id")
        else:
            sid = hit_id

        if sid and (sid not in story_info or story_info[sid]["title"] is None):
            if sid not in story_info:
                story_info[sid] = {"count": 0, "title": None, "id": sid}

            # Fetch count and title
            if story_info[sid]["count"] == 0:
                story_info[sid]["count"] = get_chapter_count(INDEX_NAME, sid)

            try:
                story_doc = get_document_by_id(INDEX_NAME, sid)
                if story_doc:
                    story_info[sid]["title"] = story_doc.get("_source", {}).get("title")
            except Exception:
                pass

    for hit in results:
        s = hit.get("_source", {})
        hit_id = hit.get("_id", "")
        sid = (hit_id.split("_chuong-")[0] if "_chuong-" in hit_id else s.get("story_id")) if s.get("doc_type") == "chapter" else hit_id

        if sid and sid in story_info:
            hit["total_chapters"] = story_info[sid]["count"]
            hit["story_title"] = story_info[sid]["title"]
            hit["story_slug"] = story_info[sid]["id"]

            # Fallback for stories
            if not hit["story_title"] and s.get("doc_type") == "story":
                 hit["story_title"] = s.get("title")

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

    # Enrichment: Total chapters and Story Title
    total_chapters = 0
    story_title = None

    # Extract story slug for lookup
    if source.get("doc_type") == "chapter":
        sid = doc_id.split("_chuong-")[0] if "_chuong-" in doc_id else source.get("story_id")
    else:
        sid = doc_id

    if sid:
        total_chapters = get_chapter_count(INDEX_NAME, sid)
        # Fetch story title
        try:
            story_doc = get_document_by_id(INDEX_NAME, sid)
            if story_doc:
                story_title = story_doc.get("_source", {}).get("title")
            elif source.get("doc_type") == "story":
                story_title = source.get("title")
        except Exception:
            pass

    # If it's a story, find the first chapter
    first_chapter_id = None
    if source.get("doc_type") == "story":
        # Strategy 1: Direct ID guess (common pattern)
        lookups = [f"{doc_id}_chuong-1", f"{doc_id}_chuong-0", f"{doc_id}_chuong-01", f"{doc_id}_chuong-1-1"]
        try:
            res_ids = client.search(index=INDEX_NAME, body={"query": {"ids": {"values": lookups}}})
            hits_ids = getattr(res_ids, "body", res_ids).get("hits", {}).get("hits", [])
            if hits_ids:
                hits_ids.sort(key=lambda x: x["_source"].get("chapter_number", 999))
                first_chapter_id = hits_ids[0]["_id"]
        except Exception:
            pass

        # Strategy 2: Search by part of URL (slug) using wildcard for keyword
        if not first_chapter_id:
            try:
                res_url = client.search(
                    index=INDEX_NAME,
                    body={
                        "query": {
                            "bool": {
                                "must": [
                                    {"wildcard": {"source_url.keyword": f"*{doc_id}*"}},
                                    {"term": {"doc_type.keyword": "chapter"}}
                                ]
                            }
                        }
                    },
                    size=1,
                    sort=[{"chapter_number": {"order": "asc"}}]
                )
                hits_url = getattr(res_url, "body", res_url).get("hits", {}).get("hits", [])
                if hits_url:
                    first_chapter_id = hits_url[0]["_id"]
            except Exception:
                pass

        # Strategy 3: Query String search on ID
        if not first_chapter_id:
            try:
                res_qs = client.search(
                    index=INDEX_NAME,
                    body={
                        "query": {
                            "bool": {
                                "must": [
                                    {"query_string": {"query": f"{doc_id}*", "default_field": "_id"}},
                                    {"term": {"doc_type.keyword": "chapter"}}
                                ]
                            }
                        }
                    },
                    size=1,
                    sort=[{"chapter_number": {"order": "asc"}}]
                )
                hits_qs = getattr(res_qs, "body", res_qs).get("hits", {}).get("hits", [])
                if hits_qs:
                    first_chapter_id = hits_qs[0]["_id"]
            except Exception:
                pass

    return templates.TemplateResponse(
        "detail.html",
        {
            "request": request,
            "doc": source,
            "doc_id": doc_id,
            "prev_id": prev_id,
            "next_id": next_id,
            "total_chapters": total_chapters,
            "story_title": story_title,
            "first_id": first_chapter_id
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
