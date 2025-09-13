import os, re, io, json, logging, argparse
import time
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from config import (
    TAVILY_API_KEY, GEMINI_API_KEY, COHERE_API_KEY, JINA_API_KEY,
    MAX_URLS_PER_ROUND, MAX_ROUNDS, REQUIRED_SLOTS, HEADERS,
    SLOT_PATTERNS, PROHIBIT_RX, SUBJECT_RX, NEGATION_RX,
    PARSE_LOCALE_PROMPT, PLANNER_PROMPT, REFLECT_PROMPT, SYNTH_PROMPT,
    get_fallback_queries, get_site_restricted_queries
)

# ---------- Prompt utils ----------
def fill_prompt(template: str, values: Dict[str, str]) -> str:
    """Safely substitute only our placeholders like {key} without touching other braces.

    This avoids str.format KeyError when prompts contain literal JSON braces such as {"site": ...}.
    """
    out = template
    for key, val in values.items():
        out = out.replace("{" + key + "}", val)
    return out

# ---------- Optional deps ----------
try:
    import pdfplumber  # type: ignore
    HAVE_PDFPLUMBER = True
except Exception:
    HAVE_PDFPLUMBER = False

# LLM SDK availability
try:
    from google import genai as google_genai  # type: ignore
    HAVE_GEMINI = True
except Exception:
    HAVE_GEMINI = False

try:
    import cohere  # type: ignore
    HAVE_COHERE = True
except Exception:
    HAVE_COHERE = False

# Tavily SDK (optional)
try:
    from tavily import TavilyClient  # type: ignore
    HAVE_TAVILY = True
except Exception:
    HAVE_TAVILY = False

if HAVE_TAVILY and TAVILY_API_KEY:
    tavily_client = TavilyClient(api_key=TAVILY_API_KEY)
else:
    tavily_client = None

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

# ---------- Locale / authority ----------
def parse_locale(question: str, answer: str, api_provider: str = "gemini") -> Dict:
    try:
        prompt = fill_prompt(PARSE_LOCALE_PROMPT, {"question": question, "answer": answer})
        if api_provider == "gemini" and HAVE_GEMINI and GEMINI_API_KEY:
            client = google_genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            t = (getattr(resp, "text", None) or "")
        elif api_provider == "cohere" and HAVE_COHERE and COHERE_API_KEY:
            co = cohere.ClientV2(COHERE_API_KEY)
            resp = co.chat(model="command-a-03-2025", messages=[{"role":"user","content": prompt}])
            parts = getattr(getattr(resp, "message", None), "content", []) or []
            t = "\n".join([getattr(p, "text", "") for p in parts if getattr(p, "type", "text") == "text"]) or ""
        else:
            t = ""
        if t:
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
    """Search via Tavily SDK when available; fallback to HTTP."""
    if not TAVILY_API_KEY:
        logging.error("[tavily] MISSING_API_KEY: set TAVILY_API_KEY")
        return []
    # Prefer SDK
    if tavily_client is not None:
        try:
            response = tavily_client.search(query=query, search_depth="basic", max_results=max_results, include_answer=False)
            results = [
                {"url": r.get("url"), "title": r.get("title", ""), "description": r.get("description", "")}
                for r in (response.get("results", []) if isinstance(response, dict) else getattr(response, "results", []))
                if r.get("url")
            ]
            logging.info("[tavily] %d results query='%s' (SDK)", len(results), query)
            return results
        except Exception as e:
            logging.warning("[tavily] SDK error, falling back to HTTP: %s", e)
    # HTTP fallback
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

def extract_with_jina(url_data: Dict, max_retries: int = 2) -> str:
    """Retrying extractor using Jina Reader with Authorization header, fallback to Tavily metadata."""
    url = url_data["url"]
    for attempt in range(max_retries + 1):
        try:
            jina_url = f"https://r.jina.ai/{url}"
            headers = {"Authorization": f"Bearer {JINA_API_KEY}"} if JINA_API_KEY else {}
            response = requests.get(jina_url, headers=headers, timeout=30)
            response.raise_for_status()
            logging.info("[jina] Successfully extracted content from %s", url)
            return response.text[:20000]
        except Exception as e:
            logging.warning("[jina] Attempt %d/%d - Error extracting content from %s: %s", attempt + 1, max_retries + 1, url, e)
            if attempt < max_retries:
                time.sleep(2)
            else:
                fallback_content = f"Title: {url_data.get('title', 'N/A')}\nDescription: {url_data.get('description', 'N/A')}"
                logging.info("[jina] Using fallback content for %s", url)
                return fallback_content if url_data.get("title") or url_data.get("description") else ""

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

# ---------- Slot patterns imported from config.py ----------

def slot_for(text: str, title: str) -> Optional[str]:
    blob = (title + "\n" + text[:1500]).lower()
    for slot, rx in SLOT_PATTERNS.items():
        if re.search(rx, blob):
            return slot
    return None

