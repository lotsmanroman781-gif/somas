'use strict';
const $=(id)=>document.getElementById(id);
const state={org:null,catalog:null,status:null,user:null,csrf:null,authMode:"login"};
function h(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function show(el){$(el).classList.remove('hidden');}
function hide(el){$(el).classList.add('hidden');}
function toast(msg,err=false){const node=$('toast');node.textContent=msg;node.className=err?'error':'';node.style.display='block';clearTimeout(window._toasttimer);window._toasttimer=setTimeout(()=>node.style.display='none',4700);}
async function request(path,opts={}){
  const method=(opts.method||'GET').toUpperCase();
  const headers={'Content-Type':'application/json',...(opts.headers||{})};
  if(state.csrf && !['GET','HEAD','OPTIONS'].includes(method)) headers['X-CSRF-Token']=state.csrf;
  const r=await fetch(path,{...opts,credentials:'same-origin',headers});
  let data=await r.json();
  if(!r.ok){
    if(r.status===401 && !path.startsWith('/api/auth/')){showAuth();}
    throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data));
  }
  return data;
}
function busy(button,on,label){button.disabled=on;if(on){button.dataset.old=button.textContent;button.textContent=label||'Working…';}else if(button.dataset.old){button.textContent=button.dataset.old;delete button.dataset.old;}}
const examples={
 retail:{name:'Northstar Commerce',industry:'E-commerce retail',goal:'Reduce late deliveries and customer complaints while improving order fulfillment.',size:'small',country:'United States',budget_usd:1000},
 software:{name:'Orbit Cloud',industry:'Software SaaS',goal:'Launch an AI-powered customer support product, validate demand, build the backend and recruit initial customers.',size:'medium',country:'Canada',budget_usd:12000},
 factory:{name:'Aster Manufacturing',industry:'Manufacturing',goal:'Reduce defects, optimize material inventory and improve factory production scheduling across three plants.',size:'enterprise',country:'Germany',budget_usd:50000},
 agency:{name:'Signal Creative',industry:'Marketing agency',goal:'Increase client lead conversions, improve campaign reporting and streamline delivery for new accounts.',size:'micro',country:'Singapore',budget_usd:500}
};
function fillExample(name){let f=$('business-form');for(let [k,v] of Object.entries(examples[name])){if(f.elements[k])f.elements[k].value=v;}toast('Scenario loaded: '+examples[name].name);}
async function loadStatus(){state.status=await request('/api/status');$('side-policy').textContent='v'+state.status.manager_policy_version;$('side-params').textContent=state.status.manager_weights.toLocaleString()+' trainable parameters';$('mode-label').textContent=state.status.has_openai_key?'LLM connected · Demo available':'Local demo · No LLM key';$('connection-dot').style.background=state.status.has_openai_key?'#50d9af':'#e6bb68';$('ai-design').disabled=!state.status.has_openai_key;$('run-ai').disabled=!state.status.has_openai_key;}
async function loadEvents(){let items=await request('/api/events');$('events-list').innerHTML=items.length?items.slice(0,8).map(e=>`<div class="event"><b>${h(e.kind.replaceAll('_',' '))}</b><span>${h(e.ref_id)}</span><time> · ${h(e.at.slice(0,16).replace('T',' '))} UTC</time></div>`).join(''):'<p class="muted">No events yet.</p>';}
async function create(event){event.preventDefault();const b=$('create-btn'),f=$('business-form'),fd=new FormData(f),obj=Object.fromEntries(fd.entries());obj.budget_usd=Number(obj.budget_usd);obj.mode=$('ai-design').checked?'ai':'demo';busy(b,true,'Designing team…');try{let org=await request('/api/organizations',{method:'POST',body:JSON.stringify(obj)});renderOrg(org);await Promise.all([loadStatus(),loadEvents()]);toast('Organization created with '+org.plan.agents.length+' independent specialist agents.');$('results').scrollIntoView({behavior:'smooth',block:'start'});}catch(e){toast(e.message,true);}finally{busy(b,false);}}
function setTab(tab){
  const hist=tab==='history',agents=tab==='agents';
  $('nav-history').classList.toggle('active',hist);
  $('nav-agents').classList.toggle('active',agents);
  $('nav-studio').classList.toggle('active',!hist&&!agents);
  if(hist){show('history');hide('my-agents');loadHistory();$('history').scrollIntoView({behavior:'smooth'});}
  else if(agents){show('my-agents');hide('history');loadAgents();$('my-agents').scrollIntoView({behavior:'smooth'});}
  else{hide('history');hide('my-agents');$('composer').scrollIntoView({behavior:'smooth'});}
}
async function loadAgents(){
 const agents=await request('/api/agents');
 $('my-agents-list').innerHTML=agents.length?agents.map(a=>`<div class="agent"><div class="agent-top"><h4>${h(a.role)}</h4><small>POLICY v${h(a.policy_version)}</small></div><small>${h(a.capability.replaceAll('_',' ').toUpperCase())}</small><p>Organization: ${h(a.business_name)}</p><button data-open-org="${h(a.org_id)}">Open organization ↗</button></div>`).join(''):'<p class="muted">No agents yet. Create your first organization above.</p>';
 $('my-agents-list').querySelectorAll('[data-open-org]').forEach(btn=>btn.addEventListener('click',async()=>{
  try{renderOrg(await request('/api/organizations/'+btn.dataset.openOrg));setTab('studio');$('results').scrollIntoView({behavior:'smooth'});}catch(e){toast(e.message,true);}
 }));
}
function graph(org){let agents=org.plan.agents,n=agents.length,w=620,boxw=Math.min(126,Math.floor((w-60)/Math.min(n,4))-12),rows=Math.ceil(n/4),height=125+rows*104;let coords={root_manager:{x:w/2,y:37}};let nodes=[];agents.forEach((a,i)=>{let row=Math.floor(i/4),cols=Math.min(4,n-row*4),col=i%4,x=(w/(cols+1))*(col+1),y=117+row*104;coords[a.id]={x,y};nodes.push({a,x,y});});let paths=org.plan.relationships.filter(x=>x.type==='reports_to').map(edge=>{let src=coords[edge.source],dst=coords[edge.target];return src&&dst?`<path d="M${src.x} ${src.y+25} V${dst.y-38} H${dst.x} V${dst.y-20}" fill="none" stroke="#52776c" stroke-width="1.4" opacity=".7"/>`:'';}).join('');let boxes=nodes.map(({a,x,y})=>`<rect x="${x-boxw/2}" y="${y-20}" width="${boxw}" height="46" rx="9" fill="#1d3440" stroke="#456e69"/><text x="${x}" y="${y-1}" fill="#e0f1ec" font-size="10" text-anchor="middle">${h(a.role.length>21?a.role.slice(0,20)+'…':a.role)}</text><text x="${x}" y="${y+15}" fill="#65c8a8" font-size="9" text-anchor="middle">policy v${h(a.policy_version)}</text>`).join('');return `<svg role="img" aria-label="Organization graph of root manager and ${n} specialists" viewBox="0 0 ${w} ${height}" xmlns="http://www.w3.org/2000/svg"><rect x="230" y="10" width="160" height="50" rx="10" fill="#1e4639" stroke="#50d9af"/><text x="310" y="30" fill="#def9eb" font-size="14" text-anchor="middle" font-weight="600">Root Manager</text><text x="310" y="47" fill="#80e5bf" font-size="10" text-anchor="middle">Independent neural filter</text>${paths}${boxes}</svg>`;}
function renderOrg(org){state.org=org;let p=org.plan;$('result-name').textContent=org.business.name+' / AI workforce';$('result-desc').textContent=p.rationale;$('topology-badge').textContent=p.topology.replaceAll('_',' ').toUpperCase();$('agent-count').textContent=p.agents.length;$('policy-version').textContent='v'+p.manager_filter.policy_version;$('planning-mode').textContent=p.planning_mode.toUpperCase();$('approval-mode').textContent=p.approvals_required?'Required':'No flags';$('org-graph').innerHTML=graph(org);let ordered=Object.entries(p.manager_filter.ranking).sort((a,b)=>b[1]-a[1]);$('signals').innerHTML=ordered.map(([key,val])=>`<div class="signal"><span>${h(state.catalog.capabilities[key].label)}</span><div class="bar"><i style="width:${Math.round(val*100)}%"></i></div><b>${Math.round(val*100)}%</b></div>`).join('');$('agent-cards').innerHTML=p.agents.map(a=>`<div class="agent"><div class="agent-top"><h4>${h(a.role)}</h4><small>POLICY v${h(a.policy_version)}</small></div><small>${h(a.capability.replaceAll('_',' ').toUpperCase())}</small><p>${h(a.task)}</p><p>Reports to: ${h(a.reports_to==='root_manager'?'Manager':p.agents.find(e=>e.id===a.reports_to)?.role||'Manager')}</p><button data-teach="${h(a.id)}">Train specialist strategy ↗</button></div>`).join('');$('agent-cards').querySelectorAll('[data-teach]').forEach(b=>b.addEventListener('click',()=>teachAgent(b.dataset.teach)));$('feedback-caps').innerHTML=Object.entries(state.catalog.capabilities).map(([k,v])=>`<label><input type="checkbox" name="corrected_cap" value="${h(k)}" ${p.agents.some(a=>a.capability===k)?'checked':''}/><span>${h(v.label)}</span></label>`).join('');show('results');show('feedback');hide('execution');hide('training-result');}
async function run(mode){if(!state.org)return;let btn=$(mode==='demo'?'run-demo':'run-ai');busy(btn,true,'Generating drafts…');try{let r=await request('/api/organizations/'+state.org.id+'/run',{method:'POST',body:JSON.stringify({mode})});$('execution-steps').innerHTML=r.outputs.steps.map((s,i)=>`<div class="deliverable"><small>STEP ${i+1} · ${h(s.capability.toUpperCase())} · ${h(s.strategy.action.toUpperCase())} · POLICY v${h(s.strategy.policy_version)}</small><h4>${h(s.role)}</h4><p>${h(s.deliverable)}</p></div>`).join('');show('execution');$('execution').scrollIntoView({behavior:'smooth'});await loadEvents();toast(`${r.outputs.steps.length} planning drafts generated. No external actions performed.`);}catch(e){toast(e.message,true);}finally{busy(btn,false);}}
async function feedback(event){event.preventDefault();if(!state.org)return;let b=$('feedback-form').querySelector('[type=submit]');busy(b,true,'Updating neural weights…');try{let f=$('feedback-form'),data={score:Number(f.elements.score.value),correct_capabilities:[...document.querySelectorAll('[name=corrected_cap]:checked')].map(x=>x.value),verified:$('verify-checkbox').checked,notes:f.elements.notes.value};let r=await request('/api/organizations/'+state.org.id+'/feedback',{method:'POST',body:JSON.stringify(data)});$('training-result').textContent=r.trained?`Neural policy updated to v${r.policy_version}. Training loss: ${r.training_result.loss_before} → ${r.training_result.loss_after}. Create or reorganize a team to apply the new weights. Single-example training may overfit.`:'Feedback recorded, no weights changed. Verify the correction and select capabilities to train.';show('training-result');await Promise.all([loadStatus(),loadEvents()]);toast(r.trained?'Training completed; neural weights persisted.':'Unverified feedback saved; no training.');}catch(e){toast(e.message,true);}finally{busy(b,false);}}
async function teachAgent(id){if(!state.org)return;let suggestion=window.prompt('Choose the verified preferred strategy: research, analyze, draft, verify, escalate, summarize');if(!suggestion)return;suggestion=suggestion.trim().toLowerCase();if(!state.catalog.strategies.includes(suggestion)){toast('Unknown strategy',true);return;}if(!window.confirm('Confirm this strategy is verified and train this specialist\'s independent neural weights?'))return;try{let res=await request(`/api/organizations/${state.org.id}/agents/${id}/feedback`,{method:'POST',body:JSON.stringify({corrected_strategy:suggestion,verified:true})});toast(`Specialist policy updated to v${res.policy_version}; ${res.before.action} → ${res.after.action}.`);await loadEvents();}catch(e){toast(e.message,true);}}
async function reorganize(){if(!state.org)return;let btn=$('reorg-btn');busy(btn,true,'Reorganizing…');try{let p=await request(`/api/organizations/${state.org.id}/reorganize`,{method:'POST',body:JSON.stringify({mode:$('ai-design').checked?'ai':'demo'})});renderOrg(p);await loadEvents();toast('New version created. Matching specialist weights were inherited.');$('results').scrollIntoView({behavior:'smooth'});}catch(e){toast(e.message,true);}finally{busy(btn,false);}}
async function exportOrg(){if(!state.org)return;let obj=await request(`/api/organizations/${state.org.id}/export`);let blob=new Blob([JSON.stringify(obj,null,2)],{type:'application/json'}),u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=state.org.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),2000);}
async function loadHistory(){let orgs=await request('/api/organizations');$('history-list').innerHTML=orgs.length?orgs.map(o=>`<div class="history-item"><div><button data-org="${h(o.id)}"><b>${h(o.business.name)}</b></button><p>${h(o.business.industry)} · ${o.agent_count} agents · ${h(o.created_at.slice(0,10))}</p></div><span class="pill">${h(o.status)}</span></div>`).join(''):'<p class="muted">Create your first organization above.</p>';$('history-list').querySelectorAll('[data-org]').forEach(b=>b.addEventListener('click',async()=>{try{renderOrg(await request('/api/organizations/'+b.dataset.org));setTab('studio');$('results').scrollIntoView({behavior:'smooth'});}catch(e){toast(e.message,true);}}));}
async function initWorkspace(){if(!state.listenersBound){state.listenersBound=true;document.querySelectorAll('[data-example]').forEach(b=>b.addEventListener('click',()=>fillExample(b.dataset.example)));$('business-form').addEventListener('submit',create);$('feedback-form').addEventListener('submit',feedback);$('nav-history').addEventListener('click',()=>setTab('history'));$('nav-studio').addEventListener('click',()=>setTab('studio'));$('nav-agents').addEventListener('click',()=>setTab('agents'));$('agents-refresh').addEventListener('click',loadAgents);$('run-demo').addEventListener('click',()=>run('demo'));$('run-ai').addEventListener('click',()=>run('ai'));$('reorg-btn').addEventListener('click',reorganize);$('export-btn').addEventListener('click',exportOrg);$('refresh-btn').addEventListener('click',loadEvents);$('history-refresh').addEventListener('click',loadHistory);}try{state.catalog=await request('/api/catalog');await Promise.all([loadStatus(),loadEvents()]);}catch(e){toast('Server not ready: '+e.message,true);}}
boot();

