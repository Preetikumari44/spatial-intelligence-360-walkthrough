"use client";
import { Inventory } from "@/components/project/Inventory";
import { ReportsPanel } from "@/components/project/ReportsPanel";
import { ProjectScope } from "@/components/layout/ProjectScope";

export default function Page() {
  return (
    <ProjectScope title="Object Inventory" subtitle="Every object detected in the selected project, with export.">
      {(d) => (
        <div className="space-y-4"><Inventory projectId={d.id} media={d.media} version={d.version} /><ReportsPanel projectId={d.id} /></div>
      )}
    </ProjectScope>
  );
}
