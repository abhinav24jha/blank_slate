// lib/research.ts
export interface StartResearchRequest {
  space: string;
  userInput: string;
  runPipeline: boolean;
}

export interface StartResearchResponse {
  success: boolean;
  message: string;
  prefix: string;
  error?: string;
}

export async function startResearch(request: StartResearchRequest): Promise<StartResearchResponse> {
  try {
    const response = await fetch('/api/research/start', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    // Check if response is ok before trying to parse JSON
    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
      try {
        const errorData = await response.json();
        errorMessage = errorData.error || errorMessage;
      } catch {
        // If we can't parse the error response, use the status text
      }
      
      return {
        success: false,
        message: 'Failed to start research',
        prefix: '',
        error: errorMessage
      };
    }

    // Try to parse JSON response
    let data;
    try {
      data = await response.json();
    } catch (jsonError) {
      return {
        success: false,
        message: 'Invalid response from server',
        prefix: '',
        error: 'Server returned non-JSON response'
      };
    }

    return data;
  } catch (error) {
    return {
      success: false,
      message: 'Network error',
      prefix: '',
      error: error instanceof Error ? error.message : 'Unknown error'
    };
  }
}
