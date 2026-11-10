"use client";
import { ArrowLeft, ArrowRight, Map as MapIcon, Maximize2, Minus, Pause, Play, Plus, Volume2, VolumeX } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty, ErrorBox, Spinner } from "@/components/ui/states";
import { useBlobUrl } from "@/hooks/useBlobUrl";
import { api, mediaContent, projectFile } from "@/lib/api";
import type { Hotspot, Media, NavConnection, NavNode, Room, Tour } from "@/lib/types";
import { FloorPlan2D } from "./FloorPlan2D";

const ROOM_KINDS = ["living_room", "bedroom", "kitchen", "bathroom", "balcony", "hallway", "other"];
const roomKindLabel = (kind: string) => kind.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

const wrap = (a: number) => ((a + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
const bearingOf = (h: Hotspot) => ("yaw" in h ? h.yaw : h.bearing);
const verifiedConnection = (connection: NavConnection, from: NavNode | undefined) =>
  connection.hotspot.verified === true || (connection.hotspot.verified == null && from?.hasPose === true);
const clock = (seconds: number) => {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
};

/** Best connection for a keyboard direction. target is a bearing in radians (0 forward, PI back, +/-PI/2 sides). */
function pick(conns: NavConnection[], target: number) {
  let best: NavConnection | null = null, bestD = Infinity;
  for (const c of conns) {
    const d = Math.abs(wrap(bearingOf(c.hotspot) - target));
    if (d < bestD && d < Math.PI / 2.2) { best = c; bestD = d; }
  }
  return best;
}

interface PanoProps {
  url: string; conns: NavConnection[]; initialYaw: number; nodes: Map<string, NavNode>;
  go: (c: NavConnection) => void; viewRef: React.MutableRefObject<{ yaw: () => number; setYaw: (y: number) => void; setFov: (f: number) => void; fov: () => number } | null>;
  onError: (message: string) => void;
}

function PanoViewer({ url, conns, initialYaw, nodes, go, viewRef, onError }: PanoProps) {
  const el = useRef<HTMLDivElement>(null);
  const runtime = useRef<{ viewer: any; scene: any } | null>(null); // eslint-disable-line @typescript-eslint/no-explicit-any
  const latest = useRef({ url, conns, initialYaw, nodes, go, onError });
  latest.current = { url, conns, initialYaw, nodes, go, onError };
  const loadScene = useRef<((imageUrl: string, yaw: number) => void) | null>(null);
  useEffect(() => {
    let dead = false;
    void import("marzipano").then((mod) => {
      if (dead || !el.current) return;
      const M = (mod as unknown as { default?: unknown }).default ?? mod;
      const Mz = M as any; // eslint-disable-line @typescript-eslint/no-explicit-any
      const viewer = new Mz.Viewer(el.current, {
        controls: { mouseViewMode: "drag", dragMode: "pan", scrollZoom: true },
      });
      runtime.current = { viewer, scene: null };
      loadScene.current = (imageUrl, yaw) => {
        const image = new Image();
        image.onload = () => {
          if (dead || !runtime.current || !el.current) return;
          if (image.naturalWidth !== image.naturalHeight * 2) {
            latest.current.onError("This image is not 2:1 equirectangular content, so it cannot be shown as a 360° panorama.");
            return;
          }
          const current = runtime.current;
          const source = Mz.ImageUrlSource.fromString(imageUrl);
          const geometry = new Mz.EquirectGeometry([{ width: image.naturalWidth }]);
          const limiter = Mz.RectilinearView.limit.traditional(image.naturalWidth, (100 * Math.PI) / 180);
          const view = new Mz.RectilinearView({ yaw, pitch: 0, fov: (90 * Math.PI) / 180 }, limiter);
          const scene = current.viewer.createScene({ source, geometry, view, pinFirstLevel: true });
          latest.current.conns.forEach((connection) => {
            if (connection.hotspot.verified !== true || connection.hotspot.directional !== true
              || !("yaw" in connection.hotspot)) return;
            const target = latest.current.nodes.get(connection.toNodeId);
            const b = document.createElement("button");
            b.className = "pano-hotspot rounded-full bg-primary/90 px-3 py-2 text-xs font-medium text-primary-foreground shadow-lg ring-2 ring-white";
            b.textContent = `→ ${target?.label ?? "Connected view"}`;
            b.setAttribute("aria-label", `Move to ${target?.label ?? "connected viewpoint"}`);
            b.onclick = () => latest.current.go(connection);
            scene.hotspotContainer().createHotspot(b, { yaw: connection.hotspot.yaw, pitch: connection.hotspot.pitch ?? 0 });
          });
          const previous = current.scene;
          current.scene = scene;
          viewRef.current = { yaw: () => view.yaw(), setYaw: (y) => view.setYaw(y), setFov: (f) => view.setFov(f), fov: () => view.fov() };
          scene.switchTo({ transitionDuration: 450 }, () => {
            if (previous && current.scene !== previous) current.viewer.destroyScene(previous);
          });
        };
        image.onerror = () => latest.current.onError("The reconstructed panorama image could not be decoded.");
        image.src = imageUrl;
      };
      loadScene.current(latest.current.url, latest.current.initialYaw);
    }).catch((error: unknown) => {
      if (!dead) latest.current.onError(`The 360° viewer could not start: ${(error as Error).message}`);
    });
    return () => {
      dead = true;
      loadScene.current = null;
      viewRef.current = null;
      runtime.current?.viewer.destroy();
      runtime.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { loadScene.current?.(url, initialYaw); }, [url, initialYaw]);
  return <div ref={el} className="h-full w-full touch-none" aria-label="Interactive equirectangular 360-degree viewer" />;
}

function FrameViewer({ url, conns, nodes, go, onError }: {
  url: string; conns: NavConnection[]; nodes: Map<string, NavNode>; go: (c: NavConnection) => void;
  onError: (message: string) => void;
}) {
  const [scale, setScale] = useState(1);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<number | null>(null);
  useEffect(() => { setScale(1); setPos({ x: 0, y: 0 }); }, [url]);
  const clamp = (s: number) => Math.min(5, Math.max(1, s));

  const move = (e: React.PointerEvent) => {
    const prev = pointers.current.get(e.pointerId);
    if (!prev) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = Array.from(pointers.current.values());
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinch.current) setScale((s) => clamp(s * (d / pinch.current!)));
      pinch.current = d;
    } else if (scale > 1) {
      setPos((p) => ({ x: p.x + e.clientX - prev.x, y: p.y + e.clientY - prev.y }));
    }
  };
  return (
    <div className="relative h-full w-full touch-none overflow-hidden"
      onWheel={(e) => setScale((s) => clamp(s * (e.deltaY < 0 ? 1.1 : 0.9)))}
      onPointerDown={(e) => pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })}
      onPointerMove={move}
      onPointerUp={(e) => { pointers.current.delete(e.pointerId); pinch.current = null; }}
      onPointerCancel={(e) => { pointers.current.delete(e.pointerId); pinch.current = null; }}>
      <div className="relative mx-auto h-full w-fit" style={{ transform: `translate(${pos.x}px, ${pos.y}px) scale(${scale})`, transformOrigin: "center" }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={url} alt="Viewpoint" className="h-full w-auto select-none" draggable={false}
          onError={() => onError("The captured viewpoint image could not be decoded. Retry loading this viewpoint.")} />
        {conns.filter((c) => c.hotspot.verified === true && c.hotspot.method === "shared-landmark"
          && "visible" in c.hotspot && c.hotspot.visible).map((c) => {
          const h = c.hotspot as { x: number; y: number };
          return (
            <button key={c.id} aria-label={`Open ${nodes.get(c.toNodeId)?.label ?? "viewpoint"} using a shared visual feature`}
              onPointerDown={(e) => e.stopPropagation()} onClick={() => go(c)}
              style={{ left: `${h.x * 100}%`, top: `${h.y * 100}%`, transform: `translate(-50%,-50%) scale(${1 / scale})` }}
              className="absolute rounded-full bg-primary/90 px-3 py-2 text-xs font-medium text-primary-foreground shadow-lg ring-2 ring-white">
              → {nodes.get(c.toNodeId)?.label}
            </button>
          );
        })}
      </div>
      <div className="absolute bottom-2 right-2 flex gap-1">
        <Button size="icon" variant="outline" aria-label="Zoom in" onClick={() => setScale((s) => clamp(s * 1.3))}><Plus className="h-4 w-4" /></Button>
        <Button size="icon" variant="outline" aria-label="Zoom out" onClick={() => setScale((s) => clamp(s / 1.3))}><Minus className="h-4 w-4" /></Button>
      </div>
    </div>
  );
}

function ViewpointTopology({ node, nodes, conns, onSelect }: {
  node: NavNode; nodes: Map<string, NavNode>; conns: NavConnection[]; onSelect: (id: string) => void;
}) {
  const links = conns.flatMap((connection) => {
    const target = nodes.get(connection.toNodeId);
    return target ? [{ connection, target }] : [];
  }).sort((a, b) => a.target.seq - b.target.seq);
  const center = { x: 150, y: 92 };
  const radius = 62;

  return (
    <div>
      <svg viewBox="0 0 300 184" className="h-48 w-full" role="group" aria-label="Schematic viewpoint connectivity, not a floor plan">
        {links.map(({ connection, target }, index) => {
          const angle = -Math.PI / 2 + (2 * Math.PI * index) / Math.max(links.length, 1);
          const x = center.x + Math.cos(angle) * radius;
          const y = center.y + Math.sin(angle) * radius;
          const verified = connection.hotspot.verified ?? node.hasPose === true;
          return (
            <g key={connection.id} role="button" tabIndex={0} aria-label={`Open ${target.label}; ${verified ? "verified visual match" : "video-order link, not visually verified"}`}
              className="cursor-pointer" onClick={() => onSelect(target.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(target.id);
                }
              }}>
              <title>{verified ? "Verified visual match" : "Video order only, not a verified visual match"}</title>
              <line x1={center.x} y1={center.y} x2={x} y2={y} stroke={verified ? "#16a34a" : "#94a3b8"}
                strokeWidth="2" strokeDasharray={verified ? undefined : "4 3"} />
              <circle cx={x} cy={y} r="18" fill={verified ? "#dcfce7" : "#f1f5f9"}
                stroke={verified ? "#16a34a" : "#94a3b8"} strokeWidth="2" />
              <text x={x} y={y + 3} textAnchor="middle" fontSize="7" fill="#0f172a">{target.label.replace("Viewpoint ", "")}</text>
            </g>
          );
        })}
        <circle cx={center.x} cy={center.y} r="22" fill="#fef3c7" stroke="#f59e0b" strokeWidth="3" />
        <text x={center.x} y={center.y + 3} textAnchor="middle" fontSize="8" fontWeight="700" fill="#0f172a">Current</text>
      </svg>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <span><span className="text-green-700">●</span> Verified visual match</span>
        <span><span className="text-slate-400">--</span> Video order only</span>
      </div>
    </div>
  );
}

