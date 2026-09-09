# LOCATION: backend/app/routes/watcher_routes.py
"""
watcher_routes.py
=================
API endpoints to control the desktop folder watcher and manage
user-authorized folder and drive permissions.

v2: resume_location now triggers background auto-indexing of all
    documents in the folder so memories are created automatically
    when a user clicks "Agree & Allow". A polling endpoint
    /watcher/locations/{id}/index-status tracks progress.
"""

from typing import Optional, List
from pathlib import Path
from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database.database import get_db
from app.models.watcher_location import WatcherLocation
from app.models.user import User
from app.auth.deps import get_current_user, get_optional_current_user

router = APIRouter(prefix="/watcher", tags=["watcher"])

_observer = None   # global watcher instance


# ── Pydantic Schemas ───────────────────────────────────────────────────────────

class LocationCreate(BaseModel):
    path: str
    display_name: str
    location_type: Optional[str] = "custom"  # standard | custom | drive
    permission_status: Optional[str] = "granted"  # granted | pending | revoked | denied
    enabled: Optional[bool] = True


class LocationUpdate(BaseModel):
    display_name: Optional[str] = None
    permission_status: Optional[str] = None
    enabled: Optional[bool] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_standard_defaults() -> list[dict]:
    home = Path.home()
    candidates = [
        {"name": "Documents", "path": str(home / "Documents"), "type": "standard", "enabled": True},
        {"name": "Desktop",   "path": str(home / "Desktop"),   "type": "standard", "enabled": True},
        {"name": "Downloads", "path": str(home / "Downloads"), "type": "standard", "enabled": False},
        {"name": "Pictures",  "path": str(home / "Pictures"),  "type": "standard", "enabled": False},
        {"name": "Videos",    "path": str(home / "Videos"),    "type": "standard", "enabled": False},
        {"name": "C: Drive",  "path": "C:\\",                  "type": "drive",    "enabled": False},
        {"name": "E: Drive",  "path": "E:\\",                  "type": "drive",    "enabled": False},
    ]
    return candidates


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
def watcher_status(
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """Returns whether the folder watcher is running and active locations count."""
    global _observer
    is_running = _observer is not None and _observer.is_alive()

    location_count = 0
    if current_user:
        location_count = (
            db.query(WatcherLocation)
            .filter(WatcherLocation.user_id == str(current_user.id), WatcherLocation.enabled.is_(True))
            .count()
        )

    watched_dirs = [
        str(d) for d in [
            Path.home() / "Desktop",
            Path.home() / "Downloads",
            Path.home() / "Documents",
            Path.home() / "Pictures",
        ] if d.exists()
    ]

    return {
        "running":         is_running,
        "watched_dirs":    watched_dirs,
        "active_locations": location_count,
    }


@router.get("/locations")
def list_locations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all authorized watch locations for the authenticated user.
    If none exist yet, automatically seeds standard user folders (Documents, Downloads, C:, E:, etc.)
    with permission_status='granted'.
    """
    locations = (
        db.query(WatcherLocation)
        .filter(WatcherLocation.user_id == str(current_user.id))
        .order_by(WatcherLocation.id.asc())
        .all()
    )

    if not locations:
        # Seed standard default folders for the new user
        seeded = []
        for item in _get_standard_defaults():
            loc = WatcherLocation(
                user_id=str(current_user.id),
                path=item["path"],
                display_name=item["name"],
                location_type=item.get("type", "standard"),
                permission_status="granted",
                enabled=item.get("enabled", False),
            )
            db.add(loc)
            seeded.append(loc)
        db.commit()
        for s in seeded:
            db.refresh(s)
        locations = seeded
    else:
        # Ensure any missing standard folders/drives (e.g. C: Drive, E: Drive) are added for existing users
        existing_names = {loc.display_name for loc in locations}
        added_any = False
        for item in _get_standard_defaults():
            if item["name"] not in existing_names:
                new_loc = WatcherLocation(
                    user_id=str(current_user.id),
                    path=item["path"],
                    display_name=item["name"],
                    location_type=item.get("type", "standard"),
                    permission_status="granted",
                    enabled=item.get("enabled", False),
                )
                db.add(new_loc)
                locations.append(new_loc)
                added_any = True
        if added_any:
            db.commit()
            for loc in locations:
                db.refresh(loc)

    return [loc.to_dict() for loc in locations]


@router.post("/locations", status_code=status.HTTP_201_CREATED)
def add_location(
    payload: LocationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a new authorized folder or drive for the authenticated user."""
    # Check if this exact path is already configured for this user
    existing = (
        db.query(WatcherLocation)
        .filter(WatcherLocation.user_id == str(current_user.id), WatcherLocation.path == payload.path.strip())
        .first()
    )
    if existing:
        existing.enabled = True
        existing.permission_status = payload.permission_status or "granted"
        if payload.display_name:
            existing.display_name = payload.display_name.strip()
        db.commit()
        db.refresh(existing)
        return existing.to_dict()

    loc = WatcherLocation(
        user_id=str(current_user.id),
        path=payload.path.strip(),
        display_name=payload.display_name.strip(),
        location_type=payload.location_type or "custom",
        permission_status=payload.permission_status or "granted",
        enabled=payload.enabled if payload.enabled is not None else True,
    )
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc.to_dict()


@router.patch("/locations/{location_id}")
def update_location(
    location_id: int,
    payload: LocationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update settings or permission status for an authorized location."""
    loc = (
        db.query(WatcherLocation)
        .filter(WatcherLocation.id == location_id, WatcherLocation.user_id == str(current_user.id))
        .first()
    )
    if not loc:
        raise HTTPException(status_code=404, detail="Watcher location not found")

    if payload.display_name is not None:
        loc.display_name = payload.display_name.strip()
    if payload.permission_status is not None:
        loc.permission_status = payload.permission_status.strip()
    if payload.enabled is not None:
        loc.enabled = payload.enabled

    db.commit()
    db.refresh(loc)
    return loc.to_dict()


@router.delete("/locations/{location_id}")
def delete_location(
    location_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke and remove an authorized watch location."""
    loc = (
        db.query(WatcherLocation)
        .filter(WatcherLocation.id == location_id, WatcherLocation.user_id == str(current_user.id))
        .first()
    )
    if not loc:
        raise HTTPException(status_code=404, detail="Watcher location not found")

    db.delete(loc)
    db.commit()
    return {"status": "ok", "deleted": location_id}


@router.post("/locations/{location_id}/pause")
def pause_location(
    location_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pause synchronization for a specific location."""
    loc = (
        db.query(WatcherLocation)
        .filter(WatcherLocation.id == location_id, WatcherLocation.user_id == str(current_user.id))
        .first()
    )
    if not loc:
        raise HTTPException(status_code=404, detail="Watcher location not found")

    loc.enabled = False
    db.commit()
    db.refresh(loc)
    return loc.to_dict()


@router.post("/locations/{location_id}/resume")
def resume_location(
    location_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Resume synchronization for a specific location.

    Also triggers a background auto-index job that converts all supported
    documents in the folder into CogniSphere memories automatically.
    Progress is available via GET /watcher/locations/{id}/index-status.
    """
    loc = (
        db.query(WatcherLocation)
        .filter(WatcherLocation.id == location_id, WatcherLocation.user_id == str(current_user.id))
        .first()
    )
    if not loc:
        raise HTTPException(status_code=404, detail="Watcher location not found")

    loc.enabled = True
    db.commit()
    db.refresh(loc)

    # 🚀 Kick off background auto-indexing of all files in this folder
    try:
        from app.services.folder_watcher import auto_index_location
        background_tasks.add_task(
            auto_index_location,
            location_id=loc.id,
            folder_path=loc.path,
            user_id=str(current_user.id),
        )
        print(f"[Watcher] Auto-index queued for location #{loc.id}: {loc.path}")
    except Exception as e:
        print(f"[Watcher] Could not queue auto-index: {e}")

    result = loc.to_dict()
    result["auto_indexing"] = True
    return result


@router.get("/locations/{location_id}/index-status")
def location_index_status(
    location_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get the current auto-indexing progress for a folder location.

    Returns:
        {
            "running": bool,       # True while indexing is in progress
            "total": int,          # Total files found
            "processed": int,      # Files successfully converted to memories
            "skipped": int,        # Duplicates skipped
            "errors": int,         # Files that failed
            "done": bool,          # True when indexing is complete
            "current_file": str    # Filename currently being processed
        }
    """
    # Verify the location belongs to this user
    loc = (
        db.query(WatcherLocation)
        .filter(WatcherLocation.id == location_id, WatcherLocation.user_id == str(current_user.id))
        .first()
    )
    if not loc:
        raise HTTPException(status_code=404, detail="Watcher location not found")

    from app.services.folder_watcher import get_index_status
    status_data = get_index_status(location_id)
    status_data["location_id"] = location_id
    status_data["path"] = loc.path
    return status_data


@router.post("/start")
def start_watcher():
    """Starts the folder watcher if not already running."""
    global _observer
    if _observer is not None and _observer.is_alive():
        return {"message": "Watcher already running"}

    try:
        from app.services.folder_watcher import start_watcher as _start
        _observer = _start()
        if _observer:
            return {"message": "Watcher started successfully"}
        return {"message": "No valid directories to watch", "started": False}
    except Exception as e:
        return {"error": str(e), "started": False}


@router.post("/stop")
def stop_watcher():
    """Stops the folder watcher."""
    global _observer
    if _observer is None or not _observer.is_alive():
        return {"message": "Watcher is not running"}
    try:
        _observer.stop()
        _observer.join()
        _observer = None
        return {"message": "Watcher stopped"}
    except Exception as e:
        return {"error": str(e)}


@router.post("/restart")
def restart_watcher():
    """Stops and restarts the folder watcher."""
    stop_watcher()
    return start_watcher()
