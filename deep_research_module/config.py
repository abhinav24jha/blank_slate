"""
Configuration file for Deep Research Pipeline

Contains all prompts, environment variables, and configuration constants
for the municipal planning feasibility research system.
"""

import os
from typing import Dict, List

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("[config] Loaded environment variables from .env file")
except ImportError:
    print("[config] python-dotenv not installed, using system environment variables")

# ---------- Environment Variables ----------
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")
JINA_API_KEY = os.getenv("JINA_API_KEY", "")

# ---------- Configuration Constants ----------
MAX_URLS_PER_ROUND = 30
MAX_ROUNDS = 3
REQUIRED_SLOTS = ["environment", "utilities", "zoning_landuse"]
HEADERS = {"User-Agent": "DeepResearch"}

# ---------- Slot Pattern Matching ----------
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

# ---------- Decision Framework Regex Patterns ----------
PROHIBIT_RX = r"\b(prohibited|not permitted|shall not|connection (?:not )?feasible|denied)\b"
SUBJECT_RX = r"\b(development|building|structure|connection|service)\b"
NEGATION_RX = r"\b(not\s+prohibit(?:ed)?|unless|except|subject to permit)\b"

# ---------- LLM Prompts ----------

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

# ---------- Fallback Query Templates ----------
def get_fallback_queries(site: str, city: str, region: str) -> List[str]:
    """Generate fallback queries when LLM is unavailable."""
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
    return queries

# ---------- Fallback Site-Restricted Queries ----------
def get_site_restricted_queries(site: str, city: str) -> List[str]:
    """Generate site-restricted fallback queries when LLM is unavailable."""
    if not city:
        return []
    
    extras = [
        f'site:{city.lower()}.ca "permitted uses" {site}',
        f"site:{city.lower()}.ca floodway {site}",
        f"site:{city.lower()}.gov zoning {site}"
    ]
    return extras
