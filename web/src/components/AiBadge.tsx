import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useDemoStatus } from "@/hooks/useDemoStatus";
import { cn } from "@/lib/utils";

/** Which engine is answering right now: live Claude, or the labelled offline fallback. */
export function AiBadge({ className }: { className?: string }) {
  const { status, unavailable } = useDemoStatus();

  if (unavailable) {
    return (
      <span
        className={cn(
          "inline-flex h-7 items-center gap-2 rounded-full border border-danger-line bg-danger-soft px-3 text-xs font-medium text-danger",
          className,
        )}
      >
        <span aria-hidden className="size-1.5 rounded-full bg-danger" />
        Service unreachable
      </span>
    );
  }
  if (!status) {
    return <span className={cn("skeleton inline-block h-7 w-24 rounded-full", className)} aria-hidden />;
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
            "inline-flex h-7 items-center gap-2 rounded-full border px-3 text-xs font-medium transition-colors",
            live
              ? "border-ok-line bg-ok-soft text-ok hover:border-ok"
              : "border-warn-line bg-warn-soft text-warn hover:border-warn",
            className,
          )}
        >
          <span aria-hidden className="relative flex size-1.5">
            {live && <span className="absolute inset-0 animate-beacon rounded-full text-ok" />}
            <span className="relative size-1.5 rounded-full bg-current" />
          </span>
          {label}
          {!live && status.offline_reason === "budget_reached" && (
            <span className="font-normal opacity-80">· daily budget used</span>
          )}
        </button>
      </TooltipTrigger>
      <TooltipContent>{explanation}</TooltipContent>
    </Tooltip>
  );
}
