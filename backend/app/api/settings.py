"""Settings endpoints: read and update DB-backed configuration.

Only allowlisted keys are writable; everything else is read-only. Secrets
(encryption_key, local_auth_token) are never returned.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import require_local_token
from app.schemas.common import SettingRead, SettingUpdate
from db.base import get_db
from db.models import Setting

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_local_token)])

# Keys the UI may edit. Keys not listed here exist in the DB but stay read-only.
WRITABLE = {"ollama_url", "ollama_default_model", "default_blog_name"}
SECRET_KEYS = {"encryption_key", "local_auth_token", "token_encrypted"}


def _visible(value: str | None, key: str) -> str | None:
    return "********" if key in SECRET_KEYS else value


@router.get("", response_model=list[SettingRead])
def list_settings(db: Session = Depends(get_db)) -> list[SettingRead]:
    rows = db.scalars(select(Setting).order_by(Setting.key)).all()
    return [SettingRead(key=r.key, value=_visible(r.value, r.key)) for r in rows]


@router.put("/{key}", response_model=SettingRead)
def update_setting(key: str, payload: SettingUpdate, db: Session = Depends(get_db)) -> SettingRead:
    if key not in WRITABLE:
        raise HTTPException(status_code=403, detail=f"Setting {key!r} is not writable")
    if payload.value is not None and len(payload.value) > 1000:
        raise HTTPException(status_code=422, detail="Value too long")
    setting = db.scalars(select(Setting).where(Setting.key == key)).first()
    if setting is None:
        setting = Setting(key=key, value=payload.value)
        db.add(setting)
    else:
        setting.value = payload.value
    db.commit()
    db.refresh(setting)
    return SettingRead(key=setting.key, value=_visible(setting.value, setting.key))
