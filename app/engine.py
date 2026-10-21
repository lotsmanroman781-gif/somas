"""Self-organizing manager: filter BEFORE LLM, validated plan AFTER LLM."""

from __future__ import annotations
import asyncio
import json, os, re, urllib.request, uuid
from .catalog import CAPABILITIES, CAP_KEYS, STRATEGIES, heuristics, risk_flags
from .neural import state_features
from . import store

MAX_AGENTS = 8


def new_id(prefix):
    return prefix + "_" + uuid.uuid4().hex[:12]


def business_state(b):
    return state_features(
        b["goal"], b["industry"], b["size"], b["budget_usd"], b["country"]
    )


async def filter_decision(user_id, b):
    policy = await store.load_policy(user_id, "root_manager")
    x = business_state(b)
    learned = policy.predict(x)
    cold = heuristics(b["goal"], b["industry"], b["size"])
    weight = 0.12 if policy.version == 0 else min(0.85, 0.45 + policy.version * 0.08)
    ranked = {
        k: round((1 - weight) * cold[k] + weight * learned[k], 5) for k in CAP_KEYS
    }
    order = sorted(CAP_KEYS, key=lambda k: ranked[k], reverse=True)
    max_count = {"micro": 3, "small": 4, "medium": 6, "enterprise": 8}[b["size"]]
    selected = [k for k in order if ranked[k] >= 0.245][:max_count]
    if len(selected) < 2:
        selected = order[:2]
    flags = risk_flags(b["goal"])
    if flags and "compliance" not in selected:
        selected = selected[: max_count - 1] + ["compliance"]
    return {
        "selected": selected,
        "ranking": ranked,
        "neural_raw": {k: round(v, 4) for k, v in learned.items()},
        "policy_version": policy.version,
        "neural_parameters": policy.parameter_count,
        "risk_flags": flags,
        "neural_weight": round(weight, 2),
    }


def topology_for(b, caps):
    if b["size"] == "enterprise" and len(caps) >= 5:
        return "hierarchical"
    if b["size"] == "medium" and len(caps) >= 5:
        return "team_based"
    return "flat"


def _safe_title(raw, default):
    if not isinstance(raw, str):
        return default
    return re.sub("[\\x00-\\x1f<>]", "", raw)[:78].strip() or default


