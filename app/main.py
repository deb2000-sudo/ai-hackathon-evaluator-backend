"""
FastAPI main application
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routes import admin, auth, submissions
from app.utils.cors_config import get_allowed_origins
from app.utils.seeder import DatabaseSeeder


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI
    """
    # Startup
    logger.info("🚀 FastAPI application starting...")

    # Run database seeding on startup
    try:
        logger.info("🌱 Initializing database...")
        seeder = DatabaseSeeder()
        seeder.seed_all()
        logger.info("Database initialization completed")
    except Exception as e:
        logger.warning(f"Database seeding encountered an issue: {str(e)}")
        # Don't fail startup if seeding fails

    yield
    # Shutdown
    logger.info("FastAPI application shutting down...")


# Create FastAPI app
app = FastAPI(
    title="AI Hackathon Evaluator Backend",
    description="FastAPI backend that evaluates hackathon submission videos with AI",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: credentials + explicit origins required for cross-origin HttpOnly cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Routes ====================
@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "message": "AI Hackathon Evaluator Backend is running",
    }


# Include routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(submissions.router)


# ==================== Error Handlers ====================
@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    """Handle ValueError exceptions"""
    logger.error(f"ValueError: {str(exc)}")
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions"""
    logger.error(f"Unhandled exception: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ==================== Root Endpoint ====================
@app.get("/", tags=["root"])
async def root():
    """Root endpoint"""
    return {
        "status": "success",
        "message": "Welcome to AI Hackathon Evaluator backend",
        "docs": "/docs",
        "openapi_schema": "/openapi.json",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
