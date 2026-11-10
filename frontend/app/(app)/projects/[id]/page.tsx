"use client";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { FloorPlanTab } from "@/components/project/FloorPlanTab";
import { ImageIntelligence } from "@/components/project/ImageIntelligence";
import { Inventory } from "@/components/project/Inventory";
import { MeasurementsPanel } from "@/components/project/MeasurementsPanel";
import { MediaPanel } from "@/components/project/MediaPanel";
import { ProjectActions } from "@/components/project/ProjectActions";
import { ReportsPanel } from "@/components/project/ReportsPanel";
import { TourViewer } from "@/components/project/TourViewer";
import { Twin3D } from "@/components/project/Twin3D";
import { ErrorBox, Spinner } from "@/components/ui/states";
import { api } from "@/lib/api";
import type { Job, Media, Project, Tour } from "@/lib/types";
import { cn } from "@/lib/utils";

const TABS = ["Media & jobs", "Image intelligence", "Spatial map", "Virtual walkthrough", "3D digital twin", "Inventory", "Measurements", "Reports"] as const;
type Tab = (typeof TABS)[number];

export default function Workspace() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [media, setMedia] = useState<Media[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [tour, setTour] = useState<Tour | null>(null);
  const [tab, setTab] = useState<Tab>("Media & jobs");
  const [nodeId, setNodeId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const [p, m, j, t] = await Promise.all([
        api<Project>(`/api/projects/${id}`),
        api<Media[]>(`/api/projects/${id}/media`),
        api<Job[]>(`/api/projects/${id}/jobs`),
        api<Tour>(`/api/projects/${id}/tour`),
      ]);
      setProject(p); setMedia(m); setJobs(j); setTour(t);
      setNodeId((cur) => (cur && t.nodes.some((n) => n.id === cur) ? cur : t.nodes[0]?.id ?? null));
      setVersion((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);
  useEffect(() => { refresh(); }, [refresh]);

  if (error) return <ErrorBox message={error} />;
  if (!project || !tour) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">{project.name}</h1>
          <p className="text-sm text-muted-foreground">{project.propertyType} · {project.status.replaceAll("_", " ").toLowerCase()}</p>
        </div>
        <ProjectActions project={project} onError={setError} onRenamed={setProject} onDeleted={() => router.replace("/projects")} />
      </div>
      <div className="-mx-3 overflow-x-auto px-3" role="tablist">
        <div className="flex gap-1 border-b">
          {TABS.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
              className={cn("whitespace-nowrap border-b-2 px-3 py-2 text-sm", tab === t ? "border-primary font-medium" : "border-transparent text-muted-foreground hover:text-foreground")}>{t}</button>
          ))}
        </div>
      </div>
      {tab === "Media & jobs" && <MediaPanel projectId={id} media={media} jobs={jobs} onChanged={refresh} />}
      {tab === "Image intelligence" && <ImageIntelligence projectId={id} media={media.filter((m) => m.kind === "IMAGE")} version={version} />}
      {tab === "Virtual walkthrough" && <TourViewer projectId={id} tour={tour} sourceVideo={media.find((m) => m.id === tour.sourceVideoId) ?? null}
        nodeId={nodeId} onSelect={setNodeId} onBackToMap={() => setTab("Spatial map")} />}
      {tab === "3D digital twin" && <Twin3D projectId={id} tour={tour} nodeId={nodeId} onSelect={(n) => { setNodeId(n); }} />}
      {tab === "Spatial map" && <FloorPlanTab projectId={id} tour={tour} nodeId={nodeId} onSelect={setNodeId} onOpenTour={() => setTab("Virtual walkthrough")} onChanged={refresh} />}
      {tab === "Inventory" && <Inventory projectId={id} media={media} version={version} />}
      {tab === "Measurements" && <MeasurementsPanel projectId={id} tour={tour} version={version} onChanged={refresh} />}
      {tab === "Reports" && <ReportsPanel projectId={id} />}
    </div>
  );
}
