"""认证与用户路由"""
from fastapi import APIRouter, HTTPException
from backend.models.models import LoginRequest, LoginResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """演示登录——不需要真实账号验证"""
    if not req.email or not req.password:
        raise HTTPException(status_code=400, detail="邮箱和密码不能为空")
    return LoginResponse(
        token="demo-token-office-agent-2026",
        user_name="访客用户",
        role="只读权限",
    )

@router.get("/me")
async def get_current_user():
    """返回当前用户信息（演示模式）"""
    return {
        "name": "访客用户",
        "role": "只读权限",
        "avatar": "访",
    }
