import React, { useEffect, useRef, useState } from "react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { CardContent, CardFooter } from "@/components/ui/card";
import { cohereChat, type ChatTurn } from "@/lib/cohere";
import { fetchReport } from "@/lib/report";
import MarkdownBubble from "./MarkdownBubble";
import { BarChart3, Map } from "lucide-react";

function Bubble({ role, children }: { role: "user" | "assistant"; children: React.ReactNode }) {
  const isUser = role === "user";
  return (
    <div className={`flex items-start gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm leading-relaxed border ${
          isUser ? "bg-emerald-500 text-black border-emerald-500/60" : "bg-white/5 border-white/10 text-neutral-100"
        }`}
      >
        {children}
      </div>
    </div>
  );
}

export default function CohereChat({
  space,
  preface,
  reportPrefix,
  analyticsData,
  showAnalyzeButton = true,
  onGoToMap,
}: {
  space: string | null;
  /** Optional content (e.g., markdown report) shown as the very first assistant bubble */
  preface?: React.ReactNode;
  /** Optional prefix for fetching the report */
  reportPrefix?: string;
  /** Optional analytics data to include in chat context */
  analyticsData?: any;
  /** Whether to show the "Analyze our data" button */
  showAnalyzeButton?: boolean;
  /** Optional function to handle "Go to Map" button click */
  onGoToMap?: () => void;
}) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [reportContent, setReportContent] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(true);
  const [reportExpanded, setReportExpanded] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [showReportModal, setShowReportModal] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const inputAreaRef = useRef<HTMLDivElement>(null);
  const [inputAreaHeight, setInputAreaHeight] = useState(0);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, preface]);

  // Measure input area height and update padding
  useEffect(() => {
    const updateInputHeight = () => {
      if (inputAreaRef.current) {
        const height = inputAreaRef.current.offsetHeight;
        setInputAreaHeight(height + 100); // Add more extra padding for better spacing
      }
    };

    // Use setTimeout to ensure DOM is fully rendered
    const timeoutId = setTimeout(updateInputHeight, 0);
    
    // Also update when input changes
    updateInputHeight();
    
    // Use ResizeObserver for more reliable height tracking
    let resizeObserver: ResizeObserver | null = null;
    if (inputAreaRef.current) {
      resizeObserver = new ResizeObserver(updateInputHeight);
      resizeObserver.observe(inputAreaRef.current);
    }
    
    return () => {
      clearTimeout(timeoutId);
      if (resizeObserver) {
        resizeObserver.disconnect();
      }
    };
  }, [input]);

  // Always fetch the markdown report
  useEffect(() => {
    const loadReport = async () => {
      setReportLoading(true);
      try {
        const result = await fetchReport(reportPrefix);
        if (result.success && result.content) {
          setReportContent(result.content);
        } else {
          console.error("Failed to load report:", result.error);
        }
      } catch (error) {
        console.error("Error loading report:", error);
      } finally {
        setReportLoading(false);
      }
    };

    loadReport();
  }, [reportPrefix]);

  const getReportPreview = (content: string) => {
    // Extract the first few lines for preview
    const lines = content.split('\n');
    const previewLines = lines.slice(0, 8); // First 8 lines
    return previewLines.join('\n') + (lines.length > 8 ? '\n...' : '');
  };

  const startActualChat = async () => {
    if (initialized) return;
    setInitialized(true);
    setLoading(true);
    try {
      // Create a comprehensive context message with the research report and analytics data
      const analyticsContext = analyticsData ? `

Here is the analytics data for this space:

${JSON.stringify(analyticsData, null, 2)}

This analytics data shows performance metrics across 4 different environments (Env 1, Env 2, Env 3, Env 4) for:
- Efficiency metrics
- Cost reduction metrics  
- Time saved metrics
- Overall performance scores

You can help analyze trends, compare environments, and provide insights based on this data.` : '';

      const contextMessage = `You are an efficiency optimization assistant helping with the space: "${space}". 

Here is the research report for this space:

${reportContent || "No research report available"}${analyticsContext}

Based on this research and analytics data, I need your help to optimize and make the ${space} more efficient. You should be able to answer questions about feasibility, constraints, regulatory requirements, environmental considerations, utility infrastructure, timelines, costs, risk mitigation strategies, and analytics insights.

Please provide concise, helpful responses based on the research findings and analytics data. What specific aspects of optimizing the ${space} would you like to focus on first?`;
      
      const reply = await cohereChat([{ role: "user", content: contextMessage }]);
      setTurns([{ role: "assistant", content: reply }]);
    } catch (e: any) {
      setTurns([{ role: "assistant", content: `⚠️ Cohere error: ${e?.message || "unknown error"}` }]);
    } finally {
      setLoading(false);
    }
  };


  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    const next = [...turns, { role: "user" as const, content: text }];
    setTurns(next);
    setLoading(true);
    try {
      // Create context message with the research report and analytics data for every request
      const analyticsContext = analyticsData ? `

Here is the analytics data for this space:

${JSON.stringify(analyticsData, null, 2)}

This analytics data shows performance metrics across 4 different environments (Env 1, Env 2, Env 3, Env 4) for:
- Efficiency metrics
- Cost reduction metrics  
- Time saved metrics
- Overall performance scores

You can help analyze trends, compare environments, and provide insights based on this data.` : '';

      const contextMessage = `You are an efficiency optimization assistant helping with the space: "${space}". 

Here is the research report for this space:

${reportContent || "No research report available"}${analyticsContext}

Based on this research and analytics data, provide helpful responses about optimizing and making the ${space} more efficient. You should be able to answer questions about feasibility, constraints, regulatory requirements, environmental considerations, utility infrastructure, timelines, costs, risk mitigation strategies, and analytics insights.

Current conversation:
${next.map(turn => `${turn.role}: ${turn.content}`).join('\n')}

Please provide a concise, helpful response based on the research findings and analytics data.`;
      
      const reply = await cohereChat([{ role: "user", content: contextMessage }]);
      setTurns([...next, { role: "assistant" as const, content: reply }]);
    } catch (e: any) {
      setTurns([...next, { role: "assistant" as const, content: `⚠️ Cohere error: ${e?.message || "unknown error"}` }]);
    } finally {
      setLoading(false);
    }
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="relative h-full">
      {/* Chat Messages Area - Takes full height with dynamic bottom padding for input */}
      <CardContent 
        className="h-full pt-4" 
        style={{ paddingBottom: `${inputAreaHeight}px` }}
      >
        <ScrollArea className="h-full">
          <div ref={listRef} className="pr-2 space-y-3 pb-4">
            {preface && <Bubble role="assistant">{preface}</Bubble>}
            
            {/* UI Question/Answer (not sent to Cohere) */}
            <Bubble role="assistant">
              Which space are we making efficient today?
            </Bubble>
            <Bubble role="user">
              {space ?? "Untitled space"}
            </Bubble>
            
            {/* Research Report */}
            {reportContent && (
              <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-lg font-semibold text-emerald-400">Research Report</h3>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setShowReportModal(true)}
                    className="text-xs text-neutral-400 hover:text-neutral-200"
                  >
                    View Full Report
                  </Button>
                </div>
                <div className="text-sm">
                  <MarkdownBubble markdown={getReportPreview(reportContent)} />
                </div>
              </div>
            )}
            
            {/* Actual Chat turns (after report) */}
            {turns.map((t, i) => (
              <Bubble key={i} role={t.role}>
                {t.role === "assistant" ? (
                  <MarkdownBubble markdown={t.content} />
                ) : (
                  t.content
                )}
              </Bubble>
            ))}
            
            {loading && <div className="text-xs text-neutral-500 px-1">Cohere is thinking…</div>}
          </div>
        </ScrollArea>
      </CardContent>

      {/* Input Area - Absolutely positioned at bottom with proper spacing */}
      <div 
        ref={inputAreaRef}
        className="absolute bottom-24 left-3 right-3 bg-black/40 backdrop-blur border border-white/10 rounded-lg p-3"
      >
        <div className="w-full space-y-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKey}
            placeholder="Chat with Cohere… (Shift+Enter for newline)"
            className="min-h-[64px] max-h-[120px] bg-white/5 border-white/10 placeholder:text-neutral-500 resize-none"
          />
          <div className="flex items-center gap-2 justify-between">
            <div className="flex items-center gap-2">
              {onGoToMap && (
                <Button
                  variant="secondary"
                  className="bg-emerald-500/20 border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/30"
                  onClick={onGoToMap}
                >
                  <Map className="h-4 w-4 mr-2" />
                  Go to Map
                </Button>
              )}
              {showAnalyzeButton && (
                <Button
                  variant="secondary"
                  className="bg-blue-500/20 border-blue-500/30 text-blue-300 hover:bg-blue-500/30"
                  onClick={() => {
                    // This will be handled by the parent component
                    window.dispatchEvent(new CustomEvent('analyzeData'));
                  }}
                >
                  <BarChart3 className="h-4 w-4 mr-2" />
                  Analyze our data
                </Button>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                className="bg-white/10 border-white/10"
                onClick={() => setInput("")}
                disabled={loading}
              >
                Clear
              </Button>
              <Button className="bg-emerald-500 text-black hover:brightness-110" onClick={send} disabled={loading}>
                {loading ? "Sending…" : "Send"}
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Report Modal/Popup */}
      {showReportModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-neutral-900 border border-white/10 rounded-lg w-full max-w-4xl h-[90vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-white/10 flex-shrink-0">
              <h2 className="text-lg font-semibold text-emerald-400">Research Report</h2>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowReportModal(false)}
                className="text-neutral-400 hover:text-neutral-200"
              >
                ✕
              </Button>
            </div>
            <ScrollArea className="flex-1 p-6">
              <div className="w-full min-w-0">
                {reportContent && <MarkdownBubble markdown={reportContent} />}
              </div>
            </ScrollArea>
          </div>
        </div>
      )}
    </div>
  );
}
