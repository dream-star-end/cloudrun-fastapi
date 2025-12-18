# Routers package
from .chat import router as chat_router
from .recognize import router as recognize_router
from .search import router as search_router
from .plan import router as plan_router
from .tasks import router as tasks_router

__all__ = [
    "chat_router",
    "recognize_router",
    "search_router",
    "plan_router",
    "tasks_router",
]

