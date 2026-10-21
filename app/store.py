"""SQLite persistence with mandatory user-level ownership checks for every workspace object."""
from __future__ import annotations
import json, os, sqlite3, threading
from datetime import datetime, timezone
from pathlib import Path
from .neural import TinyPolicy, manager_policy, worker_policy
from .catalog import CAP_KEYS, STRATEGIES

DB_PATH=Path(os.getenv('SOMAS_DB',str(Path(__file__).resolve().parents[1]/'data'/'somas_users.db')))
LOCK=threading.RLock()

def db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(str(DB_PATH),check_same_thread=False,timeout=20)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=20000')
    return conn

def init_db():
    with LOCK,db() as c:
        # Refuse to mistakenly expose or mutate the old single-user schema.
        if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orgs'").fetchone():
            columns={r['name'] for r in c.execute('PRAGMA table_info(orgs)')}
            if 'user_id' not in columns:
                raise RuntimeError('Legacy SOMAS 1.0 database detected. Use a NEW SOMAS_DB path; old data is intentionally not assigned to any new account.')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
            password_salt BLOB NOT NULL,password_hash BLOB NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions(
            token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,csrf TEXT NOT NULL,
            created_at TEXT NOT NULL,expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        CREATE TABLE IF NOT EXISTS policies(
            user_id TEXT NOT NULL,id TEXT NOT NULL,version INTEGER NOT NULL,blob BLOB NOT NULL,
            PRIMARY KEY(user_id,id),FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS orgs(
            id TEXT PRIMARY KEY,user_id TEXT NOT NULL,created_at TEXT NOT NULL,
            business TEXT NOT NULL,plan TEXT NOT NULL,status TEXT NOT NULL,
            UNIQUE(user_id,id),FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_org_owner ON orgs(user_id,created_at);
        CREATE TABLE IF NOT EXISTS agents(
            id TEXT PRIMARY KEY,user_id TEXT NOT NULL,org_id TEXT NOT NULL,capability TEXT NOT NULL,
            role TEXT NOT NULL,created_at TEXT NOT NULL,
            FOREIGN KEY(user_id,org_id) REFERENCES orgs(user_id,id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_agents_owner_org ON agents(user_id,org_id);
        CREATE TABLE IF NOT EXISTS runs(
            id TEXT PRIMARY KEY,user_id TEXT NOT NULL,org_id TEXT NOT NULL,created_at TEXT NOT NULL,
            mode TEXT NOT NULL,status TEXT NOT NULL,outputs TEXT NOT NULL,
            FOREIGN KEY(user_id,org_id) REFERENCES orgs(user_id,id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS feedback(
            id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,org_id TEXT NOT NULL,
            created_at TEXT NOT NULL,score INTEGER,capabilities TEXT,notes TEXT NOT NULL,
            verified INTEGER NOT NULL,policy_version INTEGER NOT NULL,
            FOREIGN KEY(user_id,org_id) REFERENCES orgs(user_id,id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,at TEXT NOT NULL,
            kind TEXT NOT NULL,ref_id TEXT NOT NULL,payload TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_events_owner ON events(user_id,id);
        ''')

def stamp():return datetime.now(timezone.utc).isoformat(timespec='seconds')

def add_event(user_id,kind,ref_id,payload):
    with LOCK,db() as c:
        c.execute('INSERT INTO events(user_id,at,kind,ref_id,payload) VALUES(?,?,?,?,?)',
                  (user_id,stamp(),kind,ref_id,json.dumps(payload)))

def events(user_id,limit=30):
    with db() as c:
        rows=c.execute('SELECT id,at,kind,ref_id,payload FROM events WHERE user_id=? ORDER BY id DESC LIMIT ?', (user_id,limit)).fetchall()
    return [{**dict(row),'payload':json.loads(row['payload'])} for row in rows]

def load_policy(user_id,key,kind='manager'):
    with LOCK,db() as c:
        row=c.execute('SELECT blob FROM policies WHERE user_id=? AND id=?',(user_id,key)).fetchone()
    if not row:
        seed=42+sum((user_id+key).encode())%10000
        return manager_policy() if kind=='manager' else worker_policy(seed=seed)
    return TinyPolicy.deserialize(row['blob'],CAP_KEYS if kind=='manager' else STRATEGIES)

def save_policy(user_id,key,model):
    with LOCK,db() as c:
        c.execute('INSERT INTO policies(user_id,id,version,blob) VALUES(?,?,?,?) ON CONFLICT(user_id,id) DO UPDATE SET version=excluded.version,blob=excluded.blob',
                  (user_id,key,model.version,model.serialize()))

def add_org(user_id,org_id,business,plan,agent_rows):
    with LOCK,db() as c:
        c.execute('INSERT INTO orgs(id,user_id,created_at,business,plan,status) VALUES(?,?,?,?,?,?)',
                  (org_id,user_id,stamp(),json.dumps(business),json.dumps(plan),'planned'))
        for a in agent_rows:
            c.execute('INSERT INTO agents(id,user_id,org_id,capability,role,created_at) VALUES(?,?,?,?,?,?)',
                      (a['id'],user_id,org_id,a['capability'],a['role'],stamp()))
    add_event(user_id,'organization_created',org_id,{'agents':len(agent_rows),'mode':plan['planning_mode']})

def list_orgs(user_id):
    with db() as c:
        rows=c.execute('SELECT id,created_at,business,plan,status FROM orgs WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT 100',(user_id,)).fetchall()
    return [{'id':r['id'],'created_at':r['created_at'],'business':json.loads(r['business']),
             'status':r['status'],'agent_count':len(json.loads(r['plan']).get('agents',[]))} for r in rows]

def list_agents(user_id):
    """All of the signed-in user's specialist agents, never anyone else's."""
    with db() as c:
        rows=c.execute('''SELECT a.id,a.org_id,a.capability,a.role,a.created_at,
                                 o.business,p.version AS policy_version
                          FROM agents a
                          JOIN orgs o ON o.id=a.org_id AND o.user_id=a.user_id
                          LEFT JOIN policies p ON p.user_id=a.user_id AND p.id=a.id
                          WHERE a.user_id=?
                          ORDER BY a.created_at DESC,a.id DESC LIMIT 300''',(user_id,)).fetchall()
    return [{'id':r['id'],'org_id':r['org_id'],'capability':r['capability'],
             'role':r['role'],'created_at':r['created_at'],
             'business_name':json.loads(r['business'])['name'],
             'policy_version':r['policy_version'] or 0} for r in rows]

def get_org(user_id,org_id):
    with db() as c:
        row=c.execute('SELECT id,created_at,business,plan,status FROM orgs WHERE user_id=? AND id=?',(user_id,org_id)).fetchone()
    if not row:return None
    return {'id':row['id'],'created_at':row['created_at'],'business':json.loads(row['business']),
            'plan':json.loads(row['plan']),'status':row['status']}

def record_run(user_id,run_id,org_id,mode,status,outputs):
    with LOCK,db() as c:
        # Composite FK below also enforces ownership, and status UPDATE is scoped.
        c.execute('INSERT INTO runs(id,user_id,org_id,created_at,mode,status,outputs) VALUES(?,?,?,?,?,?,?)',
                  (run_id,user_id,org_id,stamp(),mode,status,json.dumps(outputs)))
        if status=='completed':
            c.execute('UPDATE orgs SET status=? WHERE user_id=? AND id=?',
                      ('executed_demo' if mode=='demo' else 'executed_ai',user_id,org_id))
    add_event(user_id,'run_recorded',org_id,{'run_id':run_id,'status':status,'mode':mode})

def list_runs(user_id,org_id):
    with db() as c:
        rows=c.execute('SELECT id,org_id,created_at,mode,status,outputs FROM runs WHERE user_id=? AND org_id=? ORDER BY created_at DESC',
                       (user_id,org_id)).fetchall()
    return [{**dict(r),'outputs':json.loads(r['outputs'])} for r in rows]

def add_feedback(user_id,org_id,score,caps,notes,verified,policy_version):
    with LOCK,db() as c:
        c.execute('INSERT INTO feedback(user_id,org_id,created_at,score,capabilities,notes,verified,policy_version) VALUES(?,?,?,?,?,?,?,?)',
                  (user_id,org_id,stamp(),score,json.dumps(caps),notes,int(verified),policy_version))
    add_event(user_id,'verified_feedback' if verified else 'unverified_feedback',org_id,
              {'score':score,'corrected_capabilities':caps})
