// LoadingSequence.tsx
import React, { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { streamResearch, type StreamEvent } from "@/lib/stream";
import { startResearch } from "@/lib/research";

type Phase = "phase1" | "phase2" | "phase3";

interface LoadingSequenceProps {
  phase: Phase;                 // kept for external API (unused here)
  space: string;
  userInput: string;            // user's description of the space
  runPipeline: boolean;         // whether to run the actual pipeline or use existing data
  durationMs?: number;          // total run time for the progress bar
  objective?: string;
  prefix?: string;
  onDone?: () => void;
  onResearchData?: (data: { evidence: any[]; rounds: any[]; sites: string[]; bullets: string[] }) => void;
  onResearchComplete?: (prefix?: string) => void;
}

/* ---------------------------- tiny helpers ---------------------------- */
const clamp = (n: number, min = 0, max = 100) => Math.max(min, Math.min(max, n));

// Smart URL construction - tries https first, falls back to http
const buildUrl = (domain: string): string => {
  // If it already has a protocol, use it as-is
  if (domain.startsWith('http://') || domain.startsWith('https://')) {
    return domain;
  }
  // Try https first, most modern sites support it
  return `https://${domain}`;
};

/** Single child that fades/slides in after a delay (no typewriter). */
const FadeIn: React.FC<{
  children: React.ReactNode;
  delay?: number;        // ms
  duration?: number;     // ms
  className?: string;
}> = ({ children, delay = 0, duration = 400, className }) => {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setShow(true), delay);
    return () => clearTimeout(t);
  }, [delay]);
  return (
    <div
      className={[
        "transition-all",
        show ? "opacity-100 translate-y-0" : "opacity-0 translate-y-1",
        className || "",
      ].join(" ")}
      style={{ transitionDuration: `${duration}ms` }}
    >
      {children}
    </div>
  );
};

/** Renders strings one-by-one with staggered fade-ins. */
const FadeInList: React.FC<{
  items: string[];
  startDelay?: number;   // ms before first item
  stepDelay?: number;    // ms between items
  itemClassName?: string;
}> = ({ items, startDelay = 0, stepDelay = 220, itemClassName }) => {
  return (
    <>
      {items.map((text, i) => (
        <FadeIn key={`${i}-${text}`} delay={startDelay + i * stepDelay}>
          <div className={itemClassName}>{text}</div>
        </FadeIn>
      ))}
    </>
  );
};

/** Website pill that appears with fade-in animation */
const FloatingWebsite: React.FC<{
  name: string;
  delay?: number;
}> = ({ name, delay = 0 }) => {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    // Show after delay
    const showTimer = setTimeout(() => {
      setIsVisible(true);
    }, delay);

    return () => {
      clearTimeout(showTimer);
    };
  }, [delay]);

  return (
    <a
      href={buildUrl(name)}
      target="_blank"
      rel="noopener noreferrer"
      className={`text-xs px-3 py-1 rounded-lg bg-white/10 border border-white/10 text-neutral-300 text-center transition-all duration-500 transform block ${
        isVisible 
          ? 'opacity-100 scale-100 translate-y-0' 
          : 'opacity-0 scale-95 translate-y-1'
      } hover:bg-white/15 hover:scale-105 cursor-pointer`}
    >
      {name}
    </a>
  );
};

/** Disappearing "+ more" indicator */
const DisappearingMore: React.FC<{
  delay?: number;
  duration?: number;
}> = ({ delay = 0, duration = 3000 }) => {
  const [isVisible, setIsVisible] = useState(false);
  const [isFading, setIsFading] = useState(false);

  useEffect(() => {
    // Show after delay
    const showTimer = setTimeout(() => {
      setIsVisible(true);
    }, delay);

    // Start fading after duration
    const fadeTimer = setTimeout(() => {
      setIsFading(true);
    }, delay + duration);

    return () => {
      clearTimeout(showTimer);
      clearTimeout(fadeTimer);
    };
  }, [delay, duration]);

  return (
    <div
      className={`text-xs px-3 py-1 rounded-lg bg-white/5 border border-white/10 text-neutral-400 text-center transition-all duration-500 transform ${
        isVisible && !isFading 
          ? 'opacity-100 scale-100 translate-y-0' 
          : 'opacity-0 scale-95 translate-y-1'
      }`}
    >
      + more
    </div>
  );
};

