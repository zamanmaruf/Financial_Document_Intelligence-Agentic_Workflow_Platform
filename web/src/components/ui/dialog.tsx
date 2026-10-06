import * as DialogPrimitive from "@radix-ui/react-dialog";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;
export const DialogClose = DialogPrimitive.Close;

/** A modal panel over a dimmed page. Focus is trapped inside and returned on close; Esc closes. */
export function DialogContent({ className, ...props }: ComponentProps<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 animate-fade-in bg-black/70 backdrop-blur-sm" />
      <DialogPrimitive.Content
        className={cn("fixed z-50 animate-fade-in outline-none", className)}
        {...props}
      />
    </DialogPrimitive.Portal>
  );
}
