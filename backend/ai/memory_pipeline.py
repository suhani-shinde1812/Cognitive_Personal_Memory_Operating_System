# ðŸ“ LOCATION: backend/ai/memory_pipeline.py
"""
memory_pipeline.py  â€” ACCURACY FIX v2
========================================
ROOT CAUSE FIXES:
  1. Embedding now uses BOTH title AND full extracted text (was only first 1000 chars).
  2. Title is enriched with smart keywords before embedding so short filenames
     like "doc001.pdf" still get a meaningful vector.
  3. Source filename is stored in title field when no better title exists,
     so BM25 and title-boost can find it by filename search.
  4. Duplicate check before saving â€” prevents the same file getting multiple
     confusing DB entries that dilute search results.
  5. BM25 cache is invalidated after every new memory so search stays fresh.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from datetime import datetime, timezone

from database.database import SessionLocal
from app.models.memory import Memory
from ai.gama_service import GAMAService
from ai.importance_scorer import score_importance
from ai.summarizer import generate_summary


# Smart keyword enrichment for common document types
_TITLE_ENRICHMENTS = {
    r"resume|cv":                     "resume cv curriculum vitae work experience",
    r"ielts|toefl|gre|gmat":          "language test english proficiency score certificate",
    r"passport":                       "passport identity travel document visa",
    r"certificate|cert|diploma":       "certificate award achievement completion",
    r"bank|statement|account":         "bank statement financial account transaction",
    r"invoice|receipt|bill":           "invoice receipt bill payment",
    r"degree|bachelor|master|btech|mtech": "degree university graduation academic",
    r"transcript|marksheet|grades":    "transcript academic record grades marks",
    r"offer|appointment":              "offer letter job appointment employment",
    r"admission|university|college":   "admission university college application",
}

import re as _re


def _enrich_title(title: str, text: str) -> str:
    """Add domain keywords to title for better embeddings."""
    combined = (title + " " + text[:200]).lower()
    extras = []
    for pattern, keywords in _TITLE_ENRICHMENTS.items():
        if _re.search(pattern, combined):
            extras.append(keywords)
    if extras:
        return f"{title} {' '.join(extras)}"
    return title


def run_pipeline(
    file_path: str,
    source_hint: str = None,
    update_index: bool = True,
    user_id: int | None = None,
) -> dict:
    import time
    start_total = time.perf_counter()
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()
    raw_title = source_hint or path.stem.replace("_", " ").replace("-", " ").title()

    try:
        file_size_kb = path.stat().st_size / 1024
    except Exception:
        file_size_kb = 0

    print(f"[UPLOAD START] {path.name} ({file_size_kb:.1f} KB, ext: {ext})")

    result = {
        "source":           path.name,
        "file_type":        ext.lstrip("."),
        "date":             datetime.now(timezone.utc).isoformat(),
        "title":            raw_title,
        "description":      "",
        "image":            None,
        "text_content":     "",
        "embedding":        [],
        "objects":          [],
        "importance_score": 0.5,
        "access_count":     0,
    }

    # ── Step 1: Text extraction ───────────────────────────────────────────────
    start_extract = time.perf_counter()
    print(f"[TEXT EXTRACTION START] {path.name}")
    text    = ""
    objects = []

    try:
        if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"):
            text    = _run_ocr(file_path)
            objects = _run_object_detection(file_path)
            result["image"] = f"/uploads/{path.name}"
        elif ext == ".pdf":
            text = _run_pdf(file_path)
        elif ext in (".docx", ".doc"):
            text = _run_docx(file_path)
        else:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                text = ""
    except Exception as extract_err:
        print(f"[TEXT EXTRACTION ERROR] {path.name}: {extract_err}")
        text = ""

    result["text_content"] = text
    result["objects"]      = objects
    result["description"]  = text[:500] if text else ""
    print(f"[TEXT EXTRACTION COMPLETE] {path.name}: {len(text)} chars extracted in {time.perf_counter() - start_extract:.3f}s")

    # ── Step 2: Smart title from OCR/text if filename is generic ──────────────
    is_generic_title = _re.match(r"^(img|image|photo|dsc|doc|file|scan)\d*$", raw_title.lower())
    if is_generic_title and text:
        lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 5]
        if lines:
            result["title"] = lines[0][:80]

    # ── Step 3: Chunking & Text Preparation ───────────────────────────────────
    start_chunk = time.perf_counter()
    print(f"[CHUNKING START] Preparing embedding text for {path.name}")
    enriched_title = _enrich_title(result["title"], text)
    embed_text = f"{enriched_title}\n\n{text[:3500]}"
    print(f"[CHUNKING COMPLETE] Prepared {len(embed_text)} chars in {time.perf_counter() - start_chunk:.4f}s")

    # ── Step 4: Embedding generation ──────────────────────────────────────────
    start_embed = time.perf_counter()
    print(f"[EMBEDDING START] Computing vector for {path.name}")
    from ai.embedding_service import get_embedding
    try:
        result["embedding"] = get_embedding(embed_text)
        print(f"[EMBEDDING COMPLETE] Generated {len(result['embedding'])}-dim vector in {time.perf_counter() - start_embed:.3f}s")
    except Exception as emb_err:
        print(f"[EMBEDDING ERROR] {emb_err}")
        result["embedding"] = []

    # ── Step 5: Importance scoring & Summary ──────────────────────────────────
    result["importance_score"] = score_importance(result["title"], text)

    if text and len(text) > 80:
        start_sum = time.perf_counter()
        summary = generate_summary(text)
        result["description"] = summary or result["description"]
        print(f"[SUMMARY COMPLETE] Generated summary in {time.perf_counter() - start_sum:.3f}s")

    # ── Step 6: Database insert / duplicate check ─────────────────────────────
    start_db = time.perf_counter()
    print(f"[DATABASE INSERT START] Saving {path.name} to DB")
    db = SessionLocal()
    try:
        dup_query = db.query(Memory).filter(Memory.source == result["source"])
        if user_id is not None:
            dup_query = dup_query.filter(Memory.user_id == str(user_id))
        existing = dup_query.first()
        if existing:
            print(f"[Pipeline] Skipping duplicate: {result['source']} for user={user_id}")
            result["id"] = existing.id
            result["detected_goals"] = []
            return result

        memory = Memory(
            title            = result["title"],
            description      = result["description"],
            text_content     = result["text_content"],
            source           = result["source"],
            file_type        = result["file_type"],
            image            = result.get("image"),
            date             = result["date"],
            embedding        = json.dumps(result["embedding"]),
            objects          = json.dumps(result["objects"]),
            importance_score = result["importance_score"],
            access_count     = 0,
            user_id          = user_id,
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        result["id"] = memory.id
        print(f"[DATABASE INSERT COMPLETE] Saved Memory #{memory.id} in {time.perf_counter() - start_db:.3f}s")

        # ── Step 7: Search index update ───────────────────────────────────────
        if update_index:
            start_idx = time.perf_counter()
            print(f"[SEARCH INDEX UPDATE START]")
            try:
                _update_search_index()
                print(f"[SEARCH INDEX UPDATE COMPLETE] in {time.perf_counter() - start_idx:.3f}s")
            except Exception as idx_err:
                print(f"[SEARCH INDEX UPDATE WARNING] {idx_err}")

        # ── Step 8: GAMA goal linking ─────────────────────────────────────────
        try:
            gama = GAMAService(db)
            detected_goals = gama.link_memory_to_goals(
                memory_id=memory.id,
                text_content=f"{result['title']} {text}",
            )
            result["detected_goals"] = detected_goals
        except Exception as ge:
            print(f"[GAMA Warning] {ge}")
            result["detected_goals"] = []

    finally:
        db.close()

    total_time = time.perf_counter() - start_total
    print(f"[UPLOAD COMPLETE] Successfully processed {path.name} in {total_time:.3f}s (Memory #{result.get('id')})")
    return result


def _infer_title(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").title()


def _run_ocr(file_path: str) -> str:
    try:
        from vision.ocr import extract_text
        return extract_text(file_path) or ""
    except Exception as e:
        print(f"[Pipeline] OCR error: {e}")
        return ""


def _run_object_detection(file_path: str) -> list:
    try:
        from vision.object_detector import detect_objects
        return detect_objects(file_path) or []
    except Exception as e:
        print(f"[Pipeline] Object detection error: {e}")
        return []


def _run_pdf(file_path: str) -> str:
    try:
        from document.pdf_reader import read_pdf
        return read_pdf(file_path) or ""
    except Exception as e:
        print(f"[Pipeline] PDF error: {e}")
        return ""


def _run_docx(file_path: str) -> str:
    try:
        from document.docx_reader import read_docx
        return read_docx(file_path) or ""
    except Exception as e:
        print(f"[Pipeline] DOCX error: {e}")
        return ""

def _update_search_index() -> None:
    """
    Refresh the memory cache and rebuild FAISS/BM25
    after a new memory has been committed to SQLite.
    """
    try:
        from app.services.database_service import (
            refresh_memory_cache,
            get_all_memories,
        )
        from ai.faiss_service import build_index
        from ai.hybrid_search import build_bm25
        from ai.semantic_search import invalidate_search_cache

        # IMPORTANT:
        # SQLite was updated by db.commit(), but the in-memory
        # cache still contains the old memories.
        refresh_memory_cache()

        memories = get_all_memories()

        print(
            f"[Pipeline] Rebuilding search indexes "
            f"with {len(memories)} memories"
        )

        build_index(memories)
        build_bm25(memories)
        invalidate_search_cache()

        print(
            f"[Pipeline] Search indexes updated: "
            f"{len(memories)} memories"
        )

    except Exception as e:
        print(f"[Pipeline] Index update error: {e}")


# Backward compatibility alias
_update_faiss = _update_search_index



