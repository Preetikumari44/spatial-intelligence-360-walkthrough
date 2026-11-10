"use client";
import { Box, Eye, EyeOff } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { backendReachable } from "@/lib/api";

/** Centered card used by /login and /register, with a live backend reachability line. */
export function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  const [status, setStatus] = useState<{ ok: boolean; detail: string } | null>(null);
  useEffect(() => { backendReachable().then(setStatus); }, []);
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="mb-1 flex items-center gap-2 font-semibold"><Box className="h-5 w-5 text-primary" /> Spatial Intelligence</div>
          <CardTitle className="text-xl">{title}</CardTitle>
          <p className="text-sm text-muted-foreground">{subtitle}</p>
        </CardHeader>
        <CardContent className="space-y-3">
          {children}
          {status && !status.ok && (
            <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">{status.detail}</p>
          )}
          {status?.ok && <p className="text-xs text-muted-foreground">{status.detail}</p>}
        </CardContent>
      </Card>
    </main>
  );
}

export function PasswordInput({ value, onChange, label, autoComplete, placeholder }: {
  value: string; onChange: (v: string) => void; label: string; autoComplete: string; placeholder?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input type={show ? "text" : "password"} required value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}
        autoComplete={autoComplete} placeholder={placeholder ?? label} className="pr-10" />
      <button type="button" aria-label={show ? "Hide password" : "Show password"} onClick={() => setShow((s) => !s)}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
        {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
}
