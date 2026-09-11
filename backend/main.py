# LOCATION: backend/main.py
"""
main.py — CogniSphere FastAPI Application Entry Point
====================================================
Registers all routers, middleware, and startup tasks.
Production-ready for local and Render deployments.
"""

import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from typing import Optional
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database.database import engine, Base, DATABASE_URL, is_sqlite, get_db

from app.models.user           import User
from app.auth.deps             import get_optional_current_user
from app.models.memory         import Memory
from app.models.goal           import Goal
from app.models.goal_memory    import GoalMemory
from app.models.relationship   import MemoryRelationship
from app.models.decay_state    import DecayState
from app.models.memory_history import MemoryHistory

from app.services.chat_history import ChatHistory
from app.middleware.logging_middleware import LoggingMiddleware

# ── Import all routers ────────────────────────────────────────────────────────
from app.routes.memory_routes         import router as memory_router
from app.routes.search_routes         import router as search_router
from app.routes.upload_routes         import router as upload_router
from app.routes.chat_routes           import router as chat_router
from app.routes.goal_routes           import router as goal_router
from app.routes.stats_routes          import router as stats_router
from app.routes.timeline_routes       import router as timeline_router
from app.routes.pdf_routes            import router as pdf_router
from app.routes.memory_details_routes import router as memory_details_router
from app.routes.index_routes          import router as index_router
from app.routes.watcher_routes        import router as watcher_router
from app.routes.import_routes         import router as import_router
from app.routes.graph_routes          import router as graph_router
from app.routes.contradiction_routes  import router as contradiction_router
from app.routes.trajectory_routes     import router as trajectory_router
from app.routes.decay_routes          import router as decay_router
from app.routes.memory_update_routes  import router as memory_update_router
from app.routes.experiment_routes     import router as experiment_router
from app.routes.sync_routes           import router as sync_router
from app.routes.auth_routes           import router as auth_router


# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="CogniSphere — AI Personal Cognitive Memory OS",
    version="2.0.0",
    description="ACMA + GAMA powered semantic memory engine",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Dynamic CORS Configuration ────────────────────────────────────────────────
allowed_origins = [
    "https://cognisphere-frontend.onrender.com",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]

frontend_url = os.getenv("FRONTEND_URL")
if frontend_url:
    for u in frontend_url.split(","):
        u = u.strip().rstrip("/")
        if u and u not in allowed_origins:
            allowed_origins.append(u)

cors_origins_env = os.getenv("CORS_ORIGINS")
if cors_origins_env:
    for u in cors_origins_env.split(","):
        u = u.strip().rstrip("/")
        if u and u not in allowed_origins:
            allowed_origins.append(u)

# Middleware
app.add_middleware(LoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^(https?:\/\/.*\.onrender\.com|https?:\/\/localhost(:\d+)?|https?:\/\/127\.0\.0\.1(:\d+)?)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    origin = request.headers.get("origin")
    headers = {}
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Access-Control-Allow-Methods"] = "*"
        headers["Access-Control-Allow-Headers"] = "*"
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "error": type(exc).__name__},
        headers=headers,
    )

# Static uploads directory
uploads_dir_name = os.getenv("UPLOAD_DIR", "uploads")
uploads_dir = Path(uploads_dir_name)
uploads_dir.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir_name), name="uploads")

# ── Register all routers ──────────────────────────────────────────────────────
for router in [
    memory_router, search_router, upload_router, chat_router,
    goal_router, stats_router, timeline_router, pdf_router,
    memory_details_router, index_router, watcher_router,
    import_router, graph_router, contradiction_router,
    trajectory_router, decay_router,
    memory_update_router, experiment_router,
    sync_router, auth_router,
]:
    app.include_router(router)

