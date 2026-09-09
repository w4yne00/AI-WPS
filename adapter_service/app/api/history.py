from fastapi import APIRouter, Query
from typing import Optional

from app.core.errors import AdapterError
from app.services.task_history import (
    TaskHistoryError,
    TaskHistoryStore,
    get_task_history_store,
)

router = APIRouter()


@router.get("/history")
def list_history(taskType: Optional[str] = Query(default=None)):
    store = get_task_history_store()
    items = store.list_history(taskType or "")
    return {
        "success": True,
        "data": {
            "items": items,
            "total": len(items),
            "taskType": taskType or "",
        },
    }


@router.get("/history/{history_id}")
def get_history_entry(history_id: str):
    store = get_task_history_store()
    item = store.get_history(history_id)
    if item is None:
        raise AdapterError(
            "HISTORY_ENTRY_NOT_FOUND",
            "未找到指定的历史记录。",
            status_code=404,
        )
    return {
        "success": True,
        "data": {
            "item": item,
        },
    }


@router.delete("/history/{history_id}")
def delete_history_entry(history_id: str):
    store = get_task_history_store()
    deleted = store.delete_history(history_id)
    if not deleted:
        raise AdapterError(
            "HISTORY_ENTRY_NOT_FOUND",
            "未找到指定的历史记录。",
            status_code=404,
        )
    return {
        "success": True,
        "data": {
            "deleted": True,
            "id": history_id,
        },
    }


@router.delete("/history")
def clear_history(taskType: Optional[str] = Query(default=None)):
    task_type = str(taskType or "").strip()
    if not task_type:
        raise AdapterError(
            "TASK_TYPE_REQUIRED",
            "缺少 taskType 查询参数。",
            status_code=400,
        )
    store = get_task_history_store()
    cleared_count = store.clear_history(task_type)
    return {
        "success": True,
        "data": {
            "clearedCount": cleared_count,
            "taskType": task_type,
        },
    }
