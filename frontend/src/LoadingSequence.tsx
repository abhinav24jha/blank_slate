// LoadingSequence.tsx
import React, { useEffect, useRef, useState } from "react";

type Phase = "phase1" | "phase2" | "phase3";

interface LoadingSequenceProps {
  phase: Phase;                 // kept for external API (unused)
  space: string;                // still shown in the prompt text
  durationMs?: number;          // total run time for the progress bar
  objective?: string;           // appears in the prompt text
  onDone?: () => void;          // called when progress hits 100%
}

const clamp = (n: number, min = 0, max = 100) => Math.max(min, Math.min(max, n));

const LoadingSequence: React.FC<LoadingSequenceProps> = ({
  phase, // eslint-disable-line @typescript-eslint/no-unused-vars
  space,
  durationMs = 6000,
  objective,
  onDone,
}) => {
  const [progress, setProgress] = useState(0);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);
  const doneRef = useRef(false);

  const subtitle =
    (objective && objective.trim()) ||
    `Preparing your ${space || "workspace"}…`;

  // Time-based progress animation
  useEffect(() => {
    doneRef.current = false;
    setProgress(0);
    startRef.current = null;

    const tick = (t: number) => {
      if (startRef.current == null) startRef.current = t;
      const elapsed = t - startRef.current;
      const pct = clamp((elapsed / durationMs) * 100, 0, 100);
      setProgress(pct);

      if (pct < 100) {
        rafRef.current = requestAnimationFrame(tick);
      } else if (!doneRef.current) {
        doneRef.current = true;
        // small micro-delay to let the bar visually finish
        setTimeout(() => onDone?.(), 150);
      }
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [durationMs, space, objective, onDone]);

  // Optional keyboard skip (Enter/Escape)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Enter" || e.key === "Escape") {
        if (!doneRef.current) {
          doneRef.current = true;
          setProgress(100);
          setTimeout(() => onDone?.(), 100);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onDone]);

  const skip = () => {
    if (!doneRef.current) {
      doneRef.current = true;
      setProgress(100);
      setTimeout(() => onDone?.(), 100);
    }
  };

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <div className="max-w-4xl mx-auto px-4 py-14">
        {/* Prompt chip */}
        <div className="flex justify-center">
          <div className="rounded-full px-5 py-3 bg-white/5 border border-white/10 text-lg sm:text-xl text-neutral-200 shadow-lg">
            {subtitle}
          </div>
        </div>

        {/* Pretty card */}
        <div className="mt-8 rounded-2xl border border-white/10 bg-gradient-to-br from-black/40 via-black/30 to-black/20 p-6 shadow-2xl shadow-black/40">
          <div className="flex items-center justify-between">
            <div className="text-neutral-400 text-sm flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.7)] animate-pulse" />
              Loading
            </div>

            <button
              type="button"
              onClick={skip}
              className="text-xs px-3 py-1.5 rounded-full bg-white/10 border border-white/15 text-neutral-200 hover:bg-white/15 hover:border-white/25 transition-colors"
            >
              Skip
            </button>
          </div>

          {/* Progress bar */}
          <div className="mt-5">
            <div className="h-2 w-full rounded-full bg-white/5 overflow-hidden">
              <div
                className="h-full rounded-full bg-emerald-500 shadow-[0_0_12px_rgba(16,185,129,0.35)] transition-[width] duration-100"
                style={{ width: `${clamp(progress, 0, 100)}%` }}
              />
            </div>
            <div className="mt-2 text-xs text-neutral-500">
              {progress < 100 ? "Working…" : "Done"} {Math.round(clamp(progress, 0, 100))}%
            </div>
          </div>

          {/* Lightweight filler text for vibe */}
          <div className="mt-6 grid gap-2 text-sm text-neutral-400">
            <div className="h-3 w-5/6 rounded bg-white/5" />
            <div className="h-3 w-2/3 rounded bg-white/5" />
            <div className="h-3 w-4/5 rounded bg-white/5" />
          </div>
        </div>

        {/* Tiny footer hint */}
        <div className="mt-6 text-center text-xs text-neutral-500">
          Tip: Press <span className="text-neutral-300 font-medium">Enter</span> to continue.
        </div>
      </div>
    </div>
  );
};

export default LoadingSequence;