# ---------- Plan / Search / Read / Evaluate / Reflect ----------
def plan_queries(topic: str, site: str, city: str, region: str, country: str, api_provider: str = "gemini") -> List[str]:
    try:
        prompt = fill_prompt(PLANNER_PROMPT, {"topic": topic, "site": site, "city": city, "region": region, "country": country})
        if api_provider == "gemini" and HAVE_GEMINI and GEMINI_API_KEY:
            client = google_genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            t = (getattr(resp, "text", None) or "")
        elif api_provider == "cohere" and HAVE_COHERE and COHERE_API_KEY:
            co = cohere.ClientV2(COHERE_API_KEY)
            resp = co.chat(model="command-a-03-2025", messages=[{"role":"user","content": prompt}])
            parts = getattr(getattr(resp, "message", None), "content", []) or []
            t = "\n".join([getattr(p, "text", "") for p in parts if getattr(p, "type", "text") == "text"]) or ""
        else:
            t = ""
        if t:
            queries = json.loads(t[t.find("["):t.rfind("]")+1])
            logging.info("[plan] %d queries", len(queries))
            return queries
    except Exception as e:
        logging.exception("[plan] LLM failed: %s", e)
    # fallback templates
    queries = get_fallback_queries(site, city, region)
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
            txt = extract_with_jina(item); loc="HTML (Jina)"
            title=title or (url.split("/")[2] if "/" in url else url)
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
    payload = {
        "coverage": coverage_status(evs),
        "have_slots": list({e.slot for e in evs}),
        "recent_queries": queries[-6:],
        "site": site, "city": city,
    }
    try:
        prompt = fill_prompt(REFLECT_PROMPT, {"coverage": json.dumps(payload)})
        if api_provider == "gemini" and HAVE_GEMINI and GEMINI_API_KEY:
            client = google_genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            t = (getattr(resp, "text", None) or "")
        elif api_provider == "cohere" and HAVE_COHERE and COHERE_API_KEY:
            co = cohere.ClientV2(COHERE_API_KEY)
            resp = co.chat(model="command-a-03-2025", messages=[{"role":"user","content": prompt}])
            parts = getattr(getattr(resp, "message", None), "content", []) or []
            t = "\n".join([getattr(p, "text", "") for p in parts if getattr(p, "type", "text") == "text"]) or ""
        else:
            t = ""
        if t:
            js = json.loads(t[t.find("{"):t.rfind("}")+1])
            new_q = js.get("new_queries", [])
            notes = js.get("notes", [])
            merged=list(dict.fromkeys(queries + new_q))
            logging.info("[reflect] added %d new queries; total=%d", len(new_q), len(merged))
            return merged[:12], notes
    except Exception as e:
        logging.exception("[reflect] LLM failed: %s", e)
    # fallback: add site-restricted queries for common official domains
    extras = get_site_restricted_queries(site, city)
    merged=list(dict.fromkeys(queries+extras))
    logging.warning("[reflect] fallback added %d queries; total=%d", len(extras), len(merged))
    return merged[:12], ["Added site-restricted queries (fallback)"]

# ---------- Conservative Judge ----------
def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

# ---------- Decision framework patterns imported from config.py ----------
PROHIBIT_RX = re.compile(PROHIBIT_RX, re.I)
SUBJECT_RX = re.compile(SUBJECT_RX, re.I)
NEGATION_RX = re.compile(NEGATION_RX, re.I)

def call_llm_yes_no(question: str, api_provider: str = "gemini") -> str:
    """Return 'YES' or 'NO'. If unclear or error, return 'NO' (abstain)."""
    try:
        prompt = "Answer strictly YES or NO. If unclear, answer NO.\n" + question
        if api_provider == "gemini" and HAVE_GEMINI and GEMINI_API_KEY:
            client = google_genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            ans = (getattr(resp, "text", "") or "").strip().upper()
        elif api_provider == "cohere" and HAVE_COHERE and COHERE_API_KEY:
            co = cohere.ClientV2(COHERE_API_KEY)
            resp = co.chat(model="command-a-03-2025", messages=[{"role":"user","content": prompt}])
            parts = getattr(getattr(resp, "message", None), "content", []) or []
            ans = ("\n".join([getattr(p, "text", "") for p in parts if getattr(p, "type", "text") == "text"]) or "").strip().upper()
        else:
            logging.warning("[judge] LLM unavailable -> NO (abstain)")
            return "NO"
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
    payload={"topic":topic, "site":site, "city":city, "region":region, "country":country,
             "evidence":[asdict(e) for e in evs], "decision":decision, "demand_metrics":demand}
    try:
        full_prompt = SYNTH_PROMPT+"\n\nINPUT JSON:\n"+json.dumps(payload)[:120000]
        if api_provider == "gemini" and HAVE_GEMINI and GEMINI_API_KEY:
            client = google_genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=full_prompt)
            t = (getattr(resp, "text", None) or "")
        elif api_provider == "cohere" and HAVE_COHERE and COHERE_API_KEY:
            co = cohere.ClientV2(COHERE_API_KEY)
            resp = co.chat(model="command-a-03-2025", messages=[{"role":"user","content": full_prompt}])
            parts = getattr(getattr(resp, "message", None), "content", []) or []
            t = "\n".join([getattr(p, "text", "") for p in parts if getattr(p, "type", "text") == "text"]) or ""
        else:
            t = ""
        if t:
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

    # Persist - use current directory if no directory specified
    if os.path.dirname(out_prefix):
        out_dir = os.path.dirname(out_prefix)
        os.makedirs(out_dir, exist_ok=True)
        base_name = os.path.basename(out_prefix)
    else:
        out_dir = "."
        base_name = out_prefix
    with open(os.path.join(out_dir, base_name + ".evidence.json"),"w",encoding="utf-8") as f:
        json.dump([asdict(e) for e in all_evidence], f, indent=2)
    with open(os.path.join(out_dir, base_name + ".rounds.json"),"w",encoding="utf-8") as f:
        json.dump([asdict(r) for r in rounds], f, indent=2)
    with open(os.path.join(out_dir, base_name + ".report.json"),"w",encoding="utf-8") as f:
        f.write(js)
    with open(os.path.join(out_dir, base_name + ".report.md"),"w",encoding="utf-8") as f:
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
