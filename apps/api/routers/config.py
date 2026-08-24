"""
GET /api/config/branding -- a parallel path onto packages/branding/*.json
for any future client-only consumer. The web app itself prefers a direct
filesystem read (apps/web/lib/branding.ts) to avoid a network hop and to
work with static rendering of the Landing page; this endpoint exists so
the source of truth is reachable over HTTP too, never duplicated.
"""
import json

from fastapi import APIRouter

from apps.api import settings

router = APIRouter(tags=["config"])


@router.get("/config/branding")
def get_branding() -> dict:
    theme = json.loads((settings.BRANDING_DIR / "theme.json").read_text(encoding="utf-8"))
    copy = json.loads((settings.BRANDING_DIR / "copy.json").read_text(encoding="utf-8"))
    return {"theme": theme, "copy": copy}
