"""
Factors on deciding whether a hypothesis for change is meant to be considered or not:

- Ownership / Rights -> If something prevents the change of that property for that reason, regardless of request, then autorejected as making a change at that specific place.

- Environment (Floodway / Contamination) - If the site lies in a regulated floodway where development is explicitly prohibited.

- Utilities (Non-Extendable) - If water, wastewater, or electricity providers state that connection or capacity is not feasible at all within the planning horizon.

Other things provided are indications to the user, as to what would be required to go ahead with proposing this change, which are things such as:

- approvals/permits required
- political diagreeance - council minutes, news, or surveys show opposition, it’s flagged, not fatal.
- changes to the original-use agreement with the city - you need either a site plan amendment (if it affects private land requirements) or an encroachment permit (if it affects city-owned land).

or precisely as follows:

The only valid auto-rejects (tightened)

Reject only if all three parts are true: (a) primary source, (b) explicit prohibition/denial wording, (c) no credible path within horizon (18–24 mo).

Land control & legal access — UNSOLVABLE

Reject if: A primary document (title/parcel register, easement/heritage easement, court order, or Planning Act frontage/access ruling) explicitly says you cannot use or access the land (e.g., “no right of access,” “development prohibited by covenant/easement,” “no legal frontage”) and there’s no realistic path to acquire/modify rights in horizon.

Otherwise: Flag as acquisition/rights to secure (lease, easement, consent).

Regulatory “no-build” overlay — PROHIBITED

Reject if: Conservation/flood authority or statute uses prohibitive language for the exact parcel (e.g., regulated floodway where development is prohibited, heritage conservation easement prohibiting new structures, provincially significant wetland/no encroachment, source-protection policy with “prohibited activity”).

Otherwise: Treat as approval/mitigation required (e.g., floodproofing, setbacks, risk-management plan).

Utilities — CONNECTION DENIED (no plan)

Reject if: A utility denial/position or official plan says connection/capacity is not feasible and there is no capital project or alternative (onsite generation, storage, septic exception) inside horizon.

Otherwise: Approval flag (servicing upgrade/connection study).

🔎 Proof standard: The text must contain strong verbs like “prohibited,” “not permitted,” “cannot,” “denied,” “no capacity / not feasible.” Secondary blogs/news never qualify. If the language is weaker (“discouraged,” “requires permit/variance,” “insufficient today”), it’s not an auto-reject.

Things that must never auto-reject (permission levers)

Zoning/by-law mismatches → needs ZBA/variance/site plan.

Parking/ROW/encroachment rules → permit or amendment.

Heritage designation (without prohibitive easement) → heritage permit/conditions.

Political/community pushback → engage + mitigation package.

Contamination with an approved remediation path → phase II + RSC timeline, not reject.

“Utilities require upgrades” (but feasible) → servicing plan, not reject.
"""


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Open-Style Deep Research Pipeline (locale-aware, iterative reflect loop)

Implements your diagram:
Research Topic -> Plan -> Search Queries -> [Search/Read]* -> Information Sources
-> Evaluate -> (if Incomplete) Reflect -> Update Queries -> repeat -> Write -> Report

Key features:
- Locale parsing from natural-language user answer (site/city/region/country)
- Dynamic authoritative-source hints from locale (e.g., city.ca / .gov)
- Reflect loop that proposes site-restricted queries to fill missing required slots
- Strict auto-reject: conservative JUDGE with negation/scope + LLM entailment over exact sentence
- Loud debugging: no silent [] returns; all failures log with context

