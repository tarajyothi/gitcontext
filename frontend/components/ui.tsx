"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ApiError, api, type Repo, type User } from "@/lib/api";

const STYLE: Record<Repo["status"], string> = {
  pending: "bg-slate-700 text-slate-200", indexing: "bg-sky-900 text-sky-300",
  ready: "bg-emerald-900 text-emerald-300", failed: "bg-red-950 text-red-300",
};
const STAGE: Record<string, string> = { cloning: "Cloning repository", scanning: "Scanning files", embedding: "Chunking & embedding code" };

export function StatusBadge({ repo }: { repo: Repo }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium ${STYLE[repo.status]}`}>
      {repo.status === "indexing" && <span className="h-2 w-2 animate-pulse rounded-full bg-sky-400" />}
      {repo.status}{repo.status === "indexing" && repo.stage ? ` · ${STAGE[repo.stage] ?? repo.stage}` : ""}
    </span>
  );
}

export const ErrorBanner = ({ children }: { children: ReactNode }) => (
  <p role="alert" className="rounded-md border border-red-900 bg-red-950 p-3 text-sm text-red-300">{children}</p>
);

/** Loads the current user; redirects to /login on 401 (never logged in, or session expired). */
export function useUser() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  useEffect(() => {
    api<User>("/auth/me").then(setUser).catch((e: ApiError) => {
      if (e.status === 401) router.replace(`/login${e.code === "session_expired" ? "?expired=1" : ""}`);
    });
  }, [router]);
  return user;
}

export function Shell({ user, children }: { user: User | null; children: ReactNode }) {
  const router = useRouter();
  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => null);
    router.replace("/login");
  }
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-800">
        <nav className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
          <Link href="/dashboard" className="font-semibold tracking-tight">GitContext</Link>
          <div className="flex items-center gap-4 text-sm text-slate-400">
            <span className="hidden sm:inline">{user?.email}</span>
            <button onClick={logout} className="rounded border border-slate-700 px-3 py-1 hover:bg-slate-800">Log out</button>
          </div>
        </nav>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>
    </div>
  );
}
