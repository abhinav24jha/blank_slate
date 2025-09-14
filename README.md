# Blank Slate 🏙️

![Build](https://img.shields.io/badge/build-passing-brightgreen)
![Python](https://img.shields.io/badge/python-3.10+-yellow)
![React](https://img.shields.io/badge/frontend-React-blue)
![Contributions](https://img.shields.io/badge/contributions-welcome-orange)

*Blank Slate* is an AI-powered *Urban Planning & Community Development Research Platform*.  
It reimagines underused spaces by combining *automated legal research* with *agent-based simulation*, producing quantified, data-backed development proposals.

---

## 🚀 Elevator Pitch

Instead of guessing what to build in empty lots, parking spaces, or neglected community corners, Blank Slate runs research and simulations for you.  

You describe the location and your idea (e.g., "add a grocery store in this parking lot"), and Blank Slate will:  
1. Research municipal rules, zoning laws, and regulations  
2. Generate multiple development hypotheses  
3. Simulate human behavior in the new environment  
4. Produce a *quantified impact report* with metrics like reduced travel time, cost savings, and community benefits  

---

## ✨ Features

- 🔎 *Research Feasibility* – scans zoning laws, municipal documents, and environmental constraints  
- 🧠 *Generate Hypotheses* – AI proposes realistic development options (e.g., gym, cafe, housing)  
- 👥 *Simulate Human Behavior* – agent-based modeling of students, workers, and residents  
- 📊 *Measure Impact* – metrics like travel time reduction, local spending, and efficiency  
- 📑 *Comprehensive Reports* – outputs markdown with feasibility decisions and evidence citations  
- 🌐 *Interactive Dashboards* – visualize simulations and before/after comparisons  

---

## ⚙️ Tech Stack

- *Backend:* Python (Flask, Pydantic, NumPy)  
- *Frontend:* React (Vite, Tailwind, shadcn/ui), PIXI.js for visualization  
- *AI Providers:* Cohere, Gemini, Ollama (configurable via environment variables)  
- *APIs:* Tavily (search), Jina Reader (content extraction)  
- *Data Flow:* Input → Research → Hypotheses → Simulation → Metrics → Markdown Report  

---

## 🛠️ Setup & Installation

### 1. Clone the repository
```bash
git clone https://github.com/abhinav24jha/blank_slate.git
cd blank_slate


2. Backend Setup

cd backend
python3 -m venv venv
source venv/bin/activate 
pip install -r requirements.txt


3. Environemnt Variables

export COHERE_API_KEY=your_key_here
export DATA_DIR=./data
flask run --port 5000
```

4. Frontend 
```bash
cd frontend
npm run dev
```
