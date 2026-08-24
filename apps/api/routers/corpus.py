from fastapi import APIRouter

from apps.api.models.corpus import CorpusView
from apps.api.services.corpus_service import get_project_corpus

router = APIRouter(tags=["corpus"])


@router.get("/projects/{project_id}/corpus", response_model=CorpusView)
def project_corpus(project_id: str) -> CorpusView:
    return get_project_corpus(project_id)
