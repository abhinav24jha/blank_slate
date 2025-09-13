import os, re, io, json, logging
import time
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from config import (
    TAVILY_API_KEY, GEMINI_API_KEY, COHERE_API_KEY, JINA_API_KEY,
    MAX_URLS_PER_ROUND, MAX_ROUNDS,
    PARSE_LOCALE_PROMPT, HYPOTHESIS_GENERATION_PROMPT, PLANNER_PROMPT, REFLECT_PROMPT, SYNTH_PROMPT,
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
    import pdfplumber 
    HAVE_PDFPLUMBER = True
except Exception:
    HAVE_PDFPLUMBER = False

try:
    from google import genai
    client = genai.Client()
    HAVE_GEMINI = True
except Exception as e:
    HAVE_GEMINI = False
    logging.warning("[imports] Gemini import failed: %s", e)

try:
    import cohere
    co = cohere.ClientV2(COHERE_API_KEY)
    HAVE_COHERE = True
except Exception as e:
    HAVE_COHERE = False
    logging.warning("[imports] Cohere import failed: %s", e)

try:
    from tavily import TavilyClient
    HAVE_TAVILY = True
    tavily_client = TavilyClient(api_key=TAVILY_API_KEY)
except Exception:
    HAVE_TAVILY = False
    tavily_client = None

# ---------- Data Models ----------
@dataclass
class Hypothesis:
    id: str
    title: str
    description: str
    rationale: str
    category: str
    feasibility_decision: str = "PENDING"  # YES, NO, PENDING
    evidence_ids: List[str] = field(default_factory=list)
    decision_reasoning: str = ""

@dataclass
class Evidence:
    id: str
    url: str
    title: str
    locator: str
    snippet: str
    content: str

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
    hypotheses: List[Hypothesis]
    rounds: List[RoundTrace]
    evidence: List[Evidence]
    notes: List[str] = field(default_factory=list)

# ---------- Locale / authority ----------
def parse_locale(question: str, answer: str, api_provider: str = "gemini") -> Dict:
    logging.info("[locale] Starting locale parsing with provider: %s", api_provider)
    # Initialize default values
    site = answer
    city = ""
    region = ""
    country = ""
    
    try:
        prompt = fill_prompt(PARSE_LOCALE_PROMPT, {"question": question, "answer": answer})

        if api_provider == "gemini" and HAVE_GEMINI and GEMINI_API_KEY:
            response = client.models.generate_content(
                model="gemini-2.5-flash", 
                contents=prompt
            )

            text = (getattr(response, "text", None) or "")

        elif api_provider == "cohere" and HAVE_COHERE and COHERE_API_KEY:
            response = co.chat(
                model="command-a-03-2025", 
                messages=[{"role":"user","content": prompt}]
            )

            parts = getattr(getattr(response, "message", None), "content", []) or []

            text = "\n".join([getattr(p, "text", "") for p in parts if getattr(p, "type", "text") == "text"]) or ""
        else:
            text = ""

        if text:
            js = json.loads(text[text.find("{"):text.rfind("}")+1])
            site = js.get("site") or answer
            city = js.get("city") or ""
            region = js.get("region_or_state") or js.get("region") or ""
            country = js.get("country") or ""
            logging.info("[locale] site=%s, city=%s, region=%s, country=%s", site, city, region, country)

    except Exception as e:
        logging.exception("[locale] LLM parse failed: %s", e)

    return {"site": site, "city": city, "region": region, "country": country}

def generate_hypotheses(user_feedback: str, site: str, city: str, region: str, country: str, api_provider: str = "gemini") -> List[Hypothesis]:
    """Generate hypotheses for potential improvements based on user feedback."""
    try:
        prompt = fill_prompt(HYPOTHESIS_GENERATION_PROMPT, {
            "user_feedback": user_feedback,
            "site": site,
            "city": city,
            "region": region,
            "country": country
        })

        logging.info("[hypotheses] API provider: %s, HAVE_GEMINI: %s, GEMINI_API_KEY: %s", 
                    api_provider, HAVE_GEMINI, bool(GEMINI_API_KEY))

        if api_provider == "gemini" and HAVE_GEMINI and GEMINI_API_KEY:
            resp = client.models.generate_content(
                model="gemini-2.5-flash", 
                contents=prompt
            )
            t = (getattr(resp, "text", None) or "")
            logging.info("[hypotheses] Gemini response length: %d", len(t))

        elif api_provider == "cohere" and HAVE_COHERE and COHERE_API_KEY:
            resp = co.chat(
                model="command-a-03-2025", 
                messages=[{"role":"user","content": prompt}]
            )
            
            parts = getattr(getattr(resp, "message", None), "content", []) or []
            t = "\n".join([getattr(p, "text", "") for p in parts if getattr(p, "type", "text") == "text"]) or ""
            logging.info("[hypotheses] Cohere response length: %d", len(t))
        else:
            t = ""
            logging.warning("[hypotheses] No valid API provider available")
        
        if t:
            logging.info("[hypotheses] Response preview: %s", t[:200])
            js = json.loads(t[t.find("{"):t.rfind("}")+1])
            hypotheses = []
            for h_data in js.get("hypotheses", []):
                hypotheses.append(Hypothesis(
                    id=h_data.get("id", ""),
                    title=h_data.get("title", ""),
                    description=h_data.get("description", ""),
                    rationale=h_data.get("rationale", ""),
                    category=h_data.get("category", "")
                ))
            logging.info("[hypotheses] Generated %d hypotheses", len(hypotheses))
            return hypotheses
        else:
            logging.warning("[hypotheses] Empty response from API")
    except Exception as e:
        logging.exception("[hypotheses] Generation failed: %s", e)
    

    logging.warning("[hypotheses] No Hypotheses generated")
    return []


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
        r = requests.get(url, timeout=30)
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


# ---------- Plan / Search / Read / Evaluate / Reflect ----------
def plan_queries(topic: str, site: str, city: str, region: str, country: str, api_provider: str = "gemini") -> List[str]:
    try:
        prompt = fill_prompt(PLANNER_PROMPT, {"topic": topic, "site": site, "city": city, "region": region, "country": country})
        if api_provider == "gemini" and HAVE_GEMINI and GEMINI_API_KEY:
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            t = (getattr(resp, "text", None) or "")
        elif api_provider == "cohere" and HAVE_COHERE and COHERE_API_KEY:
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
    
    # fallback template s
    queries = get_fallback_queries(site, city, region)
    logging.warning("[plan] Using fallback queries (%d)", len(queries))
    return queries

def search_round(queries: List[str]) -> List[Dict]:
    """Parallel search execution for better performance."""
    all_results = []
    
    # Execute all searches in parallel
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_query = {executor.submit(tavily_search, q, 5): q for q in queries}
        for future in as_completed(future_to_query):
            query = future_to_query[future]
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as e:
                logging.warning("[search] Query '%s' failed: %s", query, e)
    
    # Limit total URLs and deduplicate
    seen = set()
    urls = []
    for r in all_results:
        if len(urls) >= MAX_URLS_PER_ROUND:
            break
        url = r.get("url")
        if url and url not in seen:
            seen.add(url)
            urls.append(r)
    
    logging.info("[search] round collected %d unique URLs from %d total results", len(urls), len(all_results))
    return urls

def collect_evidence(url_items: List[Dict], start_id: int = 1) -> List[Evidence]:
    """Collect all evidence without slotting - let LLM analyze content."""
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
        # Extract snippet for quick reference
        snippet = txt.strip()
        return Evidence(id=f"e{start_id+len(evs):03d}",url=url,title=title[:140],locator=loc,snippet=snippet,content=txt[:10000])
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(handle,u) for u in url_items]
        for fut in as_completed(futs):
            r=fut.result()
            if r: evs.append(r)
    logging.info("[read] collected %d evidence items", len(evs))
    return evs

