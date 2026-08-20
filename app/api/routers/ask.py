"""自然語言詢問的 router：POST /ask。"""

from datetime import date

from fastapi import APIRouter, Depends
from langchain_core.embeddings import Embeddings

from app.core import config
from app.dependencies import get_answerer, get_embeddings, get_router, get_today
from app.schemas.ask import AskRequest, AskResponse
from app.services import ask_workflow

router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse)
def ask(
    payload: AskRequest,
    router_client: ask_workflow.RouterClient = Depends(get_router),
    answerer: ask_workflow.AnswerClient = Depends(get_answerer),
    embeddings: Embeddings = Depends(get_embeddings),
    today: date = Depends(get_today),
) -> AskResponse:
    """自然語言詢問（中英文皆可）：判斷查法 → 查詢 → 依撈到的內容回答。"""
    deps = ask_workflow.AskDeps(
        router=router_client, answerer=answerer, embeddings=embeddings, today=today
    )
    state = ask_workflow.run_ask(payload.question, deps)

    return AskResponse(
        answer=state["answer"],
        # search_mode 與 retrieved_photo_ids 直接取自流程 state，不經過 AI
        search_mode=config.SEARCH_MODE_LABELS[state["mode"]],
        retrieved_photo_ids=[doc.metadata["id"] for doc in state["retrieved"]],
    )
