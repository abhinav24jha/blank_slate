# Backend Setup

## Installation

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment variables:**
   Create a `.env` file in the backend directory with the following variables:
   ```env
   COHERE_API_KEY=your_cohere_api_key_here
   TAVILY_API_KEY=your_tavily_api_key_here
   GEMINI_API_KEY=your_gemini_api_key_here
   JINA_API_KEY=your_jina_api_key_here
   DATA_DIR=./data
   PORT=5002
   ```

3. **Run the server:**
   ```bash
   python server.py
   ```

## API Endpoints

- `GET /api/health` - Health check
- `POST /api/research/start` - Start research pipeline
- `GET /api/research/status` - Check research status
- `GET /api/report` - Get research report
- `GET /api/analytics/data` - Get analytics data
- `POST /api/cohere/chat` - Chat with Cohere AI

## Dependencies

See `requirements.txt` for the complete list of Python packages required.

## Environment Variables

- `COHERE_API_KEY` - Required for AI chat functionality
- `TAVILY_API_KEY` - Required for web search
- `GEMINI_API_KEY` - Required for AI research pipeline
- `JINA_API_KEY` - Optional, for web content extraction
- `DATA_DIR` - Directory for storing reports and data (default: ./data)
- `PORT` - Server port (default: 5002)
