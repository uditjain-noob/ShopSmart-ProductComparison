"""
Product Comparison API

Runs alongside the browser extension. The extension calls this server to
trigger scraping, profiling, and comparison, then polls for the result.

Start locally with:
    uv run uvicorn backend.api:app --reload --port 8000
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .auth import create_token, get_current_user, hash_password, verify_password
from .database import (
    create_user,
    delete_list,
    get_all_comparisons,
    get_all_lists,
    get_comparison as get_saved_comparison,
    get_comparisons_for_list,
    get_list,
    get_product_urls_for_list,
    get_user_by_email,
    init_db,
    save_comparison,
    save_list,
)

app = FastAPI(title="Product Comparison API", version="1.1.0")
log = logging.getLogger(__name__)

# Allow all origins because browser extension origins are chrome-extension://...
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job stores. Jobs are scoped by user_id and intentionally remain
# transient; completed saved-list jobs are also persisted to Turso.
_jobs: dict[str, dict[str, Any]] = {}
_discover_jobs: dict[str, dict[str, Any]] = {}


# -- Request models ------------------------------------------------------------

class AuthRequest(BaseModel):
    email: str
    password: str


class ProductIn(BaseModel):
    url: str
    platform: str = "Unknown"
    title: str | None = None
    selected: bool = True


class SaveListRequest(BaseModel):
    name: str
    products: list[ProductIn] = []
    list_id: str | None = None


class CompareRequest(BaseModel):
    urls: list[str]


class SavedListCompareRequest(BaseModel):
    product_ids: list[str] | None = None
    urls: list[str] | None = None


class RecommendRequest(BaseModel):
    answers: dict[str, str]


class DiscoverBetterRequest(BaseModel):
    answers: dict[str, str]


class SaveComparisonRequest(BaseModel):
    job_id: str


# -- Startup ------------------------------------------------------------------

@app.on_event("startup")
def startup() -> None:
    init_db()


# -- Helpers ------------------------------------------------------------------

def _validate_compare_urls(urls: list[str]) -> None:
    if len(urls) < 2:
        raise HTTPException(status_code=400, detail="At least 2 product URLs are required.")
    if len(urls) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 product URLs allowed.")


def _safe_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in job.items()
        if key not in {"_profiles", "user_id", "save_list_id"}
    }


def _get_owned_job(job_id: str, user_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job or job.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job


def _get_owned_discover_job(discover_job_id: str, user_id: str) -> dict[str, Any]:
    job = _discover_jobs.get(discover_job_id)
    if not job or job.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"Discover job '{discover_job_id}' not found.")
    return job


def _start_job(user_id: str, urls: list[str], save_list_id: str | None = None) -> str:
    _validate_compare_urls(urls)
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "user_id": user_id,
        "save_list_id": save_list_id,
        "status": "running",
        "progress": "Starting...",
        "result": None,
        "error": None,
        "saved_comparison_id": None,
    }
    thread = threading.Thread(target=_run_job, args=(job_id, urls), daemon=True)
    thread.start()
    return job_id


# -- Background job runners ---------------------------------------------------

def _run_job(job_id: str, urls: list[str]) -> None:
    """Runs scrape -> profile -> compare in a background thread."""
    from .comparator import generate_comparison
    from .profiler import generate_profile
    from .scraper import scrape_product_with_enrichment

    job = _jobs[job_id]
    skipped: list[str] = []

    try:
        scraped = []
        for i, url in enumerate(urls, 1):
            job["progress"] = f"Scraping product {i} of {len(urls)}..."
            try:
                data = scrape_product_with_enrichment(url)
                scraped.append(data)
                log.info("[Job %s] Scraped: %s", job_id[:8], data.title[:60])
            except Exception as exc:
                reason = f"Product {i} (URL: {url[:60]}...) - scraping failed: {exc}"
                skipped.append(reason)
                log.warning("[Job %s] Skipping product %d - %s", job_id[:8], i, exc)

            if i < len(urls):
                time.sleep(3)

        if len(scraped) < 2:
            raise RuntimeError(
                f"Not enough products could be scraped (got {len(scraped)}, need at least 2). "
                + ("Skipped: " + " | ".join(skipped) if skipped else "")
            )

        profiles = []
        for i, data in enumerate(scraped, 1):
            job["progress"] = f"Analysing product {i} of {len(scraped)}: {data.title[:45]}..."
            try:
                profile = generate_profile(data)
                profiles.append(profile)
                log.info("[Job %s] Profiled: %s", job_id[:8], data.title[:60])
            except Exception as exc:
                reason = f"'{data.title[:50]}' - profiling failed: {exc}"
                skipped.append(reason)
                log.warning("[Job %s] Skipping profile for '%s' - %s", job_id[:8], data.title[:40], exc)

            if i < len(scraped):
                time.sleep(2)

        if len(profiles) < 2:
            raise RuntimeError(
                f"Not enough products could be analysed (got {len(profiles)}, need at least 2). "
                + ("Skipped: " + " | ".join(skipped) if skipped else "")
            )

        job["progress"] = "Generating comparison, recommendation & questionnaire..."
        comparison = generate_comparison(profiles)
        job["_profiles"] = profiles
        job["result"] = {
            "products": [
                {
                    "title": p.title,
                    "price": p.price,
                    "platform": p.platform,
                    "specs": p.specs,
                    "description_summary": p.description_summary,
                    "pros": p.pros,
                    "cons": p.cons,
                    "sentiment_score": p.sentiment_score,
                    "notable_quotes": p.notable_quotes,
                }
                for p in comparison.products
            ],
            "summary": comparison.summary,
            "recommendation": comparison.recommendation,
            "markdown": comparison.markdown,
            "questionnaire": comparison.questionnaire,
            "skipped_products": skipped,
        }

        if job.get("save_list_id"):
            job["saved_comparison_id"] = save_comparison(
                job["user_id"],
                job["save_list_id"],
                job["result"],
                profiles,
            )

        job["status"] = "complete"
        job["progress"] = "Done"
    except Exception as exc:
        log.error("[Job %s] Fatal error: %s", job_id[:8], exc)
        job["status"] = "error"
        job["error"] = str(exc)
        job["progress"] = "Failed"


def _run_discover_better(
    discover_job_id: str,
    profiles: list[Any],
    questions: list[dict[str, Any]],
    answers: dict[str, str],
) -> None:
    from .agent import find_better_products

    job = _discover_jobs[discover_job_id]
    try:
        job["progress"] = "Agent is starting up..."
        log.info("[DiscoverJob %s] Starting agent", discover_job_id[:8])

        def _update_progress(msg: str) -> None:
            job["progress"] = msg

        suggestions = find_better_products(profiles, questions, answers, progress_callback=_update_progress)
        job["suggestions"] = [
            {
                "title": s.title,
                "url": s.url,
                "price": s.price,
                "rating": s.rating,
                "reason": s.reason,
            }
            for s in suggestions
        ]
        job["status"] = "complete"
        job["progress"] = "Done"
    except Exception as exc:
        log.error("[DiscoverJob %s] Error: %s", discover_job_id[:8], exc)
        job["status"] = "error"
        job["error"] = str(exc)
        job["progress"] = "Failed"


# -- Public endpoints ----------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/platforms")
def get_platforms() -> dict[str, Any]:
    from .platforms import SUPPORTED_PLATFORMS

    return {
        "platforms": [
            {"name": p.name, "base_url": p.base_url}
            for p in SUPPORTED_PLATFORMS
        ]
    }


@app.post("/auth/signup")
def signup(request: AuthRequest) -> dict[str, Any]:
    email = request.email.lower().strip()
    if "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(request.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account already exists for that email.")

    user = create_user(email, hash_password(request.password))
    return {"token": create_token(user["id"], user["email"]), "email": user["email"]}


@app.post("/auth/login")
def login(request: AuthRequest) -> dict[str, Any]:
    user = get_user_by_email(request.email)
    if not user or not verify_password(request.password, user["hashed_pw"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return {"token": create_token(user["id"], user["email"]), "email": user["email"]}


@app.get("/auth/me")
def me(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return {"id": current_user["id"], "email": current_user["email"]}


# -- Protected comparison endpoints -------------------------------------------

@app.post("/compare")
def start_comparison(
    request: CompareRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    return {"job_id": _start_job(current_user["id"], request.urls)}


@app.get("/compare/{job_id}")
def get_comparison_job(
    job_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    return _safe_job(_get_owned_job(job_id, current_user["id"]))


@app.post("/compare/{job_id}/recommend")
def get_recommendation(
    job_id: str,
    request: RecommendRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    from .questionnaire import generate_personalized_recommendation

    job = _get_owned_job(job_id, current_user["id"])
    if job["status"] != "complete":
        raise HTTPException(status_code=400, detail="Job not yet complete.")
    profiles = job.get("_profiles")
    if not profiles:
        raise HTTPException(status_code=400, detail="Profile data not available.")
    questions = job.get("result", {}).get("questionnaire", {}).get("questions", [])
    return generate_personalized_recommendation(profiles, questions, request.answers)


@app.post("/compare/{job_id}/discover-better")
def start_discover_better(
    job_id: str,
    request: DiscoverBetterRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    job = _get_owned_job(job_id, current_user["id"])
    if job["status"] != "complete":
        raise HTTPException(status_code=400, detail="Comparison job not yet complete.")

    profiles = job.get("_profiles")
    if not profiles:
        raise HTTPException(status_code=400, detail="Profile data not available.")
    questions = job.get("result", {}).get("questionnaire", {}).get("questions", [])

    discover_job_id = str(uuid.uuid4())
    _discover_jobs[discover_job_id] = {
        "user_id": current_user["id"],
        "status": "running",
        "progress": "Starting search...",
        "suggestions": [],
        "error": None,
    }
    thread = threading.Thread(
        target=_run_discover_better,
        args=(discover_job_id, profiles, questions, request.answers),
        daemon=True,
    )
    thread.start()
    return {"discover_job_id": discover_job_id}


@app.get("/discover/{discover_job_id}")
def get_discover_better(
    discover_job_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    job = _get_owned_discover_job(discover_job_id, current_user["id"])
    return {key: value for key, value in job.items() if key != "user_id"}


# -- Protected saved list/comparison endpoints ---------------------------------

@app.post("/lists")
def create_or_update_list(
    request: SaveListRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    return save_list(
        current_user["id"],
        request.name.strip() or "Untitled List",
        [product.model_dump() for product in request.products],
        request.list_id,
    )


@app.put("/lists/{list_id}")
def update_list(
    list_id: str,
    request: SaveListRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return save_list(
            current_user["id"],
            request.name.strip() or "Untitled List",
            [product.model_dump() for product in request.products],
            list_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="List not found.") from exc


@app.get("/lists")
def list_saved_lists(current_user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    return get_all_lists(current_user["id"])


@app.get("/lists/{list_id}")
def get_saved_list(
    list_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    saved = get_list(current_user["id"], list_id)
    if not saved:
        raise HTTPException(status_code=404, detail="List not found.")
    return saved


@app.delete("/lists/{list_id}")
def remove_saved_list(
    list_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, bool]:
    if not delete_list(current_user["id"], list_id):
        raise HTTPException(status_code=404, detail="List not found.")
    return {"success": True}


@app.post("/lists/{list_id}/compare")
def compare_saved_list_products(
    list_id: str,
    request: SavedListCompareRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    try:
        urls = request.urls or get_product_urls_for_list(current_user["id"], list_id, request.product_ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="List not found.") from exc
    return {"job_id": _start_job(current_user["id"], urls, save_list_id=list_id)}


@app.post("/lists/{list_id}/comparisons")
def save_job_comparison(
    list_id: str,
    request: SaveComparisonRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    job = _get_owned_job(request.job_id, current_user["id"])
    if job["status"] != "complete" or not job.get("result"):
        raise HTTPException(status_code=400, detail="Comparison job is not complete.")
    if job.get("saved_comparison_id"):
        return {"comparison_id": job["saved_comparison_id"]}
    try:
        comparison_id = save_comparison(current_user["id"], list_id, job["result"], job.get("_profiles"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="List not found.") from exc
    job["saved_comparison_id"] = comparison_id
    return {"comparison_id": comparison_id}


@app.get("/lists/{list_id}/comparisons")
def list_comparisons_for_saved_list(
    list_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    try:
        return get_comparisons_for_list(current_user["id"], list_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="List not found.") from exc


@app.get("/comparisons")
def list_all_comparisons(current_user: dict[str, Any] = Depends(get_current_user)) -> list[dict[str, Any]]:
    return get_all_comparisons(current_user["id"])


@app.get("/comparisons/{comparison_id}")
def get_comparison_history_item(
    comparison_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    comparison = get_saved_comparison(current_user["id"], comparison_id)
    if not comparison:
        raise HTTPException(status_code=404, detail="Comparison not found.")
    return comparison