APIs:
- Tavily (search) — env: TAVILY_API_KEY
- Jina Reader (HTML extraction) — no key
- pdfplumber (optional) — PDF text
- Gemini (LLM for parse/plan/reflect/synthesize/judge) — env: GEMINI_API_KEY
- Cohere (LLM alternative for parse/plan/reflect/synthesize/judge) — env: COHERE_API_KEY
"""

import os, re, io, json, logging, argparse
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ---------- Optional deps ----------
try:
    import pdfplumber  # type: ignore
    HAVE_PDFPLUMBER = True
except Exception:
    HAVE_PDFPLUMBER = False

try:
    import google.generativeai as genai  # type: ignore
    HAVE_GEMINI = True
except Exception:
    HAVE_GEMINI = False

try:
    import cohere  # type: ignore
    HAVE_COHERE = True
except Exception:
    HAVE_COHERE = False

# ---------- Config ----------
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")
MAX_URLS_PER_ROUND = 30
MAX_ROUNDS = 3
REQUIRED_SLOTS = ["environment", "utilities", "zoning_landuse"]
HEADERS = {"User-Agent": "OpenDeepResearch/0.4"}

# ---------- Data Models ----------
@dataclass
class Evidence:
    id: str
    slot: str
    url: str
    title: str
    locator: str
    snippet: str
    is_primary: bool

@dataclass
class RoundTrace:
    round_id: int
    queries: List[str]
    urls_fetched: int
    evidence_ids: List[str]
    reflect_notes: List[str] = field(default_factory=list)

@dataclass
class ReportBundle:
    topic: str
    site: str
    city: str
    region: str
    country: str
    rounds: List[RoundTrace]
    evidence: List[Evidence]
    decision: Dict
    demand_metrics: Dict
    notes: List[str] = field(default_factory=list)

# ---------- LLM helpers ----------
def get_model(api_provider="gemini"):
    """Get LLM model instance for specified provider.
    
    Args:
        api_provider (str): Either 'gemini' or 'cohere'
    
    Returns:
        Model instance or None if not available
    """
    if api_provider == "gemini" and HAVE_GEMINI and GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        return genai.GenerativeModel("gemini-2.0-flash")
    elif api_provider == "cohere" and HAVE_COHERE and COHERE_API_KEY:
        return cohere.Client(COHERE_API_KEY)
    
    available_providers = []
    if HAVE_GEMINI and GEMINI_API_KEY:
        available_providers.append("gemini")
    if HAVE_COHERE and COHERE_API_KEY:
        available_providers.append("cohere")
    
    if available_providers:
        fallback = available_providers[0]
        logging.warning(f"[llm] {api_provider} not configured; falling back to {fallback}")
        return get_model(fallback)
    
    logging.warning("[llm] No LLM providers configured; using deterministic fallbacks where possible.")
    return None

PARSE_LOCALE_PROMPT = """
## ROLE
You are a geographic information extraction specialist for land-use research systems.

## TASK
Extract structured location data from user responses about specific sites or properties.

## INPUT
Question: {question}
User Response: {answer}

## EXTRACTION REQUIREMENTS
Extract the following fields with high accuracy:
- site: Specific property address, building name, or location identifier
- city: Municipal jurisdiction name
- region_or_state: Province, state, or equivalent administrative division
- country: Country name (full name or ISO-3 code)

## OUTPUT FORMAT
Return ONLY valid JSON with the exact keys specified above. No additional text or explanation.

## EXAMPLE
Input: "Let's look at 123 Main Street in Toronto, Ontario"
Output: {"site": "123 Main Street", "city": "Toronto", "region_or_state": "Ontario", "country": "Canada"}

## CRITICAL REQUIREMENTS
- If information is missing, use empty string ""
- Do not guess or infer missing data
- Ensure JSON is valid and parseable
- Return only the JSON object, no markdown formatting
"""

PLANNER_PROMPT = """
## ROLE
You are a strategic research coordinator specializing in municipal planning and land-use feasibility studies.

## OBJECTIVE
Generate comprehensive search queries to gather authoritative information for land-use change feasibility analysis.

## CONTEXT
Research Target: {topic}
Location: {site}
Municipality: {city}
Administrative Region: {region}
Country: {country}

## SEARCH STRATEGY
Prioritize official government and institutional sources in this order:
1. Municipal government websites (cityname.gov, cityname.ca, cityname.org)
2. Provincial/state government planning departments
3. Official utility company documentation
4. Conservation authority and environmental agencies
5. Transportation authority websites
6. Heritage and cultural preservation offices

## RESEARCH DOMAINS
Generate queries across these critical areas:

### PROPERTY RIGHTS & LEGAL ACCESS
- Title searches, easements, covenants, right-of-way agreements
- Land ownership verification, access restrictions

### ENVIRONMENTAL CONSTRAINTS
- Floodplain designations, conservation areas, contaminated sites
- Environmental impact assessments, source water protection

### UTILITY INFRASTRUCTURE
- Water and wastewater capacity, connection feasibility
- Electrical service availability, transformer capacity
- Gas line accessibility, telecommunications infrastructure

