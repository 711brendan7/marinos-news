import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.database import init_db
from backend.routers import tests, improvements, chat

logger = logging.getLogger("ie_lms")
logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOADS_DIR = BASE_DIR / "uploads"

app = FastAPI(title="IE-LMS API", version="1.0.0")

init_db()

app.include_router(tests.router)
app.include_router(improvements.router)
app.include_router(chat.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # 想定外の例外でプロセスごと落ちて無反応になるのを防ぎ、
    # ログに残した上で500 JSONを返す（HTTPExceptionは各routerで個別処理済み）
    if isinstance(exc, HTTPException):
        raise exc
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "サーバー内部でエラーが発生しました"},
    )

app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
