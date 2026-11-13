/* 그래프는 외부 라이브러리 없이 SVG로 직접 그립니다 (오프라인에서도 동작).
   숫자는 모두 서버(calc.py)가 계산한 값이고, 여기서는 그리기만 합니다. */
const SVGNS = "http://www.w3.org/2000/svg";
function sv(tag, attrs, ...kids) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  for (const k of kids) if (k != null) n.append(k);
  return n;
}
const svText = (x, y, text, attrs) => sv("text", { x, y, "font-size": 11, fill: "#4A5268", ...attrs }, String(text));

function chartBox(svgEl, legend) {
  const box = document.createElement("div");
  box.className = "chart";
  box.append(svgEl);
  if (legend) {
    const lg = document.createElement("div");
    lg.className = "legend";
    for (const [cls, label] of legend) {
      const i = document.createElement("span");
      i.className = "lg-item";
      const sw = document.createElement("i");
      sw.className = "lg-sw " + cls;
      i.append(sw, label);
      lg.append(i);
    }
    box.append(lg);
  }
  return box;
}

/* 기말고사 점수(가로) 별 내 환산 총점 + 반 평균선 + 예상 범위 띠 + 목표선 */
function overlayChart(plan, target) {
  const W = 640, H = 300, L = 46, R = 16, T = 28, B = 40;
  const g = plan.grades.find((x) => x.grade === target);
  const vals = plan.curve.flatMap((p) => [p.total, p.class_mean]);
  if (g && g.min_total != null) vals.push(g.min_total);
  const ymin = Math.max(0, Math.floor((Math.min(...vals) - 5) / 10) * 10);
  const ymax = Math.min(100, Math.ceil((Math.max(...vals) + 5) / 10) * 10);
  const fmax = plan.final_max || 100;
  const X = (f) => L + (f / fmax) * (W - L - R);
  const Y = (v) => T + (1 - (v - ymin) / (ymax - ymin)) * (H - T - B);
  const s = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "기말고사 점수별 환산 총점 그래프" });

  const lo = Math.max(0, plan.final_mean - plan.final_std), hi = Math.min(fmax, plan.final_mean + plan.final_std);
  s.append(sv("rect", { x: X(lo), y: T, width: X(hi) - X(lo), height: H - T - B, rx: 8, fill: "#DEE3F0" }));
  s.append(svText(X(lo) + 4, T + 12, "기말 예상 범위 (반 평균 ± 표준편차)", { "font-size": 10 }));
  const step = (ymax - ymin) / 5;
  for (let i = 0; i <= 5; i++) {
    const v = ymin + step * i;
    s.append(sv("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: "#E1E5EE" }));
    s.append(svText(L - 6, Y(v) + 4, Math.round(v), { "text-anchor": "end" }));
  }
  const tstep = [1, 2, 5, 10, 20, 25, 50, 100, 200, 500].find((st) => fmax / st <= 5) || fmax;
  const ticks = new Set();
  for (let f = 0; f < fmax - 1e-9; f += tstep) ticks.add(Math.round(f * 100) / 100);
  ticks.add(fmax);
  for (const f of ticks) s.append(svText(X(f), H - B + 16, f, { "text-anchor": "middle" }));
  s.append(svText((L + W - R) / 2, H - 6, `기말고사 점수 (만점 ${fmax})`, { "text-anchor": "middle" }));
  s.append(svText(L - 40, T - 12, "환산 총점", { "text-anchor": "start" }));

  const line = (key, attrs) => sv("polyline", { fill: "none", points: plan.curve.map((p) => `${X(p.final_score)},${Y(p[key])}`).join(" "), ...attrs });
  s.append(line("class_mean", { stroke: "#6B7490", "stroke-width": 2, "stroke-dasharray": "5 4" }));
  s.append(line("total", { stroke: "#27355F", "stroke-width": 2.5 }));
  if (g && g.min_total != null) {
    s.append(sv("line", { x1: L, x2: W - R, y1: Y(g.min_total), y2: Y(g.min_total), stroke: "#27355F", "stroke-width": 1, "stroke-dasharray": "2 3" }));
    s.append(svText(W - R - 4, Y(g.min_total) - 5, `${target} 기준선 (환산 ${g.min_total}점)`, { "text-anchor": "end", fill: "#27355F", stroke: "#FFFFFF", "stroke-width": 3, "paint-order": "stroke" }));
    s.append(sv("circle", { cx: X(g.min_score), cy: Y(g.min_total), r: 5.5, fill: "#FFFFFF", stroke: "#27355F", "stroke-width": 2 }));
    const right = g.min_score > fmax * 0.7;
    s.append(svText(X(g.min_score) + (right ? -9 : 9), Y(g.min_total) + 20, `기말 ${g.min_score}점이면 ${target}`,
      { "text-anchor": right ? "end" : "start", fill: "#27355F", "font-weight": 600, stroke: "#FFFFFF", "stroke-width": 3, "paint-order": "stroke" }));
  }
  return chartBox(s, [["lg-line", "내 환산 총점"], ["lg-dash", "반 평균 환산 점수(가정)"], ["lg-band", "기말 예상 범위"], ["lg-dot", "목표 학점에 닿는 기말 점수"]]);
}

/* 과목별 현재 환산 점수 vs 반 평균: 과목이 3개 이상이면 레이더, 아니면 막대 */
function radarChart(radar) {
  const n = radar.axes.length;
  const legend = [["lg-line", "내 환산 점수"], ["lg-dash", "반 평균(가정 포함)"]];
  if (n < 3) {
    const W = 640, rowH = 44, H = 20 + n * rowH, L = 120;
    const s = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "과목별 점수 비교" });
    radar.axes.forEach((name, i) => {
      const y = 14 + i * rowH, w = (W - L - 50) / 100;
      s.append(svText(L - 8, y + 18, name.slice(0, 10), { "text-anchor": "end", fill: "#27355F" }));
      s.append(sv("rect", { x: L, y, width: radar.mine[i] * w, height: 14, rx: 7, fill: "#27355F" }));
      s.append(svText(L + radar.mine[i] * w + 6, y + 12, radar.mine[i]));
      s.append(sv("rect", { x: L, y: y + 18, width: radar.class_mean[i] * w, height: 10, rx: 5, fill: "#AEB8D6" }));
      s.append(svText(L + radar.class_mean[i] * w + 6, y + 27, radar.class_mean[i]));
    });
    return chartBox(s, [["lg-bar", "내 환산 점수"], ["lg-bar2", "반 평균(가정 포함)"]]);
  }
  const W = 420, H = 380, cx = W / 2, cy = H / 2 + 4, Rr = 130;
  const ang = (i) => -Math.PI / 2 + (2 * Math.PI * i) / n;
  const pt = (i, v) => [cx + Math.cos(ang(i)) * Rr * (v / 100), cy + Math.sin(ang(i)) * Rr * (v / 100)];
  const poly = (arr) => arr.map((v, i) => pt(i, v).join(",")).join(" ");
  const s = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "과목별 레이더 차트" });
  for (const ring of [25, 50, 75, 100]) {
    s.append(sv("polygon", { points: poly(radar.axes.map(() => ring)), fill: "none", stroke: "#E1E5EE" }));
    s.append(svText(cx + 3, cy - Rr * (ring / 100) + 11, ring, { "font-size": 9, fill: "#aaa" }));
  }
  radar.axes.forEach((name, i) => {
    const [x, y] = pt(i, 100), [lx, ly] = pt(i, 118);
    s.append(sv("line", { x1: cx, y1: cy, x2: x, y2: y, stroke: "#E1E5EE" }));
    const c = Math.cos(ang(i));
    s.append(svText(lx, ly + 4, name.length > 8 ? name.slice(0, 8) + "…" : name,
      { "text-anchor": c > 0.3 ? "start" : c < -0.3 ? "end" : "middle", fill: "#27355F" }));
  });
  s.append(sv("polygon", { points: poly(radar.class_mean), fill: "none", stroke: "#6B7490", "stroke-width": 2, "stroke-dasharray": "5 4" }));
  s.append(sv("polygon", { points: poly(radar.mine), fill: "rgba(28,28,28,.10)", stroke: "#27355F", "stroke-width": 2.5 }));
  radar.mine.forEach((v, i) => { const [x, y] = pt(i, v); s.append(sv("circle", { cx: x, cy: y, r: 3.5, fill: "#27355F" })); });
  return chartBox(s, legend);
}