### ZONING & REGULATORY COMPLIANCE
- Current zoning designations, permitted uses
- Official plan policies, development standards
- Variance requirements, site plan approval processes

### HERITAGE & CULTURAL CONSERVATION
- Heritage designations, cultural significance
- Encroachment permits, right-of-way requirements

### TRANSPORTATION & ACCESSIBILITY
- Transit service levels, route frequency
- Traffic volumes (AADT), parking requirements
- Pedestrian and cycling infrastructure

### PRECEDENT ANALYSIS
- Recent approvals, variance decisions
- Committee of adjustment rulings, council decisions

## OUTPUT SPECIFICATIONS
- Generate exactly 12 search queries
- Use specific site addresses where applicable
- Include document type specifications (PDF, by-law, minutes)
- Target official government domains when possible
- Return as JSON array of strings only

## EXAMPLE QUERY FORMATS
- "site:waterloo.ca zoning by-law permitted uses {site}"
- "{city} floodplain map conservation authority PDF"
- "{city} wastewater capacity study {site} connection"
- "{city} council minutes variance approval {site}"

## QUALITY STANDARDS
- Each query must target specific, actionable information
- Avoid overly broad or generic search terms
- Include location-specific identifiers
- Prioritize recent and authoritative sources
"""

REFLECT_PROMPT = """
## ROLE
You are a research quality assurance specialist for municipal planning feasibility studies.

## OBJECTIVE
Analyze research coverage and identify gaps requiring additional targeted investigation.

## CURRENT RESEARCH STATUS
{coverage}

## ANALYSIS FRAMEWORK
Evaluate research completeness across three critical dimensions:

### COVERAGE ASSESSMENT
- **Environment**: Floodplain status, conservation areas, contamination
- **Utilities**: Water/wastewater capacity, electrical service availability
- **Zoning**: Current designation, permitted uses, development standards

### EVIDENCE QUALITY EVALUATION
- **Source Authority**: Official government vs. secondary sources
- **Document Type**: Legislative (by-laws, official plans) vs. interpretive
- **Recency**: Current regulations vs. outdated information
- **Specificity**: Site-specific vs. general area information

### GAP IDENTIFICATION
Identify missing or insufficient information requiring targeted follow-up queries.

## QUERY GENERATION STRATEGY
For identified gaps, create precise search queries using:
- **Site-specific targeting**: site:domain.com "specific address"
- **Document type specification**: PDF, by-law, minutes, capacity study
- **Official source emphasis**: Municipal, provincial, utility company domains
- **Temporal relevance**: Recent approvals, current regulations

## OUTPUT SPECIFICATIONS
Return structured JSON with:
- **missing_or_weak**: Array of insufficient research areas
- **new_queries**: Array of up to 6 targeted search queries
- **notes**: Array of strategic recommendations

## EXAMPLE OUTPUT
{
  "missing_or_weak": ["utilities capacity study", "heritage designation status"],
  "new_queries": [
    "site:waterloo.ca wastewater capacity study {site} connection",
    "site:waterloo.ca heritage register {site} designation"
  ],
  "notes": ["Prioritize official utility capacity reports", "Verify heritage status impacts"]
}

## QUALITY STANDARDS
- Maximum 6 additional queries to maintain focus
- Each query must address specific identified gap
- Prioritize official government sources
- Include site-specific targeting where applicable
"""

SYNTH_PROMPT = """
## ROLE
You are a senior municipal planning consultant preparing a comprehensive feasibility assessment for land-use change proposals.

## OBJECTIVE
Analyze collected evidence and provide a structured decision framework with clear recommendations and supporting documentation.

## DECISION FRAMEWORK
Apply conservative, evidence-based analysis using these criteria:

### AUTOMATIC REJECTION CRITERIA
Reject proposals ONLY when PRIMARY official sources explicitly state absolute prohibition:

#### LAND ACCESS & PROPERTY RIGHTS
- Legal access denial (no right of access, blocked frontage)
- Prohibitive easements or covenants preventing development
- Court orders or legal restrictions on property use

#### ENVIRONMENTAL PROHIBITIONS
- Regulated floodway designations with explicit development prohibition
- Heritage conservation easements prohibiting new construction
- Provincially significant wetland no-encroachment policies
- Source water protection zones with prohibited activities

#### UTILITY INFRASTRUCTURE
- Official utility company statements of "no capacity" or "not feasible"
- No planned infrastructure improvements within 24-month horizon
- No alternative service options available (onsite systems, etc.)

