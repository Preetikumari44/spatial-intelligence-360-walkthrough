"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Empty, ErrorBox, Spinner } from "@/components/ui/states";
import { api } from "@/lib/api";
import type { Job, Media, Project } from "@/lib/types";

interface Summary { total: number; projects: Project[]; images: number; videos: number; jobs: (Job & { projectName: string })[] }

export default function Overview() {
  const [s, setS] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const p = await api<{ content: Project[]; totalElements: number }>("/api/projects?size=20");
        const per = await Promise.all(p.content.map(async (pr) => ({
          pr,
          media: await api<Media[]>(`/api/projects/${pr.id}/media`),
          jobs: await api<Job[]>(`/api/projects/${pr.id}/jobs`),
        })));
        setS({
          total: p.totalElements,
          projects: p.content,
          images: per.reduce((n, x) => n + x.media.filter((m) => m.kind === "IMAGE").length, 0),
          videos: per.reduce((n, x) => n + x.media.filter((m) => m.kind === "VIDEO").length, 0),
          jobs: per.flatMap((x) => x.jobs.map((j) => ({ ...j, projectName: x.pr.name })))
            .sort((a, b) => b.createdAt.localeCompare(a.createdAt)),
        });
      } catch (e) { setError((e as Error).message); }
    })();
  }, []);

  const done = s?.jobs.filter((j) => j.status === "COMPLETED").length ?? 0;
  const failed = s?.jobs.filter((j) => j.status === "FAILED").length ?? 0;
  const running = (s?.jobs.length ?? 0) - done - failed;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Overview</h1>
        <p className="text-sm text-muted-foreground">Spatial intelligence workspace: photos to measured objects, videos to navigable 3D tours.</p>
      </div>
      {error && <ErrorBox message={error} />}
      {!s && !error && <Spinner />}
      {s && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <Stat label="Projects" value={s.total} href="/projects" />
            <Stat label="Images uploaded" value={s.images} href="/image-intelligence" />
            <Stat label="Videos uploaded" value={s.videos} href="/video-reconstruction" />
            <Stat label="Jobs completed" value={done} href="/video-reconstruction" />
            <Stat label="Jobs running / failed" value={`${running} / ${failed}`} href="/video-reconstruction" />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>Recent projects</CardTitle></CardHeader>
              <CardContent className="space-y-1">
                {s.projects.length === 0 && <Empty title="No projects yet"><Link className="text-primary underline" href="/projects">Create your first project</Link></Empty>}
                {s.projects.slice(0, 6).map((p) => (
                  <Link key={p.id} href={`/projects/${p.id}`} className="flex items-center justify-between rounded-md px-2 py-2 text-sm hover:bg-muted">
                    <span className="truncate font-medium">{p.name}</span>
                    <span className="text-xs text-muted-foreground">{p.propertyType ?? "Property"} · {p.status.replaceAll("_", " ").toLowerCase()}</span>
                  </Link>
                ))}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Processing history</CardTitle></CardHeader>
              <CardContent className="space-y-1">
                {s.jobs.length === 0 && <p className="text-sm text-muted-foreground">No processing jobs yet.</p>}
                {s.jobs.slice(0, 8).map((j) => (
                  <div key={j.id} className="flex items-center gap-2 border-b py-1.5 text-sm last:border-0">
                    <Badge tone={j.status === "COMPLETED" ? "ok" : j.status === "FAILED" ? "bad" : "info"}>{j.status.replaceAll("_", " ")}</Badge>
                    <span className="min-w-0 flex-1 truncate">{j.type === "IMAGE_ANALYSIS" ? "Image analysis" : "Video reconstruction"} · {j.projectName}</span>
                    <span className="text-xs text-muted-foreground">{new Date(j.createdAt).toLocaleString()}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, href }: { label: string; value: number | string; href: string }) {
  return (
    <Link href={href}>
      <Card className="p-4 transition-shadow hover:shadow-md">
        <p className="text-2xl font-semibold">{value}</p>
        <p className="text-xs text-muted-foreground">{label}</p>
      </Card>
    </Link>
  );
}
