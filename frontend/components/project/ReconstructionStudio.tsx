"use client";
import { Download, FileText, Square } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, ErrorBox, Spinner } from "@/components/ui/states";
import { api, blobUrl, download, fetchBuffer, projectFile } from "@/lib/api";
import type { AiCapabilities, FramesInfo, Job, ReconOutput, ReconOutputs, ReconStage } from "@/lib/types";

// three.js is large; load the viewers only when a preview tab is opened
const PlyViewer = dynamic(() => import("./ModelViewers").then((m) => m.PlyViewer), { ssr: false, loading: () => <Spinner /> });
const SplatViewer = dynamic(() => import("./ModelViewers").then((m) => m.SplatViewer), { ssr: false, loading: () => <Spinner /> });

const STAGES = [
  { status: "PROCESSING", label: "Frame extraction" },
  { status: "GENERATING_TOUR", label: "Virtual tour" },
  { status: "RECONSTRUCTING", label: "Camera poses (advanced 3D)" },
  { status: "GENERATING_MODEL", label: "Point cloud and mesh" },
  { status: "TRAINING_SPLAT", label: "Gaussian splats" },
];
const TERMINAL = ["COMPLETED", "FAILED", "CANCELLED"];
const stageTone = (s?: string) => (s === "ok" ? "ok" : s === "failed" ? "bad" : s === "unavailable" || s === "skipped" ? "warn" : "neutral") as "ok" | "bad" | "warn" | "neutral";
const mb = (b: number) => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);