### APPROVAL-REQUIRED CATEGORIES
All other constraints require approval processes, not rejection:
- Zoning by-law amendments (ZBA) or minor variances
- Site plan approval processes
- Heritage permits and conditions
- Encroachment permits for right-of-way
- Environmental permits and mitigation plans
- Utility connection agreements and upgrades

## EVIDENCE REQUIREMENTS
Every analytical conclusion MUST be supported by:
- Evidence ID reference (e.g., e003)
- Source website URL
- Specific document or policy citation
- Clear connection between evidence and conclusion

## OUTPUT STRUCTURE
Provide two integrated components:

### 1. STRUCTURED DECISION JSON
```json
{
  "hard_blocks": [
    {
      "type": "environment_prohibition",
      "evidence_ids": ["e003", "e007"],
      "description": "Regulated floodway prohibits development",
      "source_urls": ["waterloo.ca/floodplain-map", "conservation.ca/floodway-policy"]
    }
  ],
  "approval_flags": [
    {
      "type": "needs_zba",
      "evidence_ids": ["e012"],
      "description": "Current zoning requires amendment",
      "source_urls": ["waterloo.ca/zoning-bylaw"]
    }
  ],
  "demand_metrics": {
    "transit_frequency": "Every 15 minutes",
    "traffic_volume": "8,500 AADT",
    "parking_requirements": "1 space per unit"
  },
  "notes": ["Additional consultation required with conservation authority"]
}
```

### 2. EXECUTIVE SUMMARY (Maximum 400 words)
Professional brief including:
- Executive summary of findings
- Key constraints and opportunities
- Required approvals and processes
- Risk assessment and mitigation strategies
- Timeline estimates for approval processes
- Cost implications (where available)

## CITATION FORMAT
Use consistent citation format: [EvidenceID: WebsiteURL]
Example: [e003: waterloo.ca/zoning-bylaw] or [e007: ontario.ca/official-plan]

