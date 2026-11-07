import { useEffect, useState } from "react";
import { saveKey } from "../api.js";

export default function SettingsModal({ onClose, onSaved }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState(null); // {key_status, message}
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    setStatus(null);
    try {
      const res = await saveKey(key.trim());
      setStatus({ key_status: res.key_status, message: res.message });
      if (res.key_status === "valid") {
        setTimeout(() => onSaved(), 900);
      }
    } catch (err) {
      setError(String(err.message || err));
    }
    setBusy(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <form
        onSubmit={save}
        role="dialog"
        aria-modal="true"
        aria-label="OpenRouter API key settings"
        className="w-full max-w-md rounded-xl border border-slate-800 bg-slate-900 p-6 space-y-4"
      >
        <h2 className="text-lg font-semibold text-white">OpenRouter API key</h2>
        <p className="text-sm text-slate-400">
          Stored locally in <code className="text-slate-300">backend/paperskim.toml</code>{" "}
          (never committed). Keys are verified live before saving — get one at{" "}
          <a
            href="https://openrouter.ai/keys"
            target="_blank"
            rel="noreferrer"
            className="text-indigo-400 hover:underline"
          >
            openrouter.ai/keys
          </a>
          .
        </p>
        <input
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="sk-or-v1-…"
          aria-label="OpenRouter API key"
          autoFocus
          className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-200 placeholder-slate-600 focus:border-indigo-500 focus:outline-none"
        />
        {error && <p className="text-sm text-red-400">{error}</p>}
        {status && (
          <p
            className={`text-sm ${
              status.key_status === "valid" ? "text-emerald-400" : "text-yellow-400"
            }`}
          >
            {status.key_status === "valid"
              ? `✓ Key verified — saved (${status.message})`
              : `Saved, but could not verify: ${status.message}`}
          </p>
        )}
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy || !key.trim()}
            className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-40"
          >
            {busy ? "Verifying…" : "Verify & save"}
          </button>
        </div>
      </form>
    </div>
  );
}
