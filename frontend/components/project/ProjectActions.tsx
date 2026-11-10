"use client";
import { Check, Pencil, Trash2, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

/** Rename (PATCH /api/projects/{id}) and delete-with-confirmation (DELETE) controls. */
export function ProjectActions({ project, onRenamed, onDeleted, onError }: {
  project: Project; onRenamed: (p: Project) => void; onDeleted: () => void; onError: (m: string) => void;
}) {
  const [mode, setMode] = useState<"idle" | "rename" | "delete">("idle");
  const [name, setName] = useState(project.name);

  async function rename() {
    if (!name.trim() || name.trim() === project.name) { setMode("idle"); return; }
    try {
      onRenamed(await api<Project>(`/api/projects/${project.id}`, { method: "PATCH", body: JSON.stringify({ name: name.trim() }) }));
      setMode("idle");
    } catch (e) { onError((e as Error).message); }
  }
  async function remove() {
    try { await api(`/api/projects/${project.id}`, { method: "DELETE" }); onDeleted(); } catch (e) { onError((e as Error).message); setMode("idle"); }
  }

  if (mode === "rename") {
    return (
      <div className="flex items-center gap-1">
        <Input autoFocus maxLength={150} value={name} aria-label="New project name" className="h-8 w-44"
          onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") rename(); if (e.key === "Escape") setMode("idle"); }} />
        <Button size="icon" variant="ghost" aria-label="Save name" onClick={rename}><Check className="h-4 w-4" /></Button>
        <Button size="icon" variant="ghost" aria-label="Cancel rename" onClick={() => setMode("idle")}><X className="h-4 w-4" /></Button>
      </div>
    );
  }
  if (mode === "delete") {
    return (
      <div className="flex items-center gap-1 text-sm" role="alertdialog" aria-label={`Confirm deleting ${project.name}`}>
        <span className="text-destructive">Delete project and all its media and results?</span>
        <Button size="sm" variant="outline" onClick={remove}>Delete</Button>
        <Button size="sm" variant="ghost" onClick={() => setMode("idle")}>Cancel</Button>
      </div>
    );
  }
  return (
    <div className="flex items-center">
      <Button variant="ghost" size="icon" aria-label={`Rename ${project.name}`} onClick={() => { setName(project.name); setMode("rename"); }}><Pencil className="h-4 w-4" /></Button>
      <Button variant="ghost" size="icon" aria-label={`Delete ${project.name}`} onClick={() => setMode("delete")}><Trash2 className="h-4 w-4" /></Button>
    </div>
  );
}
