import { useEffect, useState } from "react";
import { getModels } from "../api.js";

function fmtPrice(cost) {
  const perM = cost * 1e6;
  if (perM === 0) return "free";
  if (perM < 0.01) return `$${perM.toFixed(4)}/M`;
  return `$${perM.toFixed(2)}/M`;
}

function fmtCtx(ctx) {
  if (!ctx) return "";
  if (ctx >= 1e6) return `${(ctx / 1e6).toFixed(0)}M ctx`;
  return `${Math.round(ctx / 1e3)}k ctx`;
}

export default function ModelDropdown({ kind, label, value, onChange }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    getModels(kind)
      .then(setData)
      .catch((e) =>
        setError(
          `${String(e.message || e)} — is the PaperSkim backend running on :8000?`
        )
      );
  }, [kind]);

  const models = data ? (showAll ? data.advanced : data.models) : [];
  const nAdvanced = data ? data.advanced.length - data.models.length : 0;

  return (
    <div className="flex-1">
      <label className="block text-xs font-medium text-slate-400 mb-1">{label}</label>
      {error ? (
        <p className="text-sm text-red-400">{error}</p>
      ) : (
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-indigo-500 focus:outline-none"
        >
          <option value="">Select a model…</option>
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
              {m.vision ? " · vision" : ""} · {fmtPrice(m.prompt_cost)}
              {m.context_length ? ` · ${fmtCtx(m.context_length)}` : ""}
            </option>
          ))}
        </select>
      )}
      {nAdvanced > 0 && (
        <button
          type="button"
          onClick={() => setShowAll(!showAll)}
          className="mt-1 text-xs text-indigo-400 hover:underline"
        >
          {showAll ? "Show top 10 only" : `Show all ${data.advanced.length} models`}
        </button>
      )}
    </div>
  );
}
