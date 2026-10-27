// Small dependency-free SVG charts. Every value drawn comes from the API; nothing is decorative.
import { h, svg } from "./dom.js";

export const COLORS = { green: "#0d7a4a", amber: "#d99a00", red: "#b42318", blue: "#1f5fbf", gray: "#94a3b8", navy: "#13335f", sky: "#7fb0f5" };

export function barChart(data, { height = 190, color = COLORS.blue, labelFmt = (s) => s } = {}) {
  const W = 520, H = height, padL = 30, padB = 26, padT = 24;
  const max = Math.max(1, ...data.map((d) => d.value));
  const top = Math.ceil(max / Math.max(1, Math.ceil(max / 4))) * Math.max(1, Math.ceil(max / 4));
  const bw = Math.min(46, (W - padL - 10) / data.length - 10);
  const s = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Bar chart" });
  const steps = 4;
  for (let i = 0; i <= steps; i++) {
    const v = (top / steps) * i, y = H - padB - ((H - padB - padT) * v) / top;
    s.append(svg("line", { class: "gl", x1: padL, x2: W - 6, y1: y, y2: y }), svg("text", { x: padL - 6, y: y + 4, "text-anchor": "end" }, Math.round(v * 10) / 10));
  }
  data.forEach((d, i) => {
    const x = padL + 12 + i * ((W - padL - 12) / data.length) + ((W - padL - 12) / data.length - bw) / 2;
    const bh = ((H - padB - padT) * d.value) / top;
    s.append(svg("rect", { x, y: H - padB - bh, width: bw, height: bh, rx: 4, fill: d.color || color }, svg("title", {}, `${d.label}: ${d.value}`)),
      svg("text", { x: x + bw / 2, y: H - 8, "text-anchor": "middle" }, labelFmt(d.label)),
      svg("text", { class: "v", x: x + bw / 2, y: H - padB - bh - 5, "text-anchor": "middle" }, d.value));
  });
  return s;
}

export function donut(data, { size = 168, centerLabel = "total" } = {}) {
  const total = data.reduce((a, d) => a + d.value, 0);
  const r = 62, c = 2 * Math.PI * r, s = svg("svg", { class: "chart", viewBox: "0 0 168 168", width: size, height: size, role: "img", "aria-label": "Donut chart" });
  s.append(svg("circle", { cx: 84, cy: 84, r, fill: "none", stroke: "#eef2f6", "stroke-width": 20 }));
  let off = 0;
  data.filter((d) => d.value > 0).forEach((d) => {
    const len = (d.value / total) * c;
    s.append(svg("circle", { cx: 84, cy: 84, r, fill: "none", stroke: d.color, "stroke-width": 20, "stroke-dasharray": `${len} ${c - len}`, "stroke-dashoffset": -off, transform: "rotate(-90 84 84)" }, svg("title", {}, `${d.label}: ${d.value}`)));
    off += len;
  });
  s.append(svg("text", { class: "big", x: 84, y: 86, "text-anchor": "middle" }, total), svg("text", { x: 84, y: 104, "text-anchor": "middle" }, centerLabel));
  return s;
}

export const legend = (items) => h("div", { class: "legend" }, items.map((i) => h("span", null, h("span", { class: "sw", style: { background: i.color } }), `${i.label} · ${i.value}`)));

export function hbars(rows, { color = COLORS.blue } = {}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return h("div", null, rows.map((r) => h("div", { class: "hbar" },
    h("span", { class: "lab", title: r.label }, r.label), h("span", { class: "bar" }, h("i", { style: { width: (r.value / max) * 100 + "%", background: r.color || color } })), h("span", { class: "n" }, r.value))));
}
