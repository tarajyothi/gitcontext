export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) { super(message); }
}

export type Repo = {
  id: number; url: string; owner: string; name: string; status: "pending" | "indexing" | "ready" | "failed";
  stage: string | null; error_message: string | null; default_branch: string | null; commit_sha: string | null;
  file_count: number; chunk_count: number; total_bytes: number; languages: Record<string, number>;
  created_at: string; updated_at: string; indexed_at: string | null;
  last_index: { mode: "full" | "incremental"; files: number; new: number; changed: number; removed: number; unchanged: number;
    chunks_total: number; chunks_reprocessed: number; chunks_reused: number; seconds: number; truncated?: boolean; redacted_secrets?: number } | null;
};
export type User = { id: number; email: string; workspace: { id: number; name: string } };
export type Usage = { plan: string; repositories: { used: number; limit: number }; files_indexed: number; chunks_indexed: number };
export type FileRow = { path: string; language: string | null; size_bytes: number };

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      credentials: "same-origin",
      ...init,
      headers: init.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ApiError("network", "Can't reach the server. Check your connection and try again.", 0);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const e = body?.error;
    let msg = e?.message ?? (res.status >= 500 ? "Something went wrong on our side. Please try again." : "Request failed.");
    if (e?.code === "validation_error") msg = e.details?.[0]?.field?.includes("password") ? "Password must be at least 8 characters." : "Please check your input and try again.";
    throw new ApiError(e?.code ?? "http_error", msg, res.status);
  }
  return body as T;
}

export const ago = (iso: string | null) => {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
};
