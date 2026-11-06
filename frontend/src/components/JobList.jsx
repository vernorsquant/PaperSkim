const STAGE_COLORS = {
  queued: "bg-slate-700 text-slate-300",
  fetch: "bg-sky-900 text-sky-300",
  extract: "bg-sky-800 text-sky-200",
  vision: "bg-violet-900 text-violet-300",
  draft: "bg-indigo-900 text-indigo-300",
  review: "bg-amber-900 text-amber-300",
  revise: "bg-amber-800 text-amber-200",
  done: "bg-emerald-900 text-emerald-300",
  failed: "bg-red-900 text-red-300",
};

export default function JobList({ jobs, onSelect, selected }) {
  if (!jobs.length) {
    return (
      <p className="text-sm text-slate-500 py-6 text-center">
        No jobs yet — paste an arXiv link above.
      </p>
    );
  }
  return (
    <div className="rounded-xl border border-slate-800 divide-y divide-slate-800">
      {jobs.map((j) => (
        <button
          key={j.id}
          onClick={() => onSelect(j.id)}
          className={`w-full text-left px-5 py-3 flex items-center justify-between gap-4 hover:bg-slate-900 ${
            selected === j.id ? "bg-slate-900" : ""
          }`}
        >
          <div className="min-w-0">
            <p className="text-sm font-medium text-slate-200 truncate">
              #{j.id} · {j.arxiv_id}
            </p>
            <p className="text-xs text-slate-500">
              {j.target_pages}p · {j.writer_model} · {j.status}
              {j.status === "queued" ? "" : ` · ${j.stage || "—"}`}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {j.warnings?.length > 0 && (
              <span
                title={j.warnings.join("\n")}
                className="rounded bg-yellow-900/60 px-2 py-0.5 text-xs text-yellow-300"
              >
                ⚠ {j.warnings.length}
              </span>
            )}
            <span
              className={`rounded px-2 py-0.5 text-xs font-medium ${
                STAGE_COLORS[j.status === "running" ? j.stage : j.status] ||
                "bg-slate-700 text-slate-300"
              }`}
            >
              {j.status === "running" ? j.stage : j.status}
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}