/* --------------------------- main component --------------------------- */
const LoadingSequence: React.FC<LoadingSequenceProps> = ({
  phase, // eslint-disable-line @typescript-eslint/no-unused-vars
  space,
  userInput,
  runPipeline,
  durationMs = 8000, // EXACT total runtime for progress bar
  objective,
  prefix,
  onDone,
  onResearchData,
  onResearchComplete,
}) => {
  const [expanded, setExpanded] = useState(false);

  // SSE-driven text content (we ignore SSE progress on purpose)
  const [prompt, setPrompt] = useState<string>("");
  const [searched, setSearched] = useState<{ query: string; results: number } | null>(null);
  const [summary, setSummary] = useState<{ title: string; bullets: string[] } | null>(null);
  const [chips, setChips] = useState<string[]>([]);

  // show bullets sequentially once summary arrives
  const [visibleBulletCount, setVisibleBulletCount] = useState(0);

  // sequential "scanned websites" sample (optional visual, not from SSE)
  const [showSourcesPanel, setShowSourcesPanel] = useState(false);
  
  // additional websites from evidence data
  const [showMoreWebsites, setShowMoreWebsites] = useState(false);
  const [additionalWebsites, setAdditionalWebsites] = useState<string[]>([]);

  // progress is backend-driven
  const [progress, setProgress] = useState(0);
  const [backendComplete, setBackendComplete] = useState(false);
  
  // Research data storage
  const [researchData, setResearchData] = useState<{
    evidence: any[];
    rounds: any[];
    sites: string[];
    bullets: string[];
  } | null>(null);
  const [researchPrefix, setResearchPrefix] = useState<string | null>(null);
  
  // Error handling
  const [hasError, setHasError] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const startedAtRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);
  const doneFiredRef = useRef(false);

  // Start research (either pipeline or use existing data)
  useEffect(() => {
    const startResearchProcess = async () => {
      try {
        // Prevent multiple simultaneous research processes
        if (startedAtRef.current) {
          console.log(`⚠️ Research already started, skipping duplicate call`);
          return;
        }
        
        startedAtRef.current = Date.now();
        console.log(`🎯 Starting research for: ${space}`);
        console.log(`📝 User input: ${userInput}`);
        console.log(`🔧 Run pipeline: ${runPipeline}`);
        
        if (runPipeline) {
          // Run the actual deep research pipeline
          const result = await startResearch({
            space: space,
            userInput: userInput,
            runPipeline: true
          });
          
          if (result.success) {
            console.log(`✅ Research pipeline started successfully with prefix: ${result.prefix}`);
            setResearchPrefix(result.prefix);
            

            // Start the real research process and poll for completion
            setPrompt(`Starting deep research pipeline for ${space}...`);
            
            // Poll for research completion
            const pollForCompletion = async () => {
              const maxAttempts = 60; // 5 minutes max (5 second intervals)
              let attempts = 0;
              
              const poll = async () => {
                attempts++;
                console.log(`🔍 Polling for research completion (attempt ${attempts}/${maxAttempts})`);
                
                try {
                  // Check if research is complete by looking for the report file
                  const response = await fetch(`/api/research/status?prefix=${result.prefix}`);
                  const status = await response.json();
                  
                  if (status.status === 'complete') {
                    console.log(`✅ Research completed successfully!`);
                    
                    // Update UI to show completion
                    setSearched({ query: "deep research analysis", results: status.data?.items || 0 });
                    setShowSourcesPanel(true);
                    
                    setSummary({ 
                      title: `Research Analysis Complete for ${space}`,
                      bullets: [
                        "Comprehensive research pipeline completed",
                        "Regulatory requirements analyzed", 
                        "Environmental considerations evaluated",
                        "Utility infrastructure assessed",
                        "Detailed feasibility report generated"
                      ]
                    });
                    
                    // Reveal bullets progressively
                    setVisibleBulletCount(0);
                    const interval = setInterval(() => {
                      setVisibleBulletCount(prev => {
                        if (prev >= 5) {
                          clearInterval(interval);
                          return prev;
                        }
                        return prev + 1;
                      });
                    }, 200);
                    
                    // Set chips from actual research data
                    setChips(status.data?.sites_list || ["waterloo.ca", "ontario.ca"]);
                    
                    // Complete the process
                    setProgress(100);
                    setBackendComplete(true);
                    
                    const data = {
                      evidence: [],
                      rounds: [],
                      sites: status.data?.sites_list || ["waterloo.ca", "ontario.ca"],
                      bullets: [
                        "Comprehensive research pipeline completed",
                        "Regulatory requirements analyzed", 
                        "Environmental considerations evaluated",
                        "Utility infrastructure assessed",
                        "Detailed feasibility report generated"
                      ]
                    };
                    setResearchData(data);
                    onResearchData?.(data);
                    onResearchComplete?.(result.prefix);
                    
                  } else if (status.status === 'error') {
                    console.error(`❌ Research failed: ${status.error}`);
                    setHasError(true);
                    setErrorMessage(`Research failed: ${status.error}`);
                  } else {
                    // Still in progress, update progress
                    const progressPercent = Math.min(90, (attempts / maxAttempts) * 100);
                    setProgress(progressPercent);
                    
                    // Update prompt to show progress
                    setPrompt(`Research in progress... (${Math.round(progressPercent)}%)`);
                    
                    if (attempts < maxAttempts) {
                      setTimeout(poll, 5000); // Poll every 5 seconds
                    } else {
                      console.error(`❌ Research timed out after ${maxAttempts} attempts`);
                      setHasError(true);
                      setErrorMessage('Research timed out. Please try again.');
                    }
                  }
                } catch (error) {
                  console.error(`❌ Error polling research status:`, error);
                  if (attempts < maxAttempts) {
                    setTimeout(poll, 5000); // Retry after 5 seconds
                  } else {
                    setHasError(true);
                    setErrorMessage('Failed to check research status. Please try again.');
                  }
                }
              };
              
              // Start polling
              poll();
            };
            
            // Start polling after a short delay
            setTimeout(pollForCompletion, 2000);
            
          } else {
            console.error(`❌ Failed to start research pipeline:`, result);
            console.error(`❌ Error details:`, result.error);
          }
        } else {
          // Use existing processed data (faster)
          console.log(`📊 Using existing processed data for: ${space}`);
          
          // Immediately mark research as complete when using existing data
          onResearchComplete?.();
          
          setTimeout(() => {
            setPrompt(`Loading existing research data for ${space}...`);
          }, 2000);
          
          setTimeout(() => {
            setSearched({ query: "existing research data", results: 8 });
            setShowSourcesPanel(true);
          }, 6000);
          
          setTimeout(() => {
            setSummary({ 
              title: `Existing Research Data for ${space}`,
              bullets: [
                "Loaded pre-processed research findings",
                "Applied existing regulatory analysis", 
                "Used cached environmental data",
                "Referenced previous infrastructure studies",
                "Applied standard cost estimates"
              ]
            });
            
            // Reveal bullets progressively
            setVisibleBulletCount(0);
            const interval = setInterval(() => {
              setVisibleBulletCount(prev => {
                if (prev >= 5) {
                  clearInterval(interval);
                  return prev;
                }
                return prev + 1;
              });
            }, 300);
          }, 10000);
          
          setTimeout(() => {
            setChips([
              "waterloo.ca",
              "ontario.ca", 
              "grandriver.ca",
              "regionofwaterloo.ca"
            ]);
          }, 12000);
          
          setTimeout(() => {
            setProgress(100);
            setBackendComplete(true);
            
            const data = {
              evidence: [],
              rounds: [],
              sites: ["waterloo.ca", "ontario.ca", "grandriver.ca", "regionofwaterloo.ca"],
              bullets: [
                "Loaded pre-processed research findings",
                "Applied existing regulatory analysis", 
                "Used cached environmental data",
                "Referenced previous infrastructure studies",
                "Applied standard cost estimates"
              ]
            };
            setResearchData(data);
            onResearchData?.(data);
            onResearchComplete?.(researchPrefix || undefined);
          }, 15000);
        }
      } catch (error) {
        console.error(`❌ Error starting research:`, error);
      }
    };

    startResearchProcess();
  }, [space, userInput, runPipeline]);

  // reset a run
  useEffect(() => {
    startedAtRef.current = null;
    doneFiredRef.current = false;
    setProgress(0);
    setShowSourcesPanel(false);
    setVisibleBulletCount(0);
    setShowMoreWebsites(false);
    setAdditionalWebsites([]);
    setBackendComplete(false);
    setHasError(false);
    setErrorMessage(null);
  }, [objective, prefix, space]);

  // Handle completion when backend finishes
  useEffect(() => {
    if (backendComplete && !doneFiredRef.current && !hasError) {
      console.log("Backend completed, transitioning to next screen");
      doneFiredRef.current = true;
      onDone?.();
    }
  }, [backendComplete, onDone, hasError]);

  // once summary arrives, reveal bullets one-by-one
  useEffect(() => {
    if (!summary || !summary.bullets?.length) return;
    setVisibleBulletCount(0);
    const step = 350; // ms between bullet reveals
    let i = 0;
    const iv = setInterval(() => {
      i += 1;
      setVisibleBulletCount((prev) => {
        const next = Math.min(summary.bullets.length, prev + 1);
        if (next >= summary.bullets.length) clearInterval(iv);
        return next;
      });
    }, step);
    return () => clearInterval(iv);
  }, [summary]);

  const fallbackPrompt = `Search the web for ${(objective && objective.trim()) || `best ways to optimize ${space || "apartment"}`}`;

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <div className="max-w-4xl mx-auto px-4 py-10">
        {/* Error display */}
        {hasError && (
          <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-300">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-red-400">⚠️</span>
              <span className="font-semibold">Connection Error</span>
            </div>
            <p className="text-sm text-red-200">{errorMessage}</p>
            <button 
              onClick={() => {
                setHasError(false);
                setErrorMessage(null);
                // Restart the research
                window.location.reload();
              }}
              className="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 rounded-lg text-sm text-red-200 hover:text-red-100 transition-colors"
            >
              Try Again
            </button>
          </div>
        )}
        
        {/* Prompt bubble */}
        <div className="flex justify-center">
          <FadeIn delay={0} duration={400}>
            <div className="rounded-full px-5 py-3 bg-white/5 border border-white/10 text-lg sm:text-xl text-neutral-200 shadow-lg">
              {prompt || fallbackPrompt}
            </div>
          </FadeIn>
        </div>

        {/* Search strip */}
        {searched && (
          <FadeIn delay={250}>
            <div className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-3 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="h-7 w-7 grid place-items-center rounded-full bg-white/10 border border-white/10">⌕</div>
                <div className="text-neutral-300">
                  Searched for <span className="text-neutral-100">"{searched.query}"</span>
                </div>
              </div>
              <div className="text-sm text-neutral-400">{searched.results} results</div>
            </div>
          </FadeIn>
        )}

         {/* Scanned sources (floating websites with fade in/out) */}
         {showSourcesPanel && chips.length > 0 && (
           <FadeIn delay={0}>
             <div className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-4">
               <div className="text-neutral-300 text-sm mb-3">Scanning sources…</div>
                <div className="flex flex-wrap gap-2">
                  {chips.slice(0, 8).map(
                    (name, idx) => (
                      <FloatingWebsite key={name} name={name} delay={150 * idx} />
                    )
                  )}
                  {chips.length > 8 && (
                    <DisappearingMore delay={150 * 8} duration={3000} />
                  )}
                </div>
             </div>
           </FadeIn>
         )}

         {/* Thinking card */}
         {summary && (
           <FadeIn delay={300}>
             <div className="mt-6 rounded-2xl border border-white/20 bg-gradient-to-br from-black/40 via-black/30 to-black/20 p-5 shadow-2xl shadow-black/40">
              <div className="flex items-center justify-between">
                <div className="text-neutral-400 text-sm flex items-center gap-2">
                  <span className="inline-block h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.7)] animate-pulse" />
                  Thinking
                </div>

                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => setExpanded((v) => !v)}
                  className="inline-flex items-center gap-2 text-sm text-neutral-300 hover:text-neutral-100 transition-colors"
                >
                  {expanded ? "Hide reasoning" : "Show reasoning"}
                  <ChevronDown className={`h-4 w-4 transition-transform ${expanded ? "" : "-rotate-90"}`} />
                </button>
              </div>

              <FadeIn delay={120}>
                <div className="mt-3 text-base font-semibold">{summary.title}</div>
              </FadeIn>

              {/* Compact summary */}
              {!expanded && (
                <FadeIn delay={220}>
                  <div className="mt-2 text-neutral-400 text-sm">
                    Running multi-source scan and de-duplication; drafting hypotheses before synthesis…
                  </div>
                </FadeIn>
              )}

              {/* Full reasoning */}
              {expanded && (
                <>
                  <ul className="mt-2 text-neutral-300 text-sm space-y-2 list-disc pl-6">
                    <FadeInList
                      items={summary.bullets.slice(0, visibleBulletCount)}
                      startDelay={80}
                      stepDelay={180}
                      itemClassName="will-change-transform"
                    />
                  </ul>

                   {chips.length > 0 && (
                     <div className="mt-4 flex flex-wrap gap-2">
                       {chips.map((c, i) => (
                         <FadeIn key={c} delay={80 + i * 90}>
                           <a
                             href={buildUrl(c)}
                             target="_blank"
                             rel="noopener noreferrer"
                             className="text-xs px-3 py-1 rounded-full bg-white/10 border border-white/10 text-neutral-300 hover:bg-white/15 hover:scale-105 transition-all duration-200 cursor-pointer"
                           >
                             {c}
                           </a>
                         </FadeIn>
                       ))}
                       {additionalWebsites.length > 0 && (
                         <FadeIn delay={80 + chips.length * 90}>
                           <button 
                             className="text-xs px-2 py-1 rounded-full bg-gradient-to-r from-white/10 to-white/5 border border-white/20 text-neutral-300 hover:from-white/15 hover:to-white/10 hover:border-white/30 hover:text-white hover:scale-105 transition-all duration-200 cursor-pointer shadow-sm hover:shadow-md font-medium"
                             onClick={() => setShowMoreWebsites(!showMoreWebsites)}
                           >
                             {showMoreWebsites ? "− Show Less" : "+ Show More"}
                           </button>
                         </FadeIn>
                       )}
                       
                       {/* Additional websites that appear when + more is clicked */}
                       {showMoreWebsites && additionalWebsites.length > 0 && (
                         <div className="flex flex-wrap gap-2">
                           {additionalWebsites.map((website, i) => (
                             <FadeIn key={website} delay={100 + i * 50}>
                               <a
                                 href={buildUrl(website)}
                                 target="_blank"
                                 rel="noopener noreferrer"
                                 className="text-xs px-3 py-1.5 rounded-lg bg-white/8 border border-white/15 text-neutral-300 hover:bg-white/12 hover:border-white/25 hover:scale-105 transition-all duration-200 cursor-pointer shadow-sm hover:shadow-md"
                               >
                                 {website}
                               </a>
                             </FadeIn>
                           ))}
                         </div>
                       )}
                     </div>
                   )}
                </>
              )}
            </div>
          </FadeIn>
        )}

        {/* Progress bar (strictly time-based) */}
        <FadeIn delay={0}>
          <div className="mt-6">
            <div className="h-2 w-full rounded-full bg-white/5 overflow-hidden">
              <div
                className="h-full rounded-full bg-emerald-500 shadow-[0_0_12px_rgba(16,185,129,0.35)]"
                style={{
                  width: `${clamp(progress, 0, 100)}%`,
                }}
              />
            </div>
            <div className="mt-2 text-xs text-neutral-500">
              {progress < 100 ? "Synthesizing…" : "Done"} {Math.round(clamp(progress, 0, 100))}%
            </div>
          </div>
        </FadeIn>
      </div>
    </div>
  );
};

export default LoadingSequence;
