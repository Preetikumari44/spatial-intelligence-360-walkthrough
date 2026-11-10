"use client";
import { useRouter } from "next/navigation";
import { ProjectScope } from "@/components/layout/ProjectScope";
import { TourViewer } from "@/components/project/TourViewer";

export default function Page() {
  const router = useRouter();
  return (
    <ProjectScope title="Virtual Walkthrough" subtitle="Explore verified viewpoints and move between connected areas.">
      {(d) => <TourViewer projectId={d.id} tour={d.tour} sourceVideo={d.media.find((m) => m.id === d.tour.sourceVideoId) ?? null}
        nodeId={d.nodeId} onSelect={d.setNodeId} onRefresh={d.refresh} onBackToMap={() => router.push("/spatial-map")} />}
    </ProjectScope>
  );
}
