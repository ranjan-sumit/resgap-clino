from fastapi import APIRouter

from apps.api.models.corpus import CorpusView, PaperDetail
from apps.api.services.corpus_service import get_paper_detail, get_project_corpus

router = APIRouter(tags=["corpus"])


@router.get("/projects/{project_id}/corpus", response_model=CorpusView)
def project_corpus(project_id: str) -> CorpusView:
    return get_project_corpus(project_id)


@router.get("/projects/{project_id}/corpus/papers/{filename}", response_model=PaperDetail)
def project_corpus_paper(project_id: str, filename: str) -> PaperDetail:
    return get_paper_detail(project_id, filename)
