import os
import uuid
import time
import shutil
from pathlib import Path
import atexit

SESSIONS_DIR = Path("/tmp") / "aol_sessions"
SESSION_TTL = 86400

_sessions = {}


def create_session():
    session_id = str(uuid.uuid4())[:8]
    session_dir = SESSIONS_DIR / f"session_{session_id}"
    dirs = [
        session_dir / "inputs",
        session_dir / "aol_extracted",
        session_dir / "tiles" / "rgb",
        session_dir / "tiles" / "multispectral",
        session_dir / "tiles" / "dem",
        session_dir / "features" / "ndvi",
        session_dir / "features" / "gndvi",
        session_dir / "features" / "dem",
        session_dir / "features" / "rgb",
        session_dir / "ml",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    session = {
        "id": session_id,
        "dir": session_dir,
        "created_at": time.time(),
        "rasters": {},
        "shapefile": None,
        "aol_extent": None,
        "tile_grid": None,
        "tile_count": 0,
        "features_done": False,
        "stats_done": False,
        "ml_done": False,
    }
    _sessions[session_id] = session
    return session


def get_session(session_id):
    session = _sessions.get(session_id)
    if session:
        if time.time() - session["created_at"] > SESSION_TTL:
            cleanup_session(session_id)
            return None
        return session
    return None


def cleanup_session(session_id):
    session = _sessions.get(session_id)
    if session:
        shutil.rmtree(session["dir"], ignore_errors=True)
        _sessions.pop(session_id, None)


def cleanup_expired():
    expired = [sid for sid, s in _sessions.items()
               if time.time() - s["created_at"] > SESSION_TTL * 2]
    for sid in expired:
        cleanup_session(sid)


atexit.register(lambda: None)
