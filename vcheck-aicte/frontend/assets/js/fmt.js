const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const p2 = (n) => String(n).padStart(2, "0");
export function date(iso) { if (!iso) return "—"; const d = new Date(iso); return isNaN(d) ? "—" : `${p2(d.getDate())} ${MON[d.getMonth()]} ${d.getFullYear()}`; }
export function dateTime(iso) { if (!iso) return "—"; const d = new Date(iso); return isNaN(d) ? "—" : `${p2(d.getDate())} ${MON[d.getMonth()]} ${d.getFullYear()} ${p2(d.getHours())}:${p2(d.getMinutes())}`; }
export function ago(iso) {
  if (!iso) return ""; const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
  if (s < 60) return "just now"; if (s < 3600) return Math.floor(s / 60) + " min ago"; if (s < 86400) return Math.floor(s / 3600) + " h ago";
  return Math.floor(s / 86400) + " d ago";
}
export const bytes = (n) => (n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB");
export const ms = (n) => (n == null ? "—" : n < 1000 ? n + " ms" : (n / 1000).toFixed(1) + " s");
export const initials = (name) => (name || "?").split(/\s+/).map((s) => s[0]).slice(0, 2).join("").toUpperCase();
export const titleCase = (s) => (s || "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
export const pct = (n) => (n == null ? "—" : Math.round(n * 100) + "%");
export const plural = (n, a, b) => `${n} ${n === 1 ? a : b || a + "s"}`;
