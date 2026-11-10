"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { AuthShell, PasswordInput } from "@/components/auth/AuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorBox } from "@/components/ui/states";
import { api, saveToken } from "@/lib/api";

const DEV_ACCESS = process.env.NODE_ENV === "development" && process.env.NEXT_PUBLIC_DEV_ACCESS === "true"; // OFF unless NEXT_PUBLIC_DEV_ACCESS=true under `next dev`; always false in production builds

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Only when development access was explicitly switched on (local testing): no sign-in needed.
  useEffect(() => { if (DEV_ACCESS) router.replace("/dashboard"); }, [router]);
  if (DEV_ACCESS) return null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) { setError("Enter a valid email address."); return; }
    if (!password) { setError("Enter your password."); return; }
    setBusy(true);
    try {
      const res = await api<{ token: string }>("/api/auth/login", { method: "POST", body: JSON.stringify({ email: email.trim(), password }) });
      saveToken(res.token, remember);
      router.replace("/dashboard");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell title="Sign in" subtitle="Sign in to your Spatial Intelligence workspace">
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Input type="email" required autoComplete="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email" />
        <PasswordInput value={password} onChange={setPassword} label="Password" autoComplete="current-password" />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Remember me <span className="text-xs text-muted-foreground">(stay signed in after closing the browser; untick on shared computers)</span>
        </label>
        {error && <ErrorBox message={error} />}
        <Button type="submit" className="w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</Button>
      </form>
      <p className="text-sm">No account yet? <Link className="text-primary underline" href="/register">Create one</Link></p>
    </AuthShell>
  );
}