def api_available():
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def _openai_text(prompt, instructions, max_output_tokens=1100):
    """Optional real LLM, no implicit browsing/tools; one HTTP request. Not used in demo."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    body = {
        "model": model,
        "instructions": instructions,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
        "store": False,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            obj = json.load(resp)
    except Exception as exc:
        raise RuntimeError("LLM request failed. Please retry later.") from exc
    out = []
    for item in obj.get("output", []):
        if item.get("type") == "message":
            out.extend(
                (
                    t.get("text", "")
                    for t in item.get("content", [])
                    if t.get("type") == "output_text"
                )
            )
    if not out:
        raise RuntimeError("LLM returned no visible text")
    return "\n".join(out)


def _json_object(s):
    s = (
        s.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start = s.find("{")
        end = s.rfind("}")
        if start >= 0 and end > start:
            return json.loads(s[start : end + 1])
        raise ValueError("Invalid LLM JSON")


def _proposal_llm(b, selected, decision):
    doc = {
        "business": b,
        "candidate_capabilities": selected,
        "risk_flags": decision["risk_flags"],
        "permitted_capabilities": CAP_KEYS,
        "max_agents": MAX_AGENTS,
    }
    instr = "You are the Manager of an experimental self-organizing business agent system. You design an appropriate SMALL workforce for the objective, not a fixed CEO/CTO/CFO template. You may reselect capabilities based on evidence, but only from permitted_capabilities. Return only a JSON object with keys: capabilities (list of permitted strings, 2-8), topology (flat,team_based,hierarchical), rationale (string), and tasks (object mapping capability strings to specific <=170 character deliverables). Do not claim actions already executed. Do not grant privileges. Flag missing information and human approvals in rationale."
    result = _json_object(_openai_text(json.dumps(doc), instr, 1050))
    if not isinstance(result, dict):
        raise ValueError("Manager proposal not an object")
    picked = []
    for c in result.get("capabilities", []):
        if c in CAPABILITIES and c not in picked:
            picked.append(c)
    picked = picked[:MAX_AGENTS]
    if len(picked) < 2:
        picked = selected
    if decision["risk_flags"] and "compliance" not in picked:
        picked = picked[: MAX_AGENTS - 1] + ["compliance"]
    topo = result.get("topology")
    if topo not in ("flat", "team_based", "hierarchical"):
        topo = topology_for(b, picked)
    tasks = {}
    raw_tasks = result.get("tasks", {})
    for c in picked:
        tasks[c] = _safe_title(
            raw_tasks.get(c) if isinstance(raw_tasks, dict) else "",
            CAPABILITIES[c]["task"],
        )
    return (
        picked,
        topo,
        _safe_title(
            result.get("rationale"), "LLM Manager selected these capabilities."
        ),
        tasks,
    )


async def build_org(user_id, b, mode="auto", parent_org_id=None):
    dec = await filter_decision(user_id, b)
    selected = dec["selected"]
    topo = topology_for(b, selected)
    rationale = "Local baseline: capabilities selected from task and industry signals, adjusted by the small neural filter. Teams are proposed for planning; no external actions are performed."
    tasks = {c: CAPABILITIES[c]["task"] for c in selected}
    using = "demo"
    if mode == "ai" and (not api_available()):
        raise RuntimeError("AI mode requires OPENAI_API_KEY")
    if mode == "ai":
        selected, topo, rationale, tasks = await asyncio.to_thread(
            _proposal_llm, b, selected, dec
        )
        using = "ai"
    parent = await store.get_org(user_id, parent_org_id) if parent_org_id else None
    if parent_org_id and (not parent):
        raise KeyError("Previous organization not found")
    prior = {a["capability"]: a for a in parent["plan"]["agents"]} if parent else {}
    agents = []
    for c in selected:
        a_id = new_id("agent")
        inherited = prior.get(c)
        agents.append(
            {
                "id": a_id,
                "capability": c,
                "role": CAPABILITIES[c]["role"],
                "team": CAPABILITIES[c]["label"],
                "status": "proposed",
                "task": tasks[c],
                "reports_to": "root_manager",
                "strategy": "",
                "policy_version": 0,
                "inherited_from": inherited["id"] if inherited else None,
            }
        )
    if topo == "hierarchical":
        for a in agents:
            if a["capability"] in ("strategy", "operations"):
                a["coordination_role"] = "team_lead"
        lead = next(
            (a for a in agents if a.get("coordination_role") == "team_lead"), None
        )
        if lead:
            for a in agents:
                if a["id"] != lead["id"] and a["capability"] not in (
                    "compliance",
                    "quality",
                ):
                    a["reports_to"] = lead["id"]
    relations = [
        {"source": a["reports_to"], "target": a["id"], "type": "reports_to"}
        for a in agents
    ]
    for a in agents:
        if a["capability"] in ("compliance", "quality"):
            relations.append(
                {
                    "source": a["id"],
                    "target": "root_manager",
                    "type": "independent_review",
                }
            )
    org_id = new_id("org")
    plan = {
        "name": b["name"],
        "goal": b["goal"],
        "topology": topo,
        "planning_mode": using,
        "rationale": rationale,
        "agents": agents,
        "relationships": relations,
        "manager_filter": dec,
        "approvals_required": bool(dec["risk_flags"]),
        "approval_flags": dec["risk_flags"],
        "external_actions_enabled": False,
        "human_owner": "business_owner",
        "parent_organization_id": parent_org_id,
    }
    policies = {}
    for a in agents:
        old = a.get("inherited_from")
        inherited_policy = (
            await store.load_policy(user_id, old, kind="worker")
            if old
            else await store.load_policy(user_id, a["id"], kind="worker")
        )
        a["policy_version"] = inherited_policy.version
        policies[a["id"]] = inherited_policy
    await store.add_org(user_id, org_id, b, plan, agents, policies)
    return await store.get_org(user_id, org_id)


async def agent_filter(user_id, agent, b):
    """Worker-owned neural filter executed before ANY worker LLM call."""
    model = await store.load_policy(user_id, agent["id"], kind="worker")
    x = state_features(
        b["goal"] + " " + agent["task"],
        b["industry"],
        b["size"],
        b["budget_usd"],
        b["country"],
    )
    neural = model.predict(x)
    defaults = {
        "research": {"research": 0.86},
        "finance": {"analyze": 0.84},
        "quality": {"verify": 0.9},
        "compliance": {"verify": 0.88},
        "engineering": {"analyze": 0.65, "draft": 0.6},
        "marketing": {"draft": 0.82},
        "sales": {"draft": 0.7},
        "customer_support": {"analyze": 0.74},
        "operations": {"analyze": 0.8},
    }
    cold = defaults.get(agent["capability"], {"analyze": 0.6})
    blend = 0.12 if model.version == 0 else min(0.9, 0.5 + 0.08 * model.version)
    scores = {
        s: (1 - blend) * cold.get(s, 0.17) + blend * neural[s] for s in STRATEGIES
    }
    best = max(scores, key=scores.get)
    return {
        "action": best,
        "policy_version": model.version,
        "parameter_count": model.parameter_count,
        "scores": {k: round(v, 4) for k, v in scores.items()},
    }


async def run_org(user_id, org_id, mode="demo"):
    org = await store.get_org(user_id, org_id)
    if not org:
        raise KeyError("Organization not found")
    if mode == "ai" and (not api_available()):
        raise RuntimeError("Configure OPENAI_API_KEY for AI execution")
    plan = org["plan"]
    b = org["business"]
    steps = []
    previous = []
    for a in plan["agents"]:
        decision = await agent_filter(user_id, a, b)
        if mode == "ai":
            context = {
                "business": b,
                "role": a["role"],
                "assigned_task": a["task"],
                "strategy": decision["action"],
                "previous_work": previous[-4:],
            }
            instructions = "You are an AI planning specialist, NOT a real-world employee. Produce an actionable analysis/draft for your assigned business task. Clearly identify assumptions, missing evidence and approvals needed. You have no business tools, cannot contact external services, and must not claim execution. Keep it under 250 words. Use the provided strategy."
            text = await asyncio.to_thread(
                _openai_text, json.dumps(context), instructions, 520
            )
        else:
            text = f"SIMULATED PLAN — {a['role']} ({decision['action']}). Proposed work: {a['task']}. Start by gathering business-specific evidence, identify 2-3 alternatives, and define acceptance criteria. No research, external tool calls, or real business actions have been performed."
        step = {
            "agent_id": a["id"],
            "role": a["role"],
            "capability": a["capability"],
            "strategy": decision,
            "deliverable": text,
            "status": "draft_only",
        }
        steps.append(step)
        previous.append({"role": a["role"], "deliverable": text[:550]})
    outputs = {
        "steps": steps,
        "summary": f"Created {len(steps)} draft planning deliverables. No external business action was performed.",
        "notice": "AI outputs are unverified drafts; demo outputs are simulated planning examples.",
        "requires_human_review": True,
    }
    rid = new_id("run")
    await store.record_run(user_id, rid, org_id, mode, "completed", outputs)
    return {
        "id": rid,
        "org_id": org_id,
        "mode": mode,
        "status": "completed",
        "outputs": outputs,
    }


async def manager_feedback(user_id, org_id, score, corrected, notes, verified):
    org = await store.get_org(user_id, org_id)
    if not org:
        raise KeyError("Organization not found")
    policy = await store.load_policy(user_id, "root_manager")
    before = policy.predict(business_state(org["business"]))
    learned = False
    result = None
    if verified and corrected:
        y = [1 if c in corrected else 0 for c in CAP_KEYS]
        result = await asyncio.to_thread(
            policy.fit, [business_state(org["business"])], [y], epochs=250, lr=0.65
        )
        learned = True

    async def commit(session):
        if learned:
            await store.save_policy(user_id, "root_manager", policy, session)
        await store.add_feedback(
            user_id, org_id, score, corrected, notes, verified, policy.version, session
        )

    await store.transaction(commit)
    after = policy.predict(business_state(org["business"]))
    return {
        "trained": learned,
        "training_result": result,
        "before": {k: round(v, 4) for k, v in before.items()},
        "after": {k: round(v, 4) for k, v in after.items()},
        "policy_version": policy.version,
        "note": "Training from one correction can overfit; validate on held-out cases.",
    }


async def worker_feedback(user_id, org_id, agent_id, strategy, verified):
    org = await store.get_org(user_id, org_id)
    if not org:
        raise KeyError("Organization not found")
    agent = next((a for a in org["plan"]["agents"] if a["id"] == agent_id), None)
    if not agent:
        raise KeyError("Agent not found in organization")
    if strategy not in STRATEGIES:
        raise ValueError("Unknown strategy")
    policy = await store.load_policy(user_id, agent_id, kind="worker")
    before = await agent_filter(user_id, agent, org["business"])
    if verified:
        b = org["business"]
        x = state_features(
            b["goal"] + " " + agent["task"],
            b["industry"],
            b["size"],
            b["budget_usd"],
            b["country"],
        )
        result = await asyncio.to_thread(
            policy.fit,
            [x],
            [[1.0 if k == strategy else 0.0 for k in STRATEGIES]],
            epochs=200,
            lr=0.6,
        )
    else:
        result = None

    async def commit(session):
        if verified:
            await store.save_policy(user_id, agent_id, policy, session)
        await store.add_worker_feedback(
            user_id, org_id, agent_id, strategy, verified, policy.version, session
        )
        await store.add_event(
            user_id,
            "agent_feedback",
            agent_id,
            {
                "verified": verified,
                "recommended_strategy": strategy,
                "version": policy.version,
            },
            session,
        )

    await store.transaction(commit)
    after = await agent_filter(user_id, agent, org["business"])
    return {
        "trained": bool(verified),
        "result": result,
        "before": before,
        "after": after,
        "policy_version": policy.version,
    }
