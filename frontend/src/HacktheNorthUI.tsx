import React, { useEffect, useRef, useState } from "react";
import { Card, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { MessageSquare, ChevronRight, Settings } from "lucide-react";

import StartScreen from "./StartScreen";
import LoadingSequence from "./LoadingSequence2";
import CohereChat from "./CohereChat";
import AnalyticsScreen from "./AnalyticsScreen";

export default function HacktheNorthUI() {
  const [space, setSpace] = useState<string | null>(null);
  const [userInput, setUserInput] = useState<string | null>(null);
  const [runPipeline, setRunPipeline] = useState<boolean>(false);
  const [stage, setStage] = useState<"intro" | "phase1" | "phase2" | "phase3" | "app" | "analytics">("intro");
  const [researchComplete, setResearchComplete] = useState<boolean>(false);
  const [researchPrefix, setResearchPrefix] = useState<string | null>(null);
  const [chatSidebarOpen, setChatSidebarOpen] = useState(false);
  const [envButtonsOpen, setEnvButtonsOpen] = useState(true);

  function startProject(name: string, input: string, pipeline: boolean) {
    setSpace(name);
    setUserInput(input);
    setRunPipeline(pipeline);
    setStage("phase1");
  }

  // Handle analytics screen navigation
  useEffect(() => {
    const handleAnalyzeData = () => {
      setStage("analytics");
    };

    window.addEventListener('analyzeData', handleAnalyzeData);
    
    return () => {
      window.removeEventListener('analyzeData', handleAnalyzeData);
    };
  }, []);


  if (stage === "intro") return <StartScreen onStart={startProject} />;

  if (stage === "analytics") {
    return <AnalyticsScreen 
      space={space} 
      onBack={() => setStage("app")} 
      onGoToMap={() => setStage("app")}
    />;
  }

  if (stage === "phase1" || stage === "phase2" || stage === "phase3") {
    return (
      <LoadingSequence
        phase={stage}
        space={space ?? ""}
        userInput={userInput ?? ""}
        runPipeline={runPipeline}
        onDone={() => {
          setStage("app");
        }}
        onResearchData={() => {
          /* optional: capture research summary for the sidebar later */
        }}
        onResearchComplete={(prefix) => {
          setResearchComplete(true);
          setResearchPrefix(prefix || null);
        }}
      />
    );
  }

  // Main app
  return (
    <div className="w-full h-full min-h-screen bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between border-b border-white/5 px-4 sm:px-6 py-4 sticky top-0 backdrop-blur bg-black/40 z-20">
        <div className="flex items-center gap-3">
          <button 
            onClick={() => setStage("intro")}
            className="h-8 w-8 rounded-xl bg-emerald-500/20 grid place-items-center hover:bg-emerald-500/30 transition-colors cursor-pointer mt-2"
            title="Back to Homepage"
          >
            <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_12px_rgba(52,211,153,0.8)]" />
          </button>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <Badge className="bg-white/10 border-white/10 text-neutral-300">{space ?? "Untitled"}</Badge>
          <Button
            variant="secondary"
            size="default"
            className="bg-emerald-500/20 border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/30 px-4"
            onClick={() => setEnvButtonsOpen(!envButtonsOpen)}
            title={envButtonsOpen ? "Hide Environment Buttons" : "Show Environment Buttons"}
          >
            <Settings className="h-4 w-4 mr-2" />
            {envButtonsOpen ? "Hide Env" : "Show Env"}
          </Button>
          <Button
            variant="secondary"
            size="default"
            className="bg-blue-500/20 border-blue-500/30 text-blue-300 hover:bg-blue-500/30 px-4"
            onClick={() => setChatSidebarOpen(!chatSidebarOpen)}
            title={chatSidebarOpen ? "Hide Chat" : "Show Chat"}
          >
            <MessageSquare className="h-4 w-4 mr-2" />
            {chatSidebarOpen ? "Hide Chat" : "Show Chat"}
          </Button>
        </div>
      </header>

      <div className="flex h-[calc(100vh-56px)]">
        {/* Left: env compare canvas */}
        <div className={`relative transition-all duration-300 ${
          chatSidebarOpen ? "flex-1" : "w-full"
        }`}>
          <EnvComparePanel envButtonsOpen={envButtonsOpen} />
        </div>

        {/* Right: Chat Interface */}
        {chatSidebarOpen && (
          <aside className="w-96 border-l border-white/5 bg-black/30 backdrop-blur p-3 sm:p-4 overflow-hidden">
            <Card className="h-full bg-black/40 border-white/10">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold">Assistant</div>
                    <div className="text-xs text-neutral-400">Space: {space ?? "Untitled"}</div>
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="bg-white/10 border-white/10 text-neutral-300 hover:bg-white/20"
                    onClick={() => setChatSidebarOpen(false)}
                    title="Collapse Chat"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </CardHeader>

              <Separator className="bg-white/10" />

              {/* Chat panel with markdown preface */}
              <CohereChat
                space={space}
                reportPrefix={researchPrefix || undefined}
              />
            </Card>
          </aside>
        )}

      </div>
    </div>
  );
}

/* ------------------------------ Env Compare UI ----------------------------- */

