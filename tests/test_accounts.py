"""Security regression tests: user data and trainable weights must never cross accounts."""
from fastapi.testclient import TestClient
from app import store, auth
from app.main import app

PASSWORD='strong-password-for-tests-99'

def signup(client,email,name):
    r=client.post('/api/auth/register',json={'email':email,'display_name':name,'password':PASSWORD})
    assert r.status_code==201,r.text
    client.headers.update({'X-CSRF-Token':r.json()['csrf_token']})
    return r.json()['user']

def business(name):
    return {'name':name,'industry':'Software services','goal':'Build a customer support and software QA process that reduces response time and improves customer outcomes',
            'size':'small','country':'US','language':'English','budget_usd':1000,'mode':'demo'}

def test_unauthenticated_routes_require_session(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DB_PATH',tmp_path/'unauth.db')
    with TestClient(app) as c:
        for route in ['/api/status','/api/catalog','/api/events','/api/agents','/api/organizations','/api/organizations/random','/api/organizations/random/export']:
            assert c.get(route).status_code==401,route
        assert c.post('/api/organizations',json=business('Fail')).status_code==401

def test_cross_account_isolation_all_resources_and_training(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DB_PATH',tmp_path/'isolation.db')
    with TestClient(app) as a,TestClient(app) as b:
        ua=signup(a,'owner.a@example.com','Alice')
        ub=signup(b,'owner.b@example.com','Bob')
        org_a=a.post('/api/organizations',json=business('Alice only')).json()
        oid=org_a['id'];aid=org_a['plan']['agents'][0]['id']
        run=a.post(f'/api/organizations/{oid}/run',json={'mode':'demo'})
        assert run.status_code==200
        assert len(a.get('/api/events').json())>0
        assert b.get('/api/organizations').json()==[]
        assert b.get('/api/agents').json()==[]
        assert len(a.get('/api/agents').json())==len(org_a['plan']['agents'])
        assert b.get('/api/events').json()==[]
        assert b.get('/api/status').json()['manager_policy_version']==0
        protected=[
            ('get',f'/api/organizations/{oid}',None),
            ('get',f'/api/organizations/{oid}/runs',None),
            ('get',f'/api/organizations/{oid}/export',None),
            ('post',f'/api/organizations/{oid}/run',{'mode':'demo'}),
            ('post',f'/api/organizations/{oid}/reorganize',{'mode':'demo'}),
            ('post',f'/api/organizations/{oid}/feedback',{'score':4,'verified':True,'correct_capabilities':['quality']}),
            ('post',f'/api/organizations/{oid}/agents/{aid}/feedback',{'verified':True,'corrected_strategy':'verify'}),
        ]
        for method,url,payload in protected:
            res=getattr(b,method)(url,json=payload) if payload else getattr(b,method)(url)
            assert res.status_code==404,(method,url,res.text)
        # The owner can still train her policy, while the other account remains untouched.
        res=a.post(f'/api/organizations/{oid}/feedback',json={'score':5,'verified':True,'correct_capabilities':['quality']})
        assert res.status_code==200 and res.json()['policy_version']==1
        assert a.get('/api/status').json()['manager_policy_version']==1
        assert b.get('/api/status').json()['manager_policy_version']==0
        assert store.load_policy(ua['id'],'root_manager').version==1
        assert store.load_policy(ub['id'],'root_manager').version==0
        org_b=b.post('/api/organizations',json=business('Bob only')).json()
        assert org_b['id']!=oid
        assert org_b['plan']['agents'][0]['id']!=aid
        assert all(row['business']['name']=='Bob only' for row in b.get('/api/organizations').json())
        assert all(row['business_name']=='Bob only' for row in b.get('/api/agents').json())
        assert all(row['business']['name']=='Alice only' for row in a.get('/api/organizations').json())
        # Both managers own independent saved policies even though they share the same base design.
        assert b.post(f"/api/organizations/{org_b['id']}/agents/{aid}/feedback",json={'verified':True,'corrected_strategy':'verify'}).status_code==404

def test_csrf_and_session_logout(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DB_PATH',tmp_path/'csrf.db')
    with TestClient(app) as c:
        user=signup(c,'security@example.com','Security Tester')
        assert c.get('/api/auth/me').json()['user']['id']==user['id']
        csrf=c.headers.pop('X-CSRF-Token')
        assert c.post('/api/organizations',json=business('blocked')).status_code==403
        c.headers['X-CSRF-Token']='bad-token'
        assert c.post('/api/organizations',json=business('blocked')).status_code==403
        c.headers['X-CSRF-Token']=csrf
        assert c.post('/api/organizations',json=business('allowed')).status_code==201
        assert c.post('/api/auth/logout').status_code==200
        assert c.get('/api/organizations').status_code==401

def test_password_login_profile_and_session_revocation(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DB_PATH',tmp_path/'password.db')
    with TestClient(app) as c,TestClient(app) as other:
        signup(c,'example@testmail.org','Initial Name')
        assert c.patch('/api/auth/profile',json={'display_name':'New Name'}).json()['display_name']=='New Name'
        assert other.post('/api/auth/login',json={'email':'example@testmail.org','password':'wrong'}).status_code==401
        token=other.post('/api/auth/login',json={'email':'example@testmail.org','password':PASSWORD})
        assert token.status_code==200
        change=c.post('/api/auth/change-password',json={'old_password':PASSWORD,'new_password':'longer-password-after-change'})
        assert change.status_code==200
        assert c.get('/api/auth/me').status_code==401
        assert other.get('/api/auth/me').status_code==401
        assert c.post('/api/auth/login',json={'email':'example@testmail.org','password':PASSWORD}).status_code==401
        assert c.post('/api/auth/login',json={'email':'example@testmail.org','password':'longer-password-after-change'}).status_code==200
        assert c.get('/api/auth/me').json()['user']['display_name']=='New Name'

def test_duplicate_account_password_rules_and_database_fk(tmp_path,monkeypatch):
    import sqlite3
    monkeypatch.setattr(store,'DB_PATH',tmp_path/'integrity.db')
    with TestClient(app) as c:
        u=signup(c,'foo@example.com','Foo')
        assert c.post('/api/auth/register',json={'email':'FOO@example.com','display_name':'Foo2','password':PASSWORD}).status_code==409
        assert c.post('/api/auth/register',json={'email':'tiny@example.com','display_name':'Tiny','password':'short'}).status_code==422
        org=c.post('/api/organizations',json=business('Foo Co')).json()
        with store.db() as conn:
            try:
                conn.execute('INSERT INTO agents(id,user_id,org_id,capability,role,created_at) VALUES(?,?,?,?,?,?)',
                             ('spoofed_agent','not_the_owner',org['id'],'quality','QA',store.stamp()))
                assert False,'Foreign key should reject mismatched owner'
            except sqlite3.IntegrityError:pass

def test_legacy_database_refuses_implicit_account_claim(tmp_path,monkeypatch):
    import sqlite3,pytest
    p=tmp_path/'legacy.db'
    with sqlite3.connect(p) as c:
        c.execute('CREATE TABLE orgs(id TEXT PRIMARY KEY,business TEXT)')
    monkeypatch.setattr(store,'DB_PATH',p)
    with pytest.raises(RuntimeError,match='Legacy SOMAS'):
        store.init_db()
