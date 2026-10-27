// API client: bearer auth, JSON errors, one retry for idempotent GETs on network failure, response-shape validation.
const BASE = "/api/v1";
const KEY = "vc_token";

export class ApiError extends Error {
  constructor(status, code, message, details) { super(message); this.status = status; this.code = code; this.details = details || {}; }
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };
export const token = () => sessionStorage.getItem(KEY);
export const setToken = (t) => (t ? sessionStorage.setItem(KEY, t) : sessionStorage.removeItem(KEY));

function qs(params) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) if (v !== undefined && v !== null && v !== "") u.set(k, v);
  const s = u.toString();
  return s ? "?" + s : "";
}

/** Throws a clear error if the server answer does not have the keys the UI relies on. */
export function need(obj, keys, label) {
  const missing = keys.filter((k) => !(obj && k in obj));
  if (missing.length) throw new ApiError(0, "bad_response", `Unexpected response from the server${label ? " (" + label + ")" : ""}: missing ${missing.join(", ")}.`);
  return obj;
}

async function request(method, path, { body, params, raw, retry = method === "GET", auth = true } = {}) {
  const headers = {};
  if (auth && token()) headers.Authorization = "Bearer " + token();
  if (body !== undefined && !raw) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(BASE + path + qs(params), { method, headers, body: raw ? body : body !== undefined ? JSON.stringify(body) : undefined });
  } catch (e) {
    if (retry) { await new Promise((r) => setTimeout(r, 400)); return request(method, path, { body, params, raw, retry: false, auth }); }
    throw new ApiError(0, "network", "Cannot reach the V-Check server. Check that it is running, then retry.");
  }
  if (res.status === 204) return null;
  const type = res.headers.get("Content-Type") || "";
  const data = type.includes("json") ? await res.json().catch(() => null) : await res.blob();
  if (!res.ok) {
    const err = (data && data.error) || {};
    const e = new ApiError(res.status, err.code || "error", err.message || `Request failed (${res.status}).`, err.details);
    e.requestId = err.request_id;
    if (res.status === 401 && auth && path !== "/auth/login") onUnauthorized(e);
    throw e;
  }
  return data;
}

export const api = {
  get: (p, params) => request("GET", p, { params }),
  post: (p, body) => request("POST", p, { body: body ?? {} }),
  patch: (p, body) => request("PATCH", p, { body }),
  put: (p, body) => request("PUT", p, { body }),
  del: (p) => request("DELETE", p),
  login: (email, password) => request("POST", "/auth/login", { body: { email, password }, auth: false }),
  meta: () => request("GET", "/meta", { auth: false }),
  blob: (p) => request("GET", p),
  /** Multipart upload with progress (fetch cannot report upload progress, XHR can). */
  upload(appId, file, docType, onProgress, replaces) {
    return new Promise((resolve, reject) => {
      const fd = new FormData();
      fd.append("file", file, file.name);
      if (docType) fd.append("document_type", docType);
      if (replaces) fd.append("replaces", replaces);
      const x = new XMLHttpRequest();
      x.open("POST", `${BASE}/applications/${appId}/documents`);
      x.setRequestHeader("Authorization", "Bearer " + token());
      x.upload.onprogress = (e) => e.lengthComputable && onProgress && onProgress(e.loaded / e.total);
      x.onerror = () => reject(new ApiError(0, "network", "Upload failed: cannot reach the server."));
      x.onload = () => {
        let data = null;
        try { data = JSON.parse(x.responseText); } catch { /* ignore */ }
        if (x.status >= 200 && x.status < 300) return resolve(data);
        const err = (data && data.error) || {};
        if (x.status === 401) onUnauthorized();
        reject(new ApiError(x.status, err.code || "error", err.message || `Upload failed (${x.status}).`, err.details));
      };
      x.send(fd);
    });
  },
};
