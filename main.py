from contextlib import asynccontextmanager
import atexit
import signal
import sys
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
import uvicorn

from src.config import Settings, setup_logger, shutdown_logger, PROJECT_ROOT
from src.helpers import (
    register_cors,
    register_middleware,
    register_error_handlers,
    init_db,
    shutdown_db,
    session_scope,
    kill_pid,
    connection,
    generate_nginx_config,
    start_frontend,
    stop_frontend
)
from sqlalchemy import text
from src.db.models import Base
from src.routers import (
    auth_router,
    services_router,
    logs_router,
    system_router
)

# 1. Initialize Logger
logger = setup_logger(
    PROJECT_ROOT / "logs" / "app.log", 
    name="app.main"
)

# 2. Define Lifespan (Startup/Shutdown events)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Database
    init_db(Settings.DATABASE_URL)
    async with connection._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Ensure SQLite backward compatibility for username column if needed
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(100);"))
        except Exception as e:
            logger.debug(f"Column check notice: {e}")
    logger.info("Database initialized")

    # Auto-sync admin user configured in .env
    try:
        async with session_scope() as session:
            from src.services.auth import sync_env_admin
            await sync_env_admin(session)
    except Exception as e:
        logger.warning(f"Could not auto-sync .env admin user: {e}")
    
    # Auto-generate Nginx configuration dynamically on boot
    if generate_nginx_config():
        logger.info("Nginx configuration auto-generated successfully")
    else:
        logger.warning("Nginx configuration auto-generation skipped or failed")
    
    yield
    
    # --- Shutdown ---
    logger.info("Shutting down application...")
    await shutdown_db()
    shutdown_logger()

# 3. Initialize FastAPI App
app = FastAPI(
    title=Settings.PROJECT_NAME,
    version=Settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs" if not Settings.is_production else None,
    redoc_url=None
)

# 4. Register Infrastructure / Helpers
register_cors(app, Settings)
register_middleware(app, logger, Settings)
register_error_handlers(app, logger)

# 5. Include Routers
app.include_router(system_router)
app.include_router(services_router)
app.include_router(logs_router)
app.include_router(auth_router)

@app.get("/", include_in_schema=False)
async def root():
    """Redirect root requests to the Next.js frontend application."""
    return RedirectResponse(url=Settings.FRONTEND_URL)

@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "ok", 
        "project": Settings.PROJECT_NAME,
        "environment": Settings.ENV,
        "version": Settings.VERSION
    }

if __name__ == "__main__":
    host = getattr(Settings, "API_HOST", "127.0.0.1")
    port = getattr(Settings, "API_PORT", 8000)

    # 1. Kill any orphaned process holding backend port
    kill_pid(port)

    # 2. Concurrently start the Next.js frontend (dev or prod according to APP_ENV)
    start_frontend()
    atexit.register(stop_frontend)

    def handle_exit(signum, frame):
        stop_frontend()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # 3. Launch Uvicorn with appropriate reload config
    try:
        is_prod = Settings.is_production
        if is_prod:
            logger.info(f"Starting API in PRODUCTION mode on http://{host}:{port}")
            uvicorn.run(
                "main:app",
                host=host,
                port=port,
                reload=False
            )
        else:
            logger.info(f"Starting API in DEVELOPMENT mode with hot-reload on http://{host}:{port}")
            uvicorn.run(
                "main:app",
                host=host,
                port=port,
                reload=True,
                reload_dirs=[str(PROJECT_ROOT / "src")],
                reload_includes=["main.py"]
            )
    finally:
        stop_frontend()
