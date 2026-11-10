"use client";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Empty, ErrorBox } from "@/components/ui/states";
import { api } from "@/lib/api";
import { usePrefs } from "@/lib/prefs";
import type { DetectedObject, Measurement, Reconstruction, Tour } from "@/lib/types";
import { formatLength } from "@/lib/units";
import { statusTone } from "./ImageIntelligence";

export function MeasurementsPanel({ projectId, tour, version, onChanged }: { projectId: string; tour: Tour; version: number; onChanged: () => void }) {
  const { unit } = usePrefs();
  const [records, setRecords] = useState<Measurement[]>([]);
  const [recon, setRecon] = useState<Reconstruction | null>(null);
  const [objects, setObjects] = useState<DetectedObject[]>([]);
  const [history, setHistory] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [dist, setDist] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api<{ records: Measurement[]; reconstruction: Reconstruction }>(`/api/projects/${projectId}/measurements?history=${history}`),
      api<DetectedObject[]>(`/api/projects/${projectId}/objects`),
    ]).then(([m, o]) => { setRecords(m.records); setRecon(m.reconstruction); setObjects(o); }).catch((e) => setError(e.message));
  }, [projectId, history, version]);

  const name = (id?: string) => objects.find((o) => o.id === id)?.label ?? "–";
  async function saveEdit(id: string) {
    setError(null);
    try { await api(`/api/measurements/${id}`, { method: "PATCH", body: JSON.stringify({ valueMm: Number(value), note: "Entered by user" }) }); setEditing(null); onChanged(); }
    catch (e) { setError((e as Error).message); }
  }
  async function calibrate() {
    setError(null);
    try {
      await api(`/api/projects/${projectId}/calibration/video`, { method: "POST", body: JSON.stringify({ nodeAId: a, nodeBId: b, realDistanceMm: Number(dist) }) });
      onChanged();
    } catch (e) { setError((e as Error).message); }
  }

  return (
    <div className="space-y-4">
      {error && <ErrorBox message={error} />}
      <Card>
        <CardHeader><CardTitle>Reconstruction extents</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          {!recon?.available ? <p className="text-muted-foreground">No reconstruction yet.</p> : (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <Badge tone={recon.status === "CALIBRATED" ? "info" : "warn"}>{recon.status?.toLowerCase()}</Badge>
                {(["x", "y", "z"] as const).map((ax) => (
                  <span key={ax}>{ax === "y" ? "Vertical" : ax === "x" ? "Along" : "Across"}:{" "}
                    <b>{recon.extentsMm ? formatLength(recon.extentsMm[ax], unit) : `${recon.extentsModelUnits![ax].toFixed(2)} units`}</b></span>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">{recon.note}</p>
              <div className="rounded-md border p-2">
                <p className="mb-1 font-medium">Set real-world scale</p>
                <p className="mb-2 text-xs text-muted-foreground">Pick two viewpoints you physically measured between (e.g. with a tape), then enter that distance in mm.</p>
                <div className="flex flex-col gap-2 sm:flex-row">
                  {[[a, setA], [b, setB]].map(([v, set], i) => (
                    <select key={i} value={v as string} onChange={(e) => (set as (s: string) => void)(e.target.value)} aria-label={`Viewpoint ${i ? "B" : "A"}`} className="h-10 rounded-md border bg-card px-2 text-sm">
                      <option value="">Viewpoint {i ? "B" : "A"}</option>
                      {tour.nodes.map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}
                    </select>
                  ))}
                  <Input type="number" min={1} placeholder="Distance (mm)" value={dist} onChange={(e) => setDist(e.target.value)} aria-label="Real distance in millimetres" />
                  <Button onClick={calibrate} disabled={!a || !b || a === b || !(Number(dist) > 0)}>Apply</Button>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">Camera positions from video SfM carry error; a single reference gives a rough scale, not survey accuracy.</p>
              </div>
            </>
          )}
        </CardContent>
      </Card>
      <Card className="overflow-x-auto">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Object measurements</CardTitle>
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} /> Show history</label>
        </CardHeader>
        {records.length === 0 ? <div className="p-4"><Empty title="No measurements" /></div> : (
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b text-left text-muted-foreground"><tr>{["Object", "Dimension", "Value", "Status", "Reliability", "Source", "When", ""].map((h) => <th key={h} className="p-3 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {[...records].reverse().map((r) => (
                <tr key={r.id} className="border-b last:border-0">
                  <td className="p-3">{name(r.objectId)}</td><td className="p-3 capitalize">{r.kind}</td>
                  <td className="p-3 font-medium">{editing === r.id
                    ? <Input className="h-8 w-28" type="number" value={value} onChange={(e) => setValue(e.target.value)} aria-label="Value in mm" />
                    : formatLength(r.valueMm, unit)}</td>
                  <td className="p-3"><Badge tone={statusTone(r.status)}>{r.status.toLowerCase()}</Badge></td>
                  <td className="p-3">{r.confidence != null ? `${(r.confidence * 100).toFixed(0)}%` : "n/a"}</td>
                  <td className="p-3 text-xs text-muted-foreground">{r.source}</td>
                  <td className="p-3 text-xs text-muted-foreground">{new Date(r.createdAt).toLocaleString()}</td>
                  <td className="p-3">{editing === r.id
                    ? <Button size="sm" onClick={() => saveEdit(r.id)} disabled={!(Number(value) > 0)}>Save mm</Button>
                    : <Button size="sm" variant="ghost" onClick={() => { setEditing(r.id); setValue(String(Math.round(r.valueMm))); }}>Edit</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="p-3 text-xs text-muted-foreground">Editing records your own measured value as “verified”; earlier values stay in history.</p>
      </Card>
    </div>
  );
}
