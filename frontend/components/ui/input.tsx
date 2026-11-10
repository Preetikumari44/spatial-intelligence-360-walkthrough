import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input ref={ref} className={cn("h-10 w-full rounded-md border bg-card px-3 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary", className)} {...p} />
));
Input.displayName = "Input";
