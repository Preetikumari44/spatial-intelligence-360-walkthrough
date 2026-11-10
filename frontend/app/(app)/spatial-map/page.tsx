"use client";
import { useRouter } from "next/navigation";
import { ProjectScope } from "@/components/layout/ProjectScope";
import { FloorPlanTab } from "@/components/project/FloorPlanTab";

export default function Page() {
  const router = useRouter();
  return (
    <ProjectScope title="Spatial Map" subtitle="Pick a room or viewpoint on the map and enter it. Rooms are confirmed by you; nothing is invented.">
      {(d) => <FloorPlanTab projectId={d.id} tour={d.tour} nodeId={d.nodeId} onSelect={d.setNodeId} onOpenTour={() => router.push("/walkthrough")} onChanged={d.refresh} />}
    </ProjectScope>
  );
}
