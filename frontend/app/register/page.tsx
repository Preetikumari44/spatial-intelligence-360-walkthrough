"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { AuthShell, PasswordInput } from "@/components/auth/AuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorBox } from "@/components/ui/states";
import { api, saveToken } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function validate(): string | null {
    if (!name.trim()) return "Enter your full name.";
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) return "Enter a valid email address.";
    if (password.length < 8) return "Password must be at least 8 characters.";
    if (new TextEncoder().encode(password).length > 72) return "Password must be at most 72 bytes.";
    if (password !== confirm) return "Passwords do not match.";
    return null;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const problem = validate();
    if (problem) { setError(problem); return; }
    setBusy(true);
    setError(null);
    try {
      // The register endpoint returns a token, so the new user is signed in immediately.
      const res = await api<{ token: string }>("/api/auth/register", {
        method: "POST", body: JSON.stringify({ displayName: name.trim(), email: email.trim(), password }),
      });
      saveToken(res.token, true);
      router.replace("/dashboard");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell title="Create your account" subtitle="Register with your email and a password">
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Input required autoComplete="name" placeholder="Full name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Full name" />
        <Input type="email" required autoComplete="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email" />
        <PasswordInput value={password} onChange={setPassword} label="Password" autoComplete="new-password" placeholder="Password (8+ characters)" />
        <PasswordInput value={confirm} onChange={setConfirm} label="Confirm password" autoComplete="new-password" />
        {error && <ErrorBox message={error} />}
        <Button type="submit" className="w-full" disabled={busy}>{busy ? "Creating account…" : "Create account"}</Button>
      </form>
      <p className="text-sm">Already registered? <Link className="text-primary underline" href="/login">Sign in</Link></p>
    </AuthShell>
  );
}
