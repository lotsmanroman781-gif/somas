"""Email/password login with PBKDF2 hashes, opaque hashed sessions and CSRF protection."""
from __future__ import annotations
import hashlib, hmac, os, secrets, sqlite3, time, uuid
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request
from fastapi.security.utils import get_authorization_scheme_param
from . import store

COOKIE_NAME='somas_session'
SESSION_SECONDS=7*24*3600
HASH_ITERATIONS=600_000
# Controls accidental fast brute force from the same account/IP in one server process.
# Production systems need a durable/distributed edge rate limit as well.
_ATTEMPTS={}

def hash_password(password:str,salt:bytes)->bytes:
    return hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,HASH_ITERATIONS)

def register(email:str,display_name:str,password:str):
    salt=secrets.token_bytes(24)
    digest=hash_password(password,salt)
    uid='usr_'+uuid.uuid4().hex
    with store.LOCK,store.db() as c:
        try:
            c.execute('INSERT INTO users(id,email,display_name,password_salt,password_hash,created_at) VALUES(?,?,?,?,?,?)',
                      (uid,email.strip().lower(),display_name.strip(),salt,digest,store.stamp()))
        except sqlite3.IntegrityError:
            raise HTTPException(409,'Account already exists for this email address')
    return {'id':uid,'email':email.strip().lower(),'display_name':display_name.strip()}

def user_by_id(uid):
    with store.db() as c:
        row=c.execute('SELECT id,email,display_name,created_at FROM users WHERE id=?',(uid,)).fetchone()
    return dict(row) if row else None

def _throttle(key):
    now=time.monotonic()
    with store.LOCK:
        attempts=[t for t in _ATTEMPTS.get(key,[]) if now-t < 15*60]
        if len(attempts)>=8:
            raise HTTPException(429,'Too many login attempts. Try again later.')
        attempts.append(now)
        _ATTEMPTS[key]=attempts

def verify_credentials(email,password,ip='local'):
    email=email.strip().lower()
    key=(email,ip)
    _throttle(key)
    with store.db() as c:
        row=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
    # Compare using real hash work even when the account does not exist.
    salt=row['password_salt'] if row else bytes.fromhex('28'*24)
    expected=row['password_hash'] if row else bytes.fromhex('29'*32)
    valid=hmac.compare_digest(hash_password(password,salt),expected)
    if not row or not valid:
        raise HTTPException(401,'Invalid email or password')
    with store.LOCK:
        _ATTEMPTS.pop(key,None)
    return dict(row)

def issue_session(uid):
    token=secrets.token_urlsafe(48)
    token_hash=hashlib.sha256(token.encode()).hexdigest()
    csrf=secrets.token_urlsafe(32)
    now=datetime.now(timezone.utc)
    with store.LOCK,store.db() as c:
        c.execute('DELETE FROM sessions WHERE expires_at<?',(now.isoformat(),))
        c.execute('INSERT INTO sessions(token_hash,user_id,csrf,created_at,expires_at) VALUES(?,?,?,?,?)',
                  (token_hash,uid,csrf,now.isoformat(),(now+timedelta(seconds=SESSION_SECONDS)).isoformat()))
    return token,csrf

def session_for(token):
    if not token:return None
    th=hashlib.sha256(token.encode()).hexdigest()
    with store.db() as c:
        row=c.execute('SELECT token_hash,user_id,csrf,expires_at FROM sessions WHERE token_hash=?',(th,)).fetchone()
    if not row or datetime.fromisoformat(row['expires_at'])<=datetime.now(timezone.utc):return None
    return dict(row)

def session_from_request(request:Request):
    header=request.headers.get('authorization','')
    scheme,token=get_authorization_scheme_param(header)
    if header:
        if scheme.lower()!='bearer':raise HTTPException(401,'Use Bearer authentication')
        return session_for(token),False
    return session_for(request.cookies.get(COOKIE_NAME)),True

def current_auth(request:Request):
    session,via_cookie=session_from_request(request)
    if not session:raise HTTPException(401,'Please sign in')
    if via_cookie and request.method.upper() not in ('GET','HEAD','OPTIONS'):
        submitted=request.headers.get('x-csrf-token','')
        if not hmac.compare_digest(submitted,session['csrf']):
            raise HTTPException(403,'Missing or invalid CSRF token')
    user=user_by_id(session['user_id'])
    if not user:raise HTTPException(401,'Account no longer exists')
    return {'user':user,'session':session,'via_cookie':via_cookie}

def current_user(auth=Depends(current_auth)):
    return auth['user']

def destroy_session(session):
    with store.LOCK,store.db() as c:
        c.execute('DELETE FROM sessions WHERE token_hash=?',(session['token_hash'],))

def destroy_all_sessions(uid):
    with store.LOCK,store.db() as c:
        c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))

def set_cookie(response,request:Request,token):
    secure=request.url.scheme=='https' or os.getenv('SOMAS_SECURE_COOKIES','').strip().lower() in ('true','1','yes')
    response.set_cookie(COOKIE_NAME,token,max_age=SESSION_SECONDS,httponly=True,
                        secure=secure,samesite='strict',path='/')