def evaluate_evidence_completeness(evs: List[Evidence]) -> Tuple[bool, List[str]]:
    """Evaluate if we have sufficient evidence for hypothesis evaluation."""
    notes = []
    
    # Check if we have enough evidence overall
    if len(evs) < 5:
        notes.append("Insufficient evidence collected")
        return False, notes
    
    complete = len(notes) == 0
    logging.info("[eval] complete=%s notes=%s", complete, notes)
    return complete, notes

def reflect_and_update(queries: List[str], evs: List[Evidence], site: str, city: str, api_provider: str = "gemini") -> Tuple[List[str], List[str]]:
    payload = {
        "evidence_count": len(evs),
        "evidence_types": [e.locator for e in evs],
        "recent_queries": queries[-6:],
        "site": site, "city": city,
        "urls_found": [e.url for e in evs[:10]]  # Sample of URLs
    }
    try:
        prompt = fill_prompt(REFLECT_PROMPT, {"coverage": json.dumps(payload)})
        if api_provider == "gemini" and HAVE_GEMINI and GEMINI_API_KEY:
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            t = (getattr(resp, "text", None) or "")
        elif api_provider == "cohere" and HAVE_COHERE and COHERE_API_KEY:
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


# ---------- Synthesis ----------
def synthesize(topic, site, city, region, country, evs: List[Evidence], hypotheses: List[Dict], demand: Dict, api_provider: str = "gemini") -> Tuple[str,str]:
    payload={"topic":topic, "site":site, "city":city, "region":region, "country":country,
             "evidence":[asdict(e) for e in evs], "hypotheses":hypotheses, "demand_metrics":demand}
    try:
        full_prompt = SYNTH_PROMPT+"\n\nINPUT JSON:\n"+json.dumps(payload)[:120000]
        if api_provider == "gemini" and HAVE_GEMINI and GEMINI_API_KEY:
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=full_prompt)
            t = (getattr(resp, "text", None) or "")
        elif api_provider == "cohere" and HAVE_COHERE and COHERE_API_KEY:
            resp = co.chat(model="command-a-03-2025", messages=[{"role":"user","content": full_prompt}])
            parts = getattr(getattr(resp, "message", None), "content", []) or []
            t = "\n".join([getattr(p, "text", "") for p in parts if getattr(p, "type", "text") == "text"]) or ""
        else:
            t = ""
        if t:
            # Extract JSON
            jstart=t.find("{"); jend=t.rfind("}")+1
            js=t[jstart:jend] if jstart!=-1 else "{}"
            
            # Extract markdown - simple approach, just get everything after JSON
            md = t[jend:].strip()
            
            logging.info("[synth] Generated JSON length: %d chars, Markdown length: %d chars", len(js), len(md))
            return js, md
    except Exception as e:
        logging.exception("[synth] ERROR: %s", e)
    logging.warning("[synth] LLM unavailable -> fallback brief")
    return json.dumps({"hypotheses":hypotheses,"demand_metrics":demand},indent=2), "# Brief unavailable"