export function TourViewer({ projectId, tour, sourceVideo, nodeId, onSelect, onBackToMap, onRefresh }: {
  projectId: string; tour: Tour; sourceVideo: Media | null; nodeId: string | null;
  onSelect: (id: string) => void; onBackToMap?: () => void; onRefresh?: () => Promise<void>;
}) {
  const stage = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const viewRef = useRef<PanoProps["viewRef"]["current"]>(null);
  const [yaw, setYaw] = useState(0);
  const [history, setHistory] = useState<string[]>([]);
  const [selectedRoom, setSelectedRoom] = useState("");
  const [search, setSearch] = useState("");
  const [newRoomName, setNewRoomName] = useState("");
  const [newRoomKind, setNewRoomKind] = useState("other");
  const [roomNameDraft, setRoomNameDraft] = useState("");
  const [roomKindDraft, setRoomKindDraft] = useState("other");
  const [nodeLabelDraft, setNodeLabelDraft] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [editBusy, setEditBusy] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [playerError, setPlayerError] = useState<string | null>(null);
  const [viewerError, setViewerError] = useState<string | null>(null);
  const [frameImageError, setFrameImageError] = useState<string | null>(null);
  const lastId = useRef<string | null>(null);
  const selectedIdRef = useRef(nodeId);
  const playbackSelectedId = useRef<string | null>(null);
  const pendingSeek = useRef<number | null>(null);
  selectedIdRef.current = nodeId;
  const skipPush = useRef(false);
  useEffect(() => {
    if (nodeId && lastId.current && lastId.current !== nodeId && !skipPush.current) setHistory((h) => [...h.slice(-19), lastId.current as string]);
    skipPush.current = false;
    lastId.current = nodeId;
  }, [nodeId]);
  const goBack = () => {
    const prev = history[history.length - 1];
    if (!prev) return;
    skipPush.current = true;
    setHistory((h) => h.slice(0, -1));
    onSelect(prev);
  };
  const node = tour.nodes.find((n) => n.id === nodeId) ?? null;
  const nodes = useMemo(() => new Map(tour.nodes.map((n) => [n.id, n])), [tour.nodes]);
  const orderedNodes = useMemo(() => [...tour.nodes].sort((a, b) => a.seq - b.seq), [tour.nodes]);
  const conns = tour.connections.filter((c) => c.fromNodeId === nodeId);
  const navigationConns = conns.filter((connection) => verifiedConnection(connection, node ?? undefined));
  const room = tour.rooms?.find((r) => r.id === node?.roomId) ?? null;
  const rooms = tour.rooms ?? [];
  const declaredPanorama = tour.manifest?.panorama_coverage?.status === "source_declared_not_content_verified";
  const reachableIds = useMemo(() => {
    const adjacent = new Map<string, string[]>();
    for (const connection of tour.connections) {
      if (!verifiedConnection(connection, nodes.get(connection.fromNodeId))) continue;
      adjacent.set(connection.fromNodeId, [...(adjacent.get(connection.fromNodeId) ?? []), connection.toNodeId]);
    }
    const reached = new Set<string>();
    const queue = nodeId ? [nodeId] : [];
    while (queue.length) {
      const current = queue.pop()!;
      if (reached.has(current)) continue;
      reached.add(current);
      queue.push(...(adjacent.get(current) ?? []));
    }
    return reached;
  }, [nodeId, nodes, tour.connections]);
  const { url: frameUrl, error: frameError, loading: frameLoading, retry: retryFrame } = useBlobUrl(
    node ? projectFile(projectId, node.framePath) : null,
  );
  const { url: videoUrl, error: videoLoadError, loading: videoLoading } = useBlobUrl(
    sourceVideo && sourceOpen ? mediaContent(sourceVideo.id) : null,
  );
  const videoError = playerError ?? videoLoadError;
  const displayedDuration = duration || sourceVideo?.durationSec || 0;
  const coverage = tour.manifest?.coverage ?? {};
  const hasCoverageCounts = Number.isSafeInteger(coverage.registered_images) && (coverage.registered_images ?? -1) >= 0
    && Number.isSafeInteger(coverage.total_images) && (coverage.total_images ?? -1) >= 0;
  const coverageAvailable = coverage.available ?? hasCoverageCounts;
  const registeredImages = Number.isSafeInteger(coverage.registered_images) && (coverage.registered_images ?? -1) >= 0
    ? coverage.registered_images! : 0;
  const totalImages = Number.isSafeInteger(coverage.total_images) && (coverage.total_images ?? -1) >= 0
    ? Math.max(coverage.total_images!, registeredImages) : registeredImages;
  const fraction = coverage.registered_fraction;
  const registeredFraction = typeof fraction === "number" && Number.isFinite(fraction)
    ? Math.max(0, Math.min(1, fraction))
    : totalImages > 0 ? registeredImages / totalImages : 0;
  const untrackedRanges = Array.isArray(coverage.untracked_time_ranges_sec)
    ? coverage.untracked_time_ranges_sec.filter((range): range is [number, number] =>
      Array.isArray(range) && range.length === 2
      && typeof range[0] === "number" && Number.isFinite(range[0]) && range[0] >= 0
      && typeof range[1] === "number" && Number.isFinite(range[1]) && range[1] >= range[0])
    : [];
  const warnings = Array.isArray(tour.manifest?.warnings)
    ? tour.manifest.warnings.filter((warning): warning is string => typeof warning === "string")
      .filter((warning) => untrackedRanges.length > 0 || !/coverage gap/i.test(warning))
    : [];
  const bounds = tour.manifest?.floorplan?.bounds;
  const hasSpatialMap = !!tour.manifest?.floorplan && Array.isArray(tour.manifest.floorplan.points)
    && !!bounds && tour.nodes.some((n) => n.hasPose === true)
    && [bounds.minx, bounds.maxx, bounds.minz, bounds.maxz].every(Number.isFinite)
    && Math.max(bounds.maxx - bounds.minx, bounds.maxz - bounds.minz) > 1e-6;
  const go = useCallback((c: NavConnection) => {
    if (c.fromNodeId !== nodeId || !verifiedConnection(c, nodes.get(c.fromNodeId))) return;
    const from = nodes.get(c.fromNodeId), to = nodes.get(c.toNodeId);
    if (from && to) {
      const currentYaw = viewRef.current?.yaw() ?? 0;
      const headingDelta = from.hasPose !== true || to.hasPose !== true ? 0 : to.headingRad - from.headingRad;
      setYaw(wrap(currentYaw - headingDelta));
    }
    onSelect(c.toNodeId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeId, nodes, onSelect]);

  useEffect(() => {
    setSelectedRoom(node?.roomId ?? "");
  }, [node?.roomId]);
  useEffect(() => {
    setFrameImageError(null);
    setViewerError(null);
  }, [nodeId, frameUrl]);
  useEffect(() => {
    setNodeLabelDraft(node?.label ?? "");
  }, [node?.id, node?.label]);
  useEffect(() => {
    setRoomNameDraft(room?.name ?? "");
    setRoomKindDraft(room?.kind ?? "other");
  }, [room?.id, room?.name, room?.kind]);

  const saveEdit = async (action: () => Promise<unknown>) => {
    setEditBusy(true);
    setEditError(null);
    try {
      await action();
      await onRefresh?.();
    } catch (error) {
      setEditError((error as Error).message);
    } finally {
      setEditBusy(false);
    }
  };

  useEffect(() => {
    setPlayerError(null);
    setCurrentTime(0);
    setDuration(0);
    setPlaying(false);
  }, [sourceVideo?.id]);
  useEffect(() => { setViewerError(null); }, [node?.id]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !videoUrl || !nodeId) return;
    const changedByPlayback = playbackSelectedId.current === nodeId;
    playbackSelectedId.current = null;
    if (changedByPlayback) return;
    const target = nodes.get(nodeId)?.timeSec;
    if (typeof target !== "number" || !Number.isFinite(target) || target < 0) return;
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
      video.currentTime = Math.min(target, Number.isFinite(video.duration) ? video.duration : target);
      setCurrentTime(video.currentTime);
    } else {
      pendingSeek.current = target;
    }
  }, [nodeId, nodes, videoUrl]);

  const onVideoTimeUpdate = useCallback((event: React.SyntheticEvent<HTMLVideoElement>) => {
    const time = event.currentTarget.currentTime;
    setCurrentTime(time);
    const candidate = [...orderedNodes].reverse().find((n) => typeof n.timeSec === "number" && n.timeSec <= time + 0.02);
    const next = candidate ?? orderedNodes.find((n) => typeof n.timeSec === "number");
    if (next && selectedIdRef.current !== next.id) {
      selectedIdRef.current = next.id;
      playbackSelectedId.current = next.id;
      onSelect(next.id);
    }
  }, [onSelect, orderedNodes]);

  const selectNode = (id: string) => {
    playbackSelectedId.current = null;
    onSelect(id);
  };
  const togglePlayback = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      video.play().catch(() => setPlayerError("The uploaded video could not be played by this browser."));
    } else {
      video.pause();
    }
  };
  const setTime = (value: number) => {
    const video = videoRef.current;
    if (!video || !Number.isFinite(value)) return;
    video.currentTime = value;
    setCurrentTime(value);
  };
  const toggleFullscreen = () => {
    setViewerError(null);
    const action = document.fullscreenElement ? document.exitFullscreen() : stage.current?.requestFullscreen();
    action?.catch(() => setViewerError("Fullscreen is not available in this browser."));
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      const isPano = node?.panorama;
      const nav = (t: number) => { const c = pick(navigationConns, t); if (c) { e.preventDefault(); go(c); } };
      if (e.key === "ArrowUp" || e.key === "w") nav(0);
      else if (e.key === "ArrowDown" || e.key === "s") nav(Math.PI);
      else if (e.key === "ArrowLeft" || e.key === "a") { if (isPano && viewRef.current) viewRef.current.setYaw(viewRef.current.yaw() - 0.15); else nav(-Math.PI / 2); }
      else if (e.key === "ArrowRight" || e.key === "d") { if (isPano && viewRef.current) viewRef.current.setYaw(viewRef.current.yaw() + 0.15); else nav(Math.PI / 2); }
      else if (e.key === "+" && viewRef.current) viewRef.current.setFov(viewRef.current.fov() * 0.9);
      else if (e.key === "-" && viewRef.current) viewRef.current.setFov(viewRef.current.fov() / 0.9);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, navigationConns, node]);

  if (!tour.available || !node) return <Empty title="No virtual tour yet">Upload a walkthrough video and run “Reconstruct”. The tour is built from the real frames of your video; nothing is shown until it has been validated.</Empty>;
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="space-y-2">
        <div ref={stage} className="relative overflow-hidden rounded-lg border bg-black">
          {frameLoading ? <Spinner label={`Loading ${node.label}`} />
            : frameError || frameImageError ? (
              <div className="space-y-3 p-4">
                <ErrorBox message={frameError ?? frameImageError ?? "The viewpoint image could not be loaded."} />
                <Button size="sm" variant="outline" onClick={() => {
                  setFrameImageError(null);
                  setViewerError(null);
                  retryFrame();
                }}>Retry loading image</Button>
              </div>
            ) : frameUrl ? (
            <div className="relative h-[60vh] min-h-[320px]">
              {node.panorama
              ? <PanoViewer url={frameUrl} conns={navigationConns} initialYaw={yaw} nodes={nodes} go={go} viewRef={viewRef}
                onError={setViewerError} />
              : <FrameViewer url={frameUrl} conns={conns} nodes={nodes} go={go}
                onError={(message) => setFrameImageError(message)} />}
            </div>
          ) : (
            <div className="p-4">
              <ErrorBox message="The selected viewpoint image is unavailable." />
              <Button size="sm" variant="outline" className="mt-3" onClick={retryFrame}>Retry loading image</Button>
            </div>
          )}
          <div className="absolute left-2 top-2 flex items-center gap-2">
            <Badge className="bg-black/60 text-white">{room ? `${room.name} · ` : ""}{node.label} · {node.seq + 1}/{tour.nodes.length}</Badge>
            <Badge tone={node.panorama ? "info" : "warn"}>{node.panorama
              ? declaredPanorama ? "Declared 360° source · 2:1 checked" : "Reconstructed 360° panorama"
              : node.hasPose !== true ? "Captured video frame · no 3D pose" : "Reconstructed perspective frame · not 360°"}</Badge>
          </div>
          <Button size="icon" variant="outline" aria-label="Fullscreen viewer" onClick={toggleFullscreen}
            className="absolute right-2 top-2 bg-background/80"><Maximize2 className="h-4 w-4" /></Button>
          {viewerError && (
            <div className="absolute inset-x-3 bottom-3 flex items-center justify-between gap-3 rounded-md bg-background/95 p-3">
              <ErrorBox message={viewerError} />
              <Button size="sm" variant="outline" onClick={() => {
                setViewerError(null);
                retryFrame();
              }}>Retry viewer</Button>
            </div>
          )}
        </div>
        {viewerError && <p className="sr-only" role="alert">{viewerError}</p>}
        <p className="text-xs text-muted-foreground">
          {node.panorama
            ? declaredPanorama
              ? "Drag or swipe to look around; use the wheel or pinch to zoom. The source was declared as 360° and its 2:1 format was checked, but image coverage was not independently verified."
              : "Drag or swipe to look around; use the wheel or pinch to zoom. Select a verified scene marker or connected location to move."
            : node.hasPose !== true
              ? "This is a captured perspective frame, not a 360° panorama. Camera-pose reconstruction is unavailable, so look-around and spatial floor markers cannot be shown."
              : "This is a reconstructed perspective frame, not a complete 360° panorama. Move using verified shared-feature markers or the connected-location controls."}
        </p>
        <section className="space-y-2 rounded-lg border p-3" aria-label="Connected viewpoint navigation">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-medium">Connected locations</h2>
            <span className="text-xs text-muted-foreground">{navigationConns.length} verified route{navigationConns.length === 1 ? "" : "s"}</span>
          </div>
          {navigationConns.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {navigationConns.map((connection) => {
                const destination = nodes.get(connection.toNodeId);
                const destinationRoom = rooms.find((item) => item.id === destination?.roomId);
                return (
                  <Button key={connection.id} size="sm" variant="outline" onClick={() => go(connection)}
                    aria-label={`Move to ${destinationRoom?.name ? `${destinationRoom.name}, ` : ""}${destination?.label ?? "connected viewpoint"}`}>
                    <ArrowRight className="h-3 w-3" />
                    {destinationRoom ? `${destinationRoom.name} · ` : ""}{destination?.label ?? "Connected view"}
                  </Button>
                );
              })}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">No verified route leaves this viewpoint. Other disconnected viewpoints remain available below.</p>
          )}
        </section>
        <details className="rounded-lg border" onToggle={(event) => {
          const open = event.currentTarget.open;
          if (!open) {
            videoRef.current?.pause();
            setPlaying(false);
          }
          setSourceOpen(open);
          if (open) setPlayerError(null);
        }}>
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            Source video (optional) · {sourceVideo?.originalName ?? "unavailable"}
          </summary>
          <div className="space-y-2 p-3">
            {sourceVideo && sourceOpen && videoUrl && (
              <>
                <video ref={videoRef} src={videoUrl} playsInline preload="metadata"
                  onLoadedMetadata={(event) => {
                    const video = event.currentTarget;
                    setDuration(Number.isFinite(video.duration) ? video.duration : 0);
                    const target = pendingSeek.current ?? node?.timeSec;
                    pendingSeek.current = null;
                    if (typeof target === "number" && Number.isFinite(target) && target >= 0) {
                      video.currentTime = Math.min(target, Number.isFinite(video.duration) ? video.duration : target);
                      setCurrentTime(video.currentTime);
                    }
                  }}
                  onTimeUpdate={onVideoTimeUpdate}
                  onPlay={() => setPlaying(true)}
                  onPause={() => setPlaying(false)}
                  onVolumeChange={(event) => setMuted(event.currentTarget.muted)}
                  onError={() => setPlayerError("The uploaded video could not be decoded. Check that it is a supported MP4 file.")}
                  className="max-h-72 w-full bg-black object-contain" />
                <div className="space-y-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Button size="icon" variant="outline" aria-label={playing ? "Pause video" : "Play video"} onClick={togglePlayback}>
                  {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                </Button>
                <span className="min-w-[5.5rem] tabular-nums" aria-live="off">{clock(currentTime)} / {clock(displayedDuration)}</span>
                <input aria-label="Video position" type="range" min={0} max={Math.max(displayedDuration, 0.01)} step={0.05}
                  value={Math.min(currentTime, displayedDuration || currentTime)} disabled={!displayedDuration}
                  onChange={(event) => setTime(Number(event.currentTarget.value))} className="min-w-24 flex-1 accent-primary" />
                <label className="flex items-center gap-1">
                  <span className="sr-only">Playback speed</span>
                  <select aria-label="Playback speed" value={playbackRate} onChange={(event) => {
                    const rate = Number(event.currentTarget.value);
                    setPlaybackRate(rate);
                    if (videoRef.current) videoRef.current.playbackRate = rate;
                  }} className="h-9 rounded-md border bg-card px-2">
                    {[0.5, 1, 1.5, 2].map((rate) => <option key={rate} value={rate}>{rate}×</option>)}
                  </select>
                </label>
                <Button size="icon" variant="outline" aria-label={muted ? "Unmute video" : "Mute video"} onClick={() => {
                  if (videoRef.current) videoRef.current.muted = !videoRef.current.muted;
                }}>{muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}</Button>
                  </div>
                </div>
              </>
            )}
            {sourceOpen && videoLoading && <Spinner label="Loading the original uploaded video…" />}
            {sourceOpen && !sourceVideo && <p className="text-sm text-warn">No original video is linked to this tour.</p>}
            {sourceOpen && videoError && <ErrorBox message={videoError} />}
            {sourceOpen && sourceVideo && !videoError && !videoLoading && !videoUrl
              && <ErrorBox message="The original video could not be loaded. It may have expired or been removed; try refreshing the project." />}
            {!sourceOpen && <p className="px-3 pb-3 text-xs text-muted-foreground">Expand to load and play the original upload. The view above is either a source equirectangular panorama or an actual extracted/reconstructed camera frame; ordinary frames are never stretched into 360° views.</p>}
            {videoUrl && typeof node.timeSec !== "number" && <p className="text-xs text-muted-foreground">This older viewpoint has no stored frame timestamp. Reconstruct the video again to synchronize this view with playback.</p>}
          </div>
        </details>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {onBackToMap && <Button size="sm" variant="outline" onClick={onBackToMap}><MapIcon className="h-3 w-3" /> Back to floor plan</Button>}
          <Button size="sm" variant="outline" disabled={history.length === 0} onClick={goBack}><ArrowLeft className="h-3 w-3" /> Back</Button>
          {history.length > 0 && (
            <span className="truncate text-xs text-muted-foreground">Trail: {history.slice(-4).map((id) => nodes.get(id)?.label ?? "").join(" → ")} → {node.label}</span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">Keys: ↑/↓ choose a connected route; ←/→ look around only in 360° mode. Drag, wheel, and pinch controls depend on the view type above.</p>
      </div>
      <div className="space-y-3">
        <section className="space-y-2 rounded-lg border p-3">
          <h2 className="font-medium">Rooms and viewpoints</h2>
          {rooms.length === 0 && <p className="text-xs text-muted-foreground">No rooms have been assigned. Room labels are currently manual; this reconstruction does not automatically identify room types.</p>}
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="block text-xs text-muted-foreground">Create room
              <input aria-label="New room name" value={newRoomName} onChange={(event) => setNewRoomName(event.currentTarget.value)}
                placeholder="Room name" maxLength={100} className="mt-1 h-9 w-full rounded-md border bg-card px-2 text-sm text-foreground" />
            </label>
            <label className="block text-xs text-muted-foreground">Room type
              <select aria-label="New room type" value={newRoomKind} onChange={(event) => setNewRoomKind(event.currentTarget.value)}
                className="mt-1 h-9 w-full rounded-md border bg-card px-2 text-sm text-foreground">
                {ROOM_KINDS.map((kind) => <option key={kind} value={kind}>{roomKindLabel(kind)}</option>)}
              </select>
            </label>
          </div>
          <Button size="sm" variant="outline" disabled={editBusy || !newRoomName.trim()} onClick={() => saveEdit(async () => {
            await api<Room>(`/api/projects/${projectId}/rooms`, { method: "POST", body: JSON.stringify({ name: newRoomName.trim(), kind: newRoomKind }) });
            setNewRoomName("");
          })}>Create room</Button>
          {room && (
            <div className="space-y-2 rounded-md border p-2">
              <p className="text-xs font-medium">Edit {room.name}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                <input aria-label="Rename current room" value={roomNameDraft} onChange={(event) => setRoomNameDraft(event.currentTarget.value)}
                  maxLength={100} className="h-9 min-w-0 rounded-md border bg-card px-2 text-sm" />
                <select aria-label="Current room type" value={roomKindDraft} onChange={(event) => setRoomKindDraft(event.currentTarget.value)}
                  className="h-9 min-w-0 rounded-md border bg-card px-2 text-sm">
                  {ROOM_KINDS.map((kind) => <option key={kind} value={kind}>{roomKindLabel(kind)}</option>)}
                </select>
              </div>
              <Button size="sm" variant="outline" disabled={editBusy || !roomNameDraft.trim()} onClick={() => saveEdit(() =>
                api<Room>(`/api/rooms/${room.id}`, { method: "PATCH", body: JSON.stringify({ name: roomNameDraft.trim(), kind: roomKindDraft }) })
              )}>Save room</Button>
            </div>
          )}
          <label className="block text-xs text-muted-foreground">Assign current viewpoint to room
            <select aria-label="Assign viewpoint room" value={node.roomId ?? ""} disabled={editBusy}
              onChange={(event) => saveEdit(() => api(`/api/nodes/${node.id}/room`, {
                method: "PUT", body: JSON.stringify({ roomId: event.currentTarget.value || null }),
              }))} className="mt-1 h-9 w-full rounded-md border bg-card px-2 text-sm text-foreground">
              <option value="">No room</option>
              {rooms.map((r) => <option key={r.id} value={r.id}>{r.name} · {roomKindLabel(r.kind)}</option>)}
            </select>
          </label>
          <label className="block text-xs text-muted-foreground">Rename current viewpoint
            <input aria-label="Rename current viewpoint" value={nodeLabelDraft} onChange={(event) => setNodeLabelDraft(event.currentTarget.value)}
              maxLength={100} className="mt-1 h-9 w-full rounded-md border bg-card px-2 text-sm text-foreground" />
          </label>
          <Button size="sm" variant="outline" disabled={editBusy || !nodeLabelDraft.trim() || nodeLabelDraft === node.label}
            onClick={() => saveEdit(() => api(`/api/nodes/${node.id}`, {
              method: "PATCH", body: JSON.stringify({ label: nodeLabelDraft.trim() }),
            }))}>Save viewpoint name</Button>
          {editError && <ErrorBox message={editError} />}
          <label className="block text-xs text-muted-foreground">Search viewpoints
            <input aria-label="Search viewpoints" value={search} onChange={(event) => setSearch(event.currentTarget.value)}
              placeholder="Room or viewpoint" className="mt-1 h-9 w-full rounded-md border bg-card px-2 text-sm text-foreground" />
          </label>
          <label className="block text-xs text-muted-foreground">Filter by room
            <select aria-label="Walkthrough room filter" value={selectedRoom} onChange={(event) => setSelectedRoom(event.currentTarget.value)}
              className="mt-1 h-9 w-full rounded-md border bg-card px-2 text-sm text-foreground">
              <option value="">All rooms</option>
              {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </label>
          <div className="max-h-52 space-y-1 overflow-y-auto">
            {orderedNodes.filter((n) => (!selectedRoom || n.roomId === selectedRoom)
              && `${n.label} ${rooms.find((r) => r.id === n.roomId)?.name ?? ""}`.toLowerCase().includes(search.toLowerCase())).map((n) => (
              <button key={n.id} onClick={() => selectNode(n.id)}
                className={`flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted ${n.id === nodeId ? "bg-muted font-medium" : ""}`}>
                <span className="truncate">{n.label}{n.roomId ? ` · ${rooms.find((r) => r.id === n.roomId)?.name ?? "Room"}` : ""}</span>
                <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{typeof n.timeSec === "number" ? clock(n.timeSec) : "—"}</span>
              </button>
            ))}
          </div>
          {orderedNodes.some((n) => n.id !== nodeId && !reachableIds.has(n.id)) && (
            <div className="border-t pt-2">
              <h3 className="text-sm font-medium">Unconnected viewpoints</h3>
              <p className="text-xs text-muted-foreground">No verified route from this viewpoint’s graph component. Open one directly to explore its component.</p>
              <div className="mt-1 max-h-32 space-y-1 overflow-y-auto">
                {orderedNodes.filter((n) => n.id !== nodeId && !reachableIds.has(n.id)).map((n) => (
                  <button key={n.id} onClick={() => selectNode(n.id)} className="block w-full truncate rounded px-2 py-1 text-left text-sm hover:bg-muted">
                    {n.label}{n.roomId ? ` · ${rooms.find((r) => r.id === n.roomId)?.name ?? "Room"}` : ""}
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
        <section className="space-y-2 rounded-lg border p-3">
          <h2 className="font-medium">Spatial view</h2>
          {hasSpatialMap && tour.manifest ? (
            <FloorPlan2D manifest={tour.manifest} nodes={tour.nodes} connections={tour.connections} nodeId={nodeId} onSelect={selectNode}
              rooms={rooms} activeRoomId={node.roomId ?? null} className="h-52 w-full" />
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                {node.hasPose !== true
                  ? "No camera poses or measured floor plan are available. This schematic shows only recorded viewpoint links and is not spatial geometry."
                  : "A spatial map is not available for this reconstruction yet."}
              </p>
              {node.hasPose !== true && <ViewpointTopology node={node} nodes={nodes} conns={conns} onSelect={selectNode} />}
            </div>
          )}
          {tour.manifest?.floorplan?.note && <p className="text-xs text-muted-foreground">{tour.manifest.floorplan.note}</p>}
        </section>
        <section className="space-y-1 rounded-lg border p-3">
          <h2 className="font-medium">Connection evidence</h2>
          {navigationConns.length === 0 && <p className="text-sm text-muted-foreground">No verified visual connections from this viewpoint.</p>}
          {navigationConns.map((connection) => {
            return (
              <div key={connection.id} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate">{nodes.get(connection.toNodeId)?.label ?? "Viewpoint"}
                  {rooms.find((item) => item.id === nodes.get(connection.toNodeId)?.roomId)?.name
                    ? ` · ${rooms.find((item) => item.id === nodes.get(connection.toNodeId)?.roomId)?.name}` : ""}
                </span>
                <Button size="sm" variant="outline" onClick={() => go(connection)}>Go</Button>
                <span className="shrink-0 text-xs text-primary">Verified visual match</span>
              </div>
            );
          })}
        </section>
        {(!coverageAvailable || warnings.length > 0 || untrackedRanges.length > 0) && (
          <div className="space-y-1 text-xs">
            {coverageAvailable
              ? <p>Tracked {registeredImages}/{totalImages} images ({(registeredFraction * 100).toFixed(0)}%).</p>
              : <p className="text-muted-foreground">Coverage information is not available yet.</p>}
            {coverageAvailable && untrackedRanges.length > 0 && (
              <p className="text-warn">Missing coverage at {untrackedRanges.map(([a, b]) => `${a.toFixed(0)}–${b.toFixed(0)}s`).join(", ")} of the video.</p>
            )}
            {warnings.map((w, index) => <p key={`${index}-${w}`} className="text-muted-foreground">{w}</p>)}
          </div>
        )}
        {tour.manifest?.panorama_coverage?.note && (
          <p className="text-xs text-muted-foreground">{tour.manifest.panorama_coverage.note}</p>
        )}
      </div>
    </div>
  );
}
