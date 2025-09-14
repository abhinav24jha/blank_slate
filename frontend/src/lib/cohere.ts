// src/lib/cohere.ts
export type ChatTurn = { role: "user" | "assistant"; content: string };

export async function cohereChat(turns: ChatTurn[]) {
  const r = await fetch("http://localhost:5002/api/cohere/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages: turns }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err?.error || `HTTP ${r.status}`);
  }
  const j = await r.json();
  return j.text as string;
}

