import type { ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { GLOSSARY, type GlossaryKey } from "@/content/glossary";

/** A glossary word with a plain-language tooltip (keyboard and touch accessible). */
export function Term({ k, children }: { k: GlossaryKey; children?: ReactNode }) {
  const entry = GLOSSARY[k];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="cursor-help rounded-sm border-b border-dotted border-ink-subtle font-[inherit] text-inherit transition-colors hover:border-brand hover:text-ink"
        >
          {children ?? entry.term.toLowerCase()}
        </button>
      </TooltipTrigger>
      <TooltipContent>
        <span className="font-semibold">{entry.term}: </span>
        {entry.short}
      </TooltipContent>
    </Tooltip>
  );
}
