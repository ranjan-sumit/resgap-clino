from fastapi import APIRouter

from apps.api.models.corpus import CorpusView, PaperDetail
from apps.api.services.corpus_service import get_paper_detail, get_project_corpus

router = APIRouter(tags=["corpus"])


@router.get("/projects/{project_id}/corpus", response_model=CorpusView)
def project_corpus(project_id: str, run_id: str | None = None) -> CorpusView:
    """Optional run_id pins every workspace tab to the same run. Omitted = the most recent run, which is what every screen did before the workspace gained a run switcher (Slice 15)."""
    return get_project_corpus(project_id, run_id)


@router.get("/projects/{project_id}/corpus/papers/{filename}", response_model=PaperDetail)
def project_corpus_paper(project_id: str, filename: str, run_id: str | None = None) -> PaperDetail:
    return get_paper_detail(project_id, filename, run_id)
