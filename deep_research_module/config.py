
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

# ---------- LLM Prompts ----------

PARSE_LOCALE_PROMPT = """
## ROLE
You are a geographic information extraction specialist for land-use research systems.

## TASK
Extract structured location data from user responses about specific sites, buildings, or areas.

## INPUT
Question: {question}
User Response: {answer}

## EXTRACTION REQUIREMENTS
Extract the following fields with high accuracy:
- site: Specific property address, building name, or location identifier (keep building names like "society145" as-is)
- city: Municipal jurisdiction name
- region_or_state: Province, state, or equivalent administrative division  
- country: Country name (full name or ISO-3 code)

## SPECIAL HANDLING FOR BUILDING NAMES
If the user mentions a building name (like "society145", "tower abc", etc.):
- Keep the building name as the site identifier
- Extract the city/region/country from context
- Do not try to convert building names to street addresses

## OUTPUT FORMAT
Return ONLY valid JSON with the exact keys specified above. No additional text or explanation.

## EXAMPLES
Input: "Let's look at 123 Main Street in Toronto, Ontario"
Output: {"site": "123 Main Street", "city": "Toronto", "region_or_state": "Ontario", "country": "Canada"}

Input: "Let's modify the space surrounding society145 in waterloo, ontario"
Output: {"site": "society145", "city": "Waterloo", "region_or_state": "Ontario", "country": "Canada"}

Input: "The area around tower blue in downtown Vancouver, BC needs improvement"
Output: {"site": "tower blue", "city": "Vancouver", "region_or_state": "British Columbia", "country": "Canada"}

## CRITICAL REQUIREMENTS
- Preserve building names exactly as mentioned by the user
- Extract city/region/country with proper capitalization
- If information is missing, use empty string ""
- Ensure JSON is valid and parseable  
- Return only the JSON object, no markdown formatting
"""

HYPOTHESIS_GENERATION_PROMPT = """
## ROLE
You are an urban planning consultant specializing in community development and optimizing underutilized spaces.

## TASK
Generate specific, actionable development hypotheses for improving underutilized areas around residential buildings based on user feedback about missing amenities and accessibility issues.

## INPUT
User Feedback: {user_feedback}
Site: {site}
City: {city}
Region: {region}
Country: {country}

## ANALYSIS FRAMEWORK
The user has identified an area with:
- Empty/underutilized space (parking lots, vacant land, unused ground floors)
- Lack of nearby amenities requiring long walks to access basic services
- Potential for community improvements

## HYPOTHESIS CATEGORIES
Generate 4-5 specific development proposals from these categories:

**COMMERCIAL AMENITIES**
- Convenience stores, grocery stores, pharmacies
- Cafes, restaurants, food courts
- Banking services, postal services

**COMMUNITY FACILITIES**
- Community centers, clubhouses, recreation facilities
- Libraries, study spaces, co-working areas
- Fitness centers, sports facilities

**PUBLIC SPACES**
- Parks, gardens, outdoor seating areas
- Playgrounds, sports courts, walking paths
- Market squares, event spaces

**MIXED-USE DEVELOPMENTS**
- Ground floor retail with community space above
- Food halls with outdoor dining
- Multi-purpose buildings with flexible programming

## OUTPUT FORMAT
Return ONLY valid JSON with this structure:
{
  "hypotheses": [
    {
      "id": "h001",
      "title": "Brief descriptive title (e.g., 'Add convenience store')",
      "description": "Specific development proposal with location details",
      "rationale": "How this addresses the identified accessibility/amenity gap",
      "category": "commercial|community|public_space|mixed_use"
    }
  ]
}

## EXAMPLE
Input: "society145 area has nothing but parking lots, people have to walk far to get basic services"
Output: {
  "hypotheses": [
    {
      "id": "h001",
      "title": "Develop convenience store and cafe",
      "description": "Convert part of the parking area to a small commercial building with convenience store, pharmacy, and cafe to serve the residential community",
      "rationale": "Eliminates long walks for daily necessities and provides local gathering space",
      "category": "commercial"
    },
    {
      "id": "h002",
      "title": "Build community clubhouse",
      "description": "Construct a multi-purpose community center with meeting rooms, recreational facilities, and event space on underutilized land",
      "rationale": "Creates social hub and eliminates need to travel for community activities",
      "category": "community"
    },
    {
      "id": "h003",
      "title": "Create neighborhood market square",
      "description": "Transform parking area into a pedestrian-friendly market square with food vendors, outdoor seating, and small retail kiosks",
      "rationale": "Provides food access and social space while maintaining some parking on periphery",
      "category": "public_space"
    },
    {
      "id": "h004",
      "title": "Develop mixed-use food hall",
      "description": "Build a food hall with multiple vendors on ground floor and community meeting spaces above, replacing portion of parking lot",
      "rationale": "Addresses food access while creating community gathering space and supporting local food entrepreneurs",
      "category": "mixed_use"
    }
  ]
}

## CRITICAL REQUIREMENTS
- Focus on ACTUAL DEVELOPMENT proposals, not regulatory analysis
- Address the specific amenity/accessibility gaps mentioned
- Propose realistic improvements for underutilized spaces
- Generate 4-5 actionable hypotheses
- Return only valid JSON, no additional text
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
- "site:waterloo.ca zoning by-law permitted uses commercial development"
- "{city} floodplain map conservation authority PDF"
- "{city} wastewater capacity study commercial development connection"
- "{city} council minutes variance approval commercial development"
- "{city} {region} official plan commercial development policies"
- "{city} building permits commercial construction requirements"

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

### EXECUTIVE SUMMARY
Professional brief that MUST include:

**1. Hypothesis Evaluation Results**
- Clear summary of each hypothesis evaluated with YES/NO decision and reasoning
- Specific feasibility determination for each proposed change/improvement

**2. Overall Assessment**
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
