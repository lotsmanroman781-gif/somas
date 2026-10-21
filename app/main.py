"""SOMAS v1.1: authenticated per-user organizations and independently trained agents."""
from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
import os, re
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from . import auth, engine, store
from .catalog import CAP_KEYS, CAPABILITIES, STRATEGIES

@asynccontextmanager
async def lifespan(app):
    store.init_db()
    yield

app=FastAPI(title='SOMAS - Self Organizing Multi Agent System',version='1.1.0',lifespan=lifespan)
PUBLIC=Path(__file__).resolve().parent/'static'
app.mount('/static',StaticFiles(directory=PUBLIC),name='static')

@app.middleware('http')
async def security_headers(request:Request, call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    return response

class Signup(BaseModel):
    email:str=Field(min_length=5,max_length=254)
    display_name:str=Field(min_length=2,max_length=80)
    password:str=Field(min_length=12,max_length=128)
    @field_validator('email')
    @classmethod
    def valid_email(cls,v):
        v=v.strip().lower()
        if not re.fullmatch(r'[a-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+',v):
            raise ValueError('Enter a valid email address')
        return v
    @field_validator('display_name')
    @classmethod
    def valid_name(cls,v):
        v=v.strip()
        if len(v)<2:raise ValueError('Please enter a display name')
        return v

class Login(BaseModel):
    email:str=Field(min_length=5,max_length=254)
    password:str=Field(min_length=1,max_length=128)

class ChangePassword(BaseModel):
    old_password:str
    new_password:str=Field(min_length=12,max_length=128)

class ProfileEdit(BaseModel):
    display_name:str=Field(min_length=2,max_length=80)

@app.post('/api/auth/register',status_code=201)
def register(payload:Signup,request:Request,response:Response):
    user=auth.register(payload.email,payload.display_name,payload.password)
    token,csrf=auth.issue_session(user['id'])
    auth.set_cookie(response,request,token)
    return {'user':user,'csrf_token':csrf}

@app.post('/api/auth/login')
def login(payload:Login,request:Request,response:Response):
    row=auth.verify_credentials(payload.email,payload.password,request.client.host if request.client else 'local')
    token,csrf=auth.issue_session(row['id'])
    auth.set_cookie(response,request,token)
    return {'user':auth.user_by_id(row['id']),'csrf_token':csrf}

@app.get('/api/auth/me')
def me(identity=Depends(auth.current_auth)):
    return {'user':identity['user'],'csrf_token':identity['session']['csrf']}

@app.post('/api/auth/logout')
def logout(response:Response,identity=Depends(auth.current_auth)):
    auth.destroy_session(identity['session'])
    response.delete_cookie(auth.COOKIE_NAME,path='/',samesite='strict')
    return {'ok':True}

@app.post('/api/auth/change-password')
def change_password(payload:ChangePassword,identity=Depends(auth.current_auth)):
    uid=identity['user']['id']
    # Reauthentication is required even when already signed in.
    auth.verify_credentials(identity['user']['email'],payload.old_password)
    import secrets
    salt=secrets.token_bytes(24)
    with store.LOCK,store.db() as c:
        c.execute('UPDATE users SET password_salt=?,password_hash=? WHERE id=?',
                  (salt,auth.hash_password(payload.new_password,salt),uid))
    auth.destroy_all_sessions(uid)
    return {'ok':True,'message':'Password changed. Please sign in again.'}

@app.patch('/api/auth/profile')
def profile(payload:ProfileEdit,identity=Depends(auth.current_auth)):
    uid=identity['user']['id']
    name=payload.display_name.strip()
    if len(name)<2:raise HTTPException(422,'Display name must contain two characters')
    with store.LOCK,store.db() as c:
        c.execute('UPDATE users SET display_name=? WHERE id=?',(name,uid))
    return auth.user_by_id(uid)

class Business(BaseModel):
    name:str=Field(min_length=2,max_length=110)
    industry:str=Field(min_length=2,max_length=120)
    goal:str=Field(min_length=12,max_length=2200)
    size:Literal['micro','small','medium','enterprise']='small'
    country:str=Field(default='Global',min_length=2,max_length=90)
    language:str=Field(default='English',min_length=2,max_length=80)
    budget_usd:float=Field(default=1000,ge=0,le=100000000)
    @field_validator('name','industry','goal','country','language')
    @classmethod
    def strip_values(cls,value):
        value=value.strip()
        if not value:raise ValueError('Value must not be blank')
        return value

class CreateBusiness(Business):
    mode:Literal['demo','ai','auto']='auto'

class RunRequest(BaseModel):
    mode:Literal['demo','ai']='demo'

class ManagerFeedback(BaseModel):
    score:int=Field(ge=1,le=5)
    correct_capabilities:list[str]=Field(default_factory=list,max_length=13)
    notes:str=Field(default='',max_length=600)
    verified:bool=False
    @field_validator('correct_capabilities')
    @classmethod
    def validate_caps(cls,caps):
        if any(c not in CAP_KEYS for c in caps):raise ValueError('Unknown capability')
        return list(dict.fromkeys(caps))

class WorkerFeedback(BaseModel):
    corrected_strategy:Literal['research','analyze','draft','verify','escalate','summarize']
    verified:bool=False

@app.get('/')
def home():return FileResponse(PUBLIC/'index.html')

@app.get('/api/status')
def status(user=Depends(auth.current_user)):
    model=store.load_policy(user['id'],'root_manager')
    return {'version':'1.1.0','mode':'ai_available' if engine.api_available() else 'demo_only',
            'has_openai_key':engine.api_available(),'openai_model':os.getenv('OPENAI_MODEL','gpt-4.1-mini') if engine.api_available() else None,
            'manager_weights':model.parameter_count,'manager_policy_version':model.version,
            'agent_limit':engine.MAX_AGENTS,'auto_execution':False,'external_actions_enabled':False}

@app.get('/api/catalog')
def catalog(user=Depends(auth.current_user)):
    return {'capabilities':CAPABILITIES,'strategies':STRATEGIES}

@app.get('/api/agents')
def my_agents(user=Depends(auth.current_user)):
    return store.list_agents(user['id'])

@app.get('/api/organizations')
def organizations(user=Depends(auth.current_user)):
    return store.list_orgs(user['id'])

@app.post('/api/organizations',status_code=201)
def create(payload:CreateBusiness,user=Depends(auth.current_user)):
    try:return engine.build_org(user['id'],payload.model_dump(exclude={'mode'}),payload.mode)
    except (RuntimeError,ValueError) as e:raise HTTPException(status_code=400,detail=str(e))

@app.get('/api/organizations/{org_id}')
def org_detail(org_id:str,user=Depends(auth.current_user)):
    obj=store.get_org(user['id'],org_id)
    if not obj:raise HTTPException(404,'Organization not found')
    return obj

@app.post('/api/organizations/{org_id}/reorganize',status_code=201)
def reorganize(org_id:str,request:RunRequest,user=Depends(auth.current_user)):
    old=store.get_org(user['id'],org_id)
    if not old:raise HTTPException(404,'Organization not found')
    try:return engine.build_org(user['id'],old['business'],request.mode,parent_org_id=org_id)
    except (RuntimeError,ValueError) as e:raise HTTPException(400,str(e))

@app.post('/api/organizations/{org_id}/run')
def run(org_id:str,request:RunRequest,user=Depends(auth.current_user)):
    try:return engine.run_org(user['id'],org_id,request.mode)
    except KeyError:raise HTTPException(404,'Organization not found')
    except RuntimeError as e:raise HTTPException(400,str(e))

@app.get('/api/organizations/{org_id}/runs')
def runs(org_id:str,user=Depends(auth.current_user)):
    if not store.get_org(user['id'],org_id):raise HTTPException(404,'Organization not found')
    return store.list_runs(user['id'],org_id)

@app.post('/api/organizations/{org_id}/feedback')
def feedback(org_id:str,payload:ManagerFeedback,user=Depends(auth.current_user)):
    try:return engine.manager_feedback(user['id'],org_id,payload.score,payload.correct_capabilities,payload.notes,payload.verified)
    except KeyError:raise HTTPException(404,'Organization not found')

@app.post('/api/organizations/{org_id}/agents/{agent_id}/feedback')
def agent_feedback(org_id:str,agent_id:str,payload:WorkerFeedback,user=Depends(auth.current_user)):
    try:return engine.worker_feedback(user['id'],org_id,agent_id,payload.corrected_strategy,payload.verified)
    except KeyError:raise HTTPException(404,'Agent or organization not found')

@app.get('/api/organizations/{org_id}/export')
def export(org_id:str,user=Depends(auth.current_user)):
    org=store.get_org(user['id'],org_id)
    if not org:raise HTTPException(404,'Organization not found')
    return {'organization':org,'runs':store.list_runs(user['id'],org_id),'export_version':2}

@app.get('/api/events')
def events(user=Depends(auth.current_user)):
    return store.events(user['id'])
