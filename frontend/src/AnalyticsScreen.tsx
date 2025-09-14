import React, { useEffect, useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer
} from "recharts";
import { Map, MessageSquare, ChevronLeft, ChevronRight, Settings } from "lucide-react";
import CohereChat from "./CohereChat";

type XY = { x: number; y: number };

interface MetricBlock {
  env1: XY[];
  env2: XY[];
  env3: XY[];
  label: string;
  color_env1: string;
  color_env2: string;
  color_env3: string;
}

interface AnalyticsData {
  metrics: Record<string, MetricBlock>;
  overall?: {
    weights: Record<string, number>;
    label?: string;
    color_env1?: string;
    color_env2?: string;
    color_env3?: string;
  };
  summary?: Record<string, string>;
  metadata?: {
    description?: string;
    time_period?: string;
    data_points?: number;
    generated_at?: string;
    version?: string;
  };
}

export default function AnalyticsScreen({
  space,
  onBack,
  onGoToMap
}: {
  space: string | null;
  onBack: () => void;
  onGoToMap: () => void;
}) {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>("overall");
  const [chatSidebarOpen, setChatSidebarOpen] = useState(false);
  const [envButtonsOpen, setEnvButtonsOpen] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch("/api/analytics/data");
        if (!response.ok) {
          // Try to parse server error JSON nicely
          let serverMsg = "";
          try {
            const errJson = await response.json();
            serverMsg = errJson?.error || JSON.stringify(errJson);
          } catch {
            serverMsg = await response.text();
          }
          throw new Error(
            `Server responded ${response.status}: ${serverMsg || "Unknown error"}`
          );
        }

        const analyticsData = (await response.json()) as AnalyticsData;

        // minimal shape check
        if (!analyticsData?.metrics) {
          throw new Error("Malformed payload: missing 'metrics'.");
        }

        setData(analyticsData);
        setError(null);
      } catch (e: any) {
        console.error("Failed to fetch analytics data:", e);
        setError(e?.message || "Failed to load analytics data.");
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  if (loading) {
    return (
      <div className="w-full h-full min-h-screen bg-neutral-950 text-neutral-100 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500 mx-auto mb-4" />
          <p className="text-neutral-400">Loading analytics data...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="w-full h-full min-h-screen bg-neutral-950 text-neutral-100 flex items-center justify-center">
        <div className="text-center max-w-md">
          <p className="text-red-400 mb-3">Failed to load analytics data</p>
          <p className="text-xs text-neutral-400 mb-5">{error}</p>
          <Button onClick={onBack} className="bg-emerald-500 text-black">
            Go Back
          </Button>
        </div>
      </div>
    );
  }

  if (!data) {
    // Shouldn’t happen, but guard anyway
    return (
      <div className="w-full h-full min-h-screen bg-neutral-950 text-neutral-100 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 mb-4">No analytics data</p>
          <Button onClick={onBack} className="bg-emerald-500 text-black">
            Go Back
          </Button>
        </div>
      </div>
    );
  }

  // Generate tabs dynamically from the data
  const tabs = data ? [
    ...Object.entries(data.metrics).map(([key, metric]) => ({
      id: key,
      label: metric.label || key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' '),
      data: key
    })),
    { id: "overall", label: "Overall", data: "overall" }
  ] : [];

  const LegendInsideLower = (
    <Legend 
      verticalAlign="bottom" 
      align="center" 
      wrapperStyle={{ 
        marginTop: 40, 
        marginBottom: -20
      }}
      iconType="circle"
      layout="horizontal"
      iconSize={8}
      content={(props) => {
        const { payload } = props;
        return (
          <div style={{ 
            display: 'flex', 
            justifyContent: 'center', 
            gap: '50px',
            marginTop: '20px'
          }}>
            {payload?.map((entry: any, index: number) => (
              <div key={index} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div 
                  style={{ 
                    width: '8px', 
                    height: '8px', 
                    borderRadius: '50%', 
                    backgroundColor: entry.color 
                  }} 
                />
                <span style={{ color: '#9ca3af', fontSize: '15px' }}>{entry.value}</span>
              </div>
            ))}
          </div>
        );
      }}
    />
  );

  const chartMargin = { top: 30, right: 30, left: 20, bottom: 20 };

  const renderChart = () => {
    if (activeTab === "overall") {
      // Overall chart - combine all metrics with weights
      const metricKeys = Object.keys(data.metrics);
      const weights = data.overall?.weights ?? {};
      const totalWeight = Object.values(weights).reduce((sum, w) => sum + (w || 0), 0) || 1;
      
      // Use the first metric as the base for data points
      const firstMetric = data.metrics[metricKeys[0]];
      if (!firstMetric) return null;

      const rows = firstMetric.env1.map((point, i) => {
        const env1 = metricKeys.reduce((sum, key) => {
          const metric = data.metrics[key];
          const weight = (weights[key] || 0) / totalWeight;
          return sum + (metric.env1[i]?.y ?? 0) * weight;
        }, 0);
        
        const env2 = metricKeys.reduce((sum, key) => {
          const metric = data.metrics[key];
          const weight = (weights[key] || 0) / totalWeight;
          return sum + (metric.env2[i]?.y ?? 0) * weight;
        }, 0);
        
        const env3 = metricKeys.reduce((sum, key) => {
          const metric = data.metrics[key];
          const weight = (weights[key] || 0) / totalWeight;
          return sum + (metric.env3[i]?.y ?? 0) * weight;
        }, 0);
        
        return {
          month: point.x,
          "Env 1(benchmark)": env1,
          "Env 2": env2,
          "Env 3": env3
        };
      });

      return (
        <ResponsiveContainer width="100%" height={420}>
          <LineChart data={rows} margin={chartMargin}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="month"
              stroke="#9ca3af"
              tick={{ fill: "#9ca3af" }}
              label={{
                value: "Months",
                position: "insideBottom",
                offset: -10,
                style: { textAnchor: "middle", fill: "#9ca3af" }
              }}
            />
            <YAxis
              stroke="#9ca3af"
              tick={{ fill: "#9ca3af" }}
              label={{
                value: "Overall Score",
                angle: -90,
                position: "insideLeft",
                style: { textAnchor: "middle", fill: "#9ca3af" }
              }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1f2937",
                border: "1px solid #374151",
                borderRadius: "8px",
                color: "#f9fafb"
              }}
            />
            <Line type="monotone" dataKey="Env 1(benchmark)" stroke={data.overall?.color_env1 || firstMetric.color_env1} strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="Env 2" stroke={data.overall?.color_env2 || firstMetric.color_env2} strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="Env 3" stroke={data.overall?.color_env3 || firstMetric.color_env3} strokeWidth={2} dot={false} />
            {LegendInsideLower}
          </LineChart>
        </ResponsiveContainer>
      );
    } else {
      // Individual metric chart
      const metric = data.metrics[activeTab];
      if (!metric) return null;

      const rows = metric.env1.map((point, i) => ({
        month: point.x,
        "Env 1(benchmark)": metric.env1[i]?.y ?? null,
        "Env 2": metric.env2[i]?.y ?? null,
        "Env 3": metric.env3[i]?.y ?? null
      }));

      return (
        <ResponsiveContainer width="100%" height={420}>
          <LineChart data={rows} margin={chartMargin}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="month"
              stroke="#9ca3af"
              tick={{ fill: "#9ca3af" }}
              label={{
                value: "Months",
                position: "insideBottom",
                offset: -10,
                style: { textAnchor: "middle", fill: "#9ca3af" }
              }}
            />
            <YAxis
              stroke="#9ca3af"
              tick={{ fill: "#9ca3af" }}
              label={{
                value: metric.label || activeTab,
                angle: -90,
                position: "insideLeft",
                style: { textAnchor: "middle", fill: "#9ca3af" }
              }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1f2937",
                border: "1px solid #374151",
                borderRadius: "8px",
                color: "#f9fafb"
              }}
            />
            <Line type="monotone" dataKey="Env 1(benchmark)" stroke={metric.color_env1} strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="Env 2" stroke={metric.color_env2} strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="Env 3" stroke={metric.color_env3} strokeWidth={2} dot={false} />
            {LegendInsideLower}
          </LineChart>
        </ResponsiveContainer>
      );
    }
  };

  return (
    <div className="w-full h-full min-h-screen bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between border-b border-white/5 px-4 sm:px-6 py-4 sticky top-0 backdrop-blur bg-black/40 z-20">
        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            className="bg-white/10 border-white/10 text-neutral-300 hover:bg-white/20"
            onClick={onBack}
          >
            ← Back
          </Button>
          <h1 className="text-xl font-semibold">Analytics Dashboard</h1>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <Badge className="bg-white/10 border-white/10 text-neutral-300">{space ?? "Untitled"}</Badge>
          {data.metadata?.time_period && (
            <Badge className="bg-blue-500/20 border-blue-500/30 text-blue-300">
              {data.metadata.time_period}
            </Badge>
          )}
          <Badge className="bg-emerald-500/20 border-emerald-500/30 text-emerald-300">
            {data.summary?.overall_rating ?? "—"}
          </Badge>
          
          {/* Toggle Buttons */}
          <div className="flex items-center gap-3 ml-6">
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
        </div>
      </header>

      <div className="flex h-[calc(100vh-56px)]">
        {/* Left: Charts */}
        <div className={`p-6 mt-20 transition-all duration-300 ${
          chatSidebarOpen ? "flex-1" : "w-full"
        }`}>
          {/* Tab Navigation */}
          {envButtonsOpen && (
            <div className="flex items-center gap-2 mb-8">
              {tabs.map((tab) => (
                <Button
                  key={tab.id}
                  variant={activeTab === tab.id ? "default" : "secondary"}
                  className={
                    activeTab === tab.id
                      ? "bg-emerald-500 text-black"
                      : "bg-white/10 border-white/10 text-neutral-300"
                  }
                  onClick={() => setActiveTab(tab.id)}
                >
                  {tab.label}
                </Button>
              ))}
            </div>
          )}

          {/* Chart */}
          <Card className="bg-black/40 border-white/10 mt-2">
            <CardContent className="p-6">{renderChart()}</CardContent>
          </Card>
        </div>

        {/* Right: Chat Interface */}
        {chatSidebarOpen && (
          <aside className="w-96 border-l border-white/5 bg-black/30 backdrop-blur p-3 sm:p-4 overflow-hidden">
            <Card className="h-full bg-black/40 border-white/10">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold">Analytics Assistant</div>
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

              <CohereChat
                space={space}
                analyticsData={data}
                showAnalyzeButton={false}
                onGoToMap={onGoToMap}
                preface={
                  data?.summary ? (
                    <div className="bg-white/5 border border-white/10 rounded-lg p-4">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-lg font-semibold text-emerald-400">
                          Analytics Summary
                        </h3>
                        {data.metadata?.generated_at && (
                          <span className="text-xs text-neutral-400">
                            Generated:{" "}
                            {new Date(data.metadata.generated_at).toLocaleString()}
                          </span>
                        )}
                      </div>
                      <div className="text-sm">
                        {Object.entries(data.summary).map(([key, value]) => (
                          <p key={key} className="text-neutral-300 mb-2">
                            <strong>{key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}:</strong> {value}
                          </p>
                        ))}
                      </div>
                    </div>
                  ) : null
                }
              />
            </Card>
          </aside>
        )}
      </div>
    </div>
  );
}
