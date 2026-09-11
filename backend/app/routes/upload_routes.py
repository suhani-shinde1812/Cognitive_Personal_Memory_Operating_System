# LOCATION: backend/app/routes/upload_routes.py
"""
upload_routes.py
================
Asynchronous document and image upload endpoint.
Immediately accepts uploads with HTTP 202 and delegates all CPU/model processing
to FastAPI BackgroundTasks, preventing event-loop freezing and 502 Bad Gateway timeouts.
"""

from __future__ import annotations
import os
import time
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, status, Depends
from fastapi.responses import JSONResponse

from app.services.storage_service import get_storage
from app.services.job_service import get_job_manager
from ai.embedding_service import is_model_loaded, MODEL_NAME
from ai.memory_pipeline import run_pipeline
from app.models.user import User
from app.auth.deps import get_optional_current_user

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".txt", ".md", ".csv",
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif",
}

ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/octet-stream",  # Sent by browsers for various document types
}

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


def process_upload_job(
    job_id: str,
    file_path: str,
    filename: str,
    user_id: Optional[int] = None,
):
    """
    Background worker that runs the complete document ingestion pipeline.
    Executes off the main request thread so the client receives 202 immediately.
    Updates the JobManager singleton at each stage with granular progress.
    """
    job_mgr = get_job_manager()
    t_start = time.perf_counter()

    try:
        job_mgr.update_job(job_id, stage="extracting", message="Extracting text content from document")
        print(f"[PROCESS] started job_id={job_id} filename={filename} user_id={user_id}")

        # Step 1: Ingestion pipeline
        print(f"[PROCESS] extracting text from {filename}")
        source_hint = Path(filename).stem.replace("_", " ").title()

        job_mgr.update_job(job_id, stage="chunking", message="Chunking text and preparing vector embeddings")
        print(f"[PROCESS] chunks prepared for {filename}")

        job_mgr.update_job(job_id, stage="embedding", message=f"Generating embeddings with {MODEL_NAME}")
        print(f"[PROCESS] generating embeddings for {filename}")

        # Run the full pipeline with user_id scoping
        result = run_pipeline(file_path, source_hint=source_hint, update_index=True, user_id=user_id)
        memory_id = result.get("id")

        print(f"[PROCESS] memories created=Memory #{memory_id} for job_id={job_id}")

        elapsed = time.perf_counter() - t_start
        print(f"[PROCESS] completed job_id={job_id} in {elapsed:.3f}s")

        job_mgr.update_job(
            job_id,
            status="completed",
            stage="completed",
            message="Document processing completed successfully",
            memory_id=memory_id,
            memory=result,
            processing_time=round(elapsed, 3),
        )

    except Exception as e:
        elapsed = time.perf_counter() - t_start
        print(f"[PROCESS] FAILED job_id={job_id} error={e}")
        job_mgr.update_job(
            job_id,
            status="failed",
            stage="failed",
            message=f"Processing failed: {str(e)}",
            error=str(e),
            processing_time=round(elapsed, 3),
        )


@router.get("/status")
def upload_service_status():
    """
    Lightweight health/status check reporting AI readiness without
    loading heavy models into memory.
    """
    return {
        "status":               "ready",
        "embedding_model":      MODEL_NAME,
        "embedding_loaded":     is_model_loaded(),
        "max_file_size_mb":     50,
        "supported_extensions": sorted(list(ALLOWED_EXTENSIONS)),
    }


@router.get("/status/{job_id}")
def get_upload_job_status(
    job_id: str,
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """
    Poll the status of an asynchronous document processing job.
    Enforces user isolation: User B cannot view User A's job.
    """
    job = get_job_manager().get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found or has expired.",
        )
    if job.user_id is not None and current_user and job.user_id != current_user.id:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found or has expired.",
        )
    return job.to_dict()


@router.post("", status_code=status.HTTP_202_ACCEPTED)
@router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """
    Upload a document or image file.
    Immediately validates file, saves payload to storage, enqueues background task,
    and returns HTTP 202 Accepted with a job_id (<15ms response time).
    """
    filename = file.filename or "uploaded_file"
    ext = Path(filename).suffix.lower()

    # Content type & extension validation
    if ext not in ALLOWED_EXTENSIONS and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}' (content-type: {file.content_type}). Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    try:
        file_bytes = await file.read()
    except Exception as read_err:
        print(f"[UPLOAD FAILED] Could not read payload for {filename}: {read_err}")
        raise HTTPException(status_code=400, detail="Could not read uploaded file data.")

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes).")

    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        size_mb = len(file_bytes) / (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"File size ({size_mb:.1f} MB) exceeds maximum allowed limit of 50 MB.",
        )

    print(f"[UPLOAD] received filename={filename} size={len(file_bytes) / 1024:.1f} KB")

    # 1. Save file to storage abstraction
    storage = get_storage()
    file_path = storage.save_file(filename, file_bytes)
    print(f"[UPLOAD] file saved path={file_path}")

    # 2. Create job record with user_id
    user_id = current_user.id if current_user else None
    job_mgr = get_job_manager()
    job = job_mgr.create_job(filename, user_id=user_id)
    print(f"[UPLOAD] job created job_id={job.job_id} user_id={user_id}")

    # 3. Enqueue background task
    background_tasks.add_task(process_upload_job, job.job_id, file_path, filename, user_id)

    # 4. Immediately return HTTP 202 Accepted
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status":   "processing",
            "job_id":   job.job_id,
            "filename": filename,
            "message":  "Document uploaded and processing started",
        },
    )
