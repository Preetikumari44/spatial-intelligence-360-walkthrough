"use client";
import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ProjectActions } from "@/components/project/ProjectActions";
import { Input } from "@/components/ui/input";
import { Empty, ErrorBox, Spinner } from "@/components/ui/states";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

const TYPES = ["Flat / apartment", "House", "Office", "Warehouse", "Single object"];

export default function Projects() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState(TYPES[0]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<{ content: Project[] }>("/api/projects?size=100").then((p) => setProjects(p.content)).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/api/projects", { method: "POST", body: JSON.stringify({ name, propertyType: type }) });
      setName("");
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Projects</h1>
      <Card className="p-4">
        <form onSubmit={create} className="flex flex-col gap-2 sm:flex-row">
          <Input required maxLength={150} placeholder="New project name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Project name" />
          <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Property type" className="h-10 rounded-md border bg-card px-3 text-sm">
            {TYPES.map((t) => <option key={t}>{t}</option>)}
          </select>
          <Button type="submit">Create</Button>
        </form>
      </Card>
      {error && <ErrorBox message={error} />}
      {!projects && !error && <Spinner />}
      {projects?.length === 0 && <Empty title="No projects yet">Create one above to start uploading photos or video.</Empty>}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {projects?.map((p) => (
          <Card key={p.id} className="flex flex-wrap items-center justify-between gap-2 p-4">
            <Link href={`/projects/${p.id}`} className="min-w-0 flex-1">
              <p className="truncate font-medium">{p.name}</p>
              <p className="text-xs text-muted-foreground">{p.propertyType} · {new Date(p.createdAt).toLocaleDateString()}</p>
            </Link>
            <ProjectActions project={p} onError={setError} onDeleted={load}
              onRenamed={(u) => setProjects((cur) => cur?.map((x) => (x.id === u.id ? u : x)) ?? cur)} />
          </Card>
        ))}
      </div>
    </div>
  );
}
