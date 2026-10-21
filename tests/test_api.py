import numpy as np
from app.neural import TinyPolicy,manager_policy,state_features
from app import store


def test_neural_policy_is_genuinely_trainable_and_serializable():
    p=TinyPolicy(['option_a','option_b'])
    x=state_features('Fix customer complaints','retail','small',100,'US')
    before=p.predict(x);w=p.w1.copy();stats=p.fit([x],[[1,0]],epochs=100,lr=.9)
    after=p.predict(x)
    assert not np.array_equal(w,p.w1)
    assert after['option_a']>before['option_a']
    assert after['option_b']<before['option_b']
    assert stats['loss_after']<stats['loss_before']
    restored=TinyPolicy.deserialize(p.serialize(),['option_a','option_b'])
    assert restored.version==1
    assert restored.predict(x)==after
    assert p.parameter_count<20000


def test_business_organization_creation(client,retail):
    resp=client.post('/api/organizations',json=retail)
    assert resp.status_code==201,resp.text
    obj=resp.json();plan=obj['plan']
    assert obj['business']['name']==retail['name']
    assert 2<=len(plan['agents'])<=4
    assert all(a['reports_to']=='root_manager' for a in plan['agents'])
    assert all(a['id']!=b['id'] for i,a in enumerate(plan['agents']) for b in plan['agents'][i+1:])
    assert plan['external_actions_enabled'] is False
    assert plan['planning_mode']=='demo'
    assert plan['manager_filter']['neural_parameters']<20000
    for a in plan['agents']:
        pol=store.load_policy(client.test_user_id,a['id'],'worker')
        assert pol.version==0
    assert client.get('/api/organizations/'+obj['id']).json()['id']==obj['id']
    assert client.get('/api/organizations').json()[0]['agent_count']==len(plan['agents'])


def test_organization_differs_by_business(client,retail):
    retail_org=client.post('/api/organizations',json=retail).json()
    soft={**retail,'name':'Tech Group','industry':'Software SaaS','goal':'Design and launch an API backend and cloud application with reliable automated tests.'}
    software_org=client.post('/api/organizations',json=soft).json()
    caps1={a['capability'] for a in retail_org['plan']['agents']}
    caps2={a['capability'] for a in software_org['plan']['agents']}
    assert caps1!=caps2
    assert 'engineering' in caps2


def test_demo_runs_are_clearly_not_real_work(client,retail):
    org=client.post('/api/organizations',json=retail).json()
    res=client.post(f"/api/organizations/{org['id']}/run",json={'mode':'demo'})
    assert res.status_code==200,res.text
    outputs=res.json()['outputs']
    assert len(outputs['steps'])==len(org['plan']['agents'])
    assert all('SIMULATED PLAN' in s['deliverable'] and s['strategy']['parameter_count']<20000 for s in outputs['steps'])
    assert 'No external business action' in outputs['summary']
    assert client.get(f"/api/organizations/{org['id']}/runs").json()[0]['mode']=='demo'


def test_verified_manager_feedback_updates_persisted_weights(client,retail):
    org=client.post('/api/organizations',json=retail).json();oid=org['id']
    orig=store.load_policy(client.test_user_id,'root_manager');w=orig.w2.copy()
    unr=client.post(f'/api/organizations/{oid}/feedback',json={'score':4,'correct_capabilities':['quality'],'verified':False}).json()
    assert unr['trained'] is False
    assert np.array_equal(store.load_policy(client.test_user_id,'root_manager').w2,w)
    res=client.post(f'/api/organizations/{oid}/feedback',json={'score':5,'correct_capabilities':['quality','operations'],'verified':True})
    assert res.status_code==200,res.text
    data=res.json()
    assert data['trained'] and data['policy_version']==1
    assert data['after']['quality']>data['before']['quality']
    assert data['training_result']['loss_after']<data['training_result']['loss_before']
    assert not np.array_equal(store.load_policy(client.test_user_id,'root_manager').w2,w)
    assert client.get('/api/status').json()['manager_policy_version']==1


