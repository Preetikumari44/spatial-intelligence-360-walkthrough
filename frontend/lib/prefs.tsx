"use client";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { UnitSystem } from "./units";

interface Prefs { unit: UnitSystem; setUnit: (u: UnitSystem) => void; dark: boolean; toggleDark: () => void }
const Ctx = createContext<Prefs | null>(null);

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [unit, setUnitState] = useState<UnitSystem>("cm");
  const [dark, setDark] = useState(false);

  useEffect(() => {
    try {
      const u = localStorage.getItem("unit") as UnitSystem | null;
      if (u) setUnitState(u);
      const d = localStorage.getItem("dark");
      setDark(d ? d === "1" : window.matchMedia("(prefers-color-scheme: dark)").matches);
    } catch {
      /* storage blocked: keep defaults */
    }
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  const setUnit = (u: UnitSystem) => {
    setUnitState(u);
    try { localStorage.setItem("unit", u); } catch { /* ignore */ }
  };
  const toggleDark = () => {
    setDark((d) => {
      try { localStorage.setItem("dark", d ? "0" : "1"); } catch { /* ignore */ }
      return !d;
    });
  };
  return <Ctx.Provider value={{ unit, setUnit, dark, toggleDark }}>{children}</Ctx.Provider>;
}

export function usePrefs() {
  const c = useContext(Ctx);
  if (!c) throw new Error("usePrefs outside PrefsProvider");
  return c;
}
