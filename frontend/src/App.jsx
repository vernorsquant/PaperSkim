import { useEffect, useState } from "react";
import { getSettings, listJobs, submitJob } from "./api.js";
import JobForm from "./components/JobForm.jsx";
import JobList from "./components/JobList.jsx";
import JobDetail from "./components/JobDetail.jsx";
import SettingsModal from "./components/SettingsModal.jsx";

export default function App() {
  const [hasKey, setHasKey] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const [showSettings, setShowSettings] = useState(false);

  const refreshSettings = () =>
    getSettings()
      .then((s) => {
        setHasKey(s.has_key);
        if (!s.has_key) setShowSettings(true);
      })
      .catch(() => setHasKey(false));

  useEffect(() => {
    refreshSettings();
    const t = setInterval(() => {
      listJobs().then(setJobs).catch(() => {});
    }, 2000);
    listJobs().then(setJobs).catch(() => {});
    return () => clearInterval(t);
  }, []);

  const onSubmit = async (body) => {
    setError("");
    try {
      const { id } = await submitJob(body);
      const jobs2 = await listJobs();
      setJobs(jobs2);
      setSelected(id);
    } catch (e) {
      setError(String(e.message || e));
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <header className="border-b border-slate-800 px-8 py-5 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Paper<span className="text-indigo-400">Skim</span>
          </h1>
          <p className="text-sm text-slate-400">
            Condense arXiv papers into short, undergrad-readable PDFs
          </p>
        </div>
        <button
          onClick={() => setShowSettings(true)}
          className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800"
        >
          {hasKey ? "Settings" : "Set API key"}
        </button>
      </header>

      <main className="mx-auto max-w-4xl px-8 py-8 space-y-8">
        <JobForm onSubmit={onSubmit} disabled={hasKey === false} />
        {error && (
          <div className="rounded-lg border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}
        <JobList jobs={jobs} onSelect={setSelected} selected={selected} />
        {selected && <JobDetail id={selected} />}
      </main>

      {showSettings && (
        <SettingsModal
          onClose={() => setShowSettings(false)}
          onSaved={() => {
            setHasKey(true);
            setShowSettings(false);
          }}
        />
      )}
    </div>
  );
}
