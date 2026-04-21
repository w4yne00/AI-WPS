from fastapi import APIRouter

from app.core.models import ProofreadResponseData, WordDocumentRequest
from app.services.word.proofreader import WordProofreader

router = APIRouter()
proofreader = WordProofreader()


@router.post("/word/proofread")
def proofread_word(request: WordDocumentRequest) -> dict:
    issues = proofreader.proofread(request)
    payload = ProofreadResponseData(issues=issues)
    return {
        "success": True,
        "traceId": "trace-word-proofread",
        "taskType": "word.proofread",
        "message": "completed",
        "data": payload.dict(by_alias=True),
        "errors": [],
    }
