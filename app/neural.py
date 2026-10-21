"""Actual agent-owned small neural networks, with NumPy backprop and SQLite persistence.

No foundation-model weights are modified. The 128-d hashed encoder is deterministic,
frozen, and shared; each agent owns a separately serialized policy.
"""
from __future__ import annotations
import hashlib, io, json, re
import numpy as np
from .catalog import CAP_KEYS, STRATEGIES, SIZES

INPUT_DIM=128+12
HIDDEN=48


def embed(text: str):
    x=np.zeros(128, dtype=np.float64)
    words=re.findall(r"[\w'-]+", text.lower(), flags=re.UNICODE)
    for token in words[:700]:
        b=hashlib.blake2b(token.encode("utf8"), digest_size=8).digest()
        n=int.from_bytes(b[:4], "little")%128
        sign=1 if b[4]%2 else -1
        x[n]+=sign
    n=np.linalg.norm(x)
    return x/n if n else x


def state_features(goal: str, industry: str, size: str, budget: float, country: str, existing: int=0):
    vec=embed(" ".join([goal,industry,country]))
    extras=np.zeros(12, dtype=np.float64)
    if size in SIZES:extras[SIZES.index(size)]=1
    extras[4]=np.log1p(min(max(0, budget),1e8))/np.log1p(1e8)
    extras[5]=min(1.0,len(goal)/700)
    extras[6]=min(1.0,existing/30)
    extras[7]=1.0 if any(c in goal.lower() for c in ("global", "worldwide", "international")) else 0
    extras[8]=1.0 if any(w in goal.lower() for w in ("new", "launch", "start")) else 0
    extras[9]=1.0 if any(w in goal.lower() for w in ("improve", "reduce", "fix", "optimize")) else 0
    extras[10]=1.0 if budget<500 else 0
    extras[11]=1.0
    return np.concatenate([vec, extras])

class TinyPolicy:
    """Single-hidden-layer multi-label network with SGD BCE training."""
    def __init__(self, outputs: list[str], seed: int=31):
        self.outputs=list(outputs)
        rng=np.random.default_rng(seed)
        self.w1=rng.normal(0,.075,(INPUT_DIM,HIDDEN))
        self.b1=np.zeros(HIDDEN)
        self.w2=rng.normal(0,.06,(HIDDEN,len(outputs)))
        self.b2=np.zeros(len(outputs))
        self.version=0

    @property
    def parameter_count(self):
        return sum(a.size for a in (self.w1,self.b1,self.w2,self.b2))

    def forward(self,x):
        x=np.asarray(x,dtype=np.float64).reshape(-1,INPUT_DIM)
        h=np.tanh(x@self.w1+self.b1)
        logits=h@self.w2+self.b2
        probs=1/(1+np.exp(-np.clip(logits,-30,30)))
        return probs,h,x

    def predict(self,x):
        return {k:float(v) for k,v in zip(self.outputs, self.forward(x)[0][0])}

    def fit(self,X,Y,epochs=75,lr=.065):
        X=np.asarray(X,dtype=np.float64).reshape(-1,INPUT_DIM)
        Y=np.asarray(Y,dtype=np.float64).reshape(-1,len(self.outputs))
        losses=[]
        for epoch in range(epochs):
            probs,h,x=self.forward(X)
            loss=-np.mean(Y*np.log(probs+1e-9)+(1-Y)*np.log(1-probs+1e-9))
            losses.append(float(loss))
            dz=(probs-Y)/(len(X)*len(self.outputs))
            dw2=h.T@dz
            db2=dz.sum(axis=0)
            dh=(dz@self.w2.T)*(1-h*h)
            dw1=x.T@dh
            db1=dh.sum(axis=0)
            # L2 penalty prevents divergent parameter changes on tiny feedback sets.
            self.w1-=lr*(dw1+.0001*self.w1)
            self.b1-=lr*db1
            self.w2-=lr*(dw2+.0001*self.w2)
            self.b2-=lr*db2
        self.version+=1
        return {"loss_before":round(losses[0],5),"loss_after":round(losses[-1],5),"version":self.version}

    def serialize(self):
        stream=io.BytesIO()
        np.savez_compressed(stream,w1=self.w1,b1=self.b1,w2=self.w2,b2=self.b2,version=np.array([self.version]))
        return stream.getvalue()

    @classmethod
    def deserialize(cls,blob,outputs):
        obj=cls(outputs)
        with np.load(io.BytesIO(blob),allow_pickle=False) as z:
            for key in ('w1','b1','w2','b2'):setattr(obj,key,z[key].copy())
            obj.version=int(z['version'][0])
        if obj.w2.shape[1]!=len(outputs):raise ValueError('Policy dimensions do not match action vocabulary')
        return obj


def manager_policy():return TinyPolicy(CAP_KEYS, seed=103)

def worker_policy(seed=42):return TinyPolicy(STRATEGIES, seed=seed)
