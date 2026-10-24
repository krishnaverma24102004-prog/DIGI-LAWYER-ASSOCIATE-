import type { AgentStage } from "@/lib/types";

const STEPS: { stage: AgentStage; label: string }[] = [
  { stage: "intake_analyzer", label: "Listening" },
  { stage: "legal_researcher", label: "Knowledge base" },
  { stage: "external_researcher", label: "Web" },
  { stage: "risk_evaluator", label: "Risks" },
  { stage: "drafter", label: "Replying" },
];

/** The "thinking" indicator: which agent is working right now. */
export function AgentStatus({ stage, message, speaking }: { stage: AgentStage; message: string; speaking: boolean }) {
  const busy = stage !== "idle";
  const current = STEPS.findIndex((s) => s.stage === stage);

  if (!busy && !speaking) return null;
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800" role="status" aria-live="polite">
      <span className="relative flex h-2.5 w-2.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-60 motion-reduce:animate-none" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-indigo-500" />
      </span>
      <span className="text-slate-700 dark:text-slate-200">{speaking && !busy ? "Speaking…" : message}</span>
      {busy ? (
        <span className="flex gap-1">
          {STEPS.map((step, i) => (
            <span
              key={step.stage}
              className={`rounded-full px-2 py-0.5 text-[11px] ${
                i === current
                  ? "bg-indigo-600 text-white"
                  : i < current
                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300"
                    : "bg-white text-slate-400 dark:bg-slate-900"
              }`}
            >
              {step.label}
            </span>
          ))}
        </span>
      ) : null}
    </div>
  );
}
