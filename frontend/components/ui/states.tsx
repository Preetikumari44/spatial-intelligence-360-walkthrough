import type { ReactNode } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

export const Spinner = ({ label }: { label?: string }) => (
  <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground" role="status">
    <Loader2 className="h-4 w-4 animate-spin" /> {label ?? "Loading…"}
  </div>
);

export const ErrorBox = ({ message }: { message: string }) => (
  <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive" role="alert">
    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> <span>{message}</span>
  </div>
);

export const Empty = ({ title, children }: { title: string; children?: ReactNode }) => (
  <div className="rounded-lg border border-dashed p-8 text-center">
    <p className="font-medium">{title}</p>
    {children && <div className="mt-2 text-sm text-muted-foreground">{children}</div>}
  </div>
);

export const NotImplemented = ({ what }: { what: string }) => (
  <div className="rounded-md border border-warn/40 bg-warn/10 p-3 text-sm text-warn">Not implemented: {what}</div>
);