## QUALITY STANDARDS
- Maintain professional, objective tone
- Avoid speculation beyond evidence
- Provide actionable recommendations
- Ensure all claims are verifiable
- Balance comprehensiveness with conciseness
"""

# ---------- Locale / authority ----------
def parse_locale(question: str, answer: str, api_provider: str = "gemini") -> Dict:
    model = get_model(api_provider)
    if model:
        try:
            if api_provider == "gemini":
            t = model.generate_content(PARSE_LOCALE_PROMPT.format(question=question, answer=answer)).text or "{}"
            elif api_provider == "cohere":
                response = model.generate(
                    model="command",
                    prompt=PARSE_LOCALE_PROMPT.format(question=question, answer=answer),
                    max_tokens=500,
                    temperature=0.1
                )
                t = response.generations[0].text or "{}"
            
            js = json.loads(t[t.find("{"):t.rfind("}")+1])
            site = js.get("site") or answer
            city = js.get("city") or ""
            region = js.get("region_or_state") or js.get("region") or ""
            country = js.get("country") or ""
            logging.info("[locale] site=%s, city=%s, region=%s, country=%s", site, city, region, country)
            return {"site":site, "city":city, "region":region, "country":country}
        except Exception as e:
            logging.exception("[locale] LLM parse failed: %s", e)
    # fallback: naive City, Region pattern
    m = re.search(r"\b([A-Z][a-zA-Z]+),\s*([A-Z][a-zA-Z]+)\b", answer)
    city = m.group(1) if m else ""
    region = m.group(2) if m else ""
    logging.warning("[locale] Fallback parse used. city=%s region=%s", city, region)
    return {"site": answer, "city": city, "region": region, "country": ""}


# ---------- HTTP / Extraction with loud debug ----------
def tavily_search(query: str, max_results: int = 5) -> List[Dict]:
    """Search via Tavily with loud debugging on failures and empties."""
    if not TAVILY_API_KEY:
        logging.error("[tavily] MISSING_API_KEY: set TAVILY_API_KEY")
        return []
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {TAVILY_API_KEY}", "Content-Type": "application/json"},
            json={"query": query, "search_depth": "basic", "max_results": max_results, "include_answer": False},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        results = [{"url": x.get("url"), "title": x.get("title",""), "description": x.get("description","")}
                   for x in data.get("results", []) if x.get("url")]
        if not results:
            logging.warning("[tavily] EMPTY_RESULTS query='%s' payload_keys=%s", query, list(data.keys()))
        else:
            logging.info("[tavily] %d results query='%s'", len(results), query)
        return results
    except Exception as e:
        logging.exception("[tavily] ERROR query='%s': %s", query, e)
        return []

def fetch_html_jina(url: str) -> Tuple[str, str]:
    """Fetch HTML via Jina Reader proxy; print debug on failure/short text."""
    if url.lower().endswith(".pdf"):
        return ("", "")
    try:
        r = requests.get(f"https://r.jina.ai/{url}", headers=HEADERS, timeout=30)
        if r.ok and len(r.text) > 80:
            title = url.split("/")[2]
            return (title, r.text[:25000])
        logging.warning("[jina] SHORT_OR_BAD status=%s url=%s", getattr(r, "status_code", None), url)
    except Exception as e:
        logging.exception("[jina] ERROR url=%s: %s", url, e)
    return ("", "")

def fetch_pdf_text(url: str) -> Tuple[str, str]:
    """Fetch and parse first ~6 pages of a PDF; print debug on issues."""
    if not HAVE_PDFPLUMBER:
        logging.warning("[pdf] pdfplumber not installed; skipping %s", url)
        return ("", "")
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if not r.ok:
            logging.warning("[pdf] HTTP_NOT_OK status=%s url=%s", r.status_code, url)
            return ("", "")
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            pages = min(6, len(pdf.pages))
            txt = "\n\n".join((pdf.pages[i].extract_text() or "") for i in range(pages))
        if len(txt) < 40:
            logging.warning("[pdf] VERY_SHORT_TEXT url=%s", url)
        return (url.split("/")[-1], txt[:25000])
    except Exception as e:
        logging.exception("[pdf] ERROR url=%s: %s", url, e)
        return ("", "")

# ---------- Slotting ----------
SLOT_PATTERNS = {
    "ownership_rights": r"(onland|parcel register|easement|right[- ]of[- ]way|covenant|title)",
    "environment": r"(floodplain|flood way|regulated area|conservation|contaminat|brownfield|source water)",
    "utilities": r"(wastewater|sanitary|watermain|water main|capacity|hydro|electric connection|transformer|utility)",
    "zoning_landuse": r"(zoning|by-law|bylaw|permitted uses|official plan|use table)",
    "approvals_precedent": r"(minor variance|rezoning|zba|site plan|approved|decision|committee of adjustment|cofa)",
    "heritage_row": r"(heritage|designation|encroachment|right[- ]of[- ]way permit)",
    "mobility_transit": r"(transit|bus|route|lrt|headway|every \d+ minutes|stop)",
    "traffic_parking_safety": r"(aadt|traffic count|parking utilization|collision|speed study)",
}

def slot_for(text: str, title: str) -> Optional[str]:
    blob = (title + "\n" + text[:1500]).lower()
    for slot, rx in SLOT_PATTERNS.items():
        if re.search(rx, blob):
            return slot
    return None

# ---------- Plan / Search / Read / Evaluate / Reflect ----------
def plan_queries(topic: str, site: str, city: str, region: str, country: str, api_provider: str = "gemini") -> List[str]:
    model = get_model(api_provider)
    if model:
        try:
            if api_provider == "gemini":
            t = model.generate_content(PLANNER_PROMPT.format(topic=topic, site=site, city=city, region=region, country=country)).text or "[]"
            elif api_provider == "cohere":
                response = model.generate(
                    model="command",
                    prompt=PLANNER_PROMPT.format(topic=topic, site=site, city=city, region=region, country=country),
                    max_tokens=2000,
                    temperature=0.3
                )
                t = response.generations[0].text or "[]"
            
            queries = json.loads(t[t.find("["):t.rfind("]")+1])
            logging.info("[plan] %d queries", len(queries))
            return queries
        except Exception as e:
            logging.exception("[plan] LLM failed: %s", e)
    # fallback templates
    addr = site or (city + ", " + region)
    queries = [
        f"{city} zoning by-law permitted uses pdf",
        f"{city} floodplain map conservation authority pdf",
        f"{city} wastewater capacity report pdf",
        f"{city} electric connection request",
        f"{city} council minutes variance {site}",
        f"{city} encroachment permit",
        f"{city} heritage register {site}",
        f"{city} transit route {site}",
        f"{city} traffic counts AADT {site}",
        f"{region} official plan pdf",
        f"{addr} site plan agreement",
    ]
    logging.warning("[plan] Using fallback queries (%d)", len(queries))
    return queries

def search_round(queries: List[str]) -> List[Dict]:
    urls = []
    for q in queries:
        results = tavily_search(q, max_results=5)
        for r in results:
            if len(urls) >= MAX_URLS_PER_ROUND: break
            urls.append(r)
        if len(urls) >= MAX_URLS_PER_ROUND: break
    # dedup
    seen=set(); out=[]
    for r in urls:
        u=r["url"]
        if u not in seen:
            seen.add(u); out.append(r)
    logging.info("[search] round collected %d unique URLs", len(out))
    return out

def read_and_slot(url_items: List[Dict], start_id: int = 1) -> List[Evidence]:
    evs=[]
    def handle(item):
        url=item["url"]; title=item.get("title","")
        if url.lower().endswith(".pdf"):
            t2,txt=fetch_pdf_text(url); loc="PDF p.1-6"
            title=title or t2
        else:
            t2,txt=fetch_html_jina(url); loc="HTML (Jina)"
            title=title or t2
        if not txt or len(txt)<60:
            logging.debug("[read] skip short text url=%s", url)
            return None
        slot=slot_for(txt,title)
        if not slot:
            logging.debug("[slot] no slot match url=%s title=%s", url, title)
            return None
        m=re.search(r"(?i)(permitted uses|flood|prohibit|variance|approved|capacity|headway|every\s+\d+\s+minutes|aadt|parking).{0,260}", txt)
        snippet=m.group(0).strip() if m else txt[:260].strip()
        return Evidence(id=f"e{start_id+len(evs):03d}",slot=slot,url=url,title=title[:140],locator=loc,snippet=snippet,is_primary=False)
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(handle,u) for u in url_items]
        for fut in as_completed(futs):
            r=fut.result()
            if r: evs.append(r)
    logging.info("[read] slotted %d evidence items", len(evs))
    return evs

def coverage_status(evs: List[Evidence]) -> Dict:
    cover={s:{"count":0} for s in REQUIRED_SLOTS}
    for e in evs:
        if e.slot in cover:
            cover[e.slot]["count"]+=1
    return cover

def evaluate(evs: List[Evidence]) -> Tuple[bool, List[str]]:
    cover=coverage_status(evs)
    complete=True; notes=[]
    for s,st in cover.items():
        if st["count"]==0:
            complete=False; notes.append(f"Missing slot {s}")
    logging.info("[eval] complete=%s notes=%s", complete, notes)
    return complete, notes

def reflect_and_update(queries: List[str], evs: List[Evidence], site: str, city: str, api_provider: str = "gemini") -> Tuple[List[str], List[str]]:
    model = get_model(api_provider)
    payload = {
        "coverage": coverage_status(evs),
        "have_slots": list({e.slot for e in evs}),
        "recent_queries": queries[-6:],
        "site": site, "city": city,
    }
    if model:
        try:
            if api_provider == "gemini":
                t = model.generate_content(REFLECT_PROMPT.format(coverage=json.dumps(payload))).text or "{}"
            elif api_provider == "cohere":
                response = model.generate(
                    model="command",
                    prompt=REFLECT_PROMPT.format(coverage=json.dumps(payload)),
                    max_tokens=1500,
                    temperature=0.2
                )
                t = response.generations[0].text or "{}"
            
            js = json.loads(t[t.find("{"):t.rfind("}")+1])
            new_q = js.get("new_queries", [])
            notes = js.get("notes", [])
            merged=list(dict.fromkeys(queries + new_q))
            logging.info("[reflect] added %d new queries; total=%d", len(new_q), len(merged))
            return merged[:12], notes
        except Exception as e:
            logging.exception("[reflect] LLM failed: %s", e)
    # fallback: add site-restricted queries for common official domains
    extras=[]
    if city:
        extras.append(f'site:{city.lower()}.ca "permitted uses" {site}')
        extras.append(f"site:{city.lower()}.ca floodway {site}")
        extras.append(f"site:{city.lower()}.gov zoning {site}")
    merged=list(dict.fromkeys(queries+extras))
    logging.warning("[reflect] fallback added %d queries; total=%d", len(extras), len(merged))
    return merged[:12], ["Added site-restricted queries (fallback)"]

# ---------- Conservative Judge ----------
def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

PROHIBIT_RX = re.compile(r"\b(prohibited|not permitted|shall not|connection (?:not )?feasible|denied)\b", re.I)
SUBJECT_RX  = re.compile(r"\b(development|building|structure|connection|service)\b", re.I)
NEGATION_RX = re.compile(r"\b(not\s+prohibit(?:ed)?|unless|except|subject to permit)\b", re.I)

def call_llm_yes_no(question: str, api_provider: str = "gemini") -> str:
    """Return 'YES' or 'NO'. If unclear or error, return 'NO' (abstain)."""
    model = get_model(api_provider)
    if not model:
        logging.warning("[judge] LLM unavailable -> NO (abstain)")
        return "NO"
    try:
        prompt = "Answer strictly YES or NO. If unclear, answer NO.\n" + question
        if api_provider == "gemini":
        resp = model.generate_content(prompt)
        ans = (resp.text or "").strip().upper()
        elif api_provider == "cohere":
            response = model.generate(
                model="command",
                prompt=prompt,
                max_tokens=10,
                temperature=0.0
            )
            ans = (response.generations[0].text or "").strip().upper()
        
        return "YES" if ans.startswith("YES") else "NO"
    except Exception as e:
        logging.exception("[judge] LLM error: %s", e)
        return "NO"

def judge_hard_block(snippet: str, url: str, slot: str, api_provider: str = "gemini") -> Dict:
    """Return {verdict: YES/NO, why: str}. Deterministic checks + LLM entailment over exact sentence."""
    for sent in _sentences(snippet):
        has_prohibit = bool(PROHIBIT_RX.search(sent))
        has_subject  = bool(SUBJECT_RX.search(sent))
        has_negation = bool(NEGATION_RX.search(sent))
        if not (has_prohibit and has_subject) or has_negation:
            continue
        # No longer filtering by primary source - let the LLM judge based on content
        q = (
            "Quote: '" + sent + "'\n"
            "Question: Does this clause explicitly PROHIBIT development/connection with no discretionary path "
            "(variance/permit) within ~24 months?"
        )
        v = call_llm_yes_no(q, api_provider)
        return {"verdict": v, "why": "entailment_yes_no"}
    return {"verdict":"NO", "why":"no_strong_sentence"}

def decide_strict(evs: List[Evidence], api_provider: str = "gemini") -> Tuple[Dict, Dict]:
    """Hard-blocks only when judge says YES; else approval flags + demand."""
    hard=[]; flags=[]; demand={}
    for e in evs:
        if e.slot in ("environment","utilities","ownership_rights"):
            j = judge_hard_block(e.snippet, e.url, e.slot, api_provider)
            if j["verdict"] == "YES":
                kind = "environment_prohibition" if e.slot=="environment" else (
                       "utility_impossible" if e.slot=="utilities" else "ownership_rights")
                hard.append({"type":kind, "evidence_ids":[e.id], "why":j["why"]})
    if any(e.slot=="zoning_landuse" for e in evs):
        flags.append({"type":"needs_zba_or_variance","evidence_ids":[e.id for e in evs if e.slot=="zoning_landuse"]})
    if any(e.slot=="approvals_precedent" for e in evs):
        flags.append({"type":"precedents","evidence_ids":[e.id for e in evs if e.slot=="approvals_precedent"]})
    if any(e.slot=="heritage_row" for e in evs):
        flags.append({"type":"heritage_or_row","evidence_ids":[e.id for e in evs if e.slot=="heritage_row"]})
    mob = " ".join(e.snippet for e in evs if e.slot=="mobility_transit")
    m = re.search(r"every\s+(\d+)\s+minutes", mob, flags=re.I)
    if m: demand["headway_hint"] = f"every {m.group(1)} minutes"
    stops = len([e for e in evs if e.slot=="mobility_transit"])
    if stops: demand["stops_refs"] = stops
    aadt_txt = " ".join(e.snippet for e in evs if e.slot=="traffic_parking_safety")
    a = re.search(r"\b(\d{4,6})\b.*(AADT|traffic)", aadt_txt, flags=re.I)
    if a: demand["aadt"] = a.group(1)
    logging.info("[decide] hard=%d flags=%d", len(hard), len(flags))
    return {"hard_blocks": hard, "approval_flags": flags}, demand

# ---------- Synthesis ----------
def synthesize(topic, site, city, region, country, evs: List[Evidence], decision: Dict, demand: Dict, api_provider: str = "gemini") -> Tuple[str,str]:
    model=get_model(api_provider)
    payload={"topic":topic, "site":site, "city":city, "region":region, "country":country,
             "evidence":[asdict(e) for e in evs], "decision":decision, "demand_metrics":demand}
    if model:
        try:
            full_prompt = SYNTH_PROMPT+"\n\nINPUT JSON:\n"+json.dumps(payload)[:120000]
            
            if api_provider == "gemini":
                t = model.generate_content(full_prompt).text or ""
            elif api_provider == "cohere":
                response = model.generate(
                    model="command",
                    prompt=full_prompt,
                    max_tokens=3000,
                    temperature=0.2
                )
                t = response.generations[0].text or ""
            
            jstart=t.find("{"); jend=t.rfind("}")+1
            js=t[jstart:jend] if jstart!=-1 else "{}"
            md=t[jend:].strip()
            return js, md
        except Exception as e:
            logging.exception("[synth] ERROR: %s", e)
    logging.warning("[synth] LLM unavailable -> fallback brief")
    return json.dumps({"decision":decision,"demand_metrics":demand},indent=2), "# Brief unavailable"

# ---------- Orchestrator ----------
def run_open_research(question: str, user_answer: str, topic: str, out_prefix: str, api_provider: str = "cohere") -> ReportBundle:
    # 1) Parse locale
    loc = parse_locale(question, user_answer, api_provider)
    site, city, region, country = loc.get("site",""), loc.get("city",""), loc.get("region",""), loc.get("country","")

    # 2) Plan
    queries = plan_queries(topic, site, city, region, country, api_provider)

    # 3) Iterate rounds: Search -> Read -> Evaluate -> Reflect
    all_evidence: List[Evidence] = []
    rounds: List[RoundTrace] = []
    used_urls=set()

    for rnd in range(1, MAX_ROUNDS+1):
        logging.info("=== ROUND %d ===", rnd)
        url_items = search_round(queries)
        url_items = [u for u in url_items if u["url"] not in used_urls]
        for u in url_items: used_urls.add(u["url"])

        evs = read_and_slot(url_items, start_id=len(all_evidence)+1)
        all_evidence.extend(evs)

        complete, eval_notes = evaluate(all_evidence)
        rounds.append(RoundTrace(round_id=rnd, queries=queries[:], urls_fetched=len(url_items),
                                 evidence_ids=[e.id for e in evs], reflect_notes=eval_notes))
        if complete or rnd==MAX_ROUNDS:
            break
        queries, rnotes = reflect_and_update(queries, all_evidence, site, city, api_provider)
        rounds[-1].reflect_notes += rnotes

    # 4) Decide + Write
    decision, demand = decide_strict(all_evidence, api_provider)
    js, md = synthesize(topic, site, city, region, country, all_evidence, decision, demand, api_provider)

    # Persist
    out_dir = os.path.dirname(out_prefix) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(out_prefix + ".evidence.json","w",encoding="utf-8") as f:
        json.dump([asdict(e) for e in all_evidence], f, indent=2)
    with open(out_prefix + ".rounds.json","w",encoding="utf-8") as f:
        json.dump([asdict(r) for r in rounds], f, indent=2)
    with open(out_prefix + ".report.json","w",encoding="utf-8") as f:
        f.write(js)
    with open(out_prefix + ".report.md","w",encoding="utf-8") as f:
        f.write(md)

    logging.info("[done] wrote %s.{evidence,rounds,report}.{json,md}", out_prefix)
    return ReportBundle(topic=topic, site=site, city=city, region=region, country=country,
                        rounds=rounds, evidence=all_evidence, decision=decision, demand_metrics=demand)

# ---------- CLI ----------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", required=True)
    ap.add_argument("--user_answer", required=True)
    ap.add_argument("--topic", required=True)
    ap.add_argument("--out", required=True, help="Output prefix (e.g., /tmp/run1)")
    ap.add_argument("--api_provider", default="cohere", choices=["gemini", "cohere"], 
                   help="LLM API provider to use (default: cohere)")
    args = ap.parse_args()
    run_open_research(args.question, args.user_answer, args.topic, args.out, args.api_provider)
