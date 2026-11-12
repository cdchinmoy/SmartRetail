import uuid
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app.core.db import engine
from app.auth.router import router as auth
from app.tenancy.router import router as tenancy
from app.platform.router import router as platform
from app.billing.router import router as billing

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('smartretail')

@asynccontextmanager
async def lifespan(app):
    with engine.connect() as conn:
        unsafe = conn.execute(text('SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user')).scalar()
        if unsafe:
            raise RuntimeError('Application role must not be superuser or BYPASSRLS')
    yield

app = FastAPI(title='SmartRetail Cloud — Foundation', version='0.2.0', lifespan=lifespan)
for router in (auth, tenancy, platform, billing):
    app.include_router(router, prefix='/api/v1')

@app.middleware('http')
async def request_id(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    start = time.monotonic()
    response = await call_next(request)
    response.headers['X-Request-ID'] = request.state.request_id
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # No payloads, tokens, emails, raw URLs, or tenant business fields.
    logger.info('request id=%s status=%s duration_ms=%.1f', request.state.request_id, response.status_code, (time.monotonic()-start)*1000)
    return response

def error(request, status, code, message):
    return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message}, 'request_id': request.state.request_id})
@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return error(request, exc.status_code, f'HTTP_{exc.status_code}', str(exc.detail))
@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return error(request, 422, 'VALIDATION_ERROR', 'Invalid request fields')
@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return error(request, 409, 'CONFLICT', 'Record conflicts with existing data or a relationship')
@app.get('/health')
def health():
    with engine.connect() as conn:
        conn.execute(text('SELECT 1'))
    return {'status': 'ok'}