def evaluate_hypothesis_feasibility(hypothesis: Hypothesis, evidence: List[Evidence], api_provider: str = "gemini") -> Tuple[str, str]:
    """Evaluate a single hypothesis and return YES/NO decision with reasoning."""
    try:
        # Create context from relevant evidence
        evidence_context = "\n\n".join([f"[{e.id}] {e.title}: {e.snippet}" for e in evidence[:15]])
        
        prompt = f"""
## TASK
Evaluate if a specific development proposal can be implemented through normal approval processes, or if there are absolute prohibitions that make it impossible.

## HYPOTHESIS TO EVALUATE
Title: {hypothesis.title}
Description: {hypothesis.description}
Rationale: {hypothesis.rationale}
Category: {hypothesis.category}

## COLLECTED EVIDENCE
{evidence_context}

## DECISION FRAMEWORK
Answer YES unless you find EXPLICIT, SITE-SPECIFIC PROHIBITIONS that make the development impossible.

### ANSWER NO ONLY IF YOU FIND:

**ABSOLUTE PROHIBITIONS AT THIS EXACT LOCATION:**
- Title/deed restrictions stating "no commercial development" or "no construction"
- Court orders specifically prohibiting development at this address
- Conservation authority stating "development is prohibited" for this specific parcel
- Utility company official statement: "service cannot be provided" to this location
- Municipal zoning stating this use is "prohibited" (not just requiring approval)

### ANSWER YES FOR EVERYTHING ELSE INCLUDING:
- Need for zoning amendments, variances, or site plan approval (normal process)
- Environmental studies and permits required (normal process) 
- Heritage permits needed (normal process)
- Utility upgrades or connection agreements needed (normal process)
- General policy discussions without site-specific prohibitions
- Requirements for traffic studies, parking plans, etc. (normal process)

### IMPORTANT NOTES:
- IGNORE general regulatory information unless it specifically prohibits this exact location
- IGNORE requirements for approvals, permits, or studies - these are normal processes
- ONLY reject if evidence shows this specific development is explicitly impossible/prohibited
- When in doubt, answer YES (feasible through approval process)

## OUTPUT FORMAT
You MUST return ONLY valid JSON in this exact format (no markdown, no extra text):
{{"decision": "YES" or "NO", "reasoning": "brief explanation focusing on any prohibitions found or confirming feasibility", "evidence_cited": ["e001", "e002"]}}

CRITICAL: Return ONLY the JSON object, no markdown formatting like **Decision:** or ```json blocks.
"""
        
        if api_provider == "gemini" and HAVE_GEMINI and GEMINI_API_KEY:
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            t = (getattr(resp, "text", None) or "")
        elif api_provider == "cohere" and HAVE_COHERE and COHERE_API_KEY:
            resp = co.chat(model="command-a-03-2025", messages=[{"role":"user","content": prompt}])
            parts = getattr(getattr(resp, "message", None), "content", []) or []
            t = "\n".join([getattr(p, "text", "") for p in parts if getattr(p, "type", "text") == "text"]) or ""
        else:
            t = ""
        
        if t:
            try:
                # Try to find JSON in the response first
                json_start = t.find("{")
                json_end = t.rfind("}") + 1
                if json_start != -1 and json_end > 0:
                    json_str = t[json_start:json_end]
                    js = json.loads(json_str)
                    decision = js.get("decision", "NO")
                    reasoning = js.get("reasoning", "Insufficient evidence")
                    evidence_cited = js.get("evidence_cited", [])
                    
                    logging.info("[hypothesis] %s: %s", decision, hypothesis.title)
                    return decision, reasoning
                else:
                    # Fallback: Parse markdown-style format
                    logging.info("[hypothesis] No JSON found, trying markdown parsing")
                    
                    # Extract decision from **Decision:** YES/NO format
                    decision_match = re.search(r'\*\*Decision:\*\*\s*(YES|NO)', t, re.IGNORECASE)
                    decision = decision_match.group(1).upper() if decision_match else "NO"
                    
                    # Extract reasoning from **Reasoning:** format
                    reasoning_match = re.search(r'\*\*Reasoning:\*\*\s*(.+?)(?=\n\n|\*\*|$)', t, re.DOTALL)
                    reasoning = reasoning_match.group(1).strip() if reasoning_match else "No reasoning provided"
                    
                    logging.info("[hypothesis] %s: %s (parsed from markdown)", decision, hypothesis.title)
                    return decision, reasoning
                    
            except json.JSONDecodeError as e:
                logging.warning("[hypothesis] JSON parse error: %s. Response: %s", e, t[:200])
                # Try markdown parsing as fallback
                decision_match = re.search(r'\*\*Decision:\*\*\s*(YES|NO)', t, re.IGNORECASE)
                decision = decision_match.group(1).upper() if decision_match else "NO"
                reasoning = f"JSON parse failed, extracted decision: {decision}"
                return decision, reasoning
            
    except Exception as e:
        logging.exception("[hypothesis] Evaluation failed: %s", e)
    
    # Fallback: conservative NO
    return "NO", "Evaluation failed - insufficient evidence"

