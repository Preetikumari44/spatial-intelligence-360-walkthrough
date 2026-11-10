"use client";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Empty, ErrorBox, Spinner } from "@/components/ui/states";
import { api } from "@/lib/api";
import { usePrefs } from "@/lib/prefs";
import type { DetectedObject, Measurement, Media } from "@/lib/types";
import { formatLength } from "@/lib/units";
import { statusTone } from "./ImageIntelligence";

export function Inventory({ projectId, media, version }: { projectId: string; media: Media[]; version: number }) {
  const { unit } = usePrefs();
  const [objects, setObjects] = useState<DetectedObject[] | null>(null);
  const [records, setRecords] = useState<Measurement[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api<DetectedObject[]>(`/api/projects/${projectId}/objects`),
      api<{ records: Measurement[] }>(`/api/projects/${projectId}/measurements`),
    ]).then(([o, m]) => { setObjects(o); setRecords(m.records); }).catch((e) => setError(e.message));
  }, [projectId, version]);

  if (error) return <ErrorBox message={error} />;
  if (!objects) return <Spinner />;
  if (objects.length === 0) return <Empty title="Inventory is empty">Analyze a photo to populate it.</Empty>;
  const src = (id: string) => media.find((m) => m.id === id)?.originalName ?? "";
  const cell = (id: string, kind: string) => {
    const r = records.find((x) => x.objectId === id && x.kind === kind);
    return r ? <span>{formatLength(r.valueMm, unit)} <Badge tone={statusTone(r.status)}>{r.status[0]}</Badge></span> : "–";
  };
  return (
    <Card className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead className="border-b text-left text-muted-foreground">
          <tr>{["Object", "Photo", "Detect %", "Width", "Height", "Depth"].map((h) => <th key={h} className="p-3 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody>
          {objects.map((o) => (
            <tr key={o.id} className="border-b last:border-0">
              <td className="p-3 font-medium">{o.label}{o.edited && <span className="ml-1 text-xs text-muted-foreground">(edited)</span>}</td>
              <td className="p-3 text-muted-foreground">{src(o.mediaId)}</td>
              <td className="p-3">{o.confidence != null ? (o.confidence * 100).toFixed(0) : "–"}</td>
              <td className="p-3">{cell(o.id, "width")}</td><td className="p-3">{cell(o.id, "height")}</td><td className="p-3">{cell(o.id, "depth")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="p-3 text-xs text-muted-foreground">E = estimated, C = calibrated, V = verified.</p>
    </Card>
  );
}
