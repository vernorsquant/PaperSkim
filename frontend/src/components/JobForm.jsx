import { useState } from "react";
import ModelDropdown from "./ModelDropdown.jsx";
import { submitJob } from "../api.js";

export default function JobForm({ onSubmit, disabled }) {
  const [input, setInput] = useState("");
  const [pages, setPages] = useState(4);
  const [writerModel, setWriterModel] = useState("");
  const [visionModel, setVisionModel] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!input.trim() || !writerModel || !visionModel) return;
    setBusy(true);
    await onSubmit({
      input: input.trim(),
      target_pages: pages,
      writer_model: writerModel,
      vision_model: visionModel,
    });
    setBusy(false);
  };

  return (
    <form
      onSubmit={submit}
      className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 space-y-5"
    >
      <div>
        <label className="block text-xs font-medium text-slate-400 mb-1">
          arXiv link or ID
        </label>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="https://arxiv.org/abs/2401.12345"
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-200 placeholder-slate-600 focus:border-indigo-500 focus:outline-none"
        />
      </div>

      <div className="flex flex-wrap gap-5">
        <ModelDropdown
          kind="writer"
          label="Writer model"
          value={writerModel}
          onChange={setWriterModel}
        />
        <ModelDropdown
          kind="vision"
          label="Vision model"
          value={visionModel}
          onChange={setVisionModel}
        />
      </div>

      <div className="flex items-end justify-between">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1">
            Target pages
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPages(Math.max(1, pages - 1))}
              className="h-9 w-9 rounded-lg border border-slate-700 bg-slate-900 text-lg hover:bg-slate-800"
            >
              −
            </button>
            <span className="w-12 text-center text-xl font-semibold text-white">
              {pages}
            </span>
            <button
              type="button"
              onClick={() => setPages(Math.min(30, pages + 1))}
              className="h-9 w-9 rounded-lg border border-slate-700 bg-slate-900 text-lg hover:bg-slate-800"
            >
              +
            </button>
          </div>
        </div>
        <button
          type="submit"
          disabled={disabled || busy || !input.trim() || !writerModel || !visionModel}
          className="rounded-lg bg-indigo-600 px-6 py-3 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {busy ? "Submitting…" : "Condense"}
        </button>
      </div>
    </form>
  );
}
