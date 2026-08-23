"""自然語言詢問的 router：POST /ask。"""

from datetime import date

from fastapi import APIRouter, Depends
from langchain_core.embeddings import Embeddings

from app.core import config
from app.dependencies import get_answerer, get_embeddings, get_router, get_today
from app.repositories import photo_repository
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
    """自然語言詢問（中英文皆可）：判斷查法 → 查詢 → 依撈到的內容回答。

    查法自 Phase 34 起有四種（照片條件／語意／實體別針／待辦），
    但仍是**同一個端點、一問一答**：走哪一路由路由層決定，
    不讓模型自己開工具（design3.md §1.2 已否決 agentic RAG）。
    """
    # 現有實體名單在端點這層撈：實體是使用者自己命名的東西（「我的 MacBook」），
    # 模型看不到有哪些名字就只能亂猜。撈名單是唯讀查詢，成本遠低於一次推論。
    entity_names = [row["name"] for row in photo_repository.list_entities()]

    deps = ask_workflow.AskDeps(
        router=router_client,
        answerer=answerer,
        embeddings=embeddings,
        today=today,
        entity_names=entity_names,
    )
    state = ask_workflow.run_ask(payload.question, deps)

    return AskResponse(
        answer=state["answer"],
        # search_mode 與 retrieved_photo_ids 直接取自流程 state，不經過 AI
        search_mode=config.SEARCH_MODE_LABELS[state["mode"]],
        retrieved_photo_ids=[doc.metadata["id"] for doc in state["retrieved"]],
    )