function showAuth(){
  state.csrf=null;state.user=null;state.org=null;state.catalog=null;hide('results');hide('execution');hide('feedback');hide('history');hide('my-agents');hide('account-settings');$('events-list').innerHTML='';$('history-list').innerHTML='';
  hide('app-shell');show('auth-gate');hide('auth-error');authTab('login');
}
function showWorkspace(user,csrf){
  state.user=user;state.csrf=csrf;
  $('account-name').textContent=user.display_name;
  $('account-email').textContent=user.email;
  $('profile-name').value=user.display_name;
  hide('auth-gate');show('app-shell');
}
function authTab(mode){
  state.authMode=mode;
  const registering=mode==='register';
  $('auth-login-tab').classList.toggle('selected',!registering);
  $('auth-register-tab').classList.toggle('selected',registering);
  $('auth-name-line').classList.toggle('hidden',!registering);
  $('auth-password-hint').classList.toggle('hidden',!registering);
  $('auth-name').required=registering;
  $('auth-password').minLength=registering?12:1;
  $('auth-password').autocomplete=registering?'new-password':'current-password';
  $('auth-submit').textContent=registering?'Create my workspace':'Sign in';
  hide('auth-error');
}
async function authSubmit(e){
  e.preventDefault();
  const b=$('auth-submit');busy(b,true,'Signing in…');
  const body={email:$('auth-email').value,password:$('auth-password').value};
  if(state.authMode==='register')body.display_name=$('auth-name').value;
  try{
    const result=await request('/api/auth/'+(state.authMode==='register'?'register':'login'),{method:'POST',body:JSON.stringify(body)});
    showWorkspace(result.user,result.csrf_token);
    await initWorkspace();
    $('auth-password').value='';
    toast('Signed in. This private workspace belongs to '+result.user.display_name+'.');
  }catch(err){$('auth-error').textContent=err.message;show('auth-error');}
  finally{busy(b,false);}
}
async function signOut(){
  try{await request('/api/auth/logout',{method:'POST'});}catch(e){console.warn('Sign out request:',e.message);}
  showAuth();toast('Signed out.');
}
async function updateProfile(e){
  e.preventDefault();
  try{const user=await request('/api/auth/profile',{method:'PATCH',body:JSON.stringify({display_name:$('profile-name').value})});
    state.user=user;$('account-name').textContent=user.display_name;toast('Profile updated.');}
  catch(err){toast(err.message,true);}
}
async function changePassword(e){
  e.preventDefault();
  let values=Object.fromEntries(new FormData(e.target));
  try{await request('/api/auth/change-password',{method:'POST',body:JSON.stringify(values)});e.target.reset();showAuth();toast('Password changed. Please sign in again.');}
  catch(err){toast(err.message,true);}
}
async function boot(){
  $('auth-login-tab').addEventListener('click',()=>authTab('login'));
  $('auth-register-tab').addEventListener('click',()=>authTab('register'));
  $('auth-form').addEventListener('submit',authSubmit);
  $('logout-btn').addEventListener('click',signOut);
  $('settings-btn').addEventListener('click',()=>{show('account-settings');$('account-settings').scrollIntoView({behavior:'smooth'});});
  $('close-settings').addEventListener('click',()=>hide('account-settings'));
  $('profile-form').addEventListener('submit',updateProfile);
  $('password-form').addEventListener('submit',changePassword);
  try{const session=await request('/api/auth/me');showWorkspace(session.user,session.csrf_token);await initWorkspace();}
  catch(e){showAuth();}
}
