import pytest
from fastapi.testclient import TestClient
from app import store
from app.main import app

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DB_PATH',tmp_path/'test.db')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with TestClient(app) as c:
        res=c.post('/api/auth/register',json={'email':'tester@example.com','display_name':'Test User','password':'correct-horse-battery-01'})
        assert res.status_code==201,res.text
        c.headers.update({'X-CSRF-Token':res.json()['csrf_token']})
        c.test_user_id=res.json()['user']['id']
        yield c

@pytest.fixture
def retail():
    return {'name':'Test Retail','industry':'E-commerce retail','goal':'Reduce late shipping deliveries and customer complaints with improved inventory operations','size':'small','country':'United States','language':'English','budget_usd':1000,'mode':'demo'}
