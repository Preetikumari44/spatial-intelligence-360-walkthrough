"use client";
import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Empty, ErrorBox, Spinner } from "@/components/ui/states";
import { api } from "@/lib/api";
import type { Job, Media, Project, Tour } from "@/lib/types";

export interface ProjectData {
  id: string;
  project: Project;
  media: Media[];
  jobs: Job[];
  tour: Tour;
  nodeId: string | null;
  setNodeId: (id: string | null) => void;
  version: number;
  refresh: () => Promise<void>;
}

const KEY = "activeProjectId";
const NODE_KEY = "activeNodeId";

/** Section page wrapper: lets the user pick a project, loads its real data from the API and hands it to the existing panels. */
export function ProjectScope({ title, subtitle, children }: { title: string; subtitle?: string; children: (d: ProjectData) => ReactNode }) {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [id, setId] = useState<string>("");
  const [data, setData] = useState<Omit<ProjectData, "setNodeId" | "refresh"> | null>(null);
  const [nodeId, setNodeId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<{ content: Project[] }>("/api/projects?size=100")
      .then((p) => {
        setProjects(p.content);
        const saved = localStorage.getItem(KEY);
        setId(p.content.find((x) => x.id === saved)?.id ?? p.content[0]?.id ?? "");
      })
      .catch((e) => setError(e.message));
  }, []);

  const refresh = useCallback(async () => {
    if (!id) return;
    try {
      const [project, media, jobs, tour] = await Promise.all([
        api<Project>(`/api/projects/${id}`),
        api<Media[]>(`/api/projects/${id}/media`),
        api<Job[]>(`/api/projects/${id}/jobs`),
        api<Tour>(`/api/projects/${id}/tour`),
      ]);
      setError(null);
      const saved = localStorage.getItem(NODE_KEY);
      setNodeId((cur) => (cur && tour.nodes.some((n) => n.id === cur) ? cur : tour.nodes.find((n) => n.id === saved)?.id ?? tour.nodes[0]?.id ?? null));
      setData((d) => ({ id, project, media, jobs, tour, nodeId: null, version: (d?.version ?? 0) + 1 }));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => { setData(null); refresh(); }, [refresh]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{title}</h1>
          {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
        </div>
        {projects && projects.length > 0 && (
          <label className="text-sm">
            <span className="mr-2 text-muted-foreground">Project</span>
            <select value={id} aria-label="Active project" className="h-9 rounded-md border bg-card px-2 text-sm"
              onChange={(e) => { setId(e.target.value); localStorage.setItem(KEY, e.target.value); }}>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
        )}
      </div>
      {error && <ErrorBox message={error} />}
      {!projects && !error && <Spinner />}
      {projects?.length === 0 && (
        <Empty title="No projects yet"><Link className="text-primary underline" href="/projects">Create a project</Link> to get started.</Empty>
      )}
      {projects && projects.length > 0 && !data && !error && <Spinner />}
      {data && children({ ...data, nodeId, setNodeId: (n) => { setNodeId(n); if (n) localStorage.setItem(NODE_KEY, n); }, refresh })}
    </div>
  );
}
