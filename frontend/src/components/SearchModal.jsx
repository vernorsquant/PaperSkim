import { useEffect, useState } from "react";
import { searchPapers } from "../api.js";

export default function SearchModal({ onClose, onPick }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const run = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError("");
    try {
      const data = await searchPapers(query.trim());
      setResults(data.results);
      if (!data.results.length) setError("No results found.");
    } catch (err) {
      setError(String(err.message || err));
      setResults(null);
    }
    setBusy(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search papers"
        className="w-full max-w-2xl rounded-xl border border-slate-800 bg-slate-900 p-6 space-y-4"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Search papers</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close search"
            className="text-slate-500 hover:text-slate-300"
          >
            ✕
          </button>
        </div>
        <p className="text-xs text-slate-500">
          Searches arXiv and Semantic Scholar. Pick a result to fill the form.
        </p>
        <form onSubmit={run} className="flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. attention is all you need"
            aria-label="Search query"
            autoFocus
            className="flex-1 rounded-lg border border-slate-700 bg-slate-950 px-4 py-2 text-sm text-slate-200 placeholder-slate-600 focus:border-indigo-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={busy || !query.trim()}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-40"
          >
            {busy ? "Searching…" : "Search"}
          </button>
        </form>

        {error && <p className="text-sm text-red-400">{error}</p>}

        {results && results.length > 0 && (
          <ul className="divide-y divide-slate-800 max-h-96 overflow-auto">
            {results.map((r, i) => (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => onPick(r)}
                  className="w-full text-left px-2 py-3 hover:bg-slate-800 rounded-lg"
                >
                  <p className="text-sm font-medium text-slate-200">{r.title}</p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {[r.authors?.slice(0, 3).join(", "), r.year, r.venue]
                      .filter(Boolean)
                      .join(" · ")}
                    {r.citations != null && r.citations > 0
                      ? ` · ${r.citations} citations`
                      : ""}
                  </p>
                  <p className="text-xs text-indigo-400 mt-0.5">
                    {r.kind === "arxiv"
                      ? `arXiv:${r.ref}`
                      : r.kind === "doi"
                        ? `DOI:${r.ref}`
                        : "PDF link"}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
