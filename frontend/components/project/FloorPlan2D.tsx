"use client";
import { Minus, Plus, RotateCcw } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { Manifest, NavConnection, NavNode, Room } from "@/lib/types";

const PALETTE = ["#2563eb", "#16a34a", "#db2777", "#9333ea", "#ea580c", "#0891b2", "#ca8a04", "#4f46e5"];
export const roomColor = (rooms: Room[] | undefined, roomId?: string | null) => {
  const i = rooms?.findIndex((r) => r.id === roomId) ?? -1;
  return i >= 0 ? PALETTE[i % PALETTE.length] : "#64748b";
};

/** Point-density map with camera poses and verified graph links; this is not a vector floor plan. */
export function FloorPlan2D({ manifest, nodes, connections, nodeId, onSelect, rooms, activeRoomId, onSelectRoom, className }: {
  manifest: Manifest; nodes: NavNode[]; connections: NavConnection[]; nodeId: string | null; onSelect: (id: string) => void;
  rooms?: Room[]; activeRoomId?: string | null; onSelectRoom?: (id: string) => void; className?: string;
}) {
  const { minx, maxx, minz, maxz } = manifest.floorplan.bounds;
  const span = Math.max(maxx - minx, maxz - minz, 1e-6);
  const pad = span * 0.06;
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const w = (maxx - minx + 2 * pad) / zoom, h = (maxz - minz + 2 * pad) / zoom;
  const cx = (minx + maxx) / 2 + pan.x, cz = (minz + maxz) / 2 + pan.y;
  const vb = `${cx - w / 2} ${cz - h / 2} ${w} ${h}`;
  const dots = useMemo(() => manifest.floorplan.points.map(([x, z]) => `M${x} ${z}h0`).join(""), [manifest]);
  const r = (span * 0.014) / Math.sqrt(zoom);
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const spatialNodes = nodes.filter((node) => node.hasPose === true);
  const links = [...new Map(connections.filter((c) => c.hotspot.verified === true)
    .map((c) => {
      const key = [c.fromNodeId, c.toNodeId].sort().join(":");
      return [key, c] as const;
    })).values()];
  const labels = useMemo(() => (rooms ?? []).map((room) => {
    const mine = nodes.filter((n) => n.roomId === room.id && n.hasPose === true);
    if (!mine.length) return null;
    return { room, x: mine.reduce((a, n) => a + n.x, 0) / mine.length, z: mine.reduce((a, n) => a + n.z, 0) / mine.length, count: mine.length };
  }).filter(Boolean) as { room: Room; x: number; z: number; count: number }[], [rooms, nodes]);

  const reset = () => { setZoom(1); setPan({ x: 0, y: 0 }); };
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!drag.current || zoom <= 1) return;
    const box = e.currentTarget.getBoundingClientRect();
    const dx = ((e.clientX - drag.current.x) / box.width) * w, dz = ((e.clientY - drag.current.y) / box.height) * h;
    if (Math.abs(dx) + Math.abs(dz) > 0) drag.current.moved = true;
    drag.current.x = e.clientX; drag.current.y = e.clientY;
    setPan((p) => ({ x: p.x - dx, y: p.y - dz }));
  };

  return (
    <div className="relative">
      <svg viewBox={vb} className={`${className ?? ""} touch-none`} role="img" aria-label="Spatial map with rooms and viewpoints"
        onWheel={(e) => setZoom((z) => Math.min(8, Math.max(1, z * (e.deltaY < 0 ? 1.15 : 0.87))))}
        onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, moved: false }; }}
        onPointerMove={onMove} onPointerUp={() => { drag.current = null; }} onPointerLeave={() => { drag.current = null; }}>
        <path d={dots} stroke="currentColor" strokeOpacity={0.35} strokeWidth={span * 0.006} strokeLinecap="round" fill="none" />
        {links.map((link) => {
          const a = nodeById.get(link.fromNodeId), b = nodeById.get(link.toNodeId);
          if (!a || !b || a.hasPose !== true || b.hasPose !== true) return null;
          return <line key={link.id} x1={a.x} y1={a.z} x2={b.x} y2={b.z}
            stroke="#2563eb" strokeOpacity={0.65} strokeWidth={span * 0.004} />;
        })}
        {spatialNodes.map((n) => {
          const on = n.id === nodeId;
          const inRoom = !!activeRoomId && n.roomId === activeRoomId;
          return (
            <g key={n.id} onClick={() => { if (!drag.current?.moved) onSelect(n.id); }} className="cursor-pointer">
              <title>{n.label}{n.roomId ? ` · ${rooms?.find((x) => x.id === n.roomId)?.name ?? ""}` : ""}</title>
              <circle cx={n.x} cy={n.z} r={r * 2.2} fill="transparent" />
              {inRoom && <circle cx={n.x} cy={n.z} r={r * 2.4} fill={roomColor(rooms, n.roomId)} fillOpacity={0.25} />}
              <circle cx={n.x} cy={n.z} r={on ? r * 1.6 : r} fill={on ? "#f59e0b" : roomColor(rooms, n.roomId)} />
              {on && <line x1={n.x} y1={n.z} x2={n.x + Math.cos(n.headingRad) * r * 4} y2={n.z + Math.sin(n.headingRad) * r * 4} stroke="#f59e0b" strokeWidth={r * 0.6} />}
            </g>
          );
        })}
        {labels.map(({ room, x, z, count }) => (
          <g key={room.id} onClick={() => onSelectRoom?.(room.id)} className={onSelectRoom ? "cursor-pointer" : ""}>
            <text x={x} y={z - r * 3} textAnchor="middle" fontSize={r * 3.2} fontWeight={room.id === activeRoomId ? 700 : 500}
              fill={roomColor(rooms, room.id)} stroke="white" strokeWidth={r * 0.5} paintOrder="stroke">{room.name} ({count})</text>
          </g>
        ))}
      </svg>
      <div className="absolute right-1 top-1 flex flex-col gap-1">
        <button className="rounded border bg-card p-1" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(8, z * 1.4))}><Plus className="h-4 w-4" /></button>
        <button className="rounded border bg-card p-1" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(1, z / 1.4))}><Minus className="h-4 w-4" /></button>
        <button className="rounded border bg-card p-1" aria-label="Reset to full map" onClick={reset}><RotateCcw className="h-4 w-4" /></button>
      </div>
    </div>
  );
}
