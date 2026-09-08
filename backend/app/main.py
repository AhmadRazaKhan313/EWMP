from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.tenant import TenantMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging, sqlalchemy
    logger = logging.getLogger("ewmp.startup")
    try:
        from app.core.database import engine
        async with engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception as e:
        logger.error("Database connection failed: %s", e)
    yield
    from app.core.database import engine
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME, version=settings.APP_VERSION,
        description="Enterprise Workforce Management Platform",
        docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    # CORS: restrict to the configured origin allowlist. A wildcard "*" must
    # never be combined with allow_credentials=True — browsers reject that pair,
    # and Starlette instead reflects the caller's Origin, which would let ANY
    # site make credentialed cross-origin requests (bug H3). ALLOWED_ORIGINS is
    # set per environment via settings.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(TenantMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)
    _register_routers(app)

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "healthy", "version": settings.APP_VERSION, "environment": settings.ENVIRONMENT}

    @app.get("/", include_in_schema=False)
    async def root():
        return {"product": settings.APP_NAME, "version": settings.APP_VERSION}

    return app


def _register_routers(app: FastAPI) -> None:
    from app.api.v1.auth.router import router as auth_router
    from app.api.v1.auth.onboarding import router as onboarding_router
    from app.api.v1.auth.admin_setup import router as admin_setup_router
    from app.api.v1.hrms.employees import router as employees_router
    from app.api.v1.hrms.employee_documents import router as employee_documents_router
    from app.api.v1.hrms.roles import router as roles_router
    from app.api.v1.hrms.departments import router as departments_router
    from app.api.v1.hrms.branches import router as branches_router
    from app.api.v1.hrms.teams import router as teams_router
    from app.api.v1.hrms.designations import router as designations_router
    from app.api.v1.hrms.shifts import router as shifts_router
    from app.api.v1.hrms.attendance import router as attendance_router
    from app.api.v1.hrms.leave import router as leave_router
    from app.api.v1.hrms.payroll import router as payroll_router
    from app.api.v1.hrms.recruitment import router as recruitment_router
    from app.api.v1.hrms.performance import router as performance_router
    from app.api.v1.hrms.assets import router as assets_router
    from app.api.v1.hrms.helpdesk import router as helpdesk_router
    from app.api.v1.hrms.dashboard import router as dashboard_router
    from app.api.v1.hrms.work_sessions import router as work_sessions_router
    from app.api.v1.devices.devices import router as devices_router
    from app.api.v1.ai.chat import router as ai_router
    from app.api.v1.webhooks.router import router as webhooks_router

    prefix = settings.API_V1_PREFIX
    for r in [
        auth_router, onboarding_router, admin_setup_router,
        employees_router, employee_documents_router, roles_router, departments_router, branches_router,
        teams_router, designations_router, shifts_router,
        attendance_router, leave_router, payroll_router,
        recruitment_router, performance_router,
        assets_router, helpdesk_router, dashboard_router, work_sessions_router,
        devices_router, ai_router, webhooks_router,
    ]:
        app.include_router(r, prefix=prefix)


app = create_app()