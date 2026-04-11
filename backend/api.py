"""
Product Comparison API

Runs alongside the browser extension. The extension calls this server to
trigger scraping, profiling, and comparison — then polls for the result.

Start with:
    uv run uvicorn backend.api:app --reload --port 8000
"""

import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Product Comparison API", version="1.0.0")

# Allow all origins — required for browser extension requests (chrome-extension://)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store. Resets on server restart (no persistence, per spec).
_jobs: dict[str, dict] = {}


# ── Request models ────────────────────────────────────────────────────────────

class CompareRequest(BaseModel):
    urls: list[str]


class RecommendRequest(BaseModel):
    answers: dict[str, str]  # question_id → answer string


# ── Background job runner ─────────────────────────────────────────────────────

def _run_job(job_id: str, urls: list[str]) -> None:
    """Runs the full scrape → profile → compare pipeline in a background thread."""
    import logging
    from .scraper import scrape_product_with_enrichment
    from .profiler import generate_profile
    from .comparator import generate_comparison

    log = logging.getLogger(__name__)
    job  = _jobs[job_id]
    skipped: list[str] = []   # human-readable skip reasons shown in the result

    try:
        # ── Stage 1: Scrape ───────────────────────────────────────────────────
        scraped = []
        for i, url in enumerate(urls, 1):
            job["progress"] = f"Scraping product {i} of {len(urls)}…"
            try:
                data = scrape_product_with_enrichment(url)
                scraped.append(data)
                log.info("[Job %s] Scraped: %s", job_id[:8], data.title[:60])
            except Exception as exc:
                reason = f"Product {i} (URL: {url[:60]}…) — scraping failed: {exc}"
                skipped.append(reason)
                log.warning("[Job %s] Skipping product %d — %s", job_id[:8], i, exc)

            if i < len(urls):
                time.sleep(3)   # breathing room between requests

        if len(scraped) < 2:
            raise RuntimeError(
                f"Not enough products could be scraped (got {len(scraped)}, need at least 2). "
                + ("Skipped: " + " | ".join(skipped) if skipped else "")
            )

        # ── Stage 2: Profile ──────────────────────────────────────────────────
        profiles = []
        for i, data in enumerate(scraped, 1):
            job["progress"] = f"Analysing product {i} of {len(scraped)}: {data.title[:45]}…"
            try:
                profile = generate_profile(data)
                profiles.append(profile)
                log.info("[Job %s] Profiled: %s", job_id[:8], data.title[:60])
            except Exception as exc:
                reason = f"'{data.title[:50]}' — profiling failed: {exc}"
                skipped.append(reason)
                log.warning("[Job %s] Skipping profile for '%s' — %s", job_id[:8], data.title[:40], exc)

            if i < len(scraped):
                time.sleep(2)

        if len(profiles) < 2:
            raise RuntimeError(
                f"Not enough products could be analysed (got {len(profiles)}, need at least 2). "
                + ("Skipped: " + " | ".join(skipped) if skipped else "")
            )

        # ── Stage 3: Compare ──────────────────────────────────────────────────
        job["progress"] = "Generating comparison, recommendation & questionnaire…"
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
            "skipped_products": skipped,   # empty list if all succeeded
        }
        job["status"] = "complete"
        job["progress"] = "Done"
        if skipped:
            log.warning("[Job %s] Completed with %d skipped product(s).", job_id[:8], len(skipped))

    except Exception as exc:
        log.error("[Job %s] Fatal error: %s", job_id[:8], exc)
        job["status"] = "error"
        job["error"]  = str(exc)
        job["progress"] = "Failed"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/platforms")
def get_platforms():
    from .platforms import SUPPORTED_PLATFORMS
    return {
        "platforms": [
            {"name": p.name, "base_url": p.base_url}
            for p in SUPPORTED_PLATFORMS
        ]
    }


@app.post("/compare")
def start_comparison(request: CompareRequest):
    if len(request.urls) < 2:
        raise HTTPException(status_code=400, detail="At least 2 product URLs are required.")
    if len(request.urls) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 product URLs allowed.")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "running",
        "progress": "Starting…",
        "result": None,
        "error": None,
    }

    thread = threading.Thread(target=_run_job, args=(job_id, request.urls), daemon=True)
    thread.start()

    return {"job_id": job_id}


@app.get("/compare/{job_id}")
def get_comparison(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job


@app.post("/compare/{job_id}/recommend")
def get_recommendation(job_id: str, request: RecommendRequest):
    """Return a personalised product recommendation based on the user's questionnaire answers."""
    from .questionnaire import generate_personalized_recommendation

    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    if job["status"] != "complete":
        raise HTTPException(status_code=400, detail="Job not yet complete.")

    profiles = job.get("_profiles")
    if not profiles:
        raise HTTPException(status_code=400, detail="Profile data not available.")

    questions = job.get("result", {}).get("questionnaire", {}).get("questions", [])
    return generate_personalized_recommendation(profiles, questions, request.answers)
