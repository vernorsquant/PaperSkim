import { useEffect, useId, useState } from "react";
import ModelDropdown from "./ModelDropdown.jsx";
import { submitJob, uploadJob } from "../api.js";

const MODEL_KEY = "paperskim.models";
const LEVEL_KEY = "paperskim.level";
// User default (2026-11-08): their GLM offload model.
const DEFAULT_WRITER = "z-ai/glm-5.3-flash";

const LEVELS = [
  { v: "eli5", label: "Explain like I'm 12", hint: "Plain language, analogies, no formulas unless unavoidable" },
  { v: "student", label: "Undergrad", hint: "Intuition first, jargon defined, key results kept" },
  { v: "grad", label: "Grad / adjacent researcher", hint: "Technical depth, methods, caveats, related work" },
  { v: "expert", label: "Domain expert", hint: "Full rigor, exact claims, limitations, open problems" },
];

function loadSavedModels() {
  try {
    return JSON.parse(localStorage.getItem(MODEL_KEY) || "{}");
  } catch {
    return {};
  }
}

function loadSavedLevel() {
  const v = localStorage.getItem(LEVEL_KEY);
  return LEVELS.some((l) => l.v === v) ? v : "student";
}

export default function JobForm({ onSubmit, disabled, onOpenSearch, prefill, setPrefill }) {
  const saved = loadSavedModels();
  const [input, setInput] = useState("");
  const [pages, setPages] = useState(4);
  const [writerModel, setWriterModel] = useState(saved.writer || DEFAULT_WRITER);
  const [visionModel, setVisionModel] = useState(saved.vision || "");
  const [level, setLevelState] = useState(loadSavedLevel);
  const [busy, setBusy] = useState(false);
  const [pdfFile, setPdfFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const linksId = useId();
  const pagesLabelId = useId();
  const fileInputId = useId();

  useEffect(() => {
    if (prefill) {
      setInput(prefill);
      setPdfFile(null);
      setPrefill("");
    }
  }, [prefill, setPrefill]);

  const rememberModels = (w, v) => {
    try {
      localStorage.setItem(MODEL_KEY, JSON.stringify({ writer: w, vision: v }));
    } catch {}
  };

  const setWriter = (m) => {
    setWriterModel(m);
    rememberModels(m, visionModel);
  };
  const setVision = (m) => {
    setVisionModel(m);
    rememberModels(writerModel, m);
  };

  const setLevel = (v) => {
    setLevelState(v);
    try {
      localStorage.setItem(LEVEL_KEY, v);
    } catch {}
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (pdfFile) {
        await onSubmit(() =>
          uploadJob(pdfFile, {
            target_pages: pages,
            writer_model: writerModel,
            vision_model: visionModel,
            explanation_level: level,
          })
        );
      } else {
        const lines = input
          .split("\n")
          .map((l) => l.trim())
          .filter(Boolean);
        for (const line of lines) {
          const payload = { input: line };
          await onSubmit(() => submitJob({ ...payload, target_pages: pages, writer_model: writerModel, vision_model: visionModel, explanation_level: level }));
        }
      }
    } finally {
      setBusy(false);
    }
  };

  const ready = !disabled && !busy && writerModel && visionModel && (pdfFile || input.trim());

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f && f.name.toLowerCase().endsWith(".pdf")) setPdfFile(f);
  };

  return (
    <form
      onSubmit={submit}
      className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 space-y-5"
    >
      <div>
        <div className="flex items-center justify-between mb-1">
          <label htmlFor={linksId} className="block text-xs font-medium text-slate-400">
            Paper links — arXiv, DOI, bioRxiv, Semantic Scholar, OpenReview, ACL, or
            direct PDF URL (one per line for batch)
          </label>
          <button
            type="button"
            onClick={onOpenSearch}
            className="text-xs text-indigo-400 hover:underline"
          >
            🔍 Search papers
          </button>
        </div>
        <textarea
          id={linksId}
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setPdfFile(null);
          }}
          rows={3}
          placeholder={"https://arxiv.org/abs/2401.12345\n10.1101/2024.01.01.575000\nhttps://example.com/paper.pdf"}
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-200 placeholder-slate-600 focus:border-indigo-500 focus:outline-none font-mono"
        />
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`rounded-lg border border-dashed px-4 py-3 text-xs text-center ${
          dragOver
            ? "border-indigo-500 text-indigo-300"
            : "border-slate-700 text-slate-500"
        }`}
      >
        {pdfFile ? (
          <span className="text-slate-300">
            📄 {pdfFile.name}{" "}
            <button
              type="button"
              onClick={() => setPdfFile(null)}
              aria-label={`Remove ${pdfFile.name}`}
              className="text-red-400 hover:underline ml-1"
            >
              remove
            </button>
          </span>
        ) : (
          <>
            …or drop a PDF here —{" "}
            <label
              htmlFor={fileInputId}
              className="text-indigo-400 hover:underline cursor-pointer"
            >
              browse
              <input
                id={fileInputId}
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    setPdfFile(f);
                    setInput("");
                  }
                }}
              />
            </label>
          </>
        )}
      </div>

      <div className="flex flex-wrap gap-5">
        <ModelDropdown
          kind="writer"
          label="Writer model"
          value={writerModel}
          onChange={setWriter}
        />
        <ModelDropdown
          kind="vision"
          label="Vision model"
          value={visionModel}
          onChange={setVision}
        />
      </div>

      <div>
        <label
          htmlFor="explain-level"
          className="block text-xs font-medium text-slate-400 mb-1"
          title="How technical should the explanation be?"
        >
          Explain it to me like…
        </label>
        <select
          id="explain-level"
          value={level}
          onChange={(e) => setLevel(e.target.value)}
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-indigo-500 focus:outline-none"
        >
          {LEVELS.map((l) => (
            <option key={l.v} value={l.v}>
              {l.label} — {l.hint}
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-end justify-between">
        <div
          role="group"
          aria-labelledby={pagesLabelId}
          aria-label={`Target pages: ${pages}`}
        >
          <label
            id={pagesLabelId}
            className="block text-xs font-medium text-slate-400 mb-1"
          >
            Target pages
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPages(Math.max(1, pages - 1))}
              aria-label="Decrease target pages"
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
              aria-label="Increase target pages"
              className="h-9 w-9 rounded-lg border border-slate-700 bg-slate-900 text-lg hover:bg-slate-800"
            >
              +
            </button>
          </div>
        </div>
        <button
          type="submit"
          disabled={!ready}
          className="rounded-lg bg-indigo-600 px-6 py-3 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {busy ? "Submitting…" : "Condense"}
        </button>
      </div>
    </form>
  );
}
