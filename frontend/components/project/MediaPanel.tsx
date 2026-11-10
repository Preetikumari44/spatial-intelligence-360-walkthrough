"use client";
import { RotateCcw, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, ErrorBox } from "@/components/ui/states";
import { api, watchJob } from "@/lib/api";
import type { Job, Media } from "@/lib/types";

const TERMINAL = ["COMPLETED", "FAILED", "CANCELLED"];
const tone = (s: string) => (s === "COMPLETED" ? "ok" : s === "FAILED" ? "bad" : s === "CANCELLED" ? "warn" : "info");

function JobRow({ job, onChanged }: { job: Job; onChanged: () => void }) {
  const [live, setLive] = useState(job);
  useEffect(() => setLive(job), [job]);
  useEffect(() => {
    if (TERMINAL.includes(job.status)) return;
    return watchJob(job.id, (j) => {
      setLive(j);
      if (TERMINAL.includes(j.status)) onChanged();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id]);

  async function retry() {
    await api(`/api/jobs/${job.id}/retry`, { method: "POST" });
    onChanged();
  }
  async function cancel() {
    await api(`/api/jobs/${job.id}/cancel`, { method: "POST" });
    onChanged();
  }
  const running = !TERMINAL.includes(live.status);
  return (
    <div className="border-b py-2 text-sm last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={tone(live.status)}>{live.status.replaceAll("_", " ")}</Badge>
        <span className="font-medium">{live.type === "IMAGE_ANALYSIS" ? "Image analysis" : "Video reconstruction"}</span>
        <span className="min-w-0 flex-1 truncate text-muted-foreground">{live.status === "FAILED" ? live.error : live.message}</span>
        {running && live.type !== "IMAGE_ANALYSIS" && <Button size="sm" variant="outline" onClick={cancel}><Square className="h-3 w-3" /> Cancel</Button>}
        {(live.status === "FAILED" || live.status === "CANCELLED") && <Button size="sm" variant="outline" onClick={retry}><RotateCcw className="h-3 w-3" /> Retry</Button>}
      </div>
      {running && typeof live.progress === "number" && live.progress > 0 && (
        <div className="mt-1 h-1.5 overflow-hidden rounded bg-muted" role="progressbar" aria-valuenow={live.progress} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full bg-primary transition-all" style={{ width: `${live.progress}%` }} />
        </div>
      )}
    </div>
  );
}

export function MediaPanel({ projectId, media, jobs, onChanged }: { projectId: string; media: Media[]; jobs: Job[]; onChanged: () => void }) {
  const imgInput = useRef<HTMLInputElement>(null);
  const vidInput = useRef<HTMLInputElement>(null);
  const [is360, setIs360] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run<T>(label: string, fn: () => Promise<T>) {
    setBusy(label); setError(null);
    try { await fn(); onChanged(); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  }

  const uploadImages = () => run("Uploading images", async () => {
    const files = imgInput.current?.files;
    if (!files?.length) return;
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    await api(`/api/projects/${projectId}/images`, { method: "POST", body: fd });
    if (imgInput.current) imgInput.current.value = "";
  });
  const uploadVideo = () => run("Uploading, validating and starting reconstruction", async () => {
    const f = vidInput.current?.files?.[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    fd.append("is360", String(is360));
    const uploaded = await api<Media>(`/api/projects/${projectId}/videos`, { method: "POST", body: fd });
    if (vidInput.current) vidInput.current.value = "";
    onChanged();
    try {
      await api<Job>("/api/ai/video-reconstruction", {
        method: "POST",
        body: JSON.stringify({ projectId, mediaId: uploaded.id }),
      });
    } catch (e) {
      throw new Error(`Video uploaded, but reconstruction could not be queued: ${(e as Error).message}. You can retry using Reconstruct.`);
    }
  });
  const start = (m: Media) => run("Queueing", () =>
    api(m.kind === "IMAGE" ? "/api/ai/image-analysis" : "/api/ai/video-reconstruction", {
      method: "POST", body: JSON.stringify({ projectId, mediaId: m.id }),
    }));

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-4">
        <Card>
          <CardHeader><CardTitle>Upload photos</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <input ref={imgInput} type="file" multiple accept="image/jpeg,image/png,image/webp" className="block w-full text-sm" aria-label="Photos" />
            <Button size="sm" onClick={uploadImages} disabled={!!busy}>Upload photos</Button>
            <p className="text-xs text-muted-foreground">Supported: JPG, PNG, WebP, up to 25 MB each.</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Upload walkthrough video</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <input ref={vidInput} type="file" accept="video/mp4,video/quicktime,video/x-msvideo,.avi,video/webm,video/x-matroska" className="block w-full text-sm" aria-label="Video" />
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={is360} onChange={(e) => setIs360(e.target.checked)} /> 360° equirectangular video (2:1)</label>
            <Button size="sm" onClick={uploadVideo} disabled={!!busy}>Upload video</Button>
            <p className="text-xs text-muted-foreground">Supported: MP4, MOV, AVI, WebM, MKV, up to 2 GB. Upload progress and processing status appear below and in the job list.</p>
            <p className="text-xs text-muted-foreground">
              Ordinary footage creates a viewpoint tour, not a 360° panorama. For a real panorama, upload the original 2:1 equirectangular 360° video and check the box. 3D reconstruction needs slow camera movement, overlapping views, and visible scene detail.
            </p>
            <p className="text-xs text-muted-foreground">After validation, reconstruction starts automatically. Multiple videos are not merged into one reconstruction.</p>
          </CardContent>
        </Card>
        {busy && <p className="text-sm text-muted-foreground" role="status">{busy}…</p>}
        {error && <ErrorBox message={error} />}
      </div>
      <div className="space-y-4">
        <Card>
          <CardHeader><CardTitle>Media</CardTitle></CardHeader>
          <CardContent>
            {media.length === 0 ? <Empty title="Nothing uploaded yet" /> : media.map((m) => (
              <div key={m.id} className="flex items-center gap-2 border-b py-2 text-sm last:border-0">
                <Badge>{m.kind === "IMAGE" ? "Photo" : m.is360 ? "360° video" : "Video"}</Badge>
                <span className="min-w-0 flex-1 truncate">{m.originalName}</span>
                <span className="hidden text-xs text-muted-foreground sm:inline">
                  {m.kind === "VIDEO" && m.durationSec ? `${m.durationSec.toFixed(0)}s · ${m.width}×${m.height}` : `${(m.sizeBytes / 1048576).toFixed(1)} MB`}
                </span>
                <Button size="sm" variant="outline" disabled={!!busy} onClick={() => start(m)}>{m.kind === "IMAGE" ? "Analyze" : "Reconstruct"}</Button>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Processing jobs</CardTitle></CardHeader>
          <CardContent>
            {jobs.length === 0 ? <Empty title="No jobs yet" /> : jobs.map((j) => <JobRow key={j.id} job={j} onChanged={onChanged} />)}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
