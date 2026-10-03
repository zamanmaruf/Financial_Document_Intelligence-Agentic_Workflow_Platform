import { Cpu, Sparkles } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useDemoStatus } from "@/hooks/useDemoStatus";
import { cn } from "@/lib/utils";

/** Which engine is answering right now: live Claude, or the labelled offline fallback. */
export function AiBadge({ className }: { className?: string }) {
  const { status, unavailable } = useDemoStatus();

  if (unavailable) {
    return (
      <span className={cn("inline-flex items-center gap-1.5 rounded-full bg-danger-soft px-3 py-1 text-xs font-medium text-danger", className)}>
        Service unreachable
      </span>
    );
  }
  if (!status) {
    return <span className={cn("inline-block h-6 w-28 animate-pulse-soft rounded-full bg-surface-muted", className)} aria-hidden />;
  }

  const live = status.ai_mode === "live";
  const label = live ? "Live AI" : "Offline engine";
  const explanation = live
    ? `Answers come from ${status.model_name} on AWS Bedrock, in real time.`
    : status.offline_reason === "budget_reached"
      ? "Today's live-AI budget is used up, so a simpler rule-based engine is answering. It resets at midnight UTC. Results are labelled."
      : "This server runs the deterministic rule-based engine instead of a live AI model. Results are labelled.";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium",
            live ? "bg-ok-soft text-ok" : "bg-warn-soft text-warn",
            className,
          )}
        >
          {live ? <Sparkles className="size-3.5" aria-hidden /> : <Cpu className="size-3.5" aria-hidden />}
          {label}
          {!live && status.offline_reason === "budget_reached" && (
            <span className="font-normal">· daily budget used</span>
          )}
        </button>
      </TooltipTrigger>
      <TooltipContent>{explanation}</TooltipContent>
    </Tooltip>
  );
}
