"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SystemDiagnostics } from "@/components/settings/SystemDiagnostics";
import { NotImplemented } from "@/components/ui/states";
import { usePrefs } from "@/lib/prefs";
import type { UnitSystem } from "@/lib/units";

const UNITS: UnitSystem[] = ["mm", "cm", "m", "in", "ft"];

export default function SettingsPage() {
  const { unit, setUnit, dark, toggleDark } = usePrefs();
  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <Card>
        <CardHeader><CardTitle>Display</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div>
            <p className="mb-1 text-sm font-medium">Measurement unit</p>
            <div className="flex flex-wrap gap-2">
              {UNITS.map((u) => (
                <button key={u} onClick={() => setUnit(u)} aria-pressed={unit === u}
                  className={`rounded-md border px-3 py-1.5 text-sm ${unit === u ? "bg-primary text-primary-foreground" : "bg-card"}`}>{u}</button>
              ))}
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={dark} onChange={toggleDark} /> Dark theme</label>
        </CardContent>
      </Card>
      <SystemDiagnostics />
      <NotImplemented what="profile, API keys and team management" />
    </div>
  );
}