# ── Startup tasks ─────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup():
    # AI models (embeddings, YOLO) are strictly lazy-loaded on first request
    # to maintain minimal startup memory footprint (<100 MiB) on constrained environments (Render Free tier).
    print("[CogniSphere] AI models configured for on-demand lazy loading.")

    # Create database tables (handles new tables like memory_history, watcher_locations)
    try:
        Base.metadata.create_all(bind=engine)
        print("[CogniSphere] Database tables verified.")
    except Exception as _e:
        print(f"[CogniSphere] Database tables verification notice: {_e}")

    # Lightweight database migrations (SQLite & PostgreSQL)
    _run_db_migrations()

    # ── Fix user_id type mismatch ──────────────────────────────────────────────
    # Memory.user_id is a String column. Old code set it as integer (user.id).
    # This migration normalises all integer user_ids to their string equivalents.
    try:
        from sqlalchemy import text as _text
        from database.database import SessionLocal as _SL
        from app.models.memory import Memory as _M
        from app.models.goal import Goal as _G
        _db = _SL()
        try:
            # Find all unique user_ids across memories and goals
            all_mem_uids = _db.execute(
                _text("SELECT DISTINCT user_id FROM memories WHERE user_id IS NOT NULL")
            ).fetchall()
            fixed = 0
            for row in all_mem_uids:
                uid = row[0]
                # If stored as integer representation (pure digits, no spaces)
                if uid and str(uid).strip().lstrip('-').isdigit() and str(uid) == str(uid).strip():
                    str_uid = str(int(uid))
                    if str_uid != uid:  # only update if different
                        _db.execute(
                            _text("UPDATE memories SET user_id = :str_uid WHERE user_id = :uid"),
                            {"str_uid": str_uid, "uid": str(uid)},
                        )
                        fixed += 1
            _db.commit()
            if fixed:
                print(f"[CogniSphere] Fixed {fixed} user_id type mismatches in memories.")
        except Exception as _me:
            _db.rollback()
            print(f"[CogniSphere] user_id migration notice: {_me}")
        finally:
            _db.close()
    except Exception as _mig_err:
        print(f"[CogniSphere] user_id migration outer error: {_mig_err}")

    # Load memory cache and build FAISS index
    try:
        from app.services.database_service import (
            load_memory_cache,
            get_all_memories,
        )
        from ai.faiss_service import build_index
        
        # Load all memories into RAM cache first
        load_memory_cache()
        print("[CogniSphere] Memory cache loaded.")
        
        # Then build FAISS index from cached memories
        memories = get_all_memories()
        if memories:
            build_index(memories)
            print(f"[CogniSphere] FAISS index built: {len(memories)} memories.")
            
            # Build BM25 index for keyword search
            from ai.hybrid_search import build_bm25
            build_bm25(memories)
            print(f"[CogniSphere] BM25 index built: {len(memories)} memories.")
        else:
            print("[CogniSphere] No memories yet.")
    except Exception as e:
        print(f"[CogniSphere] Cache/FAISS startup error: {e}")

    # Start folder watcher in background (silently skips if folders absent)
    try:
        from app.services.folder_watcher import start_watcher_thread
        start_watcher_thread()
    except Exception as e:
        print(f"[CogniSphere] Watcher startup error: {e}")



