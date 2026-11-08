import { useEffect, useState } from "react";
import { getHealth, getSettings, listJobs, stopQueue } from "./api.js";
import JobForm from "./components/JobForm.jsx";
import JobList from "./components/JobList.jsx";
import JobDetail from "./components/JobDetail.jsx";
import SearchModal from "./components/SearchModal.jsx";
import SettingsModal from "./components/SettingsModal.jsx";
import wallpaper from "./assets/waifu-wallpaper.jpg";

export default function App() {
  const [hasKey, setHasKey] = useState(null);
  const [keyStatus, setKeyStatus] = useState("unchecked");
  const [health, setHealth] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [prefill, setPrefill] = useState("");
  const [stopping, setStopping] = useState(false);

  const onStopQueue = async () => {
    if (!window.confirm("Cancel every queued job that hasn't started? Running jobs will finish.")) return;
    setStopping(true);
    try {
      await stopQueue();
      setJobs(await listJobs());
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setStopping(false);
    }
  };

  const refreshSettings = () =>
    getSettings()
      .then((s) => {
        setHasKey(s.has_key);
        setKeyStatus(s.key_status || "unchecked");
        if (!s.has_key) setShowSettings(true);
      })
      .catch(() => setHasKey(false));

  useEffect(() => {
    refreshSettings();
    getHealth().then(setHealth).catch(() => {});
    const t = setInterval(() => {
      listJobs().then(setJobs).catch(() => {});
    }, 2000);
    listJobs().then(setJobs).catch(() => {});
    return () => clearInterval(t);
  }, []);

  const onSubmit = async (submitFn) => {
    setError("");
    try {
      const { id } = await submitFn();
      const jobs2 = await listJobs();
      setJobs(jobs2);
      setSelected(id);
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  const missingTools = health
    ? ["tectonic", "pdftotext", "pdfinfo"].filter((t) => !health[t])
    : [];

  const keyBroken = hasKey && ["expired", "invalid"].includes(keyStatus);

  return (
    <div className="relative min-h-screen text-slate-200">
      {/* waifu wallpaper layer (wallhaven #5g96j3) under a heavy dark veil
          so the slate UI stays readable */}
      <div
        aria-hidden="true"
        className="fixed inset-0 bg-cover bg-center bg-no-repeat"
        style={{ backgroundImage: `url(${wallpaper})` }}
      />
      <div className="fixed inset-0 bg-slate-950/85" aria-hidden="true" />
      <div className="relative">
      <header className="border-b border-slate-800/80 bg-slate-950/40 px-8 py-5 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Paper<span className="text-indigo-400">Skim</span>
          </h1>
          <p className="text-sm text-slate-400">
            Condense papers into short, undergrad-readable PDFs
          </p>
        </div>
        <button
          onClick={() => setShowSettings(true)}
          className={`rounded-lg border px-4 py-2 text-sm hover:bg-slate-800 ${
            keyBroken
              ? "border-red-700 text-red-300"
              : "border-slate-700"
          }`}
        >
          {keyBroken
            ? `API key ${keyStatus} — fix`
            : hasKey
              ? "Settings"
              : "Set API key"}
        </button>
      </header>

      <main className="mx-auto max-w-4xl px-8 py-8 space-y-8">
        {missingTools.length > 0 && (
          <div className="rounded-lg border border-yellow-800 bg-yellow-950/40 px-4 py-3 text-sm text-yellow-300">
            Missing tools on this machine: {missingTools.join(", ")}. PDF jobs will
            fail without <code>pdftotext</code>/<code>pdfinfo</code> (poppler), and
            nothing compiles without <code>tectonic</code>. See README for install
            commands.
          </div>
        )}

        <JobForm
          onSubmit={onSubmit}
          disabled={hasKey === false}
          onOpenSearch={() => setShowSearch(true)}
          prefill={prefill}
          setPrefill={setPrefill}
        />
        {error && (
          <div className="rounded-lg border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}
        {jobs.some((j) => j.status === "queued") && (
          <div className="flex justify-end">
            <button
              onClick={onStopQueue}
              disabled={stopping}
              className="rounded-lg border border-red-800 px-4 py-2 text-sm text-red-300 hover:bg-red-950/60 disabled:opacity-50"
            >
              {stopping ? "Stopping…" : "■ Stop queue"}
            </button>
          </div>
        )}
        <JobList jobs={jobs} onSelect={setSelected} selected={selected} />
        {selected && <JobDetail id={selected} />}
      </main>

      {showSearch && (
        <SearchModal
          onClose={() => setShowSearch(false)}
          onPick={(paper) => {
            const s =
              paper.kind === "arxiv"
                ? `arXiv:${paper.ref}`
                : paper.kind === "doi"
                  ? paper.ref
                  : paper.ref;
            setPrefill(s);
            setShowSearch(false);
          }}
        />
      )}

      {showSettings && (
        <SettingsModal
          onClose={() => setShowSettings(false)}
          onSaved={() => {
            setHasKey(true);
            setKeyStatus("valid");
            setShowSettings(false);
          }}
        />
      )}
      </div>
    </div>
  );
}
