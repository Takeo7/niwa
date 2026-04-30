"""HTTP routers for the Niwa v1 API.

``api_router`` is the parent router registered under ``/api`` in
``app.main``; individual resource routers attach to it.
"""

from __future__ import annotations

from fastapi import APIRouter

from .audit import router as audit_router
from .auth import router as auth_router
from .deploy import router as deploy_router
from .deployments import router as deployments_router
from .metrics import router as metrics_router
from ..mcp.server import router as mcp_router
from .ops import router as ops_router
from .projects import router as projects_router
from .readiness import router as readiness_router
from .runs import runs_router
from .tasks import project_tasks_router, tasks_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(audit_router)
api_router.include_router(mcp_router)
api_router.include_router(metrics_router)
api_router.include_router(projects_router)
api_router.include_router(project_tasks_router)
api_router.include_router(tasks_router)
api_router.include_router(runs_router)
api_router.include_router(deploy_router)
api_router.include_router(deployments_router)
api_router.include_router(ops_router)
api_router.include_router(readiness_router)

__all__ = ["api_router"]
