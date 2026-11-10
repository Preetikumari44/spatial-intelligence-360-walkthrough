export type JobStatus =
  | "UPLOADED" | "QUEUED" | "PROCESSING" | "RECONSTRUCTING"
  | "CALIBRATING" | "GENERATING_TOUR" | "GENERATING_MODEL" | "TRAINING_SPLAT"
  | "COMPLETED" | "FAILED" | "CANCELLED";

export interface Project { id: string; name: string; propertyType?: string; status: string; createdAt: string }
export interface Media {
  id: string; projectId: string; kind: "IMAGE" | "VIDEO"; originalName: string; sizeBytes: number;
  width?: number; height?: number; durationSec?: number; is360: boolean; contentType?: string;
}
export interface Job {
  id: string; projectId: string; mediaId?: string; type: string; status: JobStatus;
  message?: string; error?: string; attempts: number; createdAt: string;
  progress?: number; cancelRequested?: boolean;
}

export type StageStatus = "ok" | "failed" | "skipped" | "unavailable";
export interface ReconStage { status: StageStatus; message: string; device_used?: string; backend?: string; [k: string]: unknown }
export interface ReconOutput { key: string; path: string; kind: string; size_bytes: number; label: string; [k: string]: unknown }
export interface ReconReport {
  stages: Record<string, ReconStage>;
  outputs: ReconOutput[];
  execution: { sfm_backend?: string; sfm_device?: string; open3d_device?: string; torch_device?: string; cpu_threads?: number; device_notes?: string[] };
  updated_at?: string;
}
export interface ReconOutputs { available: boolean; jobId?: string; report?: ReconReport; error?: string }
export interface FramesInfo { summary: { sampled?: number; kept: number; dropped_blur?: number; dropped_duplicate?: number; preview?: string; settings?: { effective_fps: number; max_side_px: number; free_ram_mb_at_start: number | null; min_frames_required: number }; warnings?: string[] }; frames: { name: string; t: number; thumb?: string }[] }
export interface AiCapabilities {
  platform: string; python: string; cpu: { name: string; logical_cores: number; threads_used: number };
  memory: { total_mb: number | null; available_mb: number | null };
  gpu: { adapters: string[]; intel: string[]; nvidia_present_but_unused: boolean };
  open3d: { installed: boolean; version?: string; sycl_available?: boolean; sycl_smoke_ok?: boolean; sycl_error?: string };
  torch: { installed: boolean; version?: string; xpu_available?: boolean };
  colmap: { found: boolean };
  devices: { open3d_device: string; torch_device: string; notes: string[] };
  sfm_backend: string;
}
export interface DetectedObject {
  id: string; mediaId: string; label: string; originalLabel: string; confidence?: number;
  bbox: [number, number, number, number]; polygon?: [number, number][]; edited: boolean;
}
export interface Measurement {
  id: string; objectId?: string; kind: string; valueMm: number; status: "ESTIMATED" | "CALIBRATED" | "VERIFIED";
  confidence?: number | null; source: string; note?: string; createdAt: string;
}
export type Hotspot = (
  | { yaw: number; pitch: number }
  | { visible: true; x: number; y: number; bearing: number }
  | { visible: false; bearing: number }
) & { verified?: boolean; kind?: string; inliers?: number; method?: string; directional?: boolean };
export interface NavNode {
  id: string; seq: number; label: string; framePath: string; panorama: boolean;
  x: number; y: number; z: number; headingRad: number; roomId?: string | null; timeSec?: number | null;
  /** false for a viewpoint-only tour: x, y, z and headingRad are placeholders (0) and must not be drawn */
  hasPose?: boolean;
  camera?: { w: number; h: number } | null;
}
export interface NavConnection { id: string; fromNodeId: string; toNodeId: string; hotspot: Hotspot; distanceUnits: number }
export interface Room { id: string; projectId: string; name: string; kind: string; source: "MANUAL" | "AUTO" }
export interface Reconstruction {
  available: boolean; status?: "CALIBRATED" | "UNCALIBRATED"; mmPerUnit?: number | null;
  extentsModelUnits?: { x: number; y: number; z: number }; extentsMm?: { x: number; y: number; z: number } | null; note?: string;
}
export interface Manifest {
  extents: { x: number; y: number; z: number }; points_path: string; warnings?: string[];
  panorama_coverage?: {
    status?: string; projection?: string | null; horizontal_degrees?: number; vertical_degrees?: number;
    asset_method?: string | null; note?: string; minimum_sphere_area_coverage?: number;
    best_candidate_sphere_area_coverage?: number | null; best_candidate_horizon_band_coverage?: number | null;
  };
  coverage?: {
    available?: boolean; registered_fraction?: number; registered_images?: number; total_images?: number;
    untracked_time_ranges_sec?: [number, number][];
  };
  floorplan: { points: [number, number][]; bounds: { minx: number; maxx: number; minz: number; maxz: number }; note: string };
}
export interface Tour {
  available: boolean; nodes: NavNode[]; connections: NavConnection[]; rooms?: Room[];
  manifest?: Manifest | null; reconstruction?: Reconstruction; sourceVideoId?: string | null;
}