def test_specialist_feedback_and_reorg_inherits_weights(client,retail):
    o=client.post('/api/organizations',json=retail).json();id=o['id'];agent=o['plan']['agents'][0]
    before=store.load_policy(client.test_user_id,agent['id'],'worker')
    a=client.post(f"/api/organizations/{id}/agents/{agent['id']}/feedback",json={'corrected_strategy':'verify','verified':True})
    assert a.status_code==200,a.text
    assert a.json()['policy_version']==1
    old_w=store.load_policy(client.test_user_id,agent['id'],'worker').w2.copy()
    new=client.post(f'/api/organizations/{id}/reorganize',json={'mode':'demo'}).json()
    assert new['plan']['parent_organization_id']==id
    matching=next(x for x in new['plan']['agents'] if x['capability']==agent['capability'])
    assert matching['inherited_from']==agent['id']
    new_policy=store.load_policy(client.test_user_id,matching['id'],'worker')
    assert new_policy.version==1 and np.array_equal(new_policy.w2,old_w)


def test_safety_flags_are_not_decided_by_neural_policy(client,retail):
    retail['goal']='Send email to customers and transfer money to suppliers to settle legal contracts across borders.'
    org=client.post('/api/organizations',json=retail).json()
    assert org['plan']['approvals_required']
    assert 'compliance' in [a['capability'] for a in org['plan']['agents']]
    assert org['plan']['external_actions_enabled'] is False


def test_no_key_ai_mode_and_validation(client,retail):
    ret=client.post('/api/organizations',json={**retail,'mode':'ai'})
    assert ret.status_code==400
    ret=client.post('/api/organizations',json={**retail,'goal':'too short'})
    assert ret.status_code==422
    ret=client.post('/api/organizations',json=retail)
    oid=ret.json()['id']
    assert client.post(f'/api/organizations/{oid}/run',json={'mode':'ai'}).status_code==400
    assert client.post(f'/api/organizations/{oid}/feedback',json={'score':3,'correct_capabilities':['invalid'],'verified':True}).status_code==422
    assert client.get('/api/organizations/not-found').status_code==404


def test_export_and_events(client,retail):
    org=client.post('/api/organizations',json=retail).json()
    out=client.get('/api/organizations/'+org['id']+'/export')
    assert out.status_code==200 and out.json()['organization']['id']==org['id']
    assert client.get('/api/events').json()[0]['kind']=='organization_created'


def test_optional_llm_planning_and_specialist_drafts_with_stubbed_provider(client,retail,monkeypatch):
    """Network-free contract test. It does not claim live OpenAI verification."""
    from app import engine
    monkeypatch.setenv('OPENAI_API_KEY','test-key-not-sent')
    calls=[]
    def fake_call(prompt,instructions,max_output_tokens=500):
        calls.append(instructions)
        if 'Manager of an experimental' in instructions:
            return '{"capabilities":["operations","supply_chain","customer_support"],"topology":"flat","rationale":"Investigate operational bottlenecks","tasks":{"operations":"Analyze delivery process","supply_chain":"Analyze supplier delays","customer_support":"Plan complaint triage"}}'
        return 'DRAFT ONLY. First confirm order timestamps and evidence; this is not a completed operation.'
    monkeypatch.setattr(engine,'_openai_text',fake_call)
    ret=client.post('/api/organizations',json={**retail,'mode':'ai'})
    assert ret.status_code==201,ret.text
    org=ret.json()
    assert org['plan']['planning_mode']=='ai'
    assert {a['capability'] for a in org['plan']['agents']}=={'operations','supply_chain','customer_support'}
    rid=client.post('/api/organizations/'+org['id']+'/run',json={'mode':'ai'})
    assert rid.status_code==200,rid.text
    assert all('DRAFT ONLY' in s['deliverable'] for s in rid.json()['outputs']['steps'])
    assert len(calls)==4


def test_no_unnecessary_approval_for_innocent_delivery_problem(client,retail):
    obj=client.post('/api/organizations',json=retail).json()
    assert obj['plan']['approvals_required'] is False
