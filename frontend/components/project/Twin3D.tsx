"use client";
import { Html, Line, OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { useEffect, useMemo, useState } from "react";
import { Empty, ErrorBox, NotImplemented, Spinner } from "@/components/ui/states";
import { api, projectFile } from "@/lib/api";
import { usePrefs } from "@/lib/prefs";
import type { Tour } from "@/lib/types";
import { formatLength } from "@/lib/units";

interface Cloud { positions: Float32Array; colors: Float32Array }

function percentileBox(pos: Float32Array) {
  const lo = [0, 0, 0], hi = [0, 0, 0];
  for (let a = 0; a < 3; a++) {
    const v: number[] = [];
    for (let i = a; i < pos.length; i += 3) v.push(pos[i]);
    v.sort((x, y) => x - y);
    lo[a] = v[Math.floor(v.length * 0.01)] ?? 0;
    hi[a] = v[Math.floor(v.length * 0.99)] ?? 0;
  }
  return { lo, hi };
}

export function Twin3D({ projectId, tour, nodeId, onSelect }: { projectId: string; tour: Tour; nodeId: string | null; onSelect: (id: string) => void }) {
  const { unit } = usePrefs();
  const [cloud, setCloud] = useState<Cloud | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [show, setShow] = useState({ points: true, path: true, box: true, labels: true });
  const pointsPath = tour.manifest?.points_path;

  useEffect(() => {
    if (!pointsPath) return;
    let cancelled = false;
    (async () => {
      try {
        const { BASE, getToken } = await import("@/lib/api");
        const res = await fetch(BASE + projectFile(projectId, pointsPath), { headers: { Authorization: `Bearer ${getToken()}` } });
        if (!res.ok) throw new Error("Could not load the point cloud");
        const j = await res.json();
        if (!cancelled) setCloud({ positions: new Float32Array(j.positions), colors: Float32Array.from(j.colors as number[], (c) => c / 255) });
      } catch (e) { if (!cancelled) setError((e as Error).message); }
    })();
    return () => { cancelled = true; };
  }, [projectId, pointsPath]);

  const box = useMemo(() => (cloud ? percentileBox(cloud.positions) : null), [cloud]);
  const size = box ? Math.max(box.hi[0] - box.lo[0], box.hi[1] - box.lo[1], box.hi[2] - box.lo[2], 1e-6) : 1;
  const path = useMemo(() => tour.nodes.map((n) => [n.x, n.y, n.z] as [number, number, number]), [tour.nodes]);

  if (!tour.available) return <Empty title="No reconstruction yet">The 3D view shows the sparse point cloud and camera path produced by reconstruction.</Empty>;
  if (tour.nodes.length > 0 && tour.nodes.every((n) => n.hasPose !== true)) {
    return <Empty title="3D reconstruction not available yet">The virtual tour is ready, but no camera poses or point cloud exist for this project. Advanced 3D reconstruction has not completed (see the job message on the Video Reconstruction page for the reason).</Empty>;
  }
  if (error) return <ErrorBox message={error} />;
  if (!cloud || !box) return <Spinner label="Loading point cloud" />;

  const rec = tour.reconstruction;
  const ext = rec?.extentsMm ?? null;
  const label = (axis: "x" | "y" | "z") => ext ? formatLength(ext[axis], unit) : `${(rec?.extentsModelUnits?.[axis] ?? 0).toFixed(2)} model units`;
  const toggle = (k: keyof typeof show) => setShow((s) => ({ ...s, [k]: !s[k] }));
  const center = box.lo.map((l, i) => (l + box.hi[i]) / 2);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 text-sm">
        {([["points", "Point cloud"], ["path", "Camera path & viewpoints"], ["box", "Extent box (wireframe)"], ["labels", "Measurements"]] as const).map(([k, l]) => (
          <label key={k} className="flex items-center gap-1"><input type="checkbox" checked={show[k]} onChange={() => toggle(k)} /> {l}</label>
        ))}
      </div>
      <div className="h-[60vh] min-h-[320px] overflow-hidden rounded-lg border bg-neutral-900">
        <Canvas camera={{ position: [center[0] + size, center[1] + size * 0.8, center[2] + size], fov: 55, near: size / 1000, far: size * 50 }} dpr={[1, 1.5]}>
          <OrbitControls target={center as [number, number, number]} makeDefault />
          {show.points && (
            <points>
              <bufferGeometry>
                <bufferAttribute attach="attributes-position" args={[cloud.positions, 3]} />
                <bufferAttribute attach="attributes-color" args={[cloud.colors, 3]} />
              </bufferGeometry>
              <pointsMaterial size={size * 0.004} vertexColors sizeAttenuation />
            </points>
          )}
          {show.path && path.length > 1 && <Line points={path} color="#60a5fa" lineWidth={2} />}
          {show.path && tour.nodes.map((n) => (
            <mesh key={n.id} position={[n.x, n.y, n.z]} onClick={() => onSelect(n.id)}>
              <sphereGeometry args={[size * (n.id === nodeId ? 0.018 : 0.011), 12, 12]} />
              <meshBasicMaterial color={n.id === nodeId ? "#f59e0b" : "#3b82f6"} />
            </mesh>
          ))}
          {show.box && (
            <mesh position={center as [number, number, number]}>
              <boxGeometry args={[box.hi[0] - box.lo[0], box.hi[1] - box.lo[1], box.hi[2] - box.lo[2]]} />
              <meshBasicMaterial color="#94a3b8" wireframe />
            </mesh>
          )}
          {show.labels && (
            <>
              <Html position={[center[0], box.hi[1], box.lo[2]]} center><span className="whitespace-nowrap rounded bg-black/70 px-1.5 py-0.5 text-xs text-white">X {label("x")}</span></Html>
              <Html position={[box.lo[0], center[1], box.lo[2]]} center><span className="whitespace-nowrap rounded bg-black/70 px-1.5 py-0.5 text-xs text-white">Y {label("y")}</span></Html>
              <Html position={[box.lo[0], box.hi[1], center[2]]} center><span className="whitespace-nowrap rounded bg-black/70 px-1.5 py-0.5 text-xs text-white">Z {label("z")}</span></Html>
            </>
          )}
        </Canvas>
      </div>
      <p className="text-xs text-muted-foreground">{ext ? "Extents use the calibrated scale." : "Extents are in arbitrary model units until you calibrate a real distance under Measurements."} Drag to orbit, right-drag to pan, scroll or pinch to zoom.</p>
      <NotImplemented what="textured mesh, Gaussian splatting, wall/door/window geometry, furniture placement, first-person walkthrough" />
    </div>
  );
}
