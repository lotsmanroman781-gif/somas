"""SOMAS v1.2: authenticated per-user organizations and independently trained agents."""

from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
import os, re
from fastapi import Depends, FastAPI, HTTPException, Request, Response, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, field_validator
from . import auth, engine, store, database
from .security import SecurityMiddleware
from sqlalchemy.exc import SQLAlchemyError
from .catalog import CAP_KEYS, CAPABILITIES, STRATEGIES


@asynccontextmanager
async def lifespan(app):
    if os.getenv("SOMAS_SECURE_COOKIES") == "1" and (
        len(os.getenv("SOMAS_PROXY_SECRET", "")) < 32
        or not os.getenv("SOMAS_ALLOWED_ORIGINS")
    ):
        raise RuntimeError(
            "HTTPS deployment requires proxy secret (32+ characters) and allowed origins"
        )
    await store.init_db()
    try:
        yield
    finally:
        await store.close_db()


app = FastAPI(
    title="SOMAS - Self Organizing Multi Agent System",
    version="1.2.0",
    lifespan=lifespan,
)
app.add_middleware(SecurityMiddleware)
PUBLIC = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/static", StaticFiles(directory=PUBLIC / "static"), name="static")


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # FastAPI's default validation payload may echo passwords or business input.
    errors = [
        {key: error[key] for key in ("loc", "msg", "type")} for error in exc.errors()
    ]
    return JSONResponse({"detail": errors}, status_code=422)


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    return JSONResponse(
        {"detail": "Database temporarily unavailable. Please retry later."},
        status_code=503,
    )


@app.exception_handler(store.PolicyConflict)
async def policy_conflict(request, exc):
    return JSONResponse(
        {"detail": "Policy changed during training. Reload and retry the correction."},
        status_code=409,
    )


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "version": "1.2.0"}


@app.get("/readyz")
async def readyz():
    try:
        await database.ping()
    except (SQLAlchemyError, RuntimeError):
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ready"}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class Signup(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    display_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, v):
        v = v.strip().lower()
        if not re.fullmatch(
            "[a-z0-9.!#$%&\\'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+",
            v,
        ):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("display_name")
    @classmethod
    def valid_name(cls, v):
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Please enter a display name")
        return v


