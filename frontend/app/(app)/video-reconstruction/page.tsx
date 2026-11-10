"use client";
import { MediaPanel } from "@/components/project/MediaPanel";
import { ReconstructionStudio } from "@/components/project/ReconstructionStudio";
import { ProjectScope } from "@/components/layout/ProjectScope";

export default function Page() {
  return (
    <ProjectScope title="Video Reconstruction" subtitle="Upload a walkthrough video, run reconstruction and follow job status, coverage and capture guidance.">
      {(d) => (
        <div className="space-y-4">
          <MediaPanel projectId={d.id} media={d.media} jobs={d.jobs.filter((j) => j.type !== "IMAGE_ANALYSIS")} onChanged={d.refresh} />
          <ReconstructionStudio projectId={d.id} jobs={d.jobs.filter((j) => j.type !== "IMAGE_ANALYSIS")} onChanged={d.refresh} />
        </div>
      )}
    </ProjectScope>
  );
}
