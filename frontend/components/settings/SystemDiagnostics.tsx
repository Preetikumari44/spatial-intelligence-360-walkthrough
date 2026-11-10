"use client";
import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BASE } from "@/lib/api";
import type { DevStatus, ServiceInfo } from "@/lib/devAccess";

type Reach = { kind: "loading" } | { kind: "unreachable"; why: string } | { kind: "ok"; status: DevStatus };

const POLL_MS = 10_000;

/** Settings → System Diagnostics: live state of Java, Python and PostgreSQL. Real failures are shown here in full. */
export function SystemDiagnostics() {
  const [reach, setReach] = useState<Reach>({ kind: "loading" });

  const load = useCallback(async () => {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 8000);
    try {
      const res = await fetch(`${BASE}/api/dev/status`, { signal: ctl.signal, cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setReach({ kind: "ok", status: (await res.json()) as DevStatus });
    } catch (e) {
      const why = (e as Error).name === "AbortError" ? "no answer within 8 s" : (e as Error).message;
      setReach({ kind: "unreachable", why });
    } finally {
      clearTimeout(timer);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const status = reach.kind === "ok" ? reach.status : null;
  const svc = status?.services;
  const detailsHidden = status && !svc;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>System Diagnostics</CardTitle>
        <Button size="sm" variant="outline" onClick={load}><RefreshCw className="h-3 w-3" /> Refresh</Button>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {reach.kind === "loading" && <p className="text-muted-foreground">Checking services…</p>}
        {reach.kind === "unreachable" && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-destructive" role="alert">
            Java backend not reachable at {BASE}: {reach.why}. Start it with scripts\start-backend.ps1 and check CORS_ORIGINS / NEXT_PUBLIC_API_URL.
          </div>
        )}
        <div className="grid gap-2 sm:grid-cols-3">
          <Row name="Frontend" info={{ status: "UP", detail: "This page is served by Next.js" }} />
          <Row name="Java backend" info={reach.kind === "unreachable" ? { status: "DOWN", detail: reach.why } : svc?.java} unknownWhy={detailsHidden ? "details are only returned when DEV_ACCESS=true" : undefined} />
          <Row name="PostgreSQL" info={svc?.postgres} unknownWhy="needs the Java backend to be reached" />
          <Row name="Python AI service" info={svc?.python} unknownWhy="needs the Java backend to be reached" />
        </div>
        {svc?.python.capabilities && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-muted-foreground">AI capabilities:</span>
            {Object.entries(svc.python.capabilities).map(([k, v]) => (
              <Badge key={k} tone={v ? "ok" : "neutral"}>{k.replaceAll("_", " ")}: {v ? "available" : "missing"}</Badge>
            ))}
          </div>
        )}
        {status?.devAccess.enabled && (
          <p className="text-muted-foreground">
            Development access is ON (local testing only). Acting as: {status.devAccess.user ? `${status.devAccess.user.email} (${status.devAccess.user.role})` : "no user yet"}. {status.devAccess.message}
          </p>
        )}
        {status && !status.devAccess.enabled && <p className="text-muted-foreground">Development access is OFF; normal sign-in is required.</p>}
        {status?.checkedAt && <p className="text-xs text-muted-foreground">Checked {new Date(status.checkedAt).toLocaleTimeString()} (auto-refresh every {POLL_MS / 1000} s).</p>}
      </CardContent>
    </Card>
  );
}

function Row({ name, info, unknownWhy }: { name: string; info?: ServiceInfo; unknownWhy?: string }) {
  const tone = !info ? "neutral" : info.status === "UP" ? "ok" : "bad";
  const text = !info ? "unknown" : info.status === "UP" ? "connected" : "DOWN";
  const extra = [info?.detail ?? unknownWhy,
    info?.users !== undefined ? `${info.users} user(s)` : null,
    info?.latencyMs !== undefined ? `${info.latencyMs} ms` : null].filter(Boolean).join(" · ");
  return (
    <div className="rounded-md border p-3">
      <div className="flex items-center justify-between"><span className="font-medium">{name}</span><Badge tone={tone}>{text}</Badge></div>
      {extra && <p className="mt-1 break-words text-xs text-muted-foreground">{extra}</p>}
    </div>
  );
}
