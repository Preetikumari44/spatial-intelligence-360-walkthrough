"use client";
import { Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Empty, ErrorBox } from "@/components/ui/states";
import { api } from "@/lib/api";
import type { Tour } from "@/lib/types";
import { FloorPlan2D } from "./FloorPlan2D";

const KINDS = ["Hall / Living room", "Bedroom", "Kitchen", "Bathroom", "Dining area", "Balcony", "Other"];

/** Spatial map: viewpoints from the reconstruction, grouped into user-confirmed rooms. Room detection is not automatic. */
export function FloorPlanTab({ projectId, tour, nodeId, onSelect, onOpenTour, onChanged }: {
  projectId: string; tour: Tour; nodeId: string | null; onSelect: (id: string) => void; onOpenTour: () => void; onChanged: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [kind, setKind] = useState(KINDS[0]);
  const [roomId, setRoomId] = useState<string | null>(null);
  const rooms = tour.rooms ?? [];
  const current = tour.nodes.find((n) => n.id === nodeId);
  const activeRoom = rooms.find((r) => r.id === roomId) ?? rooms.find((r) => r.id === current?.roomId) ?? null;
  const outgoing = useMemo(() => tour.connections.filter((c) => c.fromNodeId === nodeId), [tour, nodeId]);
  if (tour.available && tour.nodes.length > 0 && tour.nodes.every((n) => n.hasPose !== true)) {
    return <Empty title="No spatial map for this tour">This walkthrough was built from the video frames alone, so there are no 3D camera positions to map. It becomes available when the advanced 3D reconstruction succeeds. Open the Virtual Walkthrough to move between viewpoints.</Empty>;
  }
  if (!tour.available || !tour.manifest) return <Empty title="No spatial map yet">Upload a walkthrough video and run Reconstruct. The map is built only from real camera poses.</Empty>;

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try { await fn(); onChanged(); } catch (e) { setError((e as Error).message); }
  }
  const createRoom = () => run(async () => {
    if (!name.trim()) return;
    const r = await api<{ id: string }>(`/api/projects/${projectId}/rooms`, { method: "POST", body: JSON.stringify({ name: name.trim(), kind }) });
    if (current) await api(`/api/nodes/${current.id}/room`, { method: "PUT", body: JSON.stringify({ roomId: r.id }) });
    setRoomId(r.id); setName("");
  });
  const assign = (rid: string | null) => run(() => api(`/api/nodes/${current!.id}/room`, { method: "PUT", body: JSON.stringify({ roomId: rid }) }));
  const enterRoom = (rid: string) => {
    const first = tour.nodes.find((n) => n.roomId === rid);
    if (first) enterView(first.id);
  };
  const enterView = (id: string) => { onSelect(id); onOpenTour(); };
  const scale = tour.reconstruction?.status;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <Card className="p-2 text-muted-foreground">
        <FloorPlan2D manifest={tour.manifest} nodes={tour.nodes} connections={tour.connections} nodeId={nodeId} onSelect={enterView} rooms={rooms}
          activeRoomId={activeRoom?.id ?? null} onSelectRoom={(rid) => { setRoomId(rid); enterRoom(rid); }} className="h-[60vh] w-full" />
        <p className="px-2 pb-1 text-xs">{tour.manifest.floorplan.note} Colours show rooms you have assigned; grey viewpoints have no room yet.
          {tour.nodes.some((n) => n.hasPose !== true) && " Frame-only viewpoints remain available through verified connections but have no spatial position to plot."}
        </p>
      </Card>
      <div className="space-y-3 text-sm">
        <Badge tone={scale === "CALIBRATED" ? "info" : "warn"}>{scale === "CALIBRATED" ? "Scale calibrated" : "Uncalibrated model units"}</Badge>
        {error && <ErrorBox message={error} />}
        <Card className="space-y-2 p-3">
          <p className="font-medium">Rooms</p>
          {rooms.length === 0 && <p className="text-xs text-muted-foreground">No rooms yet. Select a viewpoint on the map, name the room below and it is created with that viewpoint inside it. Automatic room detection is not implemented.</p>}
          {rooms.map((r) => (
            <div key={r.id} className={`flex items-center gap-2 rounded-md border px-2 py-1 ${r.id === activeRoom?.id ? "bg-muted" : ""}`}>
              <button className="min-w-0 flex-1 truncate text-left" onClick={() => { setRoomId(r.id); enterRoom(r.id); }}>{r.name} <span className="text-xs text-muted-foreground">· {tour.nodes.filter((n) => n.roomId === r.id).length} viewpoints</span></button>
              <Button size="sm" variant="outline" disabled={!tour.nodes.some((n) => n.roomId === r.id)} onClick={() => enterRoom(r.id)}>Enter</Button>
              <Button size="icon" variant="ghost" aria-label={`Delete room ${r.name}`} onClick={() => run(() => api(`/api/rooms/${r.id}`, { method: "DELETE" }))}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
          <div className="flex gap-2">
            <Input placeholder="New room name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Room name" />
            <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Room type" className="h-10 rounded-md border bg-card px-2">
              {KINDS.map((k) => <option key={k}>{k}</option>)}
            </select>
          </div>
          <Button size="sm" onClick={createRoom} disabled={!current || !name.trim()}>Create room from selected viewpoint</Button>
        </Card>
        {current && (
          <Card className="space-y-2 p-3">
            <p className="font-medium">{current.label}</p>
            <Button size="sm" onClick={() => enterView(current.id)}>Enter this viewpoint</Button>
            {rooms.length > 0 && (
              <label className="block text-xs text-muted-foreground">Room of this viewpoint
                <select className="mt-1 h-9 w-full rounded-md border bg-card px-2 text-sm text-foreground" value={current.roomId ?? ""}
                  onChange={(e) => assign(e.target.value || null)}>
                  <option value="">No room</option>
                  {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
              </label>
            )}
            <div>
              <p className="text-xs text-muted-foreground">Verified navigation links from this viewpoint:</p>
              {outgoing.length === 0 && <p className="text-xs">None.</p>}
              {outgoing.map((c) => (
                <div key={c.id} className="flex items-center justify-between text-xs">
                  <span>→ {tour.nodes.find((n) => n.id === c.toNodeId)?.label}</span>
                  <Button size="sm" variant="ghost" onClick={() => run(() => api(`/api/connections/${c.id}`, { method: "DELETE" }))}>Remove link</Button>
                </div>
              ))}
            </div>
          </Card>
        )}
        <div className="max-h-56 overflow-y-auto rounded-md border">
          {tour.nodes.map((n) => (
            <button key={n.id} onClick={() => enterView(n.id)} className={`block w-full px-3 py-1.5 text-left hover:bg-muted ${n.id === nodeId ? "bg-muted font-medium" : ""}`}>{n.label}{n.roomId ? ` · ${rooms.find((r) => r.id === n.roomId)?.name ?? ""}` : ""}</button>
          ))}
        </div>
      </div>
    </div>
  );
}