function EnvComparePanel({ envButtonsOpen }: { envButtonsOpen: boolean }) {
  const [mode, setMode] = useState<1 | 2 | 3 | 4>(1);
  const [split, setSplit] = useState({ x: 50, y: 50 });
  const ref = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  function clamp(n: number, min: number, max: number) {
    return Math.max(min, Math.min(max, n));
  }

  const onPointerDown = (e: React.PointerEvent) => {
    dragging.current = true;
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging.current || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const x = clamp(((e.clientX - rect.left) / rect.width) * 100, 10, 90);
    const y = clamp(((e.clientY - rect.top) / rect.height) * 100, 10, 90);
    setSplit((s) => ({ x: mode === 1 ? 50 : x, y: mode === 2 ? 50 : y }));
  };
  const onPointerUp = () => {
    dragging.current = false;
  };

  const labels = [
    "area rendering one env",
    "area rendering second env",
    "area rendering third env",
    "area rendering fourth env",
  ];

  const style: React.CSSProperties = {};
  if (mode === 1) {
    Object.assign(style, { display: "grid", gridTemplateColumns: "1fr", gridTemplateRows: "1fr" });
  } else if (mode === 2) {
    Object.assign(style, { display: "grid", gridTemplateColumns: `${split.x}% 1fr`, gridTemplateRows: "1fr" });
  } else if (mode === 4 || mode === 3) {
    Object.assign(style, {
      display: "grid",
      gridTemplateColumns: `${split.x}% 1fr`,
      gridTemplateRows: `${split.y}% 1fr`,
    });
  }

  return (
    <div className="absolute inset-0 bg-[linear-gradient(135deg,#0a0a0a,#0f1013_40%,#0b0b0c)]">
      {envButtonsOpen && (
        <div className="absolute top-3 left-3 z-10 flex items-center gap-2 rounded-xl border border-white/15 bg-black/60 px-2 py-1 backdrop-blur">
          {([
            { id: 1, label: "One Env" },
            { id: 2, label: "Two Envs" },
            { id: 3, label: "Three Envs" },
            { id: 4, label: "All" },
          ] as const).map((b) => (
            <Button
              key={b.id}
              size="sm"
              variant={mode === b.id ? "default" : "secondary"}
              className={mode === b.id ? "bg-emerald-500 text-black" : "bg-white/10 border-white/10 text-neutral-300"}
              onClick={() => setMode(b.id)}
            >
              {b.label}
            </Button>
          ))}
        </div>
      )}

      <div ref={ref} className="absolute inset-0 p-4" onPointerMove={onPointerMove} onPointerUp={onPointerUp}>
        <div className="w-full h-full rounded-md border border-white/10 overflow-hidden" style={style}>
          <EnvPane
            title={labels[0]}
            className={mode >= 1 ? "block" : "hidden"}
            style={{ gridArea: mode === 3 ? "1 / 1 / 2 / 2" : undefined }}
          />
          <EnvPane
            title={labels[1]}
            className={mode >= 2 ? "block" : "hidden"}
            style={{ gridArea: mode === 3 ? "1 / 2 / 2 / 3" : undefined }}
          />
          <EnvPane
            title={labels[2]}
            className={mode >= 3 ? "block" : "hidden"}
            style={{ gridArea: mode === 3 ? "2 / 1 / 3 / 3" : undefined }}
          />
          <EnvPane
            title={labels[3]}
            className={mode === 4 ? "block" : "hidden"}
            style={{ gridArea: mode === 4 ? "2 / 2 / 3 / 3" : undefined }}
          />
        </div>

        {/* Dividers */}
        {mode >= 2 && (
          <div className="pointer-events-none absolute inset-0">
            {mode === 2 && (
              <div className="absolute top-4 bottom-4 w-px bg-white/20" style={{ left: `calc(${split.x}% )` }} />
            )}
            {mode == 3 && (
              <>
                <div className="absolute left-4 right-4 h-px bg-white/20" style={{ top: `calc(${split.y}% )` }} />
                <div
                  className="absolute w-px bg-white/20"
                  style={{
                    left: `calc(${split.x}% )`,
                    top: "1rem",
                    height: `calc(${split.y}% - 1rem)`,
                  }}
                />
              </>
            )}
          </div>
        )}

        {mode == 4 && (
          <div className="pointer-events-none absolute inset-0">
            <div className="absolute top-4 bottom-4 w-px bg-white/20" style={{ left: `calc(${split.x}% )` }} />
            {mode >= 3 && (
              <div className="absolute left-4 right-4 h-px bg-white/20" style={{ top: `calc(${split.y}% )` }} />
            )}
          </div>
        )}

        {mode >= 2 && (
          <div
            className="absolute z-10 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.7)] border border-emerald-400 cursor-grab active:cursor-grabbing"
            style={{ left: `calc(${split.x}% )`, top: `calc(${mode >= 3 ? split.y : 50}% )` }}
            onPointerDown={onPointerDown}
          />
        )}
      </div>
    </div>
  );
}

function EnvPane({
  title,
  className,
  style,
}: {
  title: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div className={`relative bg-[rgba(255,255,255,0.08)] ${className || ""}`} style={style}>
      {/* Simulation viewer iframe */}
      <iframe
        src="http://localhost:8080/simulation/viewer/index.html"
        className="w-full h-full border-0"
        title={`Simulation Viewer - ${title}`}
        allowFullScreen
      />
    </div>
  );
}
