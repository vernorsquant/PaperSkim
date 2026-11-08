async function req(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export const submitJob = (body) =>
  req("/api/jobs", { method: "POST", body: JSON.stringify(body) });

export const uploadJob = (file, { target_pages, writer_model, vision_model }) => {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("target_pages", String(target_pages));
  fd.append("writer_model", writer_model);
  fd.append("vision_model", vision_model);
  return fetch("/api/jobs/upload", { method: "POST", body: fd }).then(async (res) => {
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail || detail;
      } catch {}
      throw new Error(detail);
    }
    return res.json();
  });
};

export const listJobs = () => req("/api/jobs");
export const stopQueue = () => req("/api/queue/stop", { method: "POST" });
export const getJob = (id) => req(`/api/jobs/${id}`);
export const getModels = (kind) => req(`/api/models?kind=${kind}`);
export const getSettings = () => req("/api/settings");
export const getHealth = () => req("/api/health");
export const searchPapers = (q) =>
  req(`/api/search?q=${encodeURIComponent(q)}`);
export const saveKey = (api_key) =>
  req("/api/settings", { method: "PUT", body: JSON.stringify({ api_key }) });
export const pdfUrl = (id) => `/api/jobs/${id}/pdf`;
export const latexUrl = (id) => `/api/jobs/${id}/latex`;
export const sourcePdfUrl = (id) => `/api/jobs/${id}/source-pdf`;
