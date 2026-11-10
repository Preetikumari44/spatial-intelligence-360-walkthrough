"use client";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Empty, ErrorBox, Spinner } from "@/components/ui/states";
import { useBlobUrl } from "@/hooks/useBlobUrl";
import { api } from "@/lib/api";
import { usePrefs } from "@/lib/prefs";
import type { DetectedObject, Measurement, Media } from "@/lib/types";
import { formatLength } from "@/lib/units";

export const statusTone = (s: string) => (s === "VERIFIED" ? "ok" : s === "CALIBRATED" ? "info" : "warn");

export function ImageIntelligence({ projectId, media, version }: { projectId: string; media: Media[]; version: number }) {
  const { unit } = usePrefs();
  const [mediaId, setMediaId] = useState<string | null>(null);
  const [objects, setObjects] = useState<DetectedObject[]>([]);
  const [records, setRecords] = useState<Measurement[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [label, setLabel] = useState("");
  const [realWidth, setRealWidth] = useState("");

  useEffect(() => { if (!mediaId && media.length) setMediaId(media[0].id); }, [media, mediaId]);
  const { url, error: imgError } = useBlobUrl(mediaId ? `/api/media/${mediaId}/content` : null);

  const load = useCallback(async () => {
    if (!mediaId) return;
    setLoading(true);
    try {
      const [o, m] = await Promise.all([
        api<DetectedObject[]>(`/api/projects/${projectId}/objects?mediaId=${mediaId}`),
        api<{ records: Measurement[] }>(`/api/projects/${projectId}/measurements`),
      ]);
      setObjects(o); setRecords(m.records);
    } catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  }, [projectId, mediaId]);
  useEffect(() => { setSelected(null); setNatural(null); load(); }, [load, version]);

  const obj = objects.find((o) => o.id === selected) ?? null;
  useEffect(() => setLabel(obj?.label ?? ""), [obj?.id, obj?.label]);
  const dims = (id: string) => records.filter((r) => r.objectId === id);

  async function saveLabel() {
    if (!obj || !label.trim()) return;
    try { await api(`/api/objects/${obj.id}`, { method: "PATCH", body: JSON.stringify({ label }) }); await load(); } catch (e) { setError((e as Error).message); }
  }
  async function calibrate() {
    if (!obj) return;
    setError(null);
    try {
      await api(`/api/projects/${projectId}/calibration/image`, {
        method: "POST", body: JSON.stringify({ referenceObjectId: obj.id, realWidthMm: Number(realWidth) }),
      });
      setRealWidth("");
      await load();
    } catch (e) { setError((e as Error).message); }
  }

  if (media.length === 0) return <Empty title="No photos uploaded">Upload a photo in “Media & jobs”, then press Analyze.</Empty>;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <div className="space-y-3">
        <select value={mediaId ?? ""} onChange={(e) => setMediaId(e.target.value)} aria-label="Photo" className="h-10 rounded-md border bg-card px-3 text-sm">
          {media.map((m) => <option key={m.id} value={m.id}>{m.originalName}</option>)}
        </select>
        {imgError && <ErrorBox message={imgError} />}
        {!url && !imgError && <Spinner />}
        {url && (
          <div className="relative overflow-hidden rounded-lg border bg-muted">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={url} alt="Uploaded room" className="block h-auto w-full" onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
            {natural && (
              <svg viewBox={`0 0 ${natural.w} ${natural.h}`} className="absolute inset-0 h-full w-full">
                {objects.map((o) => {
                  const on = o.id === selected;
                  const [x1, y1, x2, y2] = o.bbox;
                  return (
                    <g key={o.id} onClick={() => setSelected(o.id)} className="cursor-pointer">
                      {o.polygon && o.polygon.length > 2 && (
                        <polygon points={o.polygon.map((p) => p.join(",")).join(" ")}
                          fill={on ? "rgba(37,99,235,0.45)" : "rgba(37,99,235,0.15)"} stroke={on ? "#2563eb" : "rgba(37,99,235,0.6)"} strokeWidth={on ? natural.w / 250 : natural.w / 600} />
                      )}
                      <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="transparent" stroke={on ? "#f59e0b" : "none"} strokeWidth={natural.w / 400} strokeDasharray={`${natural.w / 80}`} />
                    </g>
                  );
                })}
              </svg>
            )}
          </div>
        )}
        {!loading && objects.length === 0 && url && (
          <p className="text-sm text-muted-foreground">No objects stored for this photo. Press Analyze in “Media & jobs”. The default detector only knows COCO classes (no doors, windows or wardrobes).</p>
        )}
      </div>
      <Card className="h-fit">
        <CardHeader><CardTitle>{obj ? obj.label : "Select an object"}</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          {error && <ErrorBox message={error} />}
          {!obj && <p className="text-muted-foreground">{objects.length} object{objects.length === 1 ? "" : "s"} found. Click one on the photo.</p>}
          {obj && (
            <>
              <p className="text-muted-foreground">Detector: {obj.originalLabel}{obj.confidence != null && ` · ${(obj.confidence * 100).toFixed(0)}% detection confidence`}</p>
              <div className="flex gap-2">
                <Input value={label} onChange={(e) => setLabel(e.target.value)} aria-label="Object label" />
                <Button size="sm" onClick={saveLabel} disabled={label === obj.label}>Save</Button>
              </div>
              <div className="space-y-1">
                {dims(obj.id).length === 0 && <p className="text-muted-foreground">No measurement: metric depth was unavailable or the mask was too small. Calibrate with a reference below.</p>}
                {["width", "height", "depth"].map((k) => {
                  const r = dims(obj.id).find((x) => x.kind === k);
                  if (!r) return null;
                  return (
                    <div key={k} className="flex flex-wrap items-center justify-between gap-1 border-b py-1 last:border-0">
                      <span className="capitalize">{k}</span>
                      <span className="font-medium">{formatLength(r.valueMm, unit)}</span>
                      <Badge tone={statusTone(r.status)}>{r.status.toLowerCase()}</Badge>
                      <span className="w-full text-xs text-muted-foreground">
                        {r.confidence != null ? `reliability ${(r.confidence * 100).toFixed(0)}% (heuristic)` : "no confidence value for this method"}
                      </span>
                    </div>
                  );
                })}
                {dims(obj.id).find((r) => r.note) && <p className="text-xs text-muted-foreground">{dims(obj.id).find((r) => r.note)?.note}</p>}
              </div>
              <div className="rounded-md border p-2">
                <p className="mb-1 font-medium">Use as scale reference</p>
                <p className="mb-2 text-xs text-muted-foreground">Enter this object’s real width (mm). Other objects at a similar distance are rescaled.</p>
                <div className="flex gap-2">
                  <Input type="number" min={1} placeholder="mm" value={realWidth} onChange={(e) => setRealWidth(e.target.value)} aria-label="Real width in millimetres" />
                  <Button size="sm" onClick={calibrate} disabled={!(Number(realWidth) > 0)}>Calibrate</Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