class Login(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class ChangePassword(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class ProfileEdit(BaseModel):
    display_name: str = Field(min_length=2, max_length=80)


@app.post("/api/auth/register", status_code=201)
async def register(payload: Signup, request: Request, response: Response):
    if os.getenv("SOMAS_ALLOW_PUBLIC_SIGNUP", "true").lower() not in ("true", "1"):
        raise HTTPException(403, "Public registration is disabled")
    await auth.throttle("signup-ip", auth.client_identity(request), 5, 3600)
    user = await auth.register(payload.email, payload.display_name, payload.password)
    token, csrf = await auth.issue_session(user["id"])
    auth.set_cookie(response, request, token)
    return {"user": user, "csrf_token": csrf}


@app.post("/api/auth/login")
async def login(payload: Login, request: Request, response: Response):
    row = await auth.verify_credentials(
        payload.email, payload.password, auth.client_identity(request)
    )
    token, csrf = await auth.issue_session(row["id"], row.get("session_version", 0))
    auth.set_cookie(response, request, token)
    return {"user": await auth.user_by_id(row["id"]), "csrf_token": csrf}


@app.get("/api/auth/me")
async def me(identity=Depends(auth.current_auth)):
    return {"user": identity["user"], "csrf_token": identity["session"]["csrf"]}


@app.post("/api/auth/logout")
async def logout(
    request: Request, response: Response, identity=Depends(auth.current_auth)
):
    await auth.destroy_session(identity["session"])
    response.delete_cookie(
        auth.COOKIE_NAME,
        path="/",
        samesite="strict",
        httponly=True,
        secure=auth.secure_cookies(request),
    )
    return {"ok": True}


@app.post("/api/auth/change-password")
async def change_password(payload: ChangePassword, identity=Depends(auth.current_auth)):
    uid = identity["user"]["id"]
    row = await auth.verify_credentials(identity["user"]["email"], payload.old_password)
    import secrets

    salt = secrets.token_bytes(24)
    digest = await asyncio.to_thread(auth.hash_password, payload.new_password, salt)
    if not await store.change_password(
        uid, row.get("session_version", 0), salt, digest
    ):
        raise HTTPException(409, "Credentials changed. Please sign in again.")
    return {"ok": True, "message": "Password changed. Please sign in again."}


@app.patch("/api/auth/profile")
async def profile(payload: ProfileEdit, identity=Depends(auth.current_auth)):
    uid = identity["user"]["id"]
    name = payload.display_name.strip()
    if len(name) < 2:
        raise HTTPException(422, "Display name must contain two characters")
    await store.update_profile(uid, name)
    return await auth.user_by_id(uid)


class Business(BaseModel):
    name: str = Field(min_length=2, max_length=110)
    industry: str = Field(min_length=2, max_length=120)
    goal: str = Field(min_length=12, max_length=2200)
    size: Literal["micro", "small", "medium", "enterprise"] = "small"
    country: str = Field(default="Global", min_length=2, max_length=90)
    language: str = Field(default="English", min_length=2, max_length=80)
    budget_usd: float = Field(default=1000, ge=0, le=100000000)

    @field_validator("name", "industry", "goal", "country", "language")
    @classmethod
    def strip_values(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank")
        return value


class CreateBusiness(Business):
    mode: Literal["demo", "ai", "auto"] = "demo"


class RunRequest(BaseModel):
    mode: Literal["demo", "ai"] = "demo"


class ManagerFeedback(BaseModel):
    score: int = Field(ge=1, le=5)
    correct_capabilities: list[str] = Field(default_factory=list, max_length=13)
    notes: str = Field(default="", max_length=600)
    verified: bool = False

    @field_validator("correct_capabilities")
    @classmethod
    def validate_caps(cls, caps):
        if any((c not in CAP_KEYS for c in caps)):
            raise ValueError("Unknown capability")
        return list(dict.fromkeys(caps))


class WorkerFeedback(BaseModel):
    corrected_strategy: Literal[
        "research", "analyze", "draft", "verify", "escalate", "summarize"
    ]
    verified: bool = False


@app.get("/")
async def home():
    return FileResponse(PUBLIC / "index.html")


@app.get("/api/status")
async def status(user=Depends(auth.current_user)):
    model = await store.load_policy(user["id"], "root_manager")
    return {
        "version": "1.2.0",
        "mode": "ai_available" if engine.api_available() else "demo_only",
        "has_openai_key": engine.api_available(),
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        if engine.api_available()
        else None,
        "manager_weights": model.parameter_count,
        "manager_policy_version": model.version,
        "agent_limit": engine.MAX_AGENTS,
        "auto_execution": False,
        "external_actions_enabled": False,
    }


@app.get("/api/catalog")
async def catalog(user=Depends(auth.current_user)):
    return {"capabilities": CAPABILITIES, "strategies": STRATEGIES}


@app.get("/api/agents")
async def my_agents(
    user=Depends(auth.current_user),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
):
    return await store.list_agents(user["id"], limit, offset)


@app.get("/api/organizations")
async def organizations(
    user=Depends(auth.current_user),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
):
    return await store.list_orgs(user["id"], limit, offset)


@app.post("/api/organizations", status_code=201)
async def create(payload: CreateBusiness, user=Depends(auth.current_user)):
    try:
        return await engine.build_org(
            user["id"], payload.model_dump(exclude={"mode"}), payload.mode
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/organizations/{org_id}")
async def org_detail(org_id: str, user=Depends(auth.current_user)):
    obj = await store.get_org(user["id"], org_id)
    if not obj:
        raise HTTPException(404, "Organization not found")
    return obj


@app.post("/api/organizations/{org_id}/reorganize", status_code=201)
async def reorganize(org_id: str, request: RunRequest, user=Depends(auth.current_user)):
    old = await store.get_org(user["id"], org_id)
    if not old:
        raise HTTPException(404, "Organization not found")
    try:
        return await engine.build_org(
            user["id"], old["business"], request.mode, parent_org_id=org_id
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/organizations/{org_id}/run")
async def run(org_id: str, request: RunRequest, user=Depends(auth.current_user)):
    try:
        return await engine.run_org(user["id"], org_id, request.mode)
    except KeyError:
        raise HTTPException(404, "Organization not found")
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.get("/api/organizations/{org_id}/runs")
async def runs(
    org_id: str,
    user=Depends(auth.current_user),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
):
    if not await store.get_org(user["id"], org_id):
        raise HTTPException(404, "Organization not found")
    return await store.list_runs(user["id"], org_id, limit, offset)


@app.post("/api/organizations/{org_id}/feedback")
async def feedback(
    org_id: str, payload: ManagerFeedback, user=Depends(auth.current_user)
):
    try:
        return await engine.manager_feedback(
            user["id"],
            org_id,
            payload.score,
            payload.correct_capabilities,
            payload.notes,
            payload.verified,
        )
    except KeyError:
        raise HTTPException(404, "Organization not found")


@app.post("/api/organizations/{org_id}/agents/{agent_id}/feedback")
async def agent_feedback(
    org_id: str, agent_id: str, payload: WorkerFeedback, user=Depends(auth.current_user)
):
    try:
        return await engine.worker_feedback(
            user["id"], org_id, agent_id, payload.corrected_strategy, payload.verified
        )
    except KeyError:
        raise HTTPException(404, "Agent or organization not found")


@app.get("/api/organizations/{org_id}/export")
async def export(org_id: str, user=Depends(auth.current_user)):
    org = await store.get_org(user["id"], org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    return {
        "organization": org,
        "runs": await store.list_runs(user["id"], org_id),
        "export_version": 2,
    }


@app.get("/api/events")
async def events(
    user=Depends(auth.current_user),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
):
    return await store.events(user["id"], limit, offset)


@app.get("/api/manager")
async def manager(user=Depends(auth.current_user)):
    model = await store.load_policy(user["id"], "root_manager")
    return {
        "id": "root_manager",
        "owner_id": user["id"],
        "policy_version": model.version,
        "parameter_count": model.parameter_count,
    }


class AgentUpdate(BaseModel):
    task: str | None = Field(default=None, min_length=10, max_length=170)
    role: str | None = Field(default=None, min_length=2, max_length=120)


@app.get("/api/organizations/{org_id}/agents/{agent_id}")
async def get_agent(org_id: str, agent_id: str, user=Depends(auth.current_user)):
    try:
        return await store.agent_detail(user["id"], org_id, agent_id)
    except KeyError:
        raise HTTPException(404, "Agent or organization not found")


@app.patch("/api/organizations/{org_id}/agents/{agent_id}")
async def edit_agent(
    org_id: str, agent_id: str, payload: AgentUpdate, user=Depends(auth.current_user)
):
    try:
        return await store.update_agent(
            user["id"], org_id, agent_id, payload.model_dump(exclude_none=True)
        )
    except KeyError:
        raise HTTPException(404, "Agent or organization not found")


@app.get("/api/organizations/{org_id}/{resource}")
async def org_records(
    org_id: str,
    resource: Literal[
        "conversations",
        "decisions",
        "departments",
        "relationships",
        "memberships",
        "feedback",
    ],
    user=Depends(auth.current_user),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
):
    try:
        return await store.org_metadata(user["id"], org_id, resource, limit, offset)
    except KeyError:
        raise HTTPException(404, "Organization not found")
