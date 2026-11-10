"use client";
import { OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";
import { Spinner } from "@/components/ui/states";
import { fetchBuffer, projectFile } from "@/lib/api";

/** Loads a private file from the backend and hands the bytes to `parse`. Shows a spinner and the real error. */
function useRemote<T>(projectId: string, rel: string, parse: (buf: ArrayBuffer) => T) {
  const [state, setState] = useState<{ data?: T; error?: string }>({});
  useEffect(() => {
    let alive = true;
    setState({});
    fetchBuffer(projectFile(projectId, rel))
      .then((buf) => { if (alive) setState({ data: parse(buf) }); })
      .catch((e: Error) => { if (alive) setState({ error: e.message }); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, rel]);
  return state;
}

function frameOf(box: THREE.Box3) {
  const c = box.getCenter(new THREE.Vector3());
  const r = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1e-3);
  return { center: c, radius: r };
}

function Shell({ center, radius, children }: { center: THREE.Vector3; radius: number; children: React.ReactNode }) {
  return (
    <Canvas camera={{ position: [center.x, center.y + radius * 0.4, center.z + radius * 2.2], fov: 50, near: radius / 500, far: radius * 50 }}
            style={{ height: 420, background: "#0b0f14", borderRadius: 8 }} gl={{ antialias: true }}>
      <OrbitControls target={center} makeDefault />
      {children}
    </Canvas>
  );
}

/** PLY point cloud (vertex colours) or triangle mesh. */
export function PlyViewer({ projectId, path, mode }: { projectId: string; path: string; mode: "points" | "mesh" }) {
  const { data, error } = useRemote(projectId, path, (buf) => {
    const g = new PLYLoader().parse(buf);
    if (mode === "mesh" && !g.getAttribute("normal")) g.computeVertexNormals();
    g.computeBoundingBox();
    return g;
  });
  if (error) return <p className="text-sm text-destructive" role="alert">{error}</p>;
  if (!data) return <Spinner />;
  const { center, radius } = frameOf(data.boundingBox!);
  const hasColor = !!data.getAttribute("color");
  return (
    <Shell center={center} radius={radius}>
      <ambientLight intensity={0.7} />
      <directionalLight position={[radius, radius * 2, radius]} intensity={1.1} />
      {mode === "points"
        ? <points geometry={data}><pointsMaterial size={Math.max(radius / 250, 0.002)} vertexColors={hasColor} sizeAttenuation /></points>
        : <mesh geometry={data}><meshStandardMaterial vertexColors={hasColor} side={THREE.DoubleSide} roughness={0.9} metalness={0} /></mesh>}
    </Shell>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// Gaussian splats (.splat, 32 bytes per Gaussian). A small anisotropic splat renderer: each Gaussian is a screen-space
// quad shaped from its projected 2D covariance and drawn back to front. This is a browser preview, not a reference renderer.
// ---------------------------------------------------------------------------------------------------------------------
interface SplatData { n: number; pos: Float32Array; scale: Float32Array; rgba: Uint8Array; rot: Uint8Array; box: THREE.Box3 }

function parseSplat(buf: ArrayBuffer): SplatData {
  const n = Math.floor(buf.byteLength / 32);
  const f = new Float32Array(buf, 0, n * 8);   // x y z sx sy sz + 8 colour/rotation bytes = 8 floats per record
  const u = new Uint8Array(buf);
  const pos = new Float32Array(n * 3), scale = new Float32Array(n * 3), rgba = new Uint8Array(n * 4), rot = new Uint8Array(n * 4);
  const box = new THREE.Box3();
  const v = new THREE.Vector3();
  for (let i = 0; i < n; i++) {
    pos.set(f.subarray(i * 8, i * 8 + 3), i * 3);
    scale.set(f.subarray(i * 8 + 3, i * 8 + 6), i * 3);
    rgba.set(u.subarray(i * 32 + 24, i * 32 + 28), i * 4);
    rot.set(u.subarray(i * 32 + 28, i * 32 + 32), i * 4);
    box.expandByPoint(v.set(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]));
  }
  return { n, pos, scale, rgba, rot, box };
}

const VERT = /* glsl */ `
precision highp float;
attribute vec3 center; attribute vec3 gscale; attribute vec4 color; attribute vec4 grot;
uniform vec2 viewport;
varying vec4 vColor; varying vec2 vPos;
void main() {
  vec4 cam = modelViewMatrix * vec4(center, 1.0);
  float d = -cam.z;
  if (d < 0.01) { gl_Position = vec4(0.0, 0.0, 2.0, 1.0); return; }
  float fx = projectionMatrix[0][0] * viewport.x * 0.5;
  float fy = projectionMatrix[1][1] * viewport.y * 0.5;
  vec4 q = (grot - 128.0) / 128.0;                       // w, x, y, z
  q = q / max(length(q), 1e-6);
  float w = q.x, x = q.y, y = q.z, z = q.w;
  mat3 R = mat3(1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y + z * w), 2.0 * (x * z - y * w),
                2.0 * (x * y - z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z + x * w),
                2.0 * (x * z + y * w), 2.0 * (y * z - x * w), 1.0 - 2.0 * (x * x + y * y));
  mat3 S = mat3(gscale.x, 0.0, 0.0, 0.0, gscale.y, 0.0, 0.0, 0.0, gscale.z);
  mat3 M = R * S;
  mat3 Vrk = M * transpose(M);
  mat3 J = mat3(fx / d, 0.0, 0.0,   0.0, fy / d, 0.0,   fx * cam.x / (d * d), fy * cam.y / (d * d), 0.0);
  mat3 T = J * mat3(modelViewMatrix);
  mat3 cov = T * Vrk * transpose(T);
  float a = cov[0][0] + 0.3, b = cov[0][1], c = cov[1][1] + 0.3;
  float mid = 0.5 * (a + c);
  float rad = length(vec2(0.5 * (a - c), b));
  float l1 = mid + rad, l2 = max(mid - rad, 0.01);
  vec2 major = normalize(vec2(b, l1 - a));
  vec2 minor = vec2(major.y, -major.x);
  vec2 ax1 = min(sqrt(2.0 * l1), 1024.0) * major;
  vec2 ax2 = min(sqrt(2.0 * l2), 1024.0) * minor;
  vec4 clip = projectionMatrix * cam;
  vec2 ndc = clip.xy / clip.w;
  vColor = color / 255.0;
  vPos = position.xy;
  gl_Position = vec4(ndc + (position.x * ax1 + position.y * ax2) * 2.0 / viewport, clip.z / clip.w, 1.0);
}`;
const FRAG = /* glsl */ `
precision highp float;
varying vec4 vColor; varying vec2 vPos;
void main() {
  float A = -dot(vPos, vPos);
  if (A < -4.0) discard;
  float B = exp(A) * vColor.a;
  gl_FragColor = vec4(B * vColor.rgb, B);
}`;

function SplatCloud({ data }: { data: SplatData }) {
  const { camera, size, gl } = useThree();
  const meshRef = useRef<THREE.Mesh>(null);
  const lastDir = useRef(new THREE.Vector3(9, 9, 9));
  const arrays = useMemo(() => ({
    center: new Float32Array(data.pos), gscale: new Float32Array(data.scale),
    color: new Float32Array(data.rgba), grot: new Float32Array(data.rot),
  }), [data]);
  const order = useMemo(() => Array.from({ length: data.n }, (_, i) => i), [data]);

  const geometry = useMemo(() => {
    const g = new THREE.InstancedBufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array([-2, -2, 0, 2, -2, 0, 2, 2, 0, -2, 2, 0]), 3));
    g.setIndex([0, 1, 2, 0, 2, 3]);
    g.instanceCount = data.n;
    const add = (name: string, arr: Float32Array, items: number) => {
      const a = new THREE.InstancedBufferAttribute(arr, items);
      a.setUsage(THREE.DynamicDrawUsage);
      g.setAttribute(name, a);
    };
    add("center", arrays.center, 3); add("gscale", arrays.gscale, 3); add("color", arrays.color, 4); add("grot", arrays.grot, 4);
    return g;
  }, [data, arrays]);

  const material = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: false, depthTest: false,
    blending: THREE.CustomBlending, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
    uniforms: { viewport: { value: new THREE.Vector2(1, 1) } },
  }), []);

  useFrame(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const pr = gl.getPixelRatio();
    material.uniforms.viewport.value.set(size.width * pr, size.height * pr);
    const dir = camera.getWorldDirection(new THREE.Vector3());
    if (dir.distanceTo(lastDir.current) < 0.02) return;     // re-sort only when the view direction changed noticeably
    lastDir.current.copy(dir);
    const depth = new Float32Array(data.n);
    for (let i = 0; i < data.n; i++) {
      depth[i] = (data.pos[i * 3] - camera.position.x) * dir.x + (data.pos[i * 3 + 1] - camera.position.y) * dir.y + (data.pos[i * 3 + 2] - camera.position.z) * dir.z;
    }
    order.sort((a, b) => depth[b] - depth[a]);               // far to near
    const attrs: [string, Float32Array, number][] = [["center", arrays.center, 3], ["gscale", arrays.gscale, 3], ["color", arrays.color, 4], ["grot", arrays.grot, 4]];
    for (const [name, arr, k] of attrs) {
      const src = name === "center" ? data.pos : name === "gscale" ? data.scale : name === "color" ? data.rgba : data.rot;
      for (let j = 0; j < data.n; j++) for (let c = 0; c < k; c++) arr[j * k + c] = src[order[j] * k + c];
      (geometry.getAttribute(name) as THREE.InstancedBufferAttribute).needsUpdate = true;
    }
  });
  return <mesh ref={meshRef} geometry={geometry} material={material} frustumCulled={false} />;
}

export function SplatViewer({ projectId, path }: { projectId: string; path: string }) {
  const { data, error } = useRemote(projectId, path, parseSplat);
  if (error) return <p className="text-sm text-destructive" role="alert">{error}</p>;
  if (!data) return <Spinner />;
  const { center, radius } = frameOf(data.box);
  return <Shell center={center} radius={radius}><SplatCloud data={data} /></Shell>;
}
