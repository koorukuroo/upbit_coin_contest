"""API 라우터 패키지"""
from routers.auth import router as auth_router
from routers.keys import router as keys_router
from routers.competitions import router as competitions_router
from routers.trading import router as trading_router
from routers.admin import router as admin_router

__all__ = [
    "auth_router",
    "keys_router",
    "competitions_router",
    "trading_router",
    "admin_router",
]
