"""Common capability vocabulary: candidates, never a required organization chart."""
from __future__ import annotations

CAPABILITIES = {
 "strategy": {"label":"Strategy & Planning", "terms":"strategy strategic growth business plan expansion decision competitive goals roadmap pricing model", "role":"Strategy Analyst", "task":"Assess strategic options, assumptions, and risks"},
 "research": {"label":"Market & Evidence Research", "terms":"market research competitor survey trend discover evidence investigate research customer insight validate idea feasibility", "role":"Research Specialist", "task":"Research the target market, customers, and evidence gaps"},
 "product": {"label":"Product & Design", "terms":"product design ux user experience prototype feature roadmap product launch improve offering", "role":"Product Specialist", "task":"Translate the objective into product requirements and milestones"},
 "engineering": {"label":"Engineering & Technology", "terms":"software website web application developer api database cloud code bug security platform technical automation integration ecommerce e-commerce", "role":"Engineering Specialist", "task":"Propose a technical solution with dependencies and testable steps"},
 "marketing": {"label":"Marketing & Acquisition", "terms":"marketing advertising ad campaign social media brand traffic demand generation content promotion SEO", "role":"Marketing Specialist", "task":"Design messaging, channels, and an acquisition experiment"},
 "sales": {"label":"Sales & Revenue", "terms":"sales lead conversion revenue pipeline prospect outreach closing crm selling customer acquisition", "role":"Sales Specialist", "task":"Build a sales or revenue-growth action plan"},
 "finance": {"label":"Finance & Budget", "terms":"finance financial cash accounting budget costs profit forecast unit economics invoice tax spend expense funding investment price", "role":"Finance Specialist", "task":"Prepare assumptions, cost estimates, and financial risks"},
 "operations": {"label":"Operations & Delivery", "terms":"operations operational productivity workflow process delivery coordination fulfillment work efficiency scheduling optimize operations", "role":"Operations Specialist", "task":"Map operational bottlenecks and improvement steps"},
 "supply_chain": {"label":"Supply Chain & Inventory", "terms":"supply chain supplier procurement inventory stock warehouse shipping logistics delivery late order manufacturing factory materials reorder", "role":"Supply Chain Specialist", "task":"Assess inventory, suppliers, fulfillment, and supply risks"},
 "customer_support": {"label":"Customer Support & Experience", "terms":"support helpdesk customer service ticket complaint refund returns resolution customer satisfaction churn", "role":"Support Specialist", "task":"Triage customer issues and propose an evidence-based resolution workflow"},
 "people": {"label":"People & Talent", "terms":"hiring recruiting human resources employees staff training onboarding retention team workforce talent payroll", "role":"People Operations Specialist", "task":"Identify staffing and workforce process needs"},
 "compliance": {"label":"Risk & Compliance", "terms":"legal compliance privacy regulation regulatory contract security risk audit policy gdpr hipaa financial advice medical", "role":"Risk & Compliance Reviewer", "task":"Identify permissions, jurisdictional risks, and approvals to obtain"},
 "quality": {"label":"Quality Assurance", "terms":"quality verify testing test defects inspection review reliability errors audit evaluate benchmark improve", "role":"Quality Reviewer", "task":"Specify objective acceptance checks and evidence requirements"}
}
CAP_KEYS=list(CAPABILITIES)
STRATEGIES=["research", "analyze", "draft", "verify", "escalate", "summarize"]
SIZES=["micro", "small", "medium", "enterprise"]
SENSITIVE={"finance", "compliance", "people"}

from re import findall
TERMS = {k: set(findall(r"[a-z0-9]+", v["terms"].lower())) for k,v in CAPABILITIES.items()}


def heuristics(goal: str, industry: str, size: str):
    """Transparent cold-start priors; learning modifies these, never replaces safety rules."""
    words=set(findall(r"[a-z0-9]+", f"{goal} {industry}".lower()))
    scores={k:0.12 for k in CAP_KEYS}
    for k, terms in TERMS.items():
        hits=len(words & terms)
        scores[k] += min(.72, .26*hits)
    text=f"{goal} {industry}".lower()
    industry_defaults={
       "retail":("sales","marketing","supply_chain","customer_support"),
       "ecommerce":("sales","marketing","supply_chain","customer_support"),
       "e-commerce":("sales","marketing","supply_chain","customer_support"),
       "software":("product","engineering","customer_support"),
       "saas":("product","engineering","customer_support"),
       "manufactur":("supply_chain","operations","quality"),
       "healthcare":("operations","compliance","quality"),
       "logistic":("operations","supply_chain"),
       "agency":("research","marketing","sales"),
       "consult":("research","strategy","sales"),
       "restaurant":("operations","supply_chain","customer_support"),
       "education":("product","operations","people"),
    }
    for phrase, caps in industry_defaults.items():
        if phrase in industry.lower():
            for k in caps:scores[k]+=.20
    # Mandatory policy reviews are triggered by a separate risk evaluator, not these rankings.
    return {k:min(.98,v) for k,v in scores.items()}


def risk_flags(text: str):
    text=text.lower()
    flags=[]
    for label, keywords in {
       "financial_or_payment": ["pay ","payment","transfer money","bank account","invest ","wire ","purchase ","refund "],
       "legal_or_regulated": ["legal","contract","medical","diagnosis","patient","tax filing","gdpr","hipaa","regulation"],
       "employment_decisions": ["fire employee", "terminate employee", "hire employee", "salary change"],
       "external_action": ["send email", "publish ", "post on", "contact customers", "delete ", "deploy ", "place an order", "order products"]
    }.items():
        if any(x in text for x in keywords):flags.append(label)
    return flags
