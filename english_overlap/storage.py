"""Audio file storage and one-time import of legacy subtitle JSON."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def practice_data_dir() -> Path:
    role = practice_data_role()
    if role == "test":
        configured = os.environ.get("ENGLISH_OVERLAP_TEST_DATA_DIR")
        if not configured:
            raise RuntimeError("ENGLISH_OVERLAP_TEST_DATA_DIR is required for test data mode")
        return Path(configured).expanduser().resolve()
    configured = os.environ.get("ENGLISH_OVERLAP_PRODUCTION_DATA_DIR") or os.environ.get("ENGLISH_OVERLAP_DATA_DIR")
    return Path(configured).expanduser().resolve() if configured else ROOT / "practice_data"


def practice_data_role() -> str:
    role = os.environ.get("ENGLISH_OVERLAP_DATA_ROLE", "production").strip().lower()
    if role not in ("production", "test"):
        raise ValueError("ENGLISH_OVERLAP_DATA_ROLE must be production or test")
    return role


def _safe_audio_path(directory: str | Path, name: str) -> Path:
    if not name or Path(name).name != name or not name.startswith("english_overlap_"):
        raise ValueError("Invalid saved audio filename")
    path=Path(directory)/name
    if path.suffix not in ('.mp3','.wav'):
        raise ValueError("Unsupported saved audio type")
    return path


def _jst_filename_timestamp(instant: datetime) -> str:
    tokyo=timezone(timedelta(hours=9),'Asia/Tokyo')
    return instant.astimezone(tokyo).strftime('%Y%m%d_%H%M%S')


def save_audio_artifact(audio_mp3, directory: str | Path | None = None) -> str:
    """Persist only the audio binary; structured content belongs in SQLite."""
    save_dir=Path(directory) if directory is not None else practice_data_dir()
    save_dir.mkdir(parents=True,exist_ok=True)
    stamp=_jst_filename_timestamp(datetime.now(timezone.utc))+'_'+uuid.uuid4().hex[:6]
    audio_name=f'english_overlap_{stamp}.mp3'
    (save_dir/audio_name).write_bytes(audio_mp3)
    return audio_name


def unimported_material_files(directory: str | Path, imported_names: set[str]) -> tuple[list[dict],list[dict]]:
    """Read only legacy JSON files with no completed database import record."""
    root=Path(directory);items=[];errors=[]
    if not root.is_dir():return items,errors
    for file in sorted(root.glob('english_overlap_*.json'),reverse=True):
        if file.name in imported_names:continue
        try:
            raw=file.read_bytes()
            data=json.loads(raw.decode('utf-8'))
            if not isinstance(data,dict):raise ValueError('JSON root must be an object')
            items.append({'file':file.name,'data':data,'sha256':hashlib.sha256(raw).hexdigest()})
        except (OSError,UnicodeDecodeError,json.JSONDecodeError,ValueError) as error:
            errors.append({'file':file.name,'error':str(error)})
    return items,errors


def remove_material_artifacts(names, *, directory: str | Path) -> dict:
    root=Path(directory).resolve()
    result={'removed':[],'missing':[],'skipped':[],'errors':[]}
    for name in dict.fromkeys(names):
        try:path=_safe_audio_path(root,name)
        except (TypeError,ValueError):
            result['skipped'].append(str(name));continue
        try:
            if path.is_symlink() or path.resolve(strict=False).parent!=root or not path.is_file():
                result['skipped' if path.exists() else 'missing'].append(name);continue
            path.unlink();result['removed'].append(name)
        except OSError as error:
            result['errors'].append({'name':name,'error':str(error)})
    return result


def load_saved_audio(directory: str | Path, name: str) -> tuple[bytes, str]:
    root=Path(directory).resolve();path = _safe_audio_path(root, name)
    if path.is_symlink() or path.resolve(strict=False).parent!=root:
        raise ValueError('Saved audio path is outside the configured directory')
    return path.read_bytes(), ('audio/mpeg' if path.suffix == '.mp3' else 'audio/wav')
