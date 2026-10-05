import * as AccordionPrimitive from "@radix-ui/react-accordion";
import { Plus } from "lucide-react";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const Accordion = AccordionPrimitive.Root;

export function AccordionItem({ className, ...props }: ComponentProps<typeof AccordionPrimitive.Item>) {
  return <AccordionPrimitive.Item className={cn("border-b border-line", className)} {...props} />;
}

export function AccordionTrigger({
  className,
  children,
  ...props
}: ComponentProps<typeof AccordionPrimitive.Trigger>) {
  return (
    <AccordionPrimitive.Header className="flex">
      <AccordionPrimitive.Trigger
        className={cn(
          "group flex flex-1 items-center justify-between gap-4 py-5 text-left text-[15px] font-medium text-ink transition-colors hover:text-white",
          className,
        )}
        {...props}
      >
        {children}
        <span className="grid size-7 shrink-0 place-items-center rounded-full border border-line-strong text-ink-muted transition-[transform,color,border-color] duration-200 group-hover:border-line-bright group-hover:text-ink group-data-[state=open]:rotate-45">
          <Plus className="size-3.5" aria-hidden />
        </span>
      </AccordionPrimitive.Trigger>
    </AccordionPrimitive.Header>
  );
}

export function AccordionContent({
  className,
  children,
  ...props
}: ComponentProps<typeof AccordionPrimitive.Content>) {
  return (
    <AccordionPrimitive.Content className="overflow-hidden text-sm text-ink-muted" {...props}>
      <div className={cn("pb-5 pr-10 leading-relaxed", className)}>{children}</div>
    </AccordionPrimitive.Content>
  );
}
