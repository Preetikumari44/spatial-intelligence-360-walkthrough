"use client";
import { Twin3D } from "@/components/project/Twin3D";
import { ProjectScope } from "@/components/layout/ProjectScope";

export default function Page() {
  return (
    <ProjectScope title="3D Digital Twin" subtitle="Reconstructed point cloud and camera path for the selected project.">
      {(d) => (
        <Twin3D projectId={d.id} tour={d.tour} nodeId={d.nodeId} onSelect={d.setNodeId} />
      )}
    </ProjectScope>
  );
}
