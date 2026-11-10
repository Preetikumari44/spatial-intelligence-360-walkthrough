"use client";
import { ImageIntelligence } from "@/components/project/ImageIntelligence";
import { MediaPanel } from "@/components/project/MediaPanel";
import { ProjectScope } from "@/components/layout/ProjectScope";

export default function Page() {
  return (
    <ProjectScope title="Image Intelligence" subtitle="Upload photos, detect objects and review masks, labels and measurements.">
      {(d) => (
        <div className="space-y-4"><MediaPanel projectId={d.id} media={d.media} jobs={d.jobs.filter((j) => j.type === "IMAGE_ANALYSIS")} onChanged={d.refresh} /><ImageIntelligence projectId={d.id} media={d.media.filter((m) => m.kind === "IMAGE")} version={d.version} /></div>
      )}
    </ProjectScope>
  );
}