/* 학기별 평균 학점 추이 */
/* 점들을 부드러운 곡선으로 잇는 경로 (Catmull-Rom → Bezier) */
function smoothPath(P) {
  let d = `M${P[0][0]} ${P[0][1]}`;
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[Math.max(i - 1, 0)], p1 = P[i], p2 = P[i + 1], p3 = P[Math.min(i + 2, P.length - 1)];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}

function trendChart(trend) {
  const W = 640, H = 270, L = 44, R = 36, T = 34, B = 46;
  const n = trend.length;
  const X = (i) => L + (n === 1 ? (W - L - R) / 2 : (i / (n - 1)) * (W - L - R));
  const Y = (v) => T + (1 - v / 4.5) * (H - T - B);
  const s = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "학기별 평균 학점 추이" });
  for (const v of [0, 1, 2, 3, 4.5]) {
    s.append(sv("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: "#E1E5EE" }));
    s.append(svText(L - 6, Y(v) + 4, v, { "text-anchor": "end" }));
  }
  // 평균 학점이 있는 학기끼리만 선으로 잇고, P/F 과목만 있는 학기(gpa 없음)는 선을 끊고 "P/F"로 표시
  let run = [];
  const flush = () => {
    if (run.length > 1) s.append(sv("path", { fill: "none", stroke: "#27355F", "stroke-width": 3, "stroke-linecap": "round", "stroke-linejoin": "round", d: smoothPath(run) }));
    run = [];
  };
  trend.forEach((t, i) => { if (t.gpa === null) flush(); else run.push([X(i), Y(t.gpa)]); });
  flush();
  trend.forEach((t, i) => {
    if (t.gpa === null) {
      s.append(sv("circle", { cx: X(i), cy: Y(0), r: 4.5, fill: "#FFFFFF", stroke: "#6B7490", "stroke-width": 1.5 }));
      s.append(svText(X(i), Y(0) - 10, "P/F", { "text-anchor": "middle", fill: "#6B7490" }));
    } else {
      s.append(sv("circle", { cx: X(i), cy: Y(t.gpa), r: 4.5, fill: "#27355F" }));
      s.append(svText(X(i), Y(t.gpa) - 12, t.gpa.toFixed(2), { "text-anchor": "middle", fill: "#27355F", "font-weight": 600 }));
    }
    const m = /(\d{4})\s*년\s*(\d|여름|겨울)\s*학기/.exec(t.semester);
    s.append(svText(X(i), H - B + 24, m ? `${m[1].slice(2)}-${m[2]}` : t.semester.slice(0, 8), { "text-anchor": "middle", "font-size": 12 }));
  });
  return chartBox(s);
}

/* 진행 막대 */
function progressBar(label, done, now, required) {
  const pctDone = Math.min(100, required ? (done / required) * 100 : 100);
  const pctNow = Math.min(100 - pctDone, required ? (now / required) * 100 : 0);
  const wrap = document.createElement("div");
  wrap.className = "pbar";
  wrap.innerHTML = `<div class="pbar-head"><span></span><b></b></div><div class="pbar-track"><i class="p-done"></i><i class="p-now"></i></div>`;
  wrap.querySelector("span").textContent = label;
  wrap.querySelector("b").textContent = `${done + now} / ${required}학점 (${Math.round(pctDone + pctNow)}%)` +
    (now > 0 ? ` (연한 부분 포함: 취득 ${done} + 이번 학기 ${now})` : ` (취득 ${done}학점, 이번 학기 과목 없음)`);
  wrap.querySelector(".p-done").style.width = pctDone + "%";
  wrap.querySelector(".p-now").style.width = pctNow + "%";
  return wrap;
}
