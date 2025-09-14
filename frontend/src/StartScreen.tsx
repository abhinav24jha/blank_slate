import React, { useEffect, useState } from "react";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { MapPin } from "lucide-react";

// Modern Compass Logo Component
const CompassLogo = () => (
  <div className="relative h-8 w-8">
    {/* Green blob background */}
    <div className="absolute inset-0 rounded-full bg-gradient-to-br from-emerald-400 to-emerald-600 shadow-lg" />
    
    {/* Compass SVG */}
    <svg
      className="absolute inset-1 h-6 w-6 text-white"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Compass circle */}
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="1.5"
        fill="none"
      />
      
      {/* North arrow */}
      <path
        d="M12 2L14 8L12 6L10 8L12 2Z"
        fill="currentColor"
      />
      
      {/* South arrow */}
      <path
        d="M12 22L10 16L12 18L14 16L12 22Z"
        fill="currentColor"
      />
      
      {/* East arrow */}
      <path
        d="M22 12L16 10L18 12L16 14L22 12Z"
        fill="currentColor"
      />
      
      {/* West arrow */}
      <path
        d="M2 12L8 14L6 12L8 10L2 12Z"
        fill="currentColor"
      />
      
      {/* Center dot */}
      <circle
        cx="12"
        cy="12"
        r="1.5"
        fill="currentColor"
      />
    </svg>
  </div>
);

type Props = { onStart: (space: string, userInput: string, runPipeline: boolean) => void };

