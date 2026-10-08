# 2-3 minute demo script (matches `gitcontext-final-demo.mp4`)
| Time | Show | Say |
|---|---|---|
| 0:00 | Landing page (HTTPS) | "GitContext answers questions about a codebase, with evidence." |
| 0:10 | Sign up | "Real accounts; sessions are server-side and every repo belongs to one workspace." |
| 0:25 | Connect `pallets/click` | "I paste a public GitHub URL. Watch the real backend states." |
| 0:35 | Status changes to ready | "Cloned, scanned, chunked at function boundaries, embedded: 170 files, 1,693 chunks." |
| 0:45 | Re-index | "Re-indexing is incremental: unchanged files are not reprocessed." |
| 0:58 | Ask a yes/no confirmation question | "The answer cites `termui.py`, `decorators.py` and exact line ranges." |
| 1:15 | Ask about Stripe payments | "The repo has nothing about that, so it refuses and shows the closest code, labelled as not an answer." |
| 1:30 | Search with citations | "Same retrieval powers search: hybrid BM25 + vectors + exact names, reranked." |
| 1:45 | Log out, protected page redirects | "Auth is enforced server-side." |
| 1:55 | Log back in | "State persists." |
| 2:05 | Close: numbers | "Held-out Recall@5 0.83 on 12 questions; 23 of 24 refusals; I also publish where it fails." |
