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
from settings import INDEX_NAME, SCRAPE_INTERVAL_MINUTES, INDEX_CONFIG_JSON, USE_COCCOC_TOKENIZER
from supabase_helper import supabase
from tokenizer_client import tokenize
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


def _display_text(text: str | None) -> str | None:
    """Normalize text for UI rendering.

    When Cốc Cốc tokenizer is enabled, tokenized text may contain underscores
    (e.g., "học_sinh"). We keep that in the index for better matching, but we
    don't want to show underscores in the UI.
    """
    if not text:
        return text
    if not USE_COCCOC_TOKENIZER:
        return text
    return text.replace("_", " ")

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
            "scope": "all",
            "page": 1,
            "total_pages": 0,
            "total_hits": 0,
            "pages": [],
        },
    )


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, query: str, page: int = 1, scope: str = "all"):
    per_page = 10
    page = max(1, int(page))
    offset = (page - 1) * per_page

    # Keep what the user typed for UI rendering.
    display_query = query

    # Use a tokenized query only for Elasticsearch matching.
    es_query = query

    # Tokenize query if Cốc Cốc tokenizer is enabled.
    # This ensures queries match the tokenized text stored in the index.
    if USE_COCCOC_TOKENIZER:
        es_query = tokenize(query, use_coccoc=True)

    scope_norm = (scope or "all").strip().lower()
    if scope_norm not in {"all", "title", "content"}:
        scope_norm = "all"
    search_title = scope_norm in {"all", "title"}
    search_content = scope_norm in {"all", "content"}

    has_diacritics = _has_diacritics(es_query)
    should: list[dict] = []

    tokens = [t for t in (es_query or "").strip().split() if t]
    min_token_len = min((len(t) for t in tokens), default=0)

    # Diacritics-aware matching when the user types diacritics.
    if has_diacritics:
        diacritic_fields: list[str] = []
        if search_title:
            diacritic_fields.append(
                "title.with_diacritics^30" if (search_title and search_content) else "title.with_diacritics^60"
            )
        if search_content:
            diacritic_fields.append(
                "content.with_diacritics^30" if (search_title and search_content) else "content.with_diacritics^60"
            )
        if diacritic_fields:
            should.append(
                {
                    "multi_match": {
                        "query": es_query,
                        "fields": diacritic_fields,
                        "type": "phrase",
                        "slop": 1,
                    }
                }
            )

    # Accent-insensitive relevance for general queries.
    # Keep phrase matching, but don't rely on it exclusively (word order can vary).
    phrase_fields: list[str] = []
    if search_title and search_content:
        # Neutral weighting when searching across fields.
        phrase_fields.extend(["title^6", "content^6"])
    else:
        if search_title:
            phrase_fields.append("title^10")
        if search_content:
            phrase_fields.append("content^10")
    if phrase_fields:
        should.append(
            {
                "multi_match": {
                    "query": es_query,
                    "fields": phrase_fields,
                    "type": "phrase",
                    "slop": 3,
                    "boost": 3,
                }
            }
        )

    # Broader match for non-diacritic input: allow partial matches while still
    # preferring results that match most terms.
    if not has_diacritics:
        best_fields: list[str] = []
        if search_title and search_content:
            best_fields.extend(["title^6", "content^6"])
        else:
            if search_title:
                best_fields.append("title^10")
            if search_content:
                best_fields.append("content^10")
        if best_fields:
            should.append(
                {
                    "multi_match": {
                        "query": es_query,
                        "fields": best_fields,
                        "type": "best_fields",
                        "operator": "or",
                        "minimum_should_match": "3<75%",
                        "tie_breaker": 0.3,
                        "boost": 2.5,
                    }
                }
            )

        # Only use autocomplete matching when explicitly searching titles.
        if scope_norm == "title":
            should.append(
                {
                    "match": {
                        "title.autocomplete": {
                            "query": es_query,
                            "operator": "and",
                            "boost": 2.5,
                        }
                    }
                }
            )

    # Require all query terms to appear.
    if has_diacritics:
        if search_title and search_content:
            should.append(
                {
                    "multi_match": {
                        "query": es_query,
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
        elif search_title:
            should.append(
                {
                    "match": {
                        "title.with_diacritics": {
                            "query": es_query,
                            "operator": "and",
                            "boost": 3,
                        }
                    }
                }
            )
        elif search_content:
            should.append(
                {
                    "match": {
                        "content.with_diacritics": {
                            "query": es_query,
                            "operator": "and",
                            "boost": 2,
                        }
                    }
                }
            )

    if search_title and search_content:
        should.append(
            {
                "multi_match": {
                    "query": es_query,
                    "fields": [
                        "title^2",
                        "content^2",
                    ],
                    "type": "cross_fields",
                    "operator": "and",
                    "boost": 2,
                }
            }
        )
    elif search_title:
        should.append({"match": {"title": {"query": es_query, "operator": "and", "boost": 2}}})
    elif search_content:
        should.append({"match": {"content": {"query": es_query, "operator": "and", "boost": 1.5}}})

    # Fuzzy fallback can be very noisy for short tokens (e.g. 'tu', 'chi').
    if min_token_len >= 4:
        fuzzy_fields: list[str] = []
        if search_title:
            fuzzy_fields.append("title^2")
        if search_content:
            fuzzy_fields.append("content")
        if not fuzzy_fields:
            fuzzy_fields = ["title^2", "content"]
        should.append(
            {
                "multi_match": {
                    "query": es_query,
                    "fields": fuzzy_fields,
                    "fuzziness": "AUTO",
                    "prefix_length": 1,
                    "operator": "and",
                    "boost": 0.2,
                }
            }
        )

    base_query = {
        "bool": {
            "should": should,
            "minimum_should_match": 1,
        }
    }

    # Strongly prefer story docs over chapter docs to avoid generic content hits
    # dominating title searches.
    if scope_norm == "content":
        doc_type_weights = {"story": 0.5, "chapter": 2.0}
    elif scope_norm == "title":
        doc_type_weights = {"story": 8.0, "chapter": 0.15}
    else:
        doc_type_weights = {"story": 6.0, "chapter": 0.2}

    functions: list[dict] = []

    functions.extend(
        [
            {"filter": {"term": {"doc_type.keyword": "story"}}, "weight": doc_type_weights["story"]},
            {"filter": {"term": {"doc_type.keyword": "chapter"}}, "weight": doc_type_weights["chapter"]},
        ]
    )

    search_query = {
        "function_score": {
            "query": base_query,
            "functions": functions,
            "score_mode": "first",
            "boost_mode": "multiply",
        }
    }

    response = search_documents(
        INDEX_NAME,
        search_query,
        highlight_fields=(
            ["title"]
            if scope_norm == "title"
            else (["content"] if scope_norm == "content" else ["content", "title"])
        ),
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

    # UI normalization: hide tokenizer underscores in rendered fields/highlights.
    for hit in results:
        src = hit.get("_source")
        if isinstance(src, dict):
            if "title" in src:
                src["title"] = _display_text(src.get("title"))
            if "content" in src:
                src["content"] = _display_text(src.get("content"))
            if "description" in src:
                src["description"] = _display_text(src.get("description"))

        if "story_title" in hit:
            hit["story_title"] = _display_text(hit.get("story_title"))

        hl = hit.get("highlight")
        if isinstance(hl, dict):
            for k, v in list(hl.items()):
                if isinstance(v, list):
                    hl[k] = [_display_text(s) for s in v]

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
            "query": display_query,
            "scope": scope_norm,
            "page": page,
            "total_pages": total_pages,
            "total_hits": total_hits,
            "pages": pages,
        },
    )


@app.get("/autocomplete")
async def autocomplete(query: str, limit: int = 8):
    q = (query or "").strip()
    if len(q) < 2:
        return JSONResponse({"suggestions": []})

    q_es = q
    if USE_COCCOC_TOKENIZER:
        q_es = tokenize(q, use_coccoc=True)

    try:
        limit_i = int(limit)
    except Exception:
        limit_i = 8
    limit_i = max(1, min(20, limit_i))

    has_diacritics = _has_diacritics(q)
    should: list[dict] = []

    # Prefer diacritics-aware prefix matching when the user types diacritics.
    if has_diacritics:
        should.append(
            {
                "match_phrase_prefix": {
                    "title.with_diacritics": {
                        "query": q_es,
                        "boost": 5,
                    }
                }
            }
        )

    # Use the ngram-backed autocomplete field for fast prefix-ish suggestions.
    should.append(
        {
            "match": {
                "title.autocomplete": {
                    "query": q_es,
                    "operator": "and",
                    "boost": 3,
                }
            }
        }
    )

    # Fallbacks (in case the autocomplete field isn't populated for some docs).
    should.append({"match_phrase_prefix": {"title": {"query": q_es, "boost": 1}}})

    body = {
        "query": {
            "bool": {
                "must": [
                    # Keep suggestions to story titles; chapters are usually not useful.
                    {"term": {"doc_type.keyword": "story"}},
                ],
                "should": should,
                "minimum_should_match": 1,
            }
        },
        "size": limit_i,
        "_source": ["title"],
        "sort": [
            {"_score": "desc"},
            {"popularity": {"order": "desc", "unmapped_type": "long"}},
        ],
    }

    try:
        res = client.search(index=INDEX_NAME, body=body)
        hits = getattr(res, "body", res).get("hits", {}).get("hits", [])
    except Exception:
        hits = []

    seen_titles: set[str] = set()
    suggestions: list[dict] = []
    for hit in hits:
        title = (hit.get("_source") or {}).get("title")
        if not title:
            continue
        display_title = _display_text(title) or title
        norm = (display_title or "").strip().lower()
        if not norm or norm in seen_titles:
            continue
        seen_titles.add(norm)
        suggestions.append({"title": display_title, "id": hit.get("_id")})
        if len(suggestions) >= limit_i:
            break

    return JSONResponse({"suggestions": suggestions})


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
            "doc": {
                **(source or {}),
                "title": _display_text((source or {}).get("title")),
                "content": _display_text((source or {}).get("content")),
                "description": _display_text((source or {}).get("description")),
            },
            "doc_id": doc_id,
            "prev_id": prev_id,
            "next_id": next_id,
            "total_chapters": total_chapters,
            "story_title": _display_text(story_title),
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