export default function StartScreen({ onStart }: Props) {
  const [spaceName, setSpaceName] = useState("");
  const [userInput, setUserInput] = useState("");
  const [runPipeline, setRunPipeline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setError(null), [spaceName, userInput]);

  const submit = () => {
    const space = spaceName.trim();
    const input = userInput.trim();
    if (!space) return setError("Please enter a space name to continue.");
    if (!input) return setError("Please describe the space to continue.");
    onStart(space, input, runPipeline);
  };

  const suggestions = [
    "Society145, Waterloo",
    "Waterloo Park",
    "200 Lester Street, Waterloo",
  ];

  return (
    <div className="relative min-h-screen overflow-hidden bg-neutral-950 text-neutral-100">
      {/* --- Background: premium gradient + grid + vignette --- */}
      <div
        className="pointer-events-none absolute inset-0"
        aria-hidden
        style={{
          background:
            "radial-gradient(900px 500px at 20% 10%, rgba(16,185,129,0.12), transparent 60%), radial-gradient(800px 500px at 80% 90%, rgba(59,130,246,0.10), transparent 60%)",
        }}
      />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.06]"
        aria-hidden
        style={{
          background:
            "linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)",
          backgroundSize: "48px 48px",
        }}
      />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/10 via-transparent to-black/40 [mask-image:radial-gradient(ellipse_at_center,black,transparent_75%)]" />

      {/* --- Header (optional brand slot) --- */}
      <header className="relative z-10 mx-auto w-full max-w-6xl px-6 pt-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <CompassLogo />
            <span className="text-sm font-medium text-neutral-300">Blank Slate</span>
          </div>
          <span className="text-xs text-neutral-500">v0.1</span>
        </div>
      </header>

      {/* --- Main hero --- */}
      <main className="relative z-10 grid min-h-[calc(100vh-6rem)] place-items-center px-4">
        <div className="w-full max-w-2xl text-center space-y-4 mb-6">
          <h1 className="text-4xl sm:text-5xl font-semibold tracking-tight">
            Plan smarter spaces.
          </h1>
          <p className="mx-auto max-w-xl text-neutral-400">
            Tell us where you’re optimizing. We’ll structure the assessment and next steps for that context.
          </p>
        </div>

        <Card className="w-[92%] max-w-xl bg-white/5 backdrop-blur-md border border-white/10 shadow-[0_10px_50px_-10px_rgba(0,0,0,0.6)] ring-1 ring-white/10">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-neutral-300">Space details</span>
              <span className="text-[11px] text-neutral-500">Required</span>
            </div>
            <h2 className="text-2xl font-semibold tracking-tight">
              Which space are we making efficient today?
            </h2>
          </CardHeader>

          <CardContent className="space-y-4">
            <div className="space-y-4">
              <div className="relative">
                <label className="block text-sm font-medium text-neutral-300 mb-2">
                  Space Name
                </label>
                <MapPin className="pointer-events-none absolute left-3 top-1/2 translate-y-1 h-4 w-4 text-neutral-500" />
                <Input
                  value={spaceName}
                  onChange={(e) => setSpaceName(e.target.value)}
                  placeholder="e.g., Society parking l, Engineering quad, Main street strip"
                  aria-invalid={!!error}
                  aria-describedby={error ? "space-error" : undefined}
                  className="pl-9 h-12 rounded-xl bg-white/5 border-white/10 text-neutral-100 placeholder:text-neutral-500
                             focus-visible:ring-2 focus-visible:ring-emerald-400/40 focus-visible:border-emerald-400/30 transition"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-neutral-300 mb-2">
                  Describe the space and its current issues
                </label>
                <Textarea
                  value={userInput}
                  onChange={(e) => setUserInput(e.target.value)}
                  placeholder="Describe what you see in this space, what problems exist, and what improvements could be made..."
                  className="min-h-[100px] rounded-xl bg-white/5 border-white/10 text-neutral-100 placeholder:text-neutral-500
                             focus-visible:ring-2 focus-visible:ring-emerald-400/40 focus-visible:border-emerald-400/30 transition resize-none"
                />
              </div>

              {error && (
                <p id="space-error" className="text-sm text-red-400">
                  {error}
                </p>
              )}
            </div>

            {/* Pipeline Toggle */}
            <div className="flex items-center justify-between p-4 bg-white/5 border border-white/10 rounded-lg">
              <div>
                <div className="text-sm font-medium text-neutral-200">Run Deep Research Pipeline</div>
                <div className="text-xs text-neutral-400">
                  {runPipeline 
                    ? "Will run the full research pipeline (takes longer)" 
                    : "Will use existing processed data (faster)"
                  }
                </div>
              </div>
              <Switch
                checked={runPipeline}
                onCheckedChange={setRunPipeline}
                className="data-[state=checked]:bg-emerald-500"
              />
            </div>

            {/* smart suggestions */}
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSpaceName(s)}
                  className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-neutral-200
                             hover:border-white/20 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/20 transition"
                >
                  {s}
                </button>
              ))}
            </div>
          </CardContent>

          <CardFooter className="flex items-center justify-between gap-3">
            <span className="text-xs text-neutral-500">
              Press <kbd className="rounded bg-white/10 px-1.5 py-0.5 text-[10px]">Enter</kbd> to continue
            </span>
            <div className="flex gap-3">
              <Button
                variant="secondary"
                className="bg-white/10 border border-white/10 hover:bg-white/20 active:scale-[0.99] transition"
                onClick={() => {
                  setSpaceName("");
                  setUserInput("");
                }}
                disabled={!spaceName && !userInput}
              >
                Clear
              </Button>
              <Button
                className="bg-emerald-500 text-black hover:brightness-110 active:scale-[0.99]
                           shadow-[0_0_0_0_rgba(16,185,129,0)] hover:shadow-[0_0_40px_0_rgba(16,185,129,0.25)] transition"
                onClick={submit}
                disabled={!spaceName.trim() || !userInput.trim()}
              >
                Continue
              </Button>
            </div>
          </CardFooter>
        </Card>

        {/* trust bar / meta */}
        <p className="mt-6 text-center text-xs text-neutral-500">
          Your input stays private and is used only to generate your plan.
        </p>
      </main>

      {/* --- Footer --- */}
      <footer className="relative z-10 mx-auto w-full max-w-6xl px-6 pb-8">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-neutral-500">
          <div>&copy; {new Date().getFullYear()} Blank Slate Lab</div>
          <div className="flex items-center gap-4">
            <a className="hover:text-neutral-300 transition" href="#">Privacy</a>
            <a className="hover:text-neutral-300 transition" href="#">Terms</a>
            <a className="hover:text-neutral-300 transition" href="#">Contact</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