@app.get("/")
def root():
    return {
        "status":  "ok",
        "system":  "CogniSphere v2.0",
        "engine":  "ACMA + GAMA",
        "docs":    "/docs",
    }

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/recent", tags=["timeline"])
def recent_alias(
    limit: int = 20,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """Direct alias for /timeline/recent endpoint with optional user scoping."""
    from app.routes.timeline_routes import recent_memories
    return recent_memories(limit=limit, current_user=current_user, db=db)


@app.get("/status/{job_id}", tags=["upload"])
def job_status_root_alias(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Root-level alias for polling upload jobs: /status/{job_id} with user isolation."""
    from app.services.job_service import get_job_manager
    from app.auth.deps import get_optional_current_user
    from fastapi import HTTPException
    job = get_job_manager().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    
    current_user = get_optional_current_user(request, db)
    if job.user_id is not None and current_user and job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job.to_dict()

@app.get("/status", tags=["upload"])
def upload_status_root_alias():
    """Root-level alias for upload/AI status check."""
    from app.routes.upload_routes import upload_service_status
    return upload_service_status()



# ── SQLite column migrations ──────────────────────────────────────────────────
def _run_sqlite_migrations():
    """
    Lightweight ALTER TABLE migrations for SQLite.
    Adds new columns to existing tables without Alembic.
    Safe to call multiple times — silently ignores duplicate-column errors.
    """
    import sqlite3
    db_clean = DATABASE_URL.replace("sqlite:///", "").replace("sqlite://", "")
    db_path = db_clean if db_clean else "reality_search.db"
    try:
        conn = sqlite3.connect(db_path)
        cur  = conn.cursor()

        # Add version column to memories
        try:
            cur.execute("ALTER TABLE memories ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
            print("[Migration] Added 'version' column to memories.")
        except (sqlite3.OperationalError, Exception):
            pass  # Column already exists

        # Add parent_id column to memories
        try:
            cur.execute("ALTER TABLE memories ADD COLUMN parent_id INTEGER")
            print("[Migration] Added 'parent_id' column to memories.")
        except (sqlite3.OperationalError, Exception):
            pass  # Column already exists

        # Add name column to users
        try:
            cur.execute("ALTER TABLE users ADD COLUMN name VARCHAR")
        except (sqlite3.OperationalError, Exception):
            pass

        # Add password_hash column to users
        try:
            cur.execute("ALTER TABLE users ADD COLUMN password_hash VARCHAR")
        except (sqlite3.OperationalError, Exception):
            pass

        # Add hashed_password column to users
        try:
            cur.execute("ALTER TABLE users ADD COLUMN hashed_password VARCHAR")
        except (sqlite3.OperationalError, Exception):
            pass

        # Add user_id column to memories
        try:
            cur.execute("ALTER TABLE memories ADD COLUMN user_id VARCHAR")
            print("[Migration] Added 'user_id' column to memories.")
        except (sqlite3.OperationalError, Exception):
            pass

        # Add user_id column to goals
        try:
            cur.execute("ALTER TABLE goals ADD COLUMN user_id VARCHAR")
            print("[Migration] Added 'user_id' column to goals.")
        except (sqlite3.OperationalError, Exception):
            pass

        # Add user_id column to sync_devices
        try:
            cur.execute("ALTER TABLE sync_devices ADD COLUMN user_id VARCHAR")
            print("[Migration] Added 'user_id' column to sync_devices.")
        except (sqlite3.OperationalError, Exception):
            pass

        # Add user_id column to indexed_files
        try:
            cur.execute("ALTER TABLE indexed_files ADD COLUMN user_id VARCHAR")
            print("[Migration] Added 'user_id' column to indexed_files.")
        except (sqlite3.OperationalError, Exception):
            pass

        # Add pairing_code column to sync_devices
        try:
            cur.execute("ALTER TABLE sync_devices ADD COLUMN pairing_code VARCHAR")
            print("[Migration] Added 'pairing_code' column to sync_devices.")
        except (sqlite3.OperationalError, Exception):
            pass

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Migration] SQLite migration notice: {e}")


def _run_db_migrations():
    """
    Lightweight schema migrations for both SQLite and PostgreSQL.
    Safe to call multiple times.
    """
    if is_sqlite:
        _run_sqlite_migrations()
        return

    # PostgreSQL migrations: execute each statement in an isolated transaction
    # so one failure (e.g. table not existing yet) cannot abort the rest.
    from sqlalchemy import text

    # Clean up legacy foreign key constraints if any exist
    fk_cleanup = [
        "ALTER TABLE IF EXISTS watcher_locations DROP CONSTRAINT IF EXISTS watcher_locations_user_id_fkey;",
        "ALTER TABLE IF EXISTS sync_devices DROP CONSTRAINT IF EXISTS sync_devices_user_id_fkey;",
        "ALTER TABLE IF EXISTS memories DROP CONSTRAINT IF EXISTS memories_user_id_fkey;",
        "ALTER TABLE IF EXISTS goals DROP CONSTRAINT IF EXISTS goals_user_id_fkey;",
        "ALTER TABLE IF EXISTS indexed_files DROP CONSTRAINT IF EXISTS indexed_files_user_id_fkey;",
    ]
    for stmt in fk_cleanup:
        try:
            with engine.connect() as conn:
                conn.execute(text(stmt))
                conn.commit()
        except Exception:
            pass

    pg_migrations = [
        # 1. users table columns & compatibility
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS hashed_password VARCHAR;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS name VARCHAR;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at VARCHAR;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at VARCHAR;",
        "ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL;",
        "ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;",
        "ALTER TABLE users ALTER COLUMN name DROP NOT NULL;",
        "ALTER TABLE users ALTER COLUMN id TYPE VARCHAR USING id::varchar;",
        "UPDATE users SET password_hash = hashed_password WHERE password_hash IS NULL AND hashed_password IS NOT NULL;",
        "UPDATE users SET hashed_password = password_hash WHERE hashed_password IS NULL AND password_hash IS NOT NULL;",
        """
        DO $$ 
        DECLARE 
            col record;
        BEGIN 
            FOR col IN 
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'users' 
                  AND is_nullable = 'NO' 
                  AND column_name NOT IN ('id', 'email')
            LOOP 
                EXECUTE format('ALTER TABLE users ALTER COLUMN %I DROP NOT NULL', col.column_name);
            END LOOP; 
        END $$;
        """,
        # 2. sync_devices table columns & type compatibility
        "ALTER TABLE sync_devices ADD COLUMN IF NOT EXISTS user_id VARCHAR;",
        "ALTER TABLE sync_devices ALTER COLUMN user_id TYPE VARCHAR USING user_id::varchar;",
        "ALTER TABLE sync_devices ADD COLUMN IF NOT EXISTS pairing_code VARCHAR;",
        # 3. watcher_locations table columns & type compatibility
        "ALTER TABLE watcher_locations ADD COLUMN IF NOT EXISTS user_id VARCHAR;",
        "ALTER TABLE watcher_locations ALTER COLUMN user_id TYPE VARCHAR USING user_id::varchar;",
        # 4. memories table columns & type compatibility
        "ALTER TABLE memories ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;",
        "ALTER TABLE memories ADD COLUMN IF NOT EXISTS parent_id INTEGER;",
        "ALTER TABLE memories ADD COLUMN IF NOT EXISTS user_id VARCHAR;",
        "ALTER TABLE memories ALTER COLUMN user_id TYPE VARCHAR USING user_id::varchar;",
        # 5. goals table columns & type compatibility
        "ALTER TABLE goals ADD COLUMN IF NOT EXISTS user_id VARCHAR;",
        "ALTER TABLE goals ALTER COLUMN user_id TYPE VARCHAR USING user_id::varchar;",
        # 6. indexed_files table columns & type compatibility
        "ALTER TABLE indexed_files ADD COLUMN IF NOT EXISTS user_id VARCHAR;",
        "ALTER TABLE indexed_files ALTER COLUMN user_id TYPE VARCHAR USING user_id::varchar;",
    ]

    for stmt in pg_migrations:
        try:
            with engine.connect() as conn:
                conn.execute(text(stmt))
                conn.commit()
        except Exception as err:
            print(f"[Migration] PostgreSQL statement notice ({stmt[:40]}...): {err}")

    print("[CogniSphere] PostgreSQL migrations verified.")


def _seed_persisted_users():
    """
    Restores persisted accounts from persisted_accounts.json on boot
    so accounts are never lost on ephemeral container restarts.
    """
    import json
    from app.models.user import User
    from database.database import SessionLocal

    backend_dir = os.path.dirname(os.path.abspath(__file__))
    accounts_file = os.path.join(backend_dir, "persisted_accounts.json")
    if not os.path.exists(accounts_file):
        return

    try:
        with open(accounts_file, "r", encoding="utf-8") as f:
            accounts = json.load(f)

        db = SessionLocal()
        try:
            changed = False
            for acc in accounts:
                em = (acc.get("email") or "").strip().lower()
                pwd_hash = acc.get("password_hash")
                if not em or not pwd_hash:
                    continue
                exists = db.query(User).filter(User.email == em).first()
                if not exists:
                    new_u = User(
                        email=em,
                        password_hash=pwd_hash,
                        hashed_password=pwd_hash,
                        created_at=acc.get("created_at"),
                    )
                    db.add(new_u)
                    changed = True
            if changed:
                db.commit()
                print("[Seed] Restored user accounts from persisted_accounts.json")
        finally:
            db.close()
    except Exception as e:
        print(f"[Seed] Error restoring persisted accounts: {e}")


# Run initial table creation & migrations on import so test runners & TestClient have valid schema
try:
    Base.metadata.create_all(bind=engine)
    _run_db_migrations()
    _seed_persisted_users()
except Exception as _e:
    print(f"[CogniSphere] Schema initialization notice: {_e}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)

