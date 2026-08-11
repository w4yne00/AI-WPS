from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.health import SERVICE_VERSION, get_health_snapshot
from app.services.recovery import RecoveryOperationError, get_recovery_operations


router = APIRouter()


def _envelope(data: dict) -> dict:
    return {"success": True, "data": data}


@router.post("/recovery/backups")
def create_recovery_backup():
    health = get_health_snapshot()
    try:
        data = get_recovery_operations(SERVICE_VERSION).create_read_only_backup(
            current_status=health.get("status", "")
        )
    except RecoveryOperationError as error:
        recovery_mode_required = error.code == "RECOVERY_MODE_REQUIRED"
        message = (
            "只允许在恢复模式下创建只读运行数据备份。"
            if recovery_mode_required
            else "只读运行数据备份创建失败，请检查磁盘和运行状态后重试。"
        )
        return JSONResponse(
            status_code=409 if recovery_mode_required else 503,
            content={
                "success": False,
                "message": message,
                "data": {},
                "errors": [
                    {
                        "code": error.code,
                        "message": message,
                    }
                ],
            },
        )
    return _envelope(data)


@router.get("/recovery/diagnostics")
def export_recovery_diagnostics() -> dict:
    health = get_health_snapshot()
    data = get_recovery_operations(SERVICE_VERSION).build_diagnostics(health)
    return _envelope(data)
