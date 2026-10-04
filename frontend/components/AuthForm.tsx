"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { ErrorBanner } from "./ui";

function Form({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(params.get("expired") ? "Your session expired. Please log in again." : null);

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      await api(`/auth/${mode}`, { method: "POST", body: JSON.stringify({ email, password }) });
      const next = params.get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }
  const input = "w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm outline-none focus:border-emerald-500";
  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-6">
      <Link href="/" className="mb-6 text-2xl font-bold tracking-tight">GitContext</Link>
      <h1 className="text-lg font-semibold">{mode === "login" ? "Log in" : "Create your account"}</h1>
      <form onSubmit={submit} className="mt-4 space-y-3">
        <input className={input} type="email" required autoComplete="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email" />
        <input className={input} type="password" required minLength={mode === "signup" ? 8 : undefined} autoComplete={mode === "login" ? "current-password" : "new-password"}
          placeholder={mode === "signup" ? "Password (8+ characters)" : "Password"} value={password} onChange={(e) => setPassword(e.target.value)} aria-label="Password" />
        {error && <ErrorBanner>{error}</ErrorBanner>}
        <button disabled={busy} className="w-full rounded-md bg-emerald-600 py-2 text-sm font-medium disabled:opacity-50">
          {busy ? "Please wait…" : mode === "login" ? "Log in" : "Sign up"}
        </button>
      </form>
      <p className="mt-4 text-sm text-slate-400">
        {mode === "login" ? <>New here? <Link className="text-emerald-400 hover:underline" href="/signup">Create an account</Link></>
          : <>Already have an account? <Link className="text-emerald-400 hover:underline" href="/login">Log in</Link></>}
      </p>
    </main>
  );
}
export default function AuthForm({ mode }: { mode: "login" | "signup" }) {
  return <Suspense><Form mode={mode} /></Suspense>;
}
