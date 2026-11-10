"use client";
import { Box, Camera, Footprints, Map as MapIcon, FolderKanban, LayoutDashboard, ListChecks, LogOut, Menu, Moon, Orbit, Ruler, Settings, Sun, Video } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { api, clearToken, getToken } from "@/lib/api";
import { usePrefs } from "@/lib/prefs";
import { cn } from "@/lib/utils";

const DEV_ACCESS = process.env.NODE_ENV === "development" && process.env.NEXT_PUBLIC_DEV_ACCESS === "true"; // OFF unless NEXT_PUBLIC_DEV_ACCESS=true under `next dev`; always false in production builds

const NAV = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/image-intelligence", label: "Image Intelligence", icon: Camera },
  { href: "/video-reconstruction", label: "Video Reconstruction", icon: Video },
  { href: "/spatial-map", label: "Spatial Map", icon: MapIcon },
  { href: "/digital-twin", label: "3D Digital Twin", icon: Orbit },
  { href: "/walkthrough", label: "Virtual Walkthrough", icon: Footprints },
  { href: "/inventory", label: "Object Inventory", icon: ListChecks },
  { href: "/measurements", label: "Measurements", icon: Ruler },
  { href: "/settings", label: "Settings", icon: Settings },
];

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const { dark, toggleDark } = usePrefs();
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(false);

  const [me, setMe] = useState<{ displayName: string; email: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  // Validate the stored session against the backend (GET /api/auth/me) before showing any protected page.
  // 401 -> back to /login. A network failure keeps the token and shows a retryable error instead of logging the user out.
  const checkSession = () => {
    setProblem(null);
    if (DEV_ACCESS) { setReady(true); return; } // explicit local dev access only: the backend acts as an existing user
    if (!getToken()) { router.replace("/login"); return; }
    api<{ displayName: string; email: string }>("/api/auth/me")
      .then((u) => { setMe(u); setReady(true); })
      .catch((e: Error & { status?: number }) => {
        if (e.status === 401) { clearToken(); router.replace("/login"); } else setProblem(e.message);
      });
  };
  useEffect(checkSession, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setOpen(false), [path]);

  if (problem) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <div className="max-w-md space-y-3 text-sm" role="alert">
          <p className="text-destructive">{problem}</p>
          <div className="flex gap-2">
            <Button onClick={checkSession}>Retry</Button>
            <Button variant="outline" onClick={() => { clearToken(); router.replace("/login"); }}>Sign out</Button>
          </div>
        </div>
      </main>
    );
  }
  if (!ready) return null;
  const nav = (
    <nav className="flex flex-col gap-1 p-3" aria-label="Main">
      {NAV.map(({ href, label, icon: Icon }) => (
        <Link key={href} href={href}
          className={cn("flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-muted", path.startsWith(href) && "bg-muted font-medium")}>
          <Icon className="h-4 w-4" /> {label}
        </Link>
      ))}
    </nav>
  );

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 border-r bg-card md:block">
        <div className="flex h-14 items-center gap-2 border-b px-4 font-semibold"><Box className="h-5 w-5 text-primary" /> Spatial</div>
        {nav}
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <aside className="absolute left-0 top-0 h-full w-60 bg-card shadow-lg" onClick={(e) => e.stopPropagation()}>
            <div className="flex h-14 items-center gap-2 border-b px-4 font-semibold"><Box className="h-5 w-5 text-primary" /> Spatial</div>
            {nav}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b bg-card px-3">
          <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu" onClick={() => setOpen(true)}><Menu className="h-5 w-5" /></Button>
          <div className="ml-auto flex items-center gap-1">
            {DEV_ACCESS && <span className="mr-1 rounded bg-warn/15 px-2 py-0.5 text-xs text-warn" title="Local development access: sign-in is skipped. Service status is under Settings → System Diagnostics.">Local dev access</span>}
            <Button variant="ghost" size="icon" aria-label="Toggle theme" onClick={toggleDark}>{dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</Button>
            {!DEV_ACCESS && (
              <>
                {me && <span className="mr-1 hidden max-w-[12rem] truncate text-sm text-muted-foreground sm:inline" title={me.email}>{me.displayName}</span>}
                <Button variant="ghost" size="icon" aria-label="Sign out"
                  onClick={() => { clearToken(); router.replace("/login"); }}><LogOut className="h-4 w-4" /></Button>
              </>
            )}
          </div>
        </header>
        <main className="min-w-0 flex-1 p-3 md:p-6">{children}</main>
      </div>
    </div>
  );
}