function ExecutionCard({ caps, error }: { caps: AiCapabilities | null; error: string | null }) {
  return (
    <Card>
      <CardHeader><CardTitle>Execution hardware</CardTitle></CardHeader>
      <CardContent className="space-y-2 text-sm">
        {error && <ErrorBox message={error} />}
        {!caps && !error && <Spinner />}
        {caps && (
          <>
            <div className="flex flex-wrap gap-2">
              <Badge tone="info">{caps.cpu.threads_used} CPU threads of {caps.cpu.logical_cores}</Badge>
              <Badge tone={caps.devices.open3d_device.startsWith("SYCL") ? "ok" : "neutral"}>Open3D: {caps.devices.open3d_device.startsWith("SYCL") ? "Intel XPU (SYCL)" : "CPU"}</Badge>
              <Badge tone={caps.devices.torch_device === "xpu" ? "ok" : "neutral"}>Gaussian training: {caps.devices.torch_device === "xpu" ? "Intel XPU" : "CPU"}</Badge>
              <Badge tone={caps.colmap.found ? "ok" : "neutral"}>Camera poses: {caps.sfm_backend === "colmap" ? "COLMAP (CPU)" : "OpenCV (CPU)"}</Badge>
              {caps.memory.available_mb != null && <Badge>{(caps.memory.available_mb / 1024).toFixed(1)} GB RAM free</Badge>}
            </div>
            <p className="text-muted-foreground">
              {caps.gpu.intel.length ? `Intel graphics detected: ${caps.gpu.intel.join(", ")}.` : "No Intel graphics adapter was identified."}
              {" "}No CUDA or NVIDIA GPU is used.
            </p>
            {caps.devices.notes.map((n) => <p key={n} className="text-xs text-muted-foreground">{n}</p>)}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function JobCard({ job, logs, onToggleLogs, onChanged }: { job: Job; logs: string | null; onToggleLogs: () => void; onChanged: () => void }) {
  const idx = STAGES.findIndex((s) => s.status === job.status);
  const done = job.status === "COMPLETED";
  const running = !TERMINAL.includes(job.status);
  const [err, setErr] = useState<string | null>(null);
  async function cancel() {
    setErr(null);
    try { await api(`/api/jobs/${job.id}/cancel`, { method: "POST" }); onChanged(); } catch (e) { setErr((e as Error).message); }
  }
  return (
    <Card>
      <CardHeader><CardTitle>Reconstruction progress</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <ol className="flex flex-wrap gap-2">
          {STAGES.map((s, i) => {
            const state = done ? "done" : job.status === "QUEUED" ? "todo" : i < idx || (idx === -1 && job.status === "CALIBRATING" && i <= 2) ? "done" : i === idx ? "active" : "todo";
            const failedHere = (job.status === "FAILED" || job.status === "CANCELLED") && state === "active";
            return <li key={s.status}><Badge tone={failedHere ? "bad" : state === "done" ? "ok" : state === "active" ? "info" : "neutral"}>{s.label}</Badge></li>;
          })}
        </ol>
        {(running || job.progress) ? (
          <div className="h-2 overflow-hidden rounded bg-muted" role="progressbar" aria-valuenow={job.progress ?? 0} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full bg-primary transition-all" style={{ width: `${job.progress ?? 0}%` }} />
          </div>
        ) : null}
        <p className={job.status === "FAILED" ? "text-destructive" : "text-muted-foreground"}>
          {job.status === "FAILED" ? job.error : job.message ?? job.status}
        </p>
        {(done || idx >= 1 || job.status === "CALIBRATING") && (
          <p className="text-sm">
            <Link href="/walkthrough" className="font-medium text-primary underline">Open Virtual Walkthrough</Link>
            <span className="text-muted-foreground"> — available as soon as the tour step finishes; it does not wait for the advanced 3D steps.</span>
          </p>
        )}
        <div className="flex gap-2">
          {running && <Button size="sm" variant="outline" onClick={cancel}><Square className="h-3 w-3" /> Cancel job</Button>}
          <Button size="sm" variant="outline" onClick={onToggleLogs}><FileText className="h-3 w-3" /> {logs == null ? "Show log" : "Hide log"}</Button>
        </div>
        {err && <ErrorBox message={err} />}
        {logs != null && <pre className="max-h-56 overflow-auto rounded bg-muted p-2 text-xs">{logs || "No log lines yet."}</pre>}
      </CardContent>
    </Card>
  );
}

function FramesCard({ projectId, jobId }: { projectId: string; jobId: string }) {
  const [info, setInfo] = useState<FramesInfo | null>(null);
  const [sheet, setSheet] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setInfo(null); setSheet(null); setError(null);
    const base = `projects/${projectId}/jobs/${jobId}/frames`;
    fetchBuffer(projectFile(projectId, `${base}/frames.json`))
      .then(async (buf) => {
        const j = JSON.parse(new TextDecoder().decode(buf)) as FramesInfo;
        if (!alive) return;
        setInfo(j);
        if (j.summary.preview) setSheet(await blobUrl(projectFile(projectId, j.summary.preview)));
      })
      .catch(() => { if (alive) setError("Frames are not available yet (extraction has not finished, or the job failed before it)."); });
    return () => { alive = false; };
  }, [projectId, jobId]);
  if (error) return <Card><CardHeader><CardTitle>Frame extraction</CardTitle></CardHeader><CardContent><Empty title={error} /></CardContent></Card>;
  if (!info) return <Card><CardContent><Spinner /></CardContent></Card>;
  const s = info.summary;
  return (
    <Card>
      <CardHeader><CardTitle>Frame extraction</CardTitle></CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex flex-wrap gap-2">
          <Badge tone="ok">{s.kept} frames kept</Badge>
          {s.sampled != null && <Badge>{s.sampled} sampled</Badge>}
          <Badge>{s.dropped_blur ?? 0} blurry removed</Badge>
          <Badge>{s.dropped_duplicate ?? 0} duplicates removed</Badge>
          {s.settings && <Badge>{s.settings.effective_fps} fps · max {s.settings.max_side_px}px</Badge>}
        </div>
        {s.warnings?.map((w) => <p key={w} className="text-xs text-warn">{w}</p>)}
        {sheet && /* eslint-disable-next-line @next/next/no-img-element */ <img src={sheet} alt="Contact sheet of the kept frames" className="w-full rounded border" />}
      </CardContent>
    </Card>
  );
}

type Tab = "points" | "mesh" | "splat" | "render";

function Previews({ projectId, outputs }: { projectId: string; outputs: ReconOutputs }) {
  const [tab, setTab] = useState<Tab>("points");
  const [img, setImg] = useState<string | null>(null);
  const report = outputs.report;
  const files = report?.outputs ?? [];
  const find = (...keys: string[]) => keys.map((k) => files.find((o) => o.key === k)).find(Boolean);
  const cloud = find("pointcloud_dense", "pointcloud");
  const mesh = find("mesh_ply");
  const splat = find("gaussian_splat");
  const render = find("splat_open3d", "splat_preview");
  const stage = (k: string): ReconStage | undefined => report?.stages[k];

  useEffect(() => {
    setImg(null);
    if (tab !== "render" || !render) return;
    let alive = true;
    blobUrl(projectFile(projectId, render.path)).then((u) => { if (alive) setImg(u); }).catch(() => undefined);
    return () => { alive = false; };
  }, [tab, render?.path, projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  const tabs: { id: Tab; label: string; file?: ReconOutput; stage?: ReconStage }[] = [
    { id: "points", label: "Point cloud", file: cloud as ReconOutput | undefined, stage: stage("point_cloud") },
    { id: "mesh", label: "Mesh", file: mesh as ReconOutput | undefined, stage: stage("mesh") },
    { id: "splat", label: "Gaussian splat", file: splat as ReconOutput | undefined, stage: stage("gaussian_splat") },
    { id: "render", label: "Splat render", file: render as ReconOutput | undefined, stage: stage("gaussian_splat") },
  ];
  const cur = tabs.find((t) => t.id === tab)!;
  return (
    <Card>
      <CardHeader><CardTitle>3D previews</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2" role="tablist">
          {tabs.map((t) => (
            <Button key={t.id} size="sm" role="tab" aria-selected={t.id === tab} variant={t.id === tab ? "default" : "outline"} onClick={() => setTab(t.id)}>
              {t.label} {t.stage && <Badge tone={stageTone(t.stage.status)} className="ml-1">{t.stage.status}</Badge>}
            </Button>
          ))}
        </div>
        {cur.stage && cur.stage.message && <p className="text-xs text-muted-foreground">{cur.stage.message}{cur.stage.device_used ? ` · device: ${cur.stage.device_used}` : ""}</p>}
        {!cur.file && <Empty title={cur.stage ? `No file: ${cur.stage.status}` : "Not generated yet"} />}
        {cur.file && tab === "points" && <PlyViewer projectId={projectId} path={cur.file.path} mode="points" />}
        {cur.file && tab === "mesh" && <PlyViewer projectId={projectId} path={cur.file.path} mode="mesh" />}
        {cur.file && tab === "splat" && <SplatViewer projectId={projectId} path={cur.file.path} />}
        {cur.file && tab === "render" && (img
          // eslint-disable-next-line @next/next/no-img-element
          ? <img src={img} alt="Gaussian splat render" className="w-full rounded border" /> : <Spinner />)}
        {tab === "splat" && cur.file && <p className="text-xs text-muted-foreground">In-browser preview of the trained Gaussians (a compact CPU-trained model). Drag to orbit.</p>}
        {tab === "render" && !!report?.stages.gaussian_splat?.rendering && (
          <p className="text-xs text-muted-foreground">
            {(report.stages.gaussian_splat.rendering as { open3d?: { ok: boolean; message: string } }).open3d?.ok
              ? "Rendered by Open3D's Gaussian splat renderer."
              : `Open3D's renderer was not available (${(report.stages.gaussian_splat.rendering as { open3d?: { message: string } }).open3d?.message?.slice(0, 140)}). Showing the built-in rasteriser instead.`}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Downloads({ projectId, files }: { projectId: string; files: ReconOutput[] }) {
  const [err, setErr] = useState<string | null>(null);
  if (!files.length) return null;
  return (
    <Card>
      <CardHeader><CardTitle>Downloads</CardTitle></CardHeader>
      <CardContent className="space-y-1 text-sm">
        {files.map((f) => (
          <div key={f.key} className="flex items-center gap-2 border-b py-1 last:border-0">
            <span className="min-w-0 flex-1 truncate">{f.label}</span>
            <span className="text-xs text-muted-foreground">{f.path.split("/").pop()} · {mb(f.size_bytes)}</span>
            <Button size="sm" variant="outline" aria-label={`Download ${f.label}`}
                    onClick={() => download(projectFile(projectId, f.path), f.path.split("/").pop() ?? f.key).catch((e: Error) => setErr(e.message))}>
              <Download className="h-3 w-3" />
            </Button>
          </div>
        ))}
        {err && <ErrorBox message={err} />}
      </CardContent>
    </Card>
  );
}

export function ReconstructionStudio({ projectId, jobs, onChanged }: { projectId: string; jobs: Job[]; onChanged: () => void }) {
  const [caps, setCaps] = useState<AiCapabilities | null>(null);
  const [capsError, setCapsError] = useState<string | null>(null);
  const [outputs, setOutputs] = useState<ReconOutputs | null>(null);
  const [logs, setLogs] = useState<string | null>(null);
  const job = jobs[0];
  const jobId = job?.id;

  useEffect(() => {
    api<AiCapabilities>("/api/ai/capabilities").then(setCaps).catch((e: Error) => setCapsError(`AI service not reachable: ${e.message}`));
  }, []);

  const loadOutputs = useCallback(() => {
    api<ReconOutputs>(`/api/projects/${projectId}/reconstruction/outputs`).then(setOutputs).catch(() => setOutputs({ available: false }));
  }, [projectId]);
  useEffect(() => { loadOutputs(); }, [loadOutputs, job?.status, jobId]);

  const running = !!job && !TERMINAL.includes(job.status);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(loadOutputs, 5000);
    return () => clearInterval(t);
  }, [running, loadOutputs]);

  const toggleLogs = async () => {
    if (logs != null) return setLogs(null);
    try { setLogs(new TextDecoder().decode(await fetchBuffer(`/api/jobs/${jobId}/logs`))); } catch (e) { setLogs((e as Error).message); }
  };
  useEffect(() => {
    if (logs == null || !running) return;
    const t = setInterval(async () => { try { setLogs(new TextDecoder().decode(await fetchBuffer(`/api/jobs/${jobId}/logs`))); } catch { /* keep the last text */ } }, 3000);
    return () => clearInterval(t);
  }, [logs == null, running, jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-4">
      <ExecutionCard caps={caps} error={capsError} />
      {!job && <Card><CardContent><Empty title="Upload a video and press Reconstruct to see progress and 3D previews here" /></CardContent></Card>}
      {job && (
        <div className="grid gap-4 lg:grid-cols-2">
          <JobCard job={job} logs={logs} onToggleLogs={toggleLogs} onChanged={onChanged} />
          <FramesCard projectId={projectId} jobId={job.id} />
        </div>
      )}
      {outputs?.available && outputs.report && (
        <>
          <Previews projectId={projectId} outputs={outputs} />
          <Downloads projectId={projectId} files={outputs.report.outputs} />
        </>
      )}
    </div>
  );
}