# ---------- Orchestrator ----------
def run_open_research(question: str, user_answer: str, topic: str, out_prefix: str, api_provider: str = "cohere") -> ReportBundle:
    logging.info("[research] Starting open research...")
    
    # 1) Parse locale
    logging.info("[research] Step 1: Parsing locale...")
    loc = parse_locale(question, user_answer, api_provider)
    site, city, region, country = loc.get("site",""), loc.get("city",""), loc.get("region",""), loc.get("country","")
    logging.info("[research] Locale parsed: site=%s, city=%s, region=%s, country=%s", site, city, region, country)

    # 2) Generate hypotheses and plan queries in parallel
    logging.info("[research] Step 2: Generating hypotheses and planning queries in parallel...")
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        # Submit both tasks in parallel since they only depend on locale
        hypotheses_future = executor.submit(generate_hypotheses, user_answer, site, city, region, country, api_provider)
        queries_future = executor.submit(plan_queries, topic, site, city, region, country, api_provider)
        
        # Get results
        hypotheses = hypotheses_future.result()
        queries = queries_future.result()
    
    logging.info("[research] Parallel setup complete: %d hypotheses, %d queries", len(hypotheses), len(queries))

    # 4) Iterate rounds: Search -> Collect -> Evaluate -> Reflect
    all_evidence: List[Evidence] = []
    rounds: List[RoundTrace] = []
    used_urls=set()

    for rnd in range(1, MAX_ROUNDS+1):
        logging.info("=== ROUND %d ===", rnd)
        url_items = search_round(queries)
        url_items = [u for u in url_items if u["url"] not in used_urls]
        for u in url_items: used_urls.add(u["url"])

        evs = collect_evidence(url_items, start_id=len(all_evidence)+1)
        all_evidence.extend(evs)

        complete, eval_notes = evaluate_evidence_completeness(all_evidence)
        rounds.append(RoundTrace(round_id=rnd, queries=queries[:], urls_fetched=len(url_items),
                                 evidence_ids=[e.id for e in evs], reflect_notes=eval_notes))
        if complete or rnd==MAX_ROUNDS:
            break
        queries, rnotes = reflect_and_update(queries, all_evidence, site, city, api_provider)
        rounds[-1].reflect_notes += rnotes

    # 5) Evaluate each hypothesis in parallel
    logging.info("[hypotheses] Evaluating %d hypotheses in parallel", len(hypotheses))
    
    def evaluate_single_hypothesis(hypothesis):
        decision, reasoning = evaluate_hypothesis_feasibility(hypothesis, all_evidence, api_provider)
        hypothesis.feasibility_decision = decision
        hypothesis.decision_reasoning = reasoning
        logging.info("[hypothesis] %s: %s - %s", decision, hypothesis.title, reasoning[:100])
        return hypothesis
    
    # Execute hypothesis evaluations in parallel
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_hyp = {executor.submit(evaluate_single_hypothesis, h): h for h in hypotheses}
        for future in as_completed(future_to_hyp):
            try:
                future.result()  # This updates the hypothesis in place
            except Exception as e:
                hyp = future_to_hyp[future]
                logging.error("[hypothesis] Evaluation failed for '%s': %s", hyp.title, e)
                hyp.feasibility_decision = "NO"
                hyp.decision_reasoning = f"Evaluation error: {str(e)}"

    # 6) Generate final report
    js, md = synthesize(topic, site, city, region, country, all_evidence, [asdict(h) for h in hypotheses], {}, api_provider)

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
                        hypotheses=hypotheses, rounds=rounds, evidence=all_evidence)

# ---------- Main ----------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    
    # Set your variables here
    question = "What area needs improvement and what problems do you see?"
    user_answer = "The area around society145 in Waterloo, Ontario has nothing but parking lots in front of the building. People have to walk really far to get basic services like groceries. The space is underutilized and the community lacks local amenities."
    topic = "community amenity development"
    out_prefix = "society145_test"
    api_provider = "gemini"  
    
    logging.info("Starting research pipeline...")
    run_open_research(question, user_answer, topic, out_prefix, api_provider)
