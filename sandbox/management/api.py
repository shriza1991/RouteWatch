"""Predefined sandbox controls. Bind this app to loopback only."""

import hmac
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictStr, field_validator

from sandbox import app as sandbox_app


ACTION_TO_CONTROL = {
    'enforce_booking_ownership': 'enforce_booking_ownership',
    'validate_quote_fare': 'validate_quote_fare',
    'disable_legacy_booking': 'disable_legacy_booking',
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    token = os.getenv('SANDBOX_MANAGEMENT_TOKEN', '')
    if not token.strip():
        raise RuntimeError('SANDBOX_MANAGEMENT_TOKEN must be configured')
    app.state.management_token = token
    sandbox_app.init()
    connection = sandbox_app.con()
    try:
        connection.execute('''CREATE TABLE IF NOT EXISTS management_executions (
            execution_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            action_key TEXT NOT NULL,
            state TEXT NOT NULL,
            requested_at TEXT NOT NULL
        )''')
        connection.commit()
    finally:
        connection.close()
    yield
    app.state.management_token = None


app = FastAPI(title='Sandbox management', lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action_key: StrictStr
    idempotency_key: StrictStr

    @field_validator('action_key', 'idempotency_key')
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip() or value != value.strip() or len(value) > 128:
            raise ValueError('must be nonblank, trimmed, and at most 128 characters')
        return value


class ExecutionResponse(BaseModel):
    execution_id: str
    action_key: str
    state: str
    requested_at: str


def authenticate(request: Request) -> None:
    supplied = request.headers.get('authorization', '')
    prefix = 'Bearer '
    token = request.app.state.management_token
    candidate = supplied[len(prefix):] if supplied.startswith(prefix) else ''
    if not candidate or not hmac.compare_digest(candidate, token):
        raise HTTPException(status_code=401, detail='Unauthorized')


@app.post('/management/actions', response_model=ExecutionResponse,
          dependencies=[Depends(authenticate)])
def execute(action: ActionRequest):
    connection = sandbox_app.con()
    try:
        connection.execute('BEGIN IMMEDIATE')
        existing = connection.execute(
            'SELECT * FROM management_executions WHERE idempotency_key=?',
            (action.idempotency_key,),
        ).fetchone()
        if existing:
            if existing['action_key'] != action.action_key:
                connection.rollback()
                raise HTTPException(status_code=409, detail='Idempotency key already used for another action')
            result = dict(existing)
            connection.commit()
            return result

        state = 'applied' if action.action_key in ACTION_TO_CONTROL else 'unsupported'
        result = {
            'execution_id': str(uuid.uuid4()),
            'action_key': action.action_key,
            'state': state,
            'requested_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        }
        if state == 'applied':
            sandbox_app.apply_control(ACTION_TO_CONTROL[action.action_key], True,
                                      connection=connection)
        connection.execute(
            'INSERT INTO management_executions VALUES (?,?,?,?,?)',
            (result['execution_id'], action.idempotency_key, action.action_key,
             state, result['requested_at']),
        )
        connection.commit()
        return result
    except HTTPException:
        raise
    except Exception:
        connection.rollback()
        return JSONResponse(status_code=500, content={'state': 'failed', 'detail': 'Management action failed'})
    finally:
        connection.close()


@app.post('/management/reset', dependencies=[Depends(authenticate)])
def reset():
    return sandbox_app.reset()


@app.post('/management/mode/{new_mode}', dependencies=[Depends(authenticate)])
def set_mode(new_mode: str):
    return sandbox_app.set_mode(new_mode)
