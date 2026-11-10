"use client";
import { MeasurementsPanel } from "@/components/project/MeasurementsPanel";
import { ProjectScope } from "@/components/layout/ProjectScope";

export default function Page() {
  return (
    <ProjectScope title="Measurements" subtitle="Estimated, calibrated and verified measurements, with calibration tools.">
      {(d) => (
        <MeasurementsPanel projectId={d.id} tour={d.tour} version={d.version} onChanged={d.refresh} />
      )}
    </ProjectScope>
  );
}
