// src/lib/report.ts
export async function fetchReport(prefix?: string): Promise<{ success: boolean; content?: string; error?: string }> {
  try {
    // First try to get the specific report with prefix
    if (prefix) {
      const url = `http://localhost:5002/api/report?prefix=${encodeURIComponent(prefix)}`;
      const response = await fetch(url);
      const data = await response.json();
      
      if (data.exists && data.markdown) {
        return { success: true, content: data.markdown };
      }
    }
    
    // If no specific report found, try to get any existing report
    const fallbackUrl = "http://localhost:5002/api/report";
    const fallbackResponse = await fetch(fallbackUrl);
    const fallbackData = await fallbackResponse.json();
    
    if (fallbackData.exists && fallbackData.markdown) {
      return { success: true, content: fallbackData.markdown };
    } else {
      return { success: false, error: fallbackData.error || "No report found" };
    }
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : "Unknown error" };
  }
}