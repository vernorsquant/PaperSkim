import { useEffect, useState } from "react";
import { getJob, pdfUrl, latexUrl, sourcePdfUrl } from "../api.js";

export default function JobDetail({ id }) {
  const [job, setJob] = useState(null);
  const [captions, setCaptions] = useState(null);
  const [showCaptions, setShowCaptions] = useState(false);

  useEffect(() => {
    const load = () => getJob(id).then(setJob).catch(() => {});
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [id]);

  if (!job) return null;
  const done = job.status === "done" && job.pdf_path;
  const title = job.title || job.arxiv_id;

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-white truncate">#{job.id} — {title}</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            {job.source_kind || "arxiv"}
            {job.cost_usd != null && job.cost_usd > 0
              ? ` · $${job.cost_usd.toFixed(4)}`
              : ""}
          </p>
        </div>
        <div className="flex gap-3 text-sm shrink-0">
          {job.source_pdf_path && (
            <a
              href={sourcePdfUrl(job.id)}
              target="_blank"
              rel="noreferrer"
              className="text-slate-400 hover:text-slate-200 hover:underline"
            >
              Original PDF
            </a>
          )}
          {done && (
            <>
              <a
                href={pdfUrl(job.id)}
                target="_blank"
                rel="noreferrer"
                className="text-indigo-400 hover:underline"
              >
                Open PDF
              </a>
              <a
                href={latexUrl(job.id)}
                download
                className="text-indigo-400 hover:underline"
              >
                Download LaTeX
              </a>
            </>
          )}
        </div>
      </div>

      {job.error && (
        <p className="rounded-lg border border-red-900 bg-red-950/50 px-4 py-3 text-sm text-red-300">
          {job.error}
        </p>
      )}
      {job.warnings?.length > 0 && (
        <ul className="rounded-lg border border-yellow-900 bg-yellow-950/40 px-4 py-3 text-sm text-yellow-300 list-disc list-inside">
          {job.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}

      {done ? (
        <iframe
          src={pdfUrl(job.id)}
          title="Condensed paper"
          className="h-[70vh] w-full rounded-lg border border-slate-800 bg-white"
        />
      ) : (
        <div className="flex items-center gap-2 py-8 justify-center">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-400 border-t-transparent" />
          <span className="text-sm text-slate-400">
            {job.status === "failed" ? "Failed" : `Working — stage: ${job.stage || "queued"}`}
          </span>
        </div>
      )}

      {showCaptions && captions && (
        <pre className="text-xs text-slate-400 overflow-auto max-h-64">
          {JSON.stringify(captions, null, 2)}
        </pre>
      )}
    </section>
  );
}
