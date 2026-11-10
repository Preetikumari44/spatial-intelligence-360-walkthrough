"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorBox, NotImplemented } from "@/components/ui/states";
import { download } from "@/lib/api";

export function ReportsPanel({ projectId }: { projectId: string }) {
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="max-w-xl space-y-3">
      <Card>
        <CardHeader><CardTitle>Object inventory (CSV)</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          <p className="text-sm text-muted-foreground">Labels, detection confidence, current measurements and their status.</p>
          <Button size="sm" onClick={() => download(`/api/projects/${projectId}/reports/inventory.csv`, "inventory.csv").catch((e) => setError(e.message))}>Download CSV</Button>
        </CardContent>
      </Card>
      {error && <ErrorBox message={error} />}
      <NotImplemented what="PDF reports and tour/floor-plan exports" />
    </div>
  );
}
