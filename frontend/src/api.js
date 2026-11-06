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
export const listJobs = () => req("/api/jobs");
export const getJob = (id) => req(`/api/jobs/${id}`);
export const getModels = (kind) => req(`/api/models?kind=${kind}`);
export const getSettings = () => req("/api/settings");
export const saveKey = (api_key) =>
  req("/api/settings", { method: "PUT", body: JSON.stringify({ api_key }) });
export const pdfUrl = (id) => `/api/jobs/${id}/pdf`;
export const latexUrl = (id) => `/api/jobs/${id}/latex`;
