// src/lib/stream.ts
export type StreamEvent =
  | { type: "prompt"; text: string }
  | { type: "searched"; query: string; results: number }
  | { type: "thinking-summary"; title: string; bullets?: string[] }
  | { type: "round"; round_id: number; queries: string[]; chips: string[] }
  | { type: "progress"; value: number; status?: string };

const API = import.meta.env.VITE_API_URL ?? "http://localhost:5001";

export function streamResearch(
  objective: string,
  opts: { prefix?: string; onEvent: (e: StreamEvent) => void; onError?: (error: Event) => void }
) {
  const url = new URL(`${API}/api/research/stream`);
  url.searchParams.set("objective", objective);
  if (opts.prefix) url.searchParams.set("prefix", opts.prefix);

  console.log(`🔗 Connecting to SSE: ${url.toString()}`);
  const es = new EventSource(url.toString());

  es.onopen = () => {
    console.log("✅ SSE connection opened");
  };

  es.onmessage = (evt) => {
    if (!evt.data) return;
    try {
      const payload = JSON.parse(evt.data);
      console.log("📨 SSE message:", payload);
      opts.onEvent(payload);
    } catch (err) {
      console.warn("❌ Bad SSE payload:", evt.data, err);
    }
  };

  es.onerror = (err) => {
    console.error("❌ SSE error:", err);
    console.error("❌ EventSource readyState:", es.readyState);
    console.error("❌ EventSource URL:", es.url);
    console.error("❌ API URL:", API);
    
    // Call the error callback if provided
    opts.onError?.(err);
    
    // Don't close immediately, let it retry
    setTimeout(() => {
      if (es.readyState === EventSource.CLOSED) {
        console.log("🔄 SSE connection closed, will retry automatically");
        // Auto-retry the connection after a delay
        setTimeout(() => {
          console.log("🔄 Attempting to reconnect SSE...");
          // The streamResearch function will be called again by the LoadingSequence
        }, 2000);
      }
    }, 1000);
  };

  return () => {
    console.log("🔌 Closing SSE connection");
    es.close();
  };
}
