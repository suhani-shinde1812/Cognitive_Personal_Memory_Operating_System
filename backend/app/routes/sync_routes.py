# LOCATION: backend/app/routes/sync_routes.py
"""
sync_routes.py
==============
API endpoints for CogniSphere Desktop Agent synchronization.
Supports secure device pairing, heartbeat monitoring, incremental file sync,
and folder control from the web interface.
"""

from __future__ import annotations
import json
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile, File, Form, Query, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.database import get_db
from app.services import sync_service
from app.models.sync_device import SyncDevice

from app.models.user import User
from app.auth.deps import get_optional_current_user

router = APIRouter(prefix="/sync", tags=["sync"])


# ── Pydantic Request Models ───────────────────────────────────────────────────

class PairRequest(BaseModel):
    device_name: Optional[str] = "Windows PC"
    os_info: Optional[str] = "Windows"
    pairing_code: Optional[str] = None
    auth_token: Optional[str] = None


class HeartbeatRequest(BaseModel):
    device_id: str
    auth_token: str
    status: str = "connected"
    watched_folders: Optional[List[dict]] = None


class FolderUpdateRequest(BaseModel):
    watched_folders: List[dict]


class DeleteFileRequest(BaseModel):
    device_id: str
    auth_token: str
    relative_path: str


# ── Helper for Token Auth ─────────────────────────────────────────────────────

def authenticate_agent(device_id: str, auth_token: str, db: Session) -> SyncDevice:
    device = sync_service.verify_device_token(device_id, auth_token, db)
    if not device:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: invalid device ID or auth token.",
        )
    return device


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/pair")
def pair_desktop_agent(
    payload: PairRequest,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """
    Pairs a new Desktop Agent or generates a pairing code for a logged-in user.
    """
    import random
    import string
    from datetime import datetime, timezone

    # 1. Desktop agent pairing using a pre-generated pairing code
    if payload.pairing_code:
        code_clean = payload.pairing_code.strip().upper()
        device = (
            db.query(SyncDevice)
            .filter(SyncDevice.pairing_code == code_clean)
            .first()
        )
        if not device:
            raise HTTPException(
                status_code=404,
                detail="Invalid or expired pairing code. Please generate a new code from CogniSphere Web.",
            )

        device.device_name = payload.device_name or device.device_name
        device.os_info = payload.os_info or device.os_info
        device.status = "connected"
        device.last_heartbeat = datetime.now(timezone.utc).isoformat()
        db.commit()
        db.refresh(device)

        return {
            "device_id":    device.device_id,
            "device_name":  device.device_name,
            "auth_token":   device.auth_token,
            "status":       device.status,
            "user_id":      device.user_id,
            "pairing_code": device.pairing_code,
        }

    # 2. Generating a new pairing code (whether authenticated or fallback)
    chars = string.ascii_uppercase + string.digits
    rand_suffix = "".join(random.choices(chars, k=5))
    pairing_code = f"COG-{rand_suffix}"

    uid = str(current_user.id) if current_user else None
    if not uid:
        try:
            first_u = db.query(User).order_by(User.created_at.asc()).first()
            if first_u:
                uid = str(first_u.id)
        except Exception:
            pass

    return sync_service.pair_device(
        device_name=payload.device_name or "Windows PC",
        os_info=payload.os_info or "Windows",
        user_id=uid,
        pairing_code=pairing_code,
        status="pending_pairing",
        db=db,
    )


@router.get("/devices")
def list_paired_devices(
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """Lists paired desktop devices scoped to the authenticated user."""
    user_id = str(current_user.id) if current_user else None
    return sync_service.get_sync_overview(db, user_id=user_id)


@router.delete("/devices/{device_id}")
def unpair_device(
    device_id: str,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """Unpairs/disconnects a desktop device."""
    query = db.query(SyncDevice).filter(SyncDevice.device_id == device_id)
    if current_user:
        query = query.filter(SyncDevice.user_id == str(current_user.id))
    device = query.first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    db.delete(device)
    db.commit()
    return {"success": True, "message": f"Device {device_id} disconnected."}


@router.post("/devices/{device_id}/pause")
def pause_device(
    device_id: str,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """Pauses synchronization on the target desktop device."""
    query = db.query(SyncDevice).filter(SyncDevice.device_id == device_id)
    if current_user:
        query = query.filter(SyncDevice.user_id == str(current_user.id))
    device = query.first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.status = "paused"
    db.commit()
    db.refresh(device)
    return {"success": True, "device": device.to_dict()}


@router.post("/devices/{device_id}/resume")
def resume_device(
    device_id: str,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """Resumes synchronization on the target desktop device."""
    query = db.query(SyncDevice).filter(SyncDevice.device_id == device_id)
    if current_user:
        query = query.filter(SyncDevice.user_id == str(current_user.id))
    device = query.first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.status = "watching"
    db.commit()
    db.refresh(device)
    return {"success": True, "device": device.to_dict()}


@router.post("/heartbeat")
def agent_heartbeat(
    payload: HeartbeatRequest,
    db: Session = Depends(get_db),
):
    """Desktop agent heartbeat reporting current status and folders."""
    authenticate_agent(payload.device_id, payload.auth_token, db)
    success = sync_service.update_heartbeat(
        device_id=payload.device_id,
        status=payload.status,
        watched_folders=payload.watched_folders,
        db=db,
    )
    return {"success": success, "status": payload.status}


@router.post("/devices/{device_id}/folders")
def update_device_folders(
    device_id: str,
    payload: FolderUpdateRequest,
    db: Session = Depends(get_db),
):
    """Allows the web UI to pause, resume, or remove watched folders."""
    device = db.query(SyncDevice).filter(SyncDevice.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device.watched_folders = json.dumps(payload.watched_folders)
    db.commit()
    return {"success": True, "watched_folders": payload.watched_folders}


@router.post("/file")
async def sync_file(
    background_tasks: BackgroundTasks,
    device_id: str = Form(...),
    auth_token: str = Form(...),
    relative_path: str = Form(...),
    sha256_hash: str = Form(...),
    modified_at: str = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Syncs a created or modified file from the desktop agent.
    Performs SHA-256 deduplication and async memory pipeline ingestion.
    """
    authenticate_agent(device_id, auth_token, db)

    file_bytes = await file.read()
    result = sync_service.sync_file_record(
        device_id=device_id,
        relative_path=relative_path,
        filename=file.filename,
        sha256_hash=sha256_hash,
        file_modified_at=modified_at,
        file_bytes=file_bytes,
        db=db,
        background_tasks=background_tasks,
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Sync failed"))

    return result


@router.delete("/file")
def delete_file(
    payload: DeleteFileRequest,
    db: Session = Depends(get_db),
):
    """
    Notifies that a file was deleted locally on the desktop.
    Deactivates the associated memory in CogniSphere.
    """
    authenticate_agent(payload.device_id, payload.auth_token, db)
    result = sync_service.delete_file_record(
        device_id=payload.device_id,
        relative_path=payload.relative_path,
        db=db,
    )
    return result


@router.get("/status")
def sync_status(
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """General sync status endpoint for frontend dashboard & settings."""
    user_id = current_user.id if current_user else None
    return sync_service.get_sync_overview(db, user_id=user_id)
