/* POLARIS 화면 동작
   화면은 계산을 하지 않고, 서버(app.py)에 요청해서 받은 결과를 보여 주기만 합니다. */

const $ = (id) => document.getElementById(id);
let S = null;          // 서버에서 받아 온 전체 상태
let SUM = null;        // 요약(누적 평균 학점, 학기별 평균 평점 등)
let CANDS = [];        // 재수강 후보 목록
let editC = null;      // 수정 중인 지난 학기 과목 id
let editU = null;      // 수정 중인 현 학기 과목 id
let lastRetake = null; // 마지막으로 분석한 재수강 과목 {source, id}
let currentTab = "grades";

const TYPE_TEXT = { major: "전공", lib: "교양" };
// P/F 과목 성적 표시: 내부 값 P / NP를 학교 용어(합격 / F)로 보여 줌
const gradeText = (g) => (g === "NP" ? "F(P/F)" : g);
const typeLabel = (c) => TYPE_TEXT[c.type] + (c.required ? " · 필수" : "");

/* 용어 설명 (물음표 버튼에 마우스를 올리거나 누르면 보입니다) */
const GLOSSARY = {
  z: ["Z점수", "내 점수가 반 평균보다 표준편차 몇 개만큼 높은지(+) 낮은지(−) 나타낸 값입니다. z = (내 점수 − 평균) ÷ 표준편차. 0이면 평균, +1이면 평균보다 표준편차 1개만큼 위입니다."],
  std: ["표준편차", "점수가 평균 주변에 얼마나 흩어져 있는지를 나타내는 값입니다. 클수록 학생들 점수 차이가 큽니다."],
  top: ["예상 상위 비율", "z점수를 바탕으로, 점수가 종 모양(정규분포)으로 퍼져 있다고 가정했을 때 내가 반에서 상위 몇 %쯤인지 추정한 값입니다. 작을수록 상위입니다. 실제 등수와 다를 수 있습니다."],
  range: ["점수가 바뀌면(참고)", "현재 점수가 기말까지 표준편차의 일정 배수만큼 오르거나 내릴 수 있다고 가정했을 때의 최저~최고 학점입니다. 확정 성적이 아니며, 변동 폭은 '계산 기준'의 임의 설정값입니다."],
  maxg: ["최대 학점", "현재 점수 위치에서 교수님이 윗 등급을 최대한 많이 줄 때 받을 수 있는 학점입니다. 학칙상 A0 이상은 30% 이하, B0 이상은 70% 이하이고, 그 안에서 A+/A0, B+/B0 비율은 교수님이 정합니다. 상위 30% 이내면 A+, 30~70%면 B+, 그 아래는 C+입니다."],
  ming: ["최소 학점", "현재 점수 위치에서 구간 상한까지 등급이 채워진다고 가정할 때 최소한 받을 수 있는 학점입니다. 상위 30% 이내면 A0, 30~70%면 B0입니다. 교수님이 A를 적게 주면 이보다 낮아질 수 있습니다."],
  need: ["목표 달성 필요 평점", "목표 누적 평균 학점을 달성하려면 현 학기 과목들의 학점 가중 평균 평점이 얼마여야 하는지입니다. 4.5를 넘으면 현 학기만으로는 달성할 수 없습니다."],
  prob: ["목표 평점 달성 추정 가능성", "앞으로 점수가 현재 위치에서 무작위로 흔들린다고 가정하고 3000번 모의 계산했을 때, 목표 평균 학점에 도달한 비율로 정한 대략적인 가능성입니다. 실제로 검증된 확률이 아니라 가정에 따른 참고 지표입니다."],
  gparange: ["누적 평균 평점 예상 범위", "모의 계산 3000번 결과 중 가운데 80%(작은 쪽 10%와 큰 쪽 10%를 뺀 구간)가 들어가는 누적 평균 평점 범위입니다."],
  semgpa: ["현 학기 평균 평점", "현 학기 과목만으로 계산한 평점평균입니다."],
  cumgpa: ["누적 평균 평점", "지금까지 들은 모든 학기 과목을 합쳐서 계산한 평점평균입니다."],
};

/* ---------- 도우미 ---------- */

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "오류가 발생했습니다.");
  return data;
}

// 요소 만들기: el("td", {class:"num"}, "텍스트")  (textContent만 써서 입력값이 코드로 실행되지 않게 함)
function el(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const k in props || {}) {
    if (k === "class") e.className = props[k];
    else if (k.startsWith("on")) e[k] = props[k];
    else e.setAttribute(k, props[k]);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined) continue;
    e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return e;
}

// 용어 + 물음표 도움말
function term(key, label) {
  const [name, text] = GLOSSARY[key];
  return el("span", { class: "term" }, label || name,
    el("button", { type: "button", class: "help", "data-tip": `${name}: ${text}`, "aria-label": name + " 설명" }, "?"));
}

const f2 = (v) => (v === null || v === undefined ? "-" : v.toFixed(2));
const signed = (v) => (v > 0.0049 ? "+" : "") + v.toFixed(2);
const diff = (a, b) => (a === null || b === null ? "-" : signed(b - a));
const fillSelect = (sel, options, selected) => {
  sel.innerHTML = "";
  for (const [value, text] of options) {
    const o = el("option", { value }, text);
    if (value === selected) o.selected = true;
    sel.append(o);
  }
};

function table(headers, rows, numFrom = 1) {
  const thead = el("thead", {}, el("tr", {}, headers.map((h, i) => el("th", { class: i >= numFrom ? "num" : "" }, h))));
  const tbody = el("tbody", {}, rows);
  return el("div", { class: "scroll" }, el("table", {}, thead, tbody));
}
const tr = (cells, numFrom = 1) =>
  el("tr", {}, cells.map((c, i) => el("td", { class: i >= numFrom ? "num" : "" }, c)));

function cards(items, two) {
  return el("div", { class: "cards" + (two ? " two" : "") },
    items.map(([label, value, note]) =>
      el("div", { class: "card" }, el("div", { class: "label" }, label),
        el("div", { class: "value" }, value), note ? el("div", { class: "note" }, note) : null)));
}

function say(id, text) {
  const m = $(id);
  m.textContent = text || "";
  m.classList.remove("warn");
  m.removeAttribute("role");
}

/* 경고: 메시지를 경고 모양으로 보여 주고, 문제가 있는 입력칸을 강조(붉은 테두리·흔들림)한 뒤 그 칸에 커서를 둡니다 */
function warn(id, text, input) {
  const m = $(id);
  m.textContent = text;
  m.classList.add("warn");
  m.setAttribute("role", "alert");
  if (input) markInvalid(input);
}
function markInvalid(input) {
  input.classList.remove("invalid");
  void input.offsetWidth;                       // 흔들림 애니메이션을 다시 시작
  input.classList.add("invalid");
  input.focus();
}
// 서버가 돌려준 오류 문장("학점: ...")의 앞부분으로 어느 칸 문제인지 찾아 강조
function warnErr(id, err, fields) {
  const hit = fields && Object.keys(fields).find((k) => err.message.startsWith(k + ":"));
  warn(id, err.message, hit ? fields[hit] : null);
}
document.addEventListener("input", (e) => { if (e.target.classList && e.target.classList.contains("invalid")) e.target.classList.remove("invalid"); });

/* 입력 확인: 비었거나 범위를 벗어난 첫 칸을 찾음. 서버도 같은 검사를 다시 하지만, 보내기 전에 바로 알려 줌 */
function firstProblem(fields) {
  for (const [inp, label] of fields) {
    const v = inp.value.trim();
    if (!inp.hasAttribute("data-num")) { if (v === "") return [inp, `${label}: 값을 입력해 주세요.`]; continue; }
    const n = parseFloat(v);
    if (v === "" || Number.isNaN(n)) return [inp, `${label}: 숫자로 입력해 주세요.`];
    const lo = inp.min === "" ? null : parseFloat(inp.min), hi = inp.max === "" ? null : parseFloat(inp.max);
    if (lo !== null && hi !== null && lo > 0 && (n < lo || n > hi)) return [inp, `${label}: ${lo}~${hi} 사이로 입력해 주세요.`];
    if (hi !== null && n > hi) return [inp, `${label}: 값은 ${hi} 이하여야 합니다.`];
    if (lo !== null && n < lo) return [inp, `${label}: 값은 ${lo} 이상이어야 합니다.`];
  }
  return null;
}

/* 숫자 칸 입력 제한: + - e는 아예 써지지 않고, 정수 칸은 소수점도 막고, 소수 칸은 둘째 자리까지만 */
const isNumInput = (t) => t instanceof HTMLInputElement && t.hasAttribute("data-num");
const isIntField = (t) => !t.step || t.step === "1";
document.addEventListener("keydown", (e) => {
  if (!isNumInput(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
  if (["+", "-", "e", "E", ","].includes(e.key) || (isIntField(e.target) && e.key === ".")) e.preventDefault();
});
document.addEventListener("beforeinput", (e) => {          // 휴대폰 키보드 등 keydown이 안 오는 경우까지 막음
  if (!isNumInput(e.target) || !e.data) return;
  if (/[+\-eE,]/.test(e.data) || (isIntField(e.target) && e.data.includes("."))) e.preventDefault();
});
document.addEventListener("paste", (e) => {
  if (!isNumInput(e.target)) return;
  const txt = ((e.clipboardData || window.clipboardData).getData("text") || "").trim();
  if (!(isIntField(e.target) ? /^\d+$/ : /^\d*\.?\d+$/).test(txt)) e.preventDefault();
});
document.addEventListener("input", (e) => {
  const t = e.target;
  if (!isNumInput(t) || isIntField(t)) return;
  const m = /^(\d*)\.(\d{3,})$/.exec(t.value);
  if (m) t.value = m[1] + "." + m[2].slice(0, 2);
});

/* 학기 표기 통일 (서버 semester.py와 같은 규칙): 2026-1, 26-1, 2026년 1학기 → "2026년 1학기" */
function normSemester(raw) {
  const t = String(raw || "").replace(/\s+/g, "");
  if (!t) return null;
  const year = (x) => { let y = parseInt(x, 10); if (x.length === 2) y += 2000; return y >= 1990 && y <= 2100 ? y : null; };
  const Y = "(\\d{4}|\\d{2})";
  const pats = [new RegExp(`^${Y}[-./_](\\d)$`), new RegExp(`^${Y}(?:년도?|학년도?)[-./_]?(\\d)(?:학기)?$`),
    new RegExp(`^${Y}[-./_]?(\\d)학기$`), /^(\d{4})(\d)$/];
  for (const p of pats) {
    const m = p.exec(t);
    if (m) { const y = year(m[1]), n = +m[2]; return y && (n === 1 || n === 2) ? `${y}년 ${n}학기` : null; }
  }
  const m = new RegExp(`^${Y}(?:년도?|학년도?|[-./_])?(여름|하계|summer|s|겨울|동계|winter|w)(?:계절)?(?:학기)?$`, "i").exec(t);
  if (m && year(m[1])) return `${year(m[1])}년 ${["여름", "하계", "summer", "s"].includes(m[2].toLowerCase()) ? "여름" : "겨울"}학기`;
  return null;
}

/* ---------- 도움말 말풍선 ---------- */

const tip = $("tip");
function showTip(btn) {
  tip.textContent = btn.dataset.tip;
  tip.hidden = false;
  const r = btn.getBoundingClientRect();
  const w = tip.offsetWidth;
  let left = r.left + window.scrollX + r.width / 2 - w / 2;
  left = Math.max(8, Math.min(left, window.scrollX + document.documentElement.clientWidth - w - 8));
  tip.style.left = left + "px";
  tip.style.top = r.bottom + window.scrollY + 8 + "px";
}
document.addEventListener("mouseover", (e) => { if (e.target.classList.contains("help")) showTip(e.target); });
document.addEventListener("mouseout", (e) => { if (e.target.classList.contains("help")) tip.hidden = true; });
document.addEventListener("focusin", (e) => { if (e.target.classList.contains("help")) showTip(e.target); });
document.addEventListener("focusout", () => { tip.hidden = true; });
document.addEventListener("click", (e) => {
  if (e.target.classList.contains("help")) { e.preventDefault(); showTip(e.target); }
  else tip.hidden = true;
});

/* ---------- 탭 / 모드 ---------- */

function showTab(tab) {
  currentTab = tab;
  for (const b of $("nav").children) b.classList.toggle("active", b.dataset.tab === tab);
  for (const t of document.querySelectorAll(".tab")) t.hidden = t.id !== "tab-" + tab;
  const nb = $("nav").querySelector(`[data-tab="${tab}"]`);
  $("pageTitle").textContent = nb ? nb.firstChild.textContent.trim() : "";
  $("pageEyebrow").textContent = { grades: "ACADEMIC OVERVIEW", predict: "GRADE FORECAST", withdraw: "COURSE WITHDRAWAL", retake: "RETAKE ANALYSIS", guide: "ACADEMIC GUIDE", settings: "SETTINGS" }[tab] || "";
  if (tab === "withdraw") renderWithdrawSelect();
  if (tab === "guide") renderGuide();
  if (tab === "retake") ensureRetake();
  renderSetupNotice();
  window.scrollTo(0, 0);
}
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-go]");
  if (g) showTab(g.dataset.go);
});
$("brandLink").addEventListener("click", (e) => { e.preventDefault(); showTab("grades"); });
$("nav").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b && b.dataset.tab) showTab(b.dataset.tab);
});

const MODE_NOTES = {
  predict: {
    mid: "중간고사 이후 모드: 기말까지 점수가 많이 바뀔 수 있다고 보고 예상 범위를 넓게 계산합니다.",
    final: "기말고사 이후 모드: 점수가 거의 확정됐다고 보고 예상 범위를 좁게 계산합니다. 확정된 성적은 '내 성적' 탭에 입력해 두세요.",
  },
  withdraw: {
    mid: "수강 철회는 보통 중간고사 이후에 판단합니다. 철회 가능 기간은 학사일정에서 확인하세요.",
    final: "기말고사 이후에는 철회 신청 기간이 이미 지났을 수 있습니다. 참고용 비교로만 사용하세요.",
  },
  retake: {
    mid: "재수강은 기말고사 이후 성적이 확정된 뒤 판단하는 기능입니다. 지금은 미리 확인용으로 볼 수 있고, 현 학기 과목은 현재 점수 기준 예상 성적으로 계산합니다.",
    final: "기말고사 이후 모드: 최종 성적을 기준으로 재수강 여부를 판단합니다.",
  },
};

function renderMode() {
  const m = S.settings.mode;
  for (const b of document.querySelectorAll("[data-mode]")) {
    if (b.closest("#intro")) continue;
    b.classList.toggle("on", b.dataset.mode === m);
  }
  for (const t of document.querySelectorAll(".tabtag")) t.classList.toggle("match", t.dataset.when === m);
  $("noteMid").textContent = MODE_NOTES.predict[m];
  $("noteWithdraw").textContent = MODE_NOTES.withdraw[m];
  $("noteRetake").textContent = MODE_NOTES.retake[m];
}

async function setMode(m) {
  await api("PUT", "/api/mode", { mode: m });
  await loadAll();
  $("predictResult").innerHTML = "";
  $("withdrawResult").innerHTML = "";
  $("retakeResult").innerHTML = "";
  if (lastRetake) { if (currentTab === "retake") runRetake(lastRetake.source, lastRetake.id); else lastRetake = null; }
}
$("modeSwitch").addEventListener("click", (e) => {
  const m = e.target.dataset.mode;
  if (m) setMode(m);
});

/* ---------- 사용방법 (첫 접속 안내) ---------- */

let introMode = "mid";
function openIntro() {
  introMode = S.settings.mode;
  paintIntroMode();
  $("intro").hidden = false;
}
function paintIntroMode() {
  for (const b of $("introMode").children) b.classList.toggle("on", b.dataset.mode === introMode);
}
$("introMode").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) { introMode = b.dataset.mode; paintIntroMode(); }
});
async function closeIntro(never) {
  $("intro").hidden = true;
  const first = !S.settings_done;
  if (introMode !== S.settings.mode) await api("PUT", "/api/mode", { mode: introMode });
  if (never) await api("PUT", "/api/onboarded", { onboarded: true });
  await loadAll();
  if (first) showTab("settings");          // 처음이면 설정부터 확인하게 함
}
$("introStart").addEventListener("click", () => closeIntro(false));
$("introNever").addEventListener("click", () => closeIntro(true));
$("helpBtn").addEventListener("click", openIntro);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("intro").hidden) closeIntro(false); });

/* ---------- 설정 안내 (저장 전에는 기본값으로 계산 중임을 알림) ---------- */

function renderSetupNotice() {
  const need = !S.settings_done;
  $("setupBanner").hidden = !(need && currentTab !== "settings" && currentTab !== "grades");
}
$("goSettings").addEventListener("click", () => showTab("settings"));

/* ---------- 불러오기 ---------- */

async function loadAll() {
  S = await api("GET", "/api/state");
  const sum = await api("GET", "/api/summary");
  SUM = sum;
  CANDS = (await api("GET", "/api/retake/candidates")).candidates;
  renderMode();
  renderSetupNotice();
  renderSummary(sum);
  renderCompleted();
  renderCurrent();
  renderSettings();
  renderWithdrawSelect();
  renderSimSelect();
  if (currentTab === "retake") ensureRetake(); else renderRetakeList();
}

/* ---------- 1. 내 성적 ---------- */

let spSeq = 0;


function renderSummary(sum) {
  const box = $("summary");
  box.innerHTML = "";
  box.classList.add("kpis");
  const bar = (parts) => el("div", { class: "kbar" }, parts.filter((x) => x.v > 0).map((x) => el("i", { class: x.c, style: `flex:${x.v}` })));
  const legend = (parts) => el("div", { class: "klegend" }, parts.map((x) => el("span", {}, el("i", { class: "dot " + x.c }), x.t + " ", el("b", {}, x.n))));
  // 누적 평균 평점 카드: 성적 분포(A·B·C 이하)와 직전 학기 대비 변화
  const graded = S.completed.filter((c) => c.grade !== "P" && c.grade !== "NP");
  const grp = { a: 0, b: 0, c: 0 };
  for (const c of graded) { if (c.grade[0] === "A") grp.a++; else if (c.grade[0] === "B") grp.b++; else grp.c++; }
  const pct = (n) => (graded.length ? Math.round((n / graded.length) * 100) + "%" : "-");
  const gp = sum.semesters.filter((x) => x.gpa !== undefined);
  let delta = null;
  if (gp.length >= 2) {
    const d = gp[gp.length - 1].gpa - gp[gp.length - 2].gpa;
    delta = el("span", { class: d > 0.004 ? "kdelta up" : d < -0.004 ? "kdelta down" : "kdelta" },
      d > 0.004 ? `▲ ${d.toFixed(2)}` : d < -0.004 ? `▼ ${Math.abs(d).toFixed(2)}` : "변동 없음", " 직전 학기 평점 대비");
  }
  const gradeParts = [{ v: grp.a, c: "k-navy", t: "A 계열", n: pct(grp.a) }, { v: grp.b, c: "k-gold", t: "B 계열", n: pct(grp.b) }, { v: grp.c, c: "k-gray", t: "C 이하", n: pct(grp.c) }];
  const cur = S.current.reduce((a, c) => a + c.credit, 0);
  const rem = Math.max(0, sum.required - sum.earned - cur);
  const earnParts = [{ v: sum.major, c: "k-navy", t: "전공", n: sum.major }, { v: sum.lib, c: "k-blue", t: "교양", n: sum.lib },
    { v: cur, c: "k-gold", t: "현 학기", n: cur }];
  box.append(
    el("div", { class: "kpi" },
      el("div", { class: "klabel" }, "누적 평균 학점"),
      el("div", { class: "kvalue" }, f2(sum.gpa), el("small", {}, "/ 4.5"), delta),
      el("div", { class: "knote" }, graded.length ? `평점이 있는 ${graded.length}과목의 성적 분포` : "지난 학기 성적을 입력하면 분포가 나옵니다"),
      graded.length ? bar(gradeParts) : null, graded.length ? legend(gradeParts) : null),
    el("div", { class: "kpi" },
      el("div", { class: "klabel" }, "취득 학점"),
      el("div", { class: "kvalue" }, sum.earned, el("small", {}, `/ ${sum.required}학점`),
        cur > 0 ? el("span", { class: "kdelta up" }, `▲ 현 학기 +${cur} 예정`) : null),
      el("div", { class: "knote" }, `연한 부분은 현 학기 수강 중인 학점입니다 · 등록 학점 ${sum.registered}학점`),
      bar([...earnParts, { v: rem, c: "k-gray", t: "", n: "" }]), legend(earnParts)));
  const b = sum.burden;
  $("gradLine").innerHTML = "";
  $("gradLine").append(
    "졸업까지 ", el("b", {}, b.remaining + "학점"), " 남음 (총 ", sum.required, "학점 기준) · 전공 ",
    el("b", {}, sum.major_remaining + "학점"), " 남음 (", sum.major_required, "학점 기준)");
  renderExtraCredit(sum);
  if ($("sideProg") && sum.required) {
    const pct = Math.max(0, Math.min(100, Math.round(sum.earned / sum.required * 100)));
    $("sideProg").hidden = false;
    $("spText").textContent = `${sum.earned} / ${sum.required}학점`;
    $("spPct").textContent = `${pct}%`;
    $("spFill").style.width = pct + "%";
  }
  const tr_ = sum.semesters.map((x) => ({ semester: x.name, gpa: x.gpa === undefined ? null : x.gpa }));   // P/F만 있는 학기는 gpa 없음(null)
  $("trendSection").hidden = !tr_.some((x) => x.gpa !== null);
  $("trendChart").innerHTML = "";
  if (!$("trendSection").hidden) $("trendChart").append(trendChart(tr_));
  if (b.seasonal_plan > 0) {
    $("gradLine").append(el("div", { class: "dim" },
      `계절학기 계획 ${b.seasonal_plan}학점을 반영하면 정규 학기에 ${b.need_regular}학점이 남습니다.`));
  }
}

/* 차기 학기 최대 신청 학점: 직전 학기 평균 학점·취득 학점이 기준에 얼마나 가까운지 한눈에 */
function renderExtraCredit(sum) {
  const box = $("extraCredit");
  box.innerHTML = "";
  const x = sum.extra_credit, rule = sum.extra_rule;
  if (!x || !rule) return;
  const base = x.next_max - x.extra;
  const gpaOk = x.gpa !== null && x.gpa >= x.min_gpa - 1e-9, crOk = x.earned >= x.min_earned;
  const meter = (label, value, frac, mark, ok, note) => el("div", { class: "xc-meter" },
    el("div", { class: "xc-ml" }, label, el("b", {}, value)),
    el("div", { class: "xc-track" },
      el("i", { class: "xc-fill" + (ok ? " ok" : ""), style: `width:${Math.max(0, Math.min(100, frac * 100))}%` }),
      el("i", { class: "xc-mark", style: `left:${mark * 100}%` })),
    el("div", { class: "xc-note" + (ok ? " ok" : "") }, note));
  box.append(el("div", { class: "xc" + (x.eligible ? " ok" : "") },
    el("div", { class: "xc-head" },
      el("div", {},
        el("div", { class: "xc-title" }, "차기 학기 최대 신청 학점"),
        el("div", { class: "xc-sub" }, `직전 학기(${x.semester}) 기준 · 그 학기에만 적용`)),
      el("div", { class: "xc-big" }, el("b", {}, x.next_max), "학점", x.eligible ? el("span", { class: "xc-badge" }, `+${x.extra} 추가`) : null)),
    el("div", { class: "xc-rule" }, `평균 평점 ${x.min_gpa} 이상 + ${x.min_earned}학점 이상 취득이면 ${rule.extra}학점 더 신청할 수 있어요 (기본 ${base}학점).`),
    el("div", { class: "xc-meters" },
      meter("직전 학기 평균 학점", x.gpa === null ? "-" : x.gpa.toFixed(2), (x.gpa || 0) / 4.5, x.min_gpa / 4.5, gpaOk,
        x.gpa === null ? "P/F 과목만 있어 평균 학점이 없습니다" : gpaOk ? `기준 ${x.min_gpa} 충족` : `기준까지 ${(x.min_gpa - x.gpa).toFixed(2)} 부족`),
      meter("직전 학기 취득 학점", x.earned + "학점", x.earned / base, x.min_earned / base, crOk,
        crOk ? `기준 ${x.min_earned}학점 충족` : `기준까지 ${x.min_earned - x.earned}학점 부족`))));
}

function resetCompletedForm() {
  editC = null;
  $("cSubmit").textContent = "추가";
  $("cCancel").hidden = true;
  $("cName").value = "";
  setPick("");
  $("cCredit").value = 3;
  $("cMajor").checked = false;
  $("cRequired").checked = false;
  $("cGrade").value = "A+";
}

let semFilter = "all";      // 내 성적에서 보고 있는 학기 (all = 전체)

function renderSemFilter(names) {
  const box = $("semFilter");
  box.innerHTML = "";
  box.hidden = names.length < 2;                       // 학기가 하나뿐이면 고를 필요가 없음
  if (box.hidden) return;
  const chip = (v, label) => el("button", { type: "button", class: "chip sm" + (semFilter === v ? " on" : ""), "aria-pressed": semFilter === v ? "true" : "false",
    onclick: () => { semFilter = v; renderCompleted(); } }, label);
  box.append(el("span", { class: "chip-title inline" }, "학기별로 보기"), chip("all", "전체"), ...names.map((n) => chip(n, n)));
}

function renderCompleted() {
  fillSelect($("cGrade"), [...S.grades.map((g) => [g, g === "F" ? "F (일반 과목, 평점 0)" : g]), ["P", "합격 (P/F 과목)"], ["NP", "불합격 (P/F 과목)"]], $("cGrade").value || "A+");
  const box = $("completedList");
  box.innerHTML = "";
  const names = [...new Set(S.completed.map((c) => c.semester))];
  if (semFilter !== "all" && !names.includes(semFilter)) semFilter = "all";
  renderSemFilter(names);
  if (S.completed.length === 0) {
    box.append(el("div", { class: "empty" }, "등록된 성적 정보가 없습니다."));
    return;
  }
  const retakable = new Set(CANDS.filter((x) => x.source === "completed").map((x) => x.id));
  const groups = {};
  for (const c of S.completed) (groups[c.semester] = groups[c.semester] || []).push(c);
  for (const name in groups) {
    if (semFilter !== "all" && name !== semFilter) continue;
    const list = groups[name];
    const info = SUM.semesters.find((x) => x.name === name);
    const gpaText = info.gpa === null || info.gpa === undefined ? "P/F 과목만 있어 평균 평점 없음" : `평균 평점 ${f2(info.gpa)}`;
    box.append(el("div", { class: "sem-title" }, name,
      el("span", {}, `${gpaText} · 등록 ${info.credits}학점 · 취득 ${info.earned}학점`)));
    box.append(table(["과목명", "구분", "학점", "성적", ""],
      list.map((c) => el("tr", {},
        el("td", {}, c.name),
        el("td", { class: "num" }, el("span", { class: "tag" }, typeLabel(c))),
        el("td", { class: "num" }, c.credit),
        el("td", { class: "num" }, gradeText(c.grade)),
        el("td", { class: "num acts" },
          retakable.has(c.id) ? el("button", { class: "btn-link", onclick: () => goRetake("completed", c.id) }, "재수강 분석") : null,
          el("button", { class: "btn-ghost", onclick: () => startEditCompleted(c) }, "수정"),
          el("button", { class: "btn-ghost", onclick: async () => {
            await api("DELETE", "/api/completed/" + c.id);
            if (editC === c.id) resetCompletedForm();
            loadAll();
          } }, "삭제"))))));
  }
}

function startEditCompleted(c) {
  editC = c.id;
  $("cSemester").value = c.semester;
  $("cName").value = c.name;
  setPick(c.name);
  $("cCredit").value = c.credit;
  $("cMajor").checked = c.type === "major";
  $("cRequired").checked = c.required;
  $("cGrade").value = c.grade;
  $("cSubmit").textContent = "수정 저장";
  $("cCancel").hidden = false;
  say("cMsg", `'${c.name}' 과목을 수정하는 중입니다.`);
  $("completedForm").scrollIntoView({ behavior: "smooth", block: "center" });
}
$("cCancel").addEventListener("click", () => { resetCompletedForm(); say("cMsg", ""); });

$("completedForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  say("cMsg", "");
  if (!$("cPick").hidden && $("cPick").value === "") { warn("cMsg", "과목명: 목록에서 과목을 선택해 주세요.", $("cPick")); return; }
  const prob = firstProblem([[$("cSemester"), "학기"], ...($("cName").hidden ? [] : [[$("cName"), "과목명"]]), [$("cCredit"), "학점"]]);
  if (prob) { warn("cMsg", prob[1], prob[0]); return; }
  const body = {
    semester: $("cSemester").value, name: $("cName").value, credit: $("cCredit").value,
    type: $("cMajor").checked ? "major" : "lib", required: $("cRequired").checked, grade: $("cGrade").value,
  };
  try {
    if (editC) await api("PUT", "/api/completed/" + editC, body);
    else await api("POST", "/api/completed", body);
    const saved = normSemester(body.semester) || body.semester.trim();
    resetCompletedForm();
    $("cSemester").value = saved;                    // 같은 학기를 이어서 입력하기 편하게 학기 칸은 남겨 둠
    showSemHint();
    await loadAll();
  } catch (err) { warnErr("cMsg", err, { "학기": $("cSemester"), "과목명": $("cName"), "학점": $("cCredit") }); }
});
function showSemHint() {
  const raw = $("cSemester").value.trim(), h = $("cSemHint");
  const norm = normSemester(raw);
  h.className = "semhint" + (raw && norm && norm !== raw ? " conv" : "");
  h.textContent = !raw ? "" : !norm ? "알아볼 수 없는 학기라 입력한 그대로 저장됩니다. (예: 2026-1)"
    : norm === raw ? "" : `→ ${norm}(으)로 저장됩니다`;
}
$("cSemester").addEventListener("input", showSemHint);

/* 성적 데이터 일괄 등록: 파일 선택 -> 미리 보기 -> 확인 후 추가 */
let importRows = [];

function clearImport() {
  $("importFile").value = "";
  $("importPreview").innerHTML = "";
  importRows = [];
}

$("importFile").addEventListener("change", async () => {
  const file = $("importFile").files[0];
  say("importMsg", "");
  $("importPreview").innerHTML = "";
  importRows = [];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch("/api/import/preview", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "파일을 읽지 못했습니다.");
    renderImportPreview(data);
  } catch (err) { warn("importMsg", err.message); }
});

function renderImportPreview(data) {
  const box = $("importPreview");
  const fresh = data.rows.filter((r) => !r.duplicate);
  const dup = data.rows.length - fresh.length;
  importRows = fresh;
  box.append(el("div", { class: "sub-title" },
    `읽은 과목 ${data.rows.length}개 · 새로 추가 ${fresh.length}개` + (dup ? ` · 이미 있어 제외 ${dup}개` : "") +
    (data.errors.length ? ` · 오류 ${data.errors.length}줄` : "")));
  if (data.rows.length) {
    box.append(table(["줄", "학기", "과목명", "구분", "학점", "성적", "상태"],
      data.rows.map((r) => el("tr", { class: r.duplicate ? "dup" : "" },
        el("td", { class: "num" }, r.line),
        el("td", {}, r.semester),
        el("td", {}, r.name),
        el("td", { class: "num" }, el("span", { class: "tag" }, typeLabel(r))),
        el("td", { class: "num" }, r.credit),
        el("td", { class: "num" }, gradeText(r.grade)),
        el("td", { class: "num" }, r.duplicate ? "중복(제외)" : "추가")))));
  }
  if (data.errors.length) {
    box.append(el("div", { class: "callout" }, "아래 줄은 오류가 있어 불러오지 않습니다. 파일을 고친 뒤 다시 올려 주세요.",
      el("ul", {}, data.errors.map((e) => el("li", {}, `${e.line}번째 줄: ${e.message}`)))));
  }
  const actions = el("div", { class: "row import-actions" });
  if (fresh.length) {
    actions.append(el("button", { class: "btn", type: "button", onclick: confirmImport }, `${fresh.length}개 과목 추가`));
  }
  actions.append(el("button", { class: "btn-ghost", type: "button", onclick: () => { clearImport(); say("importMsg", ""); } }, "취소"));
  box.append(actions);
}

async function confirmImport() {
  try {
    const r = await api("POST", "/api/completed/bulk", { rows: importRows });
    clearImport();
    say("importMsg", `${r.added}개 과목을 추가했습니다.` + (r.skipped ? ` (중복 ${r.skipped}개 제외)` : ""));
    await loadAll();
  } catch (err) { warn("importMsg", err.message); }
}

/* ---------- 2. 성적 예측 ---------- */

function resetCurrentForm() {
  editU = null;
  $("uSubmit").textContent = "추가";
  $("uCancel").hidden = true;
  for (const id of ["uName", "uScore", "uMax", "uMean", "uStd", "uExamRatio", "uFinRatio", "uFinMax"]) $(id).value = "";
  $("uCredit").value = 3;
  $("uMajor").checked = false;
  $("uRequired").checked = false;
  $("uUseExtra").checked = false;
  $("uItems").innerHTML = "";
  syncExtra();
  applyMax();
}

/* 만점 칸에 적은 값(비우면 100)을 점수·평균·표준편차 칸의 입력 한도로 반영: "값은 35 이하여야 합니다" */
const maxOf = (v) => (parseFloat(v) > 0 ? parseFloat(v) : 100);
function applyMax() {
  const m = maxOf($("uMax").value);
  $("uScore").max = m;
  $("uMean").max = m;
  $("uStd").max = m / 2;
  for (const r of $("uItems").children) r.querySelector(".it-score").max = maxOf(r.querySelector(".it-max").value);
}
$("uMax").addEventListener("input", applyMax);

/* 반영 비율 입력: 체크하면 중간·기말 비율과 항목(퀴즈·과제·출석 등) 입력줄이 나타남 (기본은 중간고사 점수만) */
function syncExtra() {
  $("uExtra").hidden = !$("uUseExtra").checked;
  if ($("uUseExtra").checked && $("uItems").children.length === 0 && !$("uExamRatio").value) addItemRow();
  updateRatioSum();
}
function addItemRow(it) {
  const row = el("div", { class: "item-row" },
    el("input", { type: "text", lang: "ko", class: "it-name", placeholder: "항목 (예: 퀴즈)", maxlength: 20, value: it ? it.name : "" }),
    el("input", { type: "text", inputmode: "decimal", "data-num": "", class: "it-score", step: "0.01", min: 0, max: it && it.max ? it.max : 100, placeholder: "점수", value: it ? it.score : "" }),
    el("input", { type: "text", inputmode: "decimal", "data-num": "", class: "it-max", step: "0.01", min: 0, placeholder: "만점(100)", title: "항목 만점 (비우면 100)", value: it && it.max ? it.max : "" }),
    el("input", { type: "text", inputmode: "decimal", "data-num": "", class: "it-ratio", step: "0.01", min: 0.01, max: 100, placeholder: "비율(%)", value: it ? it.ratio : "" }),
    el("button", { type: "button", class: "btn-ghost", onclick: () => { row.remove(); updateRatioSum(); } }, "삭제"));
  row.addEventListener("input", () => { applyMax(); updateRatioSum(); });
  $("uItems").append(row);
}
function readItems() {
  return [...$("uItems").children].map((r) => ({
    name: r.querySelector(".it-name").value, score: r.querySelector(".it-score").value,
    max: r.querySelector(".it-max").value, ratio: r.querySelector(".it-ratio").value,
  }));
}
function updateRatioSum() {
  if (!$("uUseExtra").checked) { say("uRatioSum", ""); return; }
  const sum = [$("uExamRatio").value, $("uFinRatio").value, ...readItems().map((i) => i.ratio)]
    .reduce((a, v) => a + (parseFloat(v) || 0), 0);
  say("uRatioSum", `비율 합계 ${Math.round(sum * 100) / 100}%` + (sum > 100 ? " (100%를 넘을 수 없습니다)" : ""));
}
$("uUseExtra").addEventListener("change", syncExtra);
$("uAddItem").addEventListener("click", () => addItemRow());
$("uExamRatio").addEventListener("input", updateRatioSum);
$("uFinRatio").addEventListener("input", updateRatioSum);

function evalText(c) {
  if (c.exam_ratio === undefined) return "중간고사만";
  const parts = [`중간 ${c.exam_ratio}%`];
  if (c.fin_ratio !== undefined) parts.push(`기말 ${c.fin_ratio}% (점수 미정${c.fin_max ? ", 만점 " + c.fin_max : ""})`);
  for (const it of c.items || []) parts.push(`${it.name} ${it.score}${it.max ? "/" + it.max : ""}점 ${it.ratio}%`);
  return parts.join(" · ");
}

function renderCurrent() {
  fillSelect($("uGrading"), Object.entries(S.grading_modes), $("uGrading").value || "relative");
  const box = $("currentList");
  box.innerHTML = "";
  if (S.current.length === 0) {
    box.append(el("div", { class: "empty" }, "현 학기 과목을 추가해 주세요."));
    return;
  }
  box.append(table(["과목명", "구분", "학점", "중간 점수", "평균", "표준편차", "반영 항목", "평가 방식", ""],
    S.current.map((c) => el("tr", {},
      el("td", {}, c.name),
      el("td", { class: "num" }, el("span", { class: "tag" }, typeLabel(c))),
      el("td", { class: "num" }, c.credit),
      el("td", { class: "num" }, c.max_score ? `${c.score}/${c.max_score}` : c.score),
      el("td", { class: "num" }, c.mean),
      el("td", { class: "num" }, c.std),
      el("td", {}, evalText(c)),
      el("td", { class: "num" }, S.grading_modes[c.grading]),
      el("td", { class: "num acts" },
        el("button", { class: "btn-ghost", onclick: () => startEditCurrent(c) }, "수정"),
        el("button", { class: "btn-ghost", onclick: async () => {
          await api("DELETE", "/api/current/" + c.id);
          if (editU === c.id) resetCurrentForm();
          loadAll();
        } }, "삭제"))))));
}

function startEditCurrent(c) {
  editU = c.id;
  $("uName").value = c.name;
  $("uCredit").value = c.credit;
  $("uMajor").checked = c.type === "major";
  $("uRequired").checked = c.required;
  $("uScore").value = c.score;
  $("uMax").value = c.max_score ?? "";
  $("uMean").value = c.mean;
  $("uStd").value = c.std;
  $("uGrading").value = c.grading;
  $("uExamRatio").value = c.exam_ratio ?? "";
  $("uFinRatio").value = c.fin_ratio ?? "";
  $("uFinMax").value = c.fin_max ?? "";
  $("uItems").innerHTML = "";
  for (const it of c.items || []) addItemRow(it);
  applyMax();
  $("uUseExtra").checked = c.exam_ratio !== undefined;
  syncExtra();
  $("uSubmit").textContent = "수정 저장";
  $("uCancel").hidden = false;
  say("uMsg", `'${c.name}' 과목을 수정하는 중입니다.`);
  $("currentForm").scrollIntoView({ behavior: "smooth", block: "center" });
}
$("uCancel").addEventListener("click", () => { resetCurrentForm(); say("uMsg", ""); });

$("currentForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  say("uMsg", "");
  const must = [[$("uName"), "과목명"], [$("uCredit"), "학점"], [$("uScore"), "중간고사 점수"], [$("uMean"), "평균"], [$("uStd"), "표준편차"]];
  if ($("uUseExtra").checked) {
    must.push([$("uExamRatio"), "중간고사 반영 비율"]);
    if ($("uFinRatio").value.trim() !== "") must.push([$("uFinRatio"), "기말고사 반영 비율"]);
    for (const r of $("uItems").children) {
      const f = ["it-name", "it-score", "it-ratio"].map((c) => r.querySelector("." + c));
      if (f.some((i) => i.value.trim() !== "")) must.push([f[0], "항목 이름"], [f[1], "항목 점수"], [f[2], "항목 반영 비율"]);
    }
  }
  const prob = firstProblem(must);
  if (prob) { warn("uMsg", prob[1], prob[0]); return; }
  const body = {
    name: $("uName").value, credit: $("uCredit").value, type: $("uMajor").checked ? "major" : "lib", required: $("uRequired").checked,
    score: $("uScore").value, max_score: $("uMax").value, mean: $("uMean").value, std: $("uStd").value, grading: $("uGrading").value,
  };
  if ($("uUseExtra").checked) {
    body.exam_ratio = $("uExamRatio").value;
    if ($("uFinRatio").value) { body.fin_ratio = $("uFinRatio").value; body.fin_max = $("uFinMax").value; }
    body.items = readItems().filter((i) => i.name || i.score || i.ratio);
  }
  try {
    if (editU) await api("PUT", "/api/current/" + editU, body);
    else await api("POST", "/api/current", body);
    resetCurrentForm();
    await loadAll();
  } catch (err) {
    warnErr("uMsg", err, { "과목명": $("uName"), "학점": $("uCredit"), "중간고사 점수": $("uScore"), "평균": $("uMean"), "표준편차": $("uStd"),
      "중간고사 반영 비율": $("uExamRatio"), "기말고사 반영 비율": $("uFinRatio"), "중간고사 만점": $("uMax"), "기말고사 총점": $("uFinMax") });
  }
});

/* 계산 기준 상자 (학교 규정 vs 프로그램 가정) */
async function renderRules(target) {
  const r = await api("GET", "/api/rules");
  target.innerHTML = "";
  target.append(
    el("div", { class: "rules" },
      el("div", {}, el("div", { class: "rules-title" }, "학교 규정 · 확인된 기준"),
        el("ul", {}, r.school.map((t) => el("li", {}, t)))),
      el("div", {}, el("div", { class: "rules-title" }, "프로그램의 가정 (실제와 다를 수 있음)"),
        el("ul", {}, r.assumptions.map((t) => el("li", {}, t))))));
}
$("rulesBtn").addEventListener("click", async () => {
  const box = $("rulesBox");
  if (box.hidden) { await renderRules(box); box.hidden = false; $("rulesBtn").textContent = "계산 기준 닫기"; }
  else { box.hidden = true; $("rulesBtn").textContent = "예측 산출 기준"; }
});

const PLAN_GRADES = ["A+", "A0", "B+", "B0", "C+", "C0", "D+", "D0"];
let planPick = "all";      // 기말 계획 그래프에서 고른 과목 (all = 전체)
const planTarget = {};      // 과목별로 고른 목표 학점 (화면에서만 기억)

/* 기말 점수 구간: 결론 문장 + 한 줄 띠 + 구간 목록 */
function finalBand(fn, tg, need) {
  const max = fn.final_max;
  const pct = (v) => Math.max(0, Math.min(100, (v / max) * 100));
  const segs = [];                                     // 점수가 낮은 쪽부터
  const none = [];
  fn.grades.forEach((g, i) => {
    const up = i > 0 ? fn.grades[i - 1] : null;
    if (g.min_score === null) { segs.push({ grade: g.grade, impossible: true }); return; }
    const hi = up && up.min_score !== null ? up.min_score : max;
    if (hi <= g.min_score) { none.push(g.grade); return; }
    segs.push({ grade: g.grade, lo: g.min_score, hi });
  });
  const ok = segs.filter((x) => !x.impossible).reverse();
  const head = need.min_score === null ? [`${tg}는 기말 만점(${max}점)으로도 어려워요.`]
    : need.min_score === 0 ? [`${tg}는 기말 0점이어도 가능합니다.`, el("small", {}, "(평균 가정 기준)")]
    : [`${tg}를 받으려면`, el("br"), `기말 `, el("u", {}, `${need.min_score}점 이상`), `이 필요합니다.`];
  const box = el("div", { class: "fp" }, el("div", { class: "fp-head" }, head));
  const mine = ok.find((x) => x.grade === tg);
  if (ok.length) {
    const bar = el("div", { class: "fp-bar" }), below = el("div", { class: "fp-small" });
    if (ok[0] && pct(ok[0].lo) > 0.01) bar.append(el("div", { class: "fp-seg fp-low", style: `width:${pct(ok[0].lo)}%` }, pct(ok[0].lo) >= 9 ? "미만" : ""));
    ok.forEach((x) => {
      const w = pct(x.hi) - pct(x.lo);
      const on = x.grade === tg;
      const cell = el("div", { class: "fp-seg" + (on ? " on" : ""), style: `width:${w}%` }, w >= 3.5 ? x.grade : "");
      if (on && w >= 14) cell.append(el("span", {}, "목표"));
      bar.append(cell);
      if (w < 3.5) below.append(el("span", { style: pct(x.lo) > 50 ? `right:${100 - pct(x.hi)}%` : `left:${pct(x.lo)}%` }, `${x.grade} ${x.lo}~${x.hi}`));
    });
    const wrap = el("div", { class: "fp-wrap" });
    if (mine) {
      const ex = Math.min(max, Math.round((mine.lo + mine.hi) / 2));
      const at = Math.min(92, Math.max(8, pct(ex)));
      wrap.append(el("div", { class: "fp-pin", style: `left:${at}%` }, el("div", {}, `예: ${ex}점이면 ${tg}`), el("div", {}, "▼")));
    }
    wrap.append(bar);
    const ticks = el("div", { class: "fp-ticks" });
    let last = -99;
    const xs = [...ok.map((x) => x.lo), max];
    xs.forEach((v) => {
      const p = pct(v);
      if (p - last < 4 && !(mine && v === mine.lo)) return;
      last = p;
      ticks.append(el("span", { class: mine && v === mine.lo ? "hit" : "", style: `left:${p}%` }, v === max ? `${max}점` : String(v)));
    });
    wrap.append(ticks, below);
    box.append(wrap);
  }
  const list = el("div", { class: "fp-list" });
  segs.forEach((x) => {
    list.append(el("div", { class: "fp-li" + (x.grade === tg ? " on" : "") }, el("span", {}, x.grade),
      el("span", {}, x.impossible ? `만점(${max}점)으로도 어려움` : x.hi >= max ? `${x.lo}점 이상` : `${x.lo}점 ~ ${x.hi}점 미만`)));
  });
  box.append(list);
  if (none.length) box.append(el("div", { class: "fp-foot" }, `${none.join("·")}는 기말 0점이어도 더 높은 학점이 나와서, 해당하는 구간이 없습니다.`));
  return box;
}

function renderFinalPlan(c, fn, makePick) {
  const box = el("div", { class: "plan" });
  const target = planTarget[c.id] || "A0";
  const draw = () => {
    box.innerHTML = "";
    const cur = fn.current;
    const tg = planTarget[c.id] || target;
    const sel = el("select", { class: "target-sel", onchange: (e) => { planTarget[c.id] = e.target.value; draw(); } },
      PLAN_GRADES.map((g) => el("option", { value: g }, g)));
    sel.value = tg;
    const need = fn.grades.find((g) => g.grade === tg);
    box.append(el("div", { class: "sub-title plan-title" }, makePick(), " 기말고사를 몇 점 맞으면?"));
    box.append(el("div", { class: "row target-row" }, "목표 학점", sel));
    box.append(finalBand(fn, tg, need));
    box.append(el("div", { class: "dim plan-note" }, "중간고사 정보를 바탕으로 만들어진 결과입니다. 실제 기말시험에 따라 달라질 수 있습니다."));
    box.append(cards([
      ["지금까지 환산 점수", cur.converted === null ? "-" : cur.converted.toFixed(1), `반영된 ${cur.known_ratio}% 중 100점 만점 기준`],
      ["지금까지 얻은 점수", cur.earned.toFixed(1), `총점 ${cur.total_ratio}점 만점 중`],
      ["기말까지 모두 맞으면", cur.max_possible.toFixed(1), `기말 ${cur.final_ratio}% 반영`],
    ]));
    const ai = el("div", { class: "ai-box" });
    let opened = false;
    const btn = el("button", { class: "btn-ghost", type: "button" }, "취약점·보완 방법 보기");
    const close = () => { opened = false; ai.innerHTML = ""; btn.textContent = "취약점·보완 방법 보기"; };
    btn.addEventListener("click", async () => {
      if (opened) { close(); return; }                 // 열려 있으면 닫기
      opened = true;
      btn.textContent = "닫기";
      ai.innerHTML = "";
      ai.append(el("div", { class: "dim" }, "분석 문장을 만드는 중…"));
      try {
        const r = await api("POST", "/api/explain", { course_id: c.id, target_grade: tg });
        if (!opened) return;                           // 불러오는 중에 닫았으면 그대로 둠
        ai.innerHTML = "";
        ai.append(el("div", { class: "ai-tag" }, "배분안 설명"),
          el("ul", {}, r.text.split("\n").filter((t) => t.trim()).map((t) => el("li", {}, t.replace(/^-\s*/, "")))),
                    el("button", { class: "btn-ghost", type: "button", onclick: close }, "닫기"));
      } catch (err) { ai.innerHTML = ""; ai.append(el("div", { class: "msg" }, err.message)); }
    });
    box.append(el("div", { class: "row" }, btn), ai);
  };
  draw();
  return box;
}

$("predictBtn").addEventListener("click", async () => {
  say("pMsg", "");
  $("predictResult").innerHTML = "";
  try {
    const r = await api("GET", "/api/predict");
    const out = $("predictResult");
    const sigma = r.uncertainty;

    out.append(el("div", { class: "callout" }, el("ul", { class: "plain" },
      el("li", {}, el("b", {}, "확정 성적이 아닌 참고용 예측입니다.")),
      el("li", {}, `입력한 점수·평균·표준편차로 반 안에서의 위치를 추정합니다.`),
      el("li", {}, `기말까지 점수가 지금보다 올라가거나 내려갈 수 있다고 보고, 그 범위를 표준편차(반 점수가 흩어진 정도)의 ${sigma}배까지로 잡았어요. 예: 표준편차가 10점이면 최대 ${(sigma * 10).toFixed(0)}점 안팎의 변동을 가정.`),
      el("li", {}, "최대 학점은 점수가 올랐을 때, 최소 학점은 내렸을 때의 학점입니다. 교수님이 학점을 가장 후하게 주는 경우를 최대로 보고, 누적 비율표(A+ 15%, A0 30%…)를 기준으로 계산합니다."),
      el("li", {}, "차기 학기 추가 신청 학점은 현 학기 예상 평균 학점으로 판단하며, 아직 확정 성적이 아니므로 '지금 예상' 기준입니다."),
      el("li", {}, S.current.some((c) => c.exam_ratio !== undefined)
        ? "출석·과제는 반영 비율로 합산하고(반 평균·표준편차는 예시값), 기말 점수는 반영하지 않습니다."
        : "출석·과제 등 다른 평가 항목과 기말 점수는 반영하지 않습니다."))));

    const candIds = new Set(CANDS.filter((x) => x.source === "current").map((x) => x.id));
    const rows = S.current.map((c) => {
      const e = r.estimates[c.id];
      const range = e.best === e.worst ? e.expected : `${e.worst} ~ ${e.best}`;
      return tr([c.name, c.credit, e.z.toFixed(2), "상위 " + e.top_percent.toFixed(0) + "%", e.max_grade, e.min_grade, range,
        el("span", { class: "acts" },
          el("button", { class: "btn-link", onclick: () => goWithdraw(c.id) }, "철회 분석"),
          candIds.has(c.id) ? el("button", { class: "btn-link", onclick: () => goRetake("current", c.id) }, "재수강 분석") : null)]);
    });
    out.append(el("div", { class: "sub-title" }, "과목별 받을 수 있는 학점 (최대 · 최소)"));
    out.append(el("p", { class: "hint" }, "학칙은 A0 이상 30% 이하, B0 이상 70% 이하만 정하고, A+/A0 비율은 교수님이 정합니다. 그래서 현재 위치에서 받을 수 있는 최대와 최소를 보여 줍니다."));
    out.append(table(["과목명", "학점", term("z"), term("top"), term("maxg"), term("ming"), term("range"), ""], rows));

    const planCourses = S.current.filter((c) => r.final_needed[c.id]);
    if (planCourses.length) {
      if (!planCourses.some((c) => c.id === planPick)) planPick = planCourses[0].id;   // 처음엔 첫 과목
      const host = el("div", {});
      const show = () => {
        const c = planCourses.find((x) => x.id === planPick);
        host.innerHTML = "";
        host.append(renderFinalPlan(c, r.final_needed[c.id], () => {
          const pick = el("select", { class: "course-sel", "aria-label": "과목 선택", onchange: (e) => { planPick = e.target.value; show(); } },
            planCourses.map((x) => el("option", { value: x.id }, x.name)));
          pick.value = planPick;
          return pick;
        }));
      };
      show();
      out.append(host);
    }
    const cd = await api("GET", "/api/chart-data");
    if (cd.radar.axes.length) {
      out.append(el("div", { class: "sub-title" }, "과목별 현재 환산 점수 vs 반 평균"));
      out.append(el("p", { class: "hint" }, "항목별 반영 비율로 합친 지금까지의 환산 점수입니다. 반 평균은 중간고사 평균과 가정값(출석·과제 등)을 비율대로 합친 값입니다."));
      out.append(radarChart(cd.radar));
    }
    out.append(el("div", { class: "row dl-row" },
      el("span", { class: "dim" }, "그래프 데이터 내려받기 (발표·엑셀용):"),
      el("a", { class: "btn-link", href: "/api/chart-data?download=1", download: "gradepath_chart_data.json" }, "JSON"),
      el("a", { class: "btn-link", href: "/api/chart-data?format=csv", download: "gradepath_chart_data.csv" }, "CSV")));

    const sc = r.scenarios;
    out.append(el("div", { class: "sub-title" }, "현 학기 이후 평균 평점 시나리오"));
    out.append(el("p", { class: "hint" }, "'현 학기 평균 학점'는 현 학기 과목만, '전체 누적 평균 학점'는 지난 학기까지 포함한 값입니다. 현재 누적 평균 학점(현 학기 반영 전): ", f2(r.base_gpa)));
    const rs = r.rule_scenarios;
    out.append(table(["", term("semgpa"), term("cumgpa")], [
      tr(["현재 점수 기준 최대 (모든 과목 최대 학점)", f2(rs.max.semester_gpa), f2(rs.max.cumulative_gpa)]),
      tr(["현재 점수 기준 최소 (모든 과목 최소 학점)", f2(rs.min.semester_gpa), f2(rs.min.cumulative_gpa)]),      tr(["기말이 부진하면 (참고)", f2(sc.pessimistic.semester_gpa), f2(sc.pessimistic.cumulative_gpa)]),
      tr(["예상 (누적 비율표 기준)", f2(sc.expected.semester_gpa), f2(sc.expected.cumulative_gpa)]),
      tr(["기말이 잘 나오면 (참고)", f2(sc.optimistic.semester_gpa), f2(sc.optimistic.cumulative_gpa)]),
    ]));

    const xr = SUM.extra_rule;
    if (xr) {
      const cr = S.current.reduce((a, c) => a + c.credit, 0), g = sc.expected.semester_gpa;
      const okG = g !== null && g >= xr.min_prev_gpa - 1e-9, okC = cr >= xr.min_prev_earned;
      out.append(el("div", { class: "callout" }, el("b", {}, "차기 학기 추가 신청: "),
        `현 학기 평균 학점이 ${xr.min_prev_gpa} 이상이고 ${xr.min_prev_earned}학점 이상 취득하면 차기 학기에 ${xr.extra}학점을 더 신청할 수 있습니다 (최대 ${S.settings.max_credits_per_semester + xr.extra}학점). `,
        g === null ? "현 학기 평균 학점을 계산할 수 없습니다." : okG && okC ? `지금 예상 평균 평점 ${f2(g)} 기준으로 조건을 채웁니다.`
          : !okG ? `지금 예상 평균 학점은 ${f2(g)}로 ${(xr.min_prev_gpa - g).toFixed(2)} 부족합니다.` : `현 학기 학점이 ${xr.min_prev_earned - cr}학점 부족합니다.`));
    }
    out.append(el("div", { class: "sub-title" }, `목표 누적 평균 평점 ${r.target_gpa.toFixed(2)} 달성 가능성 (모의 계산)`));
    const need = r.required_avg_point;
    const needText = r.already_secured ? "이미 달성 가능권" : (!r.reachable ? "4.5 초과 (불가능)" : need.toFixed(2));
    out.append(cards([
      [term("need"), needText, "현 학기 학점 가중 평균"],
      [term("prob"), r.probability_label, `모의 ${r.trials}번 중 ${r.hits}번 목표 도달`],
      [term("gparange"), `${f2(r.gpa_p10)} ~ ${f2(r.gpa_p90)}`, "중앙값 " + f2(r.gpa_p50)],
    ]));
    out.append(el("div", { class: "callout" },
      "목표 평점 달성 추정 가능성은 점수 변동을 무작위로 가정한 모의 계산이며, 실제로 검증된 확률이 아닙니다. 가정의 자세한 내용은 '예측 산출 기준'에서 학교 규정과 구분해 확인할 수 있습니다."));
  } catch (err) { warn("pMsg", err.message); }
});

/* 목표 GPA 시뮬레이션: 과목을 고르면 등급별 평균 평점 표를 보여 줌 */
function renderSimSelect() {
  const sel = $("simCourse");
  const prev = sel.value;
  fillSelect(sel, S.current.length ? S.current.map((c) => [c.id, `${c.name} (${c.credit}학점)`]) : [["", "현 학기 과목이 없습니다"]], prev);
  $("simResult").innerHTML = "";
  if (sel.value) runSimulate();                    // 버튼 없이 바로 보여 줌
}

async function runSimulate() {
  say("simMsg", "");
  $("simResult").innerHTML = "";
  try {
    const r = await api("POST", "/api/simulate", { course_id: $("simCourse").value });
    const out = $("simResult");
    const need = r.needed_grade;
    out.append(cards([
      [`${r.course.name} 예상 학점 기준`, f2(r.base.cumulative_gpa), `예상 ${r.expected_grade} · 현 학기 ${f2(r.base.semester_gpa)}`],
      ["목표 누적 평균 학점", r.target_gpa.toFixed(2), "설정 탭에서 변경"],
      ["목표 달성에 필요한 최소 등급", need || "불가능", need ? "이 과목에서 이 등급 이상 받으면 목표 달성" : "어떤 등급을 받아도 목표 미달"],
    ]));
    const okRows = r.rows.filter((x) => x.meets_target && x.semester_gpa !== null);
    if (okRows.length) out.append(el("p", { class: "hint" }, `현 학기 목표: 목표 누적 평균 ${r.target_gpa.toFixed(2)}를 이루려면 현 학기 평균 학점이 약 `, el("b", {}, f2(Math.min(...okRows.map((x) => x.semester_gpa)))), " 이상이어야 합니다."));
    out.append(el("p", { class: "hint" }, "다른 과목은 현재 점수 기준 예상 학점으로 고정한 값입니다. 확정 성적이 아닙니다."));
    out.append(table(["취득 성적 등급", "현 학기 평균 학점", "누적 평균 학점", "예상 평점 대비 증감", "목표"],
      r.rows.map((x) => el("tr", { class: x.is_expected ? "picked" : "" },
        el("td", {}, x.grade + (x.is_expected ? " (예상)" : "")),
        el("td", { class: "num" }, f2(x.semester_gpa)),
        el("td", { class: "num" }, f2(x.cumulative_gpa)),
        el("td", { class: "num" }, el("span", { class: "pos" }, x.delta === null ? "-" : signed(x.delta))),
        el("td", { class: "num" }, x.meets_target ? "달성" : "미달")))));
  } catch (err) { warn("simMsg", err.message); }
}

$("simCourse").addEventListener("change", () => { if ($("simCourse").value) runSimulate(); });

/* ---------- 3. 수강 철회 ---------- */

let wPick = null, wSeq = 0;
function renderWithdrawSelect() {
  const box = $("wChips");
  box.innerHTML = "";
  if (!S.current.length) {
    wPick = null;
    $("withdrawResult").innerHTML = "";
    box.append(el("div", { class: "empty" }, "현 학기 과목이 없습니다. '성적 예측' 탭에서 먼저 입력해 주세요."));
    return;
  }
  if (!S.current.some((c) => c.id === wPick)) wPick = S.current[0].id;     // 처음엔 첫 과목
  for (const c of S.current) {
    const on = c.id === wPick;
    box.append(el("button", { type: "button", class: "chip" + (on ? " on" : ""), "aria-pressed": on ? "true" : "false",
      onclick: () => { wPick = c.id; renderWithdrawSelect(); } },
      el("b", {}, c.name), el("span", {}, `${c.credit}학점 · ${typeLabel(c)}`)));
  }
  if (currentTab === "withdraw") runWithdraw();
}

function burdenParts(b) {
  const per = b.per_semester === null ? "-" : b.per_semester.toFixed(1) + "학점";
  return [b.label, `남은 학기당 ${per}` + (b.extra_semesters ? ` · 추가 ${b.extra_semesters}학기 필요` : "")];
}

function goWithdraw(id) {
  wPick = id;
  showTab("withdraw");
}

async function runWithdraw() {
  say("wMsg", "");
  $("withdrawResult").innerHTML = "";
  if (!wPick) return;
  const my = ++wSeq;     // 과목을 빠르게 바꿔 눌러도 마지막으로 누른 과목의 결과만 보이게 함
  try {
    const r = await api("POST", "/api/withdraw", { course_id: wPick });
    if (my !== wSeq) return;
    const out = $("withdrawResult");
    const e = r.estimate;
    const row = (label, a, b, fmt = f2) => tr([label, fmt(a), fmt(b), el("span", { class: "pos" }, diff(a, b))]);
    const x = r.expected, w = r.worst;
    out.append(el("div", { class: "wd-title" }, `${r.course.name} · 끝까지 들을까, 철회할까`));
    out.append(el("div", { class: "wd-sub" }, `현재 점수 기준 예상 ${e.expected} (예상 학점 범위 ${e.worst === e.best ? e.expected : e.worst + " ~ " + e.best})`));
    const dCr = x.withdraw.earned - x.stay.earned;
    const base = x.withdraw.gpa;
    const noBase = base === null || base === undefined;       // 다른 성적이 없어 비교할 평균이 없는 경우
    const cE = noBase ? 0 : x.stay.gpa - base, cW = noBase ? 0 : w.stay.gpa - base;
    const r2 = (v) => Math.round(v * 100) / 100, sv = (d) => (Math.abs(d) < 0.005 ? "0.00" : signed(r2(d)));
    const box = (title, grade, gpa, d) => el("div", { class: "wd-box" }, el("div", { class: "wd-bt" }, `${title} (${grade})`),
      el("div", { class: "wd-bn" }, f2(gpa)), el("div", { class: "wd-bd " + (d < -0.005 ? "dn" : "up") }, noBase ? "비교할 다른 성적 없음" : (d < -0.005 ? "▼ " : d > 0.005 ? "▲ " : "") + sv(d)));
    out.append(el("div", { class: "wd-sec" }, "1. 끝까지 들었을 때", el("span", { class: "wd-tag" }, noBase ? "다른 성적이 없어 평균 변화는 비교할 수 없습니다" : `이 과목을 뺀 누적 평균 ${f2(base)} 기준`)));
    out.append(el("div", { class: "wd-hint" }, "철회하지 않고 기말까지 가면 누적 평균 학점이 이렇게 됩니다."));
    out.append(el("div", { class: "wd-two" }, box("현재 점수대로 끝나면", e.expected, x.stay.gpa, cE), box("기말이 부진하면", e.worst, w.stay.gpa, cW)));
    const rec = noBase ? ["다른 성적이 없어 평균 변화는 비교할 수 없습니다.", "철회하면 이 과목 학점이 취득되지 않아 졸업이 늦어질 수 있습니다."]
      : cE < -0.005 ? ["현재 점수대로 끝나도 평균이 내려갑니다. 철회를 추천합니다.", "취득 학점 손실과 졸업 지연도 아래에서 함께 확인하세요."]
      : cW < -0.005 ? ["끝까지 듣되, 기말이 부진하면 평균이 내려갑니다. 기말을 잘 준비하세요.", "기말 점수가 많이 떨어질 것 같다면 철회도 아래에서 비교해 보세요."]
      : ["현재 점수대로 끝나도, 기말이 부진해도 평균이 내려가지 않습니다. 끝까지 듣기를 추천합니다.", "철회하면 취득 학점만 줄어듭니다."];
    out.append(el("div", { class: "wd-rec" }, rec[0], el("small", {}, rec[1]),
      el("small", {}, "추천 기준: 현재 점수대로 끝나도 평균이 내려가면 철회 추천 · 기말 부진 때만 내려가면 기말 주의 · 둘 다 안 내려가면 끝까지 듣기")));
    out.append(el("div", { class: "wd-sec" }, "2. 철회했을 때", el("span", { class: "wd-tag" }, "이 과목이 평균에서 빠집니다")));
    out.append(el("div", { class: "wd-hint" }, "철회하면 이 과목 성적이 평균에 들어가지 않고, 학점도 취득되지 않습니다."));
    const dMaj = x.stay.earned_major - x.withdraw.earned_major, dLib = x.stay.earned_lib - x.withdraw.earned_lib;
    const dRem = x.withdraw.burden.remaining - x.stay.burden.remaining;
    out.append(el("div", { class: "wd-head" }, "취득 학점이 ", dCr < 0 ? ["전공 ", el("u", {}, `${dMaj}학점`), " · 교양 ", el("u", {}, `${dLib}학점`), " 줄어듭니다."] : "변하지 않습니다.",
      dRem !== 0 ? [el("br"), "졸업까지 남는 학점이 ", el("u", {}, `${x.stay.burden.remaining}학점 → ${x.withdraw.burden.remaining}학점`), dRem > 0 ? "으로 늘어납니다." : "으로 줄어듭니다."] : null));
    if (dCr === 0 && r.credit_reason) out.append(el("div", { class: "wd-why" }, el("b", {}, "왜 변하지 않나요? "), r.credit_reason));
    const st = (label, a, b, extra, sub) => el("div", { class: "wd-stat" }, el("div", { class: "wd-sl" }, label),
      el("div", { class: "wd-sv" }, `${a} → ${b}`, extra ? el("small", {}, ` (${extra})`) : null),
      sub ? el("div", { class: "wd-ss" }, sub) : null);
    out.append(el("div", { class: "wd-cap" }, "각 칸의 숫자는 ‘끝까지 들었을 때 → 철회했을 때’ 순서입니다."));
    out.append(el("div", { class: "wd-stats" },
      st("누적 평균 학점", f2(x.stay.gpa), f2(x.withdraw.gpa), null, "현재 점수대로 끝나는 경우 기준"),
      st("현 학기 후 취득 학점", x.stay.earned, x.withdraw.earned, (dCr > 0 ? "+" : "") + dCr,
        `전공 ${x.stay.earned_major} → ${x.withdraw.earned_major} · 교양 ${x.stay.earned_lib} → ${x.withdraw.earned_lib}`),
      st("졸업까지 남은 학점", x.stay.burden.remaining, x.withdraw.burden.remaining, "+" + (x.withdraw.burden.remaining - x.stay.burden.remaining),
        `전공 ${x.stay.major_remaining} → ${x.withdraw.major_remaining} (전공 졸업학점 기준)`)));
    const det = el("details", { class: "howto" }, el("summary", {}, "자세한 표 보기 (학기 평균 평점 등)"));
    det.append(table(["", "끝까지", "철회", "차이"], [
      row(el("span", {}, term("semgpa"), " (현재 점수대로)"), x.stay.semester_gpa, x.withdraw.semester_gpa),
      row(el("span", {}, term("semgpa"), " (기말 부진)"), w.stay.semester_gpa, w.withdraw.semester_gpa),
      row(el("span", {}, term("cumgpa"), " (현재 점수대로)"), x.stay.gpa, x.withdraw.gpa),
      row(el("span", {}, term("cumgpa"), " (기말 부진)"), w.stay.gpa, w.withdraw.gpa),
      tr(["현 학기 후 취득 학점", x.stay.earned, x.withdraw.earned, el("span", { class: "pos" }, dCr + "")]),
      tr(["　└ 전공 취득 학점", x.stay.earned_major, x.withdraw.earned_major, el("span", { class: "pos" }, (x.withdraw.earned_major - x.stay.earned_major) + "")]),
      tr(["　└ 교양 취득 학점", x.stay.earned_lib, x.withdraw.earned_lib, el("span", { class: "pos" }, (x.withdraw.earned_lib - x.stay.earned_lib) + "")]),
      tr(["졸업까지 남은 학점", x.stay.burden.remaining, x.withdraw.burden.remaining,
        el("span", { class: "pos" }, "+" + (x.withdraw.burden.remaining - x.stay.burden.remaining))]),
    ]));
    out.append(det);
    out.append(el("div", { class: "sub-title" }, "남은 학기 수강 부담"));
    const capSem = x.stay.burden.semester_cap;
    out.append(el("p", { class: "hint" }, `남은 학기에 학기당 평균 몇 학점을 들어야 하는지로 나눕니다. 여유: 학기 최대(${capSem}학점)의 70% 이하 · 보통: 70~90% · 빡빡함: 90% 초과 · 졸업 지연 위험: 최대로 들어도 남은 학기 안에 못 채움.`));
    out.append(cards([
      ["끝까지 듣기", ...burdenParts(x.stay.burden)],
      ["철회", ...burdenParts(x.withdraw.burden)],
    ], true));
    const bs = x.stay.burden;
    if (bs.seasonal_plan > 0) {
      out.append(el("p", { class: "hint" }, `설정에 입력한 계절학기 계획 ${bs.seasonal_plan}학점을 반영한 값입니다. (계절학기를 쓰지 않으면 학기당 ${f2(bs.per_semester_without_seasonal)}학점)`));
    }
    out.append(el("div", { class: "callout" }, "참고 정리",
      el("ul", {}, r.notes.map((n) => el("li", {}, n)))));
  } catch (err) { warn("wMsg", err.message); }
}

/* ---------- 4. 재수강 ---------- */

function renderRetakeList() {
  const box = $("retakeList");
  box.innerHTML = "";
  $("retakeHint").textContent =
    `기존 취득 성적이 ${S.settings.retake_max_prior} 이하인 교과목에 한해 재수강이 가능합니다. 교과목 선택 시 재수강 성적 등급에 따른 평균 평점 변화를 확인할 수 있습니다. ('내 성적' 및 '성적 예측' 페이지에서도 해당 분석으로 이동할 수 있습니다.) 재수강 가능 성적과 성적 상한은 학교 학사 규정에 따른 값입니다.`;
  if (CANDS.length === 0) {
    box.append(el("div", { class: "empty" }, `재수강 대상 교과목이 없습니다. (재수강 가능 기준: ${S.settings.retake_max_prior} 이하)`));
    return;
  }
  for (const [src, title] of [["completed", "지난 학기 성적"], ["current", "현 학기 (현재 점수 기준 예상 성적)"]]) {
    const list = CANDS.filter((c) => c.source === src);
    if (!list.length) continue;
    box.append(el("div", { class: "chip-title" }, title),
      el("div", { class: "chips", role: "group", "aria-label": title }, list.map((c) => {
        const on = lastRetake && lastRetake.source === c.source && lastRetake.id === c.id;
        return el("button", { type: "button", class: "chip" + (on ? " on" : ""), "aria-pressed": on ? "true" : "false",
          onclick: () => runRetake(c.source, c.id) },
          el("b", {}, c.name + (c.required ? " · 필수" : "")),
          el("span", {}, `${c.credit}학점 · ${c.grade}${src === "current" ? " (예상)" : ""}` + (src === "completed" ? ` · ${c.where}` : "")));
      })));
  }
}

// 재수강 탭을 열면 고른 과목이 없을 때 첫 과목을 자동으로 분석 (고른 과목이 사라졌으면 다시 고름)
function ensureRetake() {
  if (lastRetake && !CANDS.some((c) => c.source === lastRetake.source && c.id === lastRetake.id)) {
    lastRetake = null;
    $("retakeResult").innerHTML = "";
  }
  if (!lastRetake && CANDS.length) runRetake(CANDS[0].source, CANDS[0].id);
  else renderRetakeList();
}

/* 재수강 결과: 재수강 취득 성적별 막대 (가운데 선이 지금 누적 평균 학점) */
function retakeView(r) {
  const EPS = 0.0049;
  const rows = [];                                    // 상한 때문에 같은 반영 성적이 되는 줄은 "A+ · A0"로 합침
  for (const x of r.rows) {
    const same = rows.find((y) => y.applied === x.applied);
    if (same) { same.labels.push(x.received); same.capped = same.capped || x.capped; }
    else rows.push({ applied: x.applied, labels: [x.received], delta: x.delta, gpa: x.gpa, earned_delta: x.earned_delta, capped: !!x.capped });
  }
  const kind = (d) => (d > EPS ? "up" : d < -EPS ? "down" : "same");
  const maxAbs = Math.max(0.01, ...rows.map((g) => Math.abs(g.delta)));
  const row = (g) => {
    const k = kind(g.delta);
    const w = k === "same" ? 0 : Math.max(2, (Math.abs(g.delta) / maxAbs) * 62);
    const bar = el("i", { class: "rt-bar " + k, style: `width:${w}%` });
    const num = el("b", {}, k === "same" ? "0.00" : signed(g.delta));
    const note = g.earned_delta < 0 ? el("span", { class: "rt-note" }, `취득 학점 ${g.earned_delta}`) : null;
    let left, right;
    if (k === "down") { left = el("div", { class: "rt-half left" }, note, num, bar); right = el("div", { class: "rt-half right" }); }
    else if (k === "up") { left = el("div", { class: "rt-half left" }); right = el("div", { class: "rt-half right" }, bar, num, note); }
    else { left = el("div", { class: "rt-half left" }, el("span", { class: "rt-note" }, "변화 없음 (지금 성적)")); right = el("div", { class: "rt-half right" }, num); }
    const out = [el("div", { class: "rt-row " + k },
      el("div", { class: "rt-grade" }, g.labels.join(" · ")),
      el("div", { class: "rt-bars" }, left, right),
      el("div", { class: "rt-after" }, f2(g.gpa)))];
    if (g.labels.length > 1 && g.capped) out.push(el("div", { class: "rt-cap" }, `재수강 성적 상한은 ${S.settings.retake_cap}으로 적용됩니다. 상한을 초과하는 성적을 취득하더라도 누적 평점에는 ${g.applied} 등급까지만 반영됩니다.`));
    return out;
  };
  const wrap = el("div", { class: "rt" },
    el("div", { class: "rt-sub" }, `현재 누적 평균 평점은 `, el("b", {}, f2(r.base_gpa)), `입니다. 재수강 후 취득 성적에 따른 누적 평점 변화를 확인할 수 있습니다.`),
    el("div", { class: "rt-legend" }, el("span", {}, el("i", { class: "rt-bar up" }), "올라감"), el("span", {}, el("i", { class: "rt-bar down" }), "내려감")),
    el("div", { class: "rt-head" }, el("span", {}, "재수강 취득 성적"), el("span", { class: "c" }, `누적 평균 평점 변동 (기준 평점 ${f2(r.base_gpa)})`), el("span", { class: "r" }, "재수강 후 누적 평점")));
  const body = el("div", { class: "rt-body" });
  rows.forEach((g) => row(g).forEach((n) => body.append(n)));
  wrap.append(body);
  return wrap;
}

function goRetake(source, id) {
  lastRetake = { source, id };
  showTab("retake");
  runRetake(source, id);
}

let retakeSeq = 0;      // 과목을 빠르게 바꿔 눌러도 마지막으로 누른 과목의 결과만 보이게 함
async function runRetake(source, id) {
  say("rMsg", "");
  const my = ++retakeSeq;
  lastRetake = { source, id };
  renderRetakeList();
  try {
    const r = await api("POST", "/api/retake", {
      source, course_id: id, other_credits: $("rOtherCredits").value, other_avg_point: $("rOtherAvg").value,
    });
    if (my !== retakeSeq) return;
    const out = $("retakeResult");
    out.innerHTML = "";
    out.append(el("div", { class: "sub-title" },
      `${r.course.name} (${r.course.credit}학점, 기존 ${r.course.grade}${source === "current" ? " · 현 학기 예상" : ""})`));
    const oc = parseFloat($("rOtherCredits").value);
    if (oc > 0) out.append(el("div", { class: "opt-applied" }, `✓ 옵션 반영 중: 함께 듣는 다른 과목 ${oc}학점 · 예상 평균 ${$("rOtherAvg").value || "0"} (아래 '재수강 학기 예상 평균 평점'에 적용)`));
    out.append(cards([
      ["현재 성적 유지 시 누적 평균 학점", f2(r.base_gpa), `${r.course.name} ${r.course.grade}`],
      ["재수강 시 누적 평균 평점 최대 상승폭", signed(r.max_gain), "재수강 성적 상한 적용"],
      ["평균 학점이 오르는 최저 성적", r.break_even || "없음", "재수강에서 이 성적 이상을 취득하면 평점이 올라갑니다"],
    ]));
    out.append(el("div", { class: "sub-title" }, "재수강 성적별 결과"));
    const semHead = r.other_credits > 0 ? "재수강 학기 예상 평균 평점" : "재수강 교과목 기준 예상 평점";
    out.append(retakeView(r));
    out.append(el("details", { class: "howto" }, el("summary", {}, "자세한 표 보기"),
      table(["재수강 취득 성적", "반영 성적", semHead, "재수강 후 누적 평점 평균 학점", "누적 변화", "취득 학점 변화"],
        r.rows.map((x) => tr([
          x.received, x.applied + (x.capped ? " (상한)" : ""), f2(x.semester_gpa), f2(x.gpa),
          el("span", { class: "pos" }, signed(x.delta)), x.earned_delta > 0 ? "+" + x.earned_delta : x.earned_delta,
        ])))));
    const notes = [];
    if (r.course.required && r.course.grade === "F") notes.push("필수 교과목에서 F등급을 취득한 경우, 졸업 요건 충족을 위해 해당 교과목의 재이수가 필요합니다. 대체 이수 가능 여부는 학과 규정을 확인하세요.");
    notes.push("재수강 학기 평균 평점은 해당 학기의 성적을 기준으로 산출됩니다. 누적 평균 평점은 기존 성적을 재수강 성적으로 대체한 후 전체 이수 내역을 반영하여 산출됩니다.");
    notes.push(`해당 교과목 재수강 시 차기 학기 수강 가능 학점 중 ${r.burden_credit}학점(${(r.burden_ratio * 100).toFixed(0)}%)이 배정됩니다.`);
    notes.push(`본 분석은 재수강 성적이 기존 성적을 대체하는 것을 전제로 하며, 재수강 성적 상한 ${S.settings.retake_cap}을 적용하여 산출됩니다. 누적 평점 상승폭은 입력 조건에 따른 예상값입니다.`);
    if (source === "current") notes.push("현 학기 과목은 현재 점수 기준 예상 성적이 확정된다고 가정했습니다. 실제 성적이 나온 뒤 다시 확인하세요.");
    out.append(el("div", { class: "callout" }, "참고 정리", el("ul", {}, notes.map((n) => el("li", {}, n)))));
  } catch (err) {
    if (my !== retakeSeq) return;
    $("retakeResult").innerHTML = "";
    warnErr("rMsg", err, { "함께 듣는 다른 과목 학점": $("rOtherCredits"), "다른 과목 예상 평균 평점": $("rOtherAvg") });
  }
}
for (const id of ["rOtherCredits", "rOtherAvg"]) {
  $(id).addEventListener("change", () => { if (lastRetake) runRetake(lastRetake.source, lastRetake.id); });
}

/* ---------- 5. 설정 ---------- */

/* 현 학기(학년·학기)를 토글로 고르면, 남은 정규 학기 수는 8학기 기준으로 자동 계산 */
let semYear = 4, semTerm = 2, semTouched = false;
const semIdx = () => (semYear - 1) * 2 + semTerm;
function paintSem() {
  for (const b of $("sYear").children) b.classList.toggle("on", +b.dataset.v === semYear);
  for (const b of $("sTerm").children) b.classList.toggle("on", +b.dataset.v === semTerm);
  const left = 8 - semIdx();
  $("sSemNote").textContent = `${semYear}학년 ${semTerm}학기 → 현 학기 이후 정규 학기 ${left}개 남음 (8학기 졸업 기준)`;
}
$("sYear").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { semYear = +b.dataset.v; semTouched = true; paintSem(); } });
$("sTerm").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { semTerm = +b.dataset.v; semTouched = true; paintSem(); } });

function renderSettings() {
  const s = S.settings;
  $("sTotal").value = s.total_credits_required;
  $("sMajor").value = s.major_credits_required;
  $("sMax").value = s.max_credits_per_semester;
  $("sMaxYear").value = s.max_credits_per_year;
  const idx = Math.min(8, Math.max(1, 8 - s.remaining_semesters));        // 현 학기 번호 (1학년 1학기 = 1)
  semYear = Math.ceil(idx / 2);
  semTerm = idx % 2 === 1 ? 1 : 2;
  semTouched = false;
  paintSem();
  $("sSeasonal").value = s.seasonal_plan_credits;
  try { const m = JSON.parse(localStorage.getItem("polarisProfile") || "{}"); if (m.dept) $("sDept").value = m.dept; $("sEntry").value = m.entry || String(new Date().getFullYear()); $("sUniv").value = m.univ || $("sUniv").value; } catch (e) {}
  $("sTarget").value = s.target_gpa;
  const g = S.grades.map((x) => [x, x]);
  fillSelect($("sCap"), g, s.retake_cap);
  fillSelect($("sPrior"), g, s.retake_max_prior);
  renderRules($("rulesSettings"));
}

$("settingsForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  say("sMsg", "");
  const prob = firstProblem([[$("sTotal"), "졸업 학점"], [$("sMajor"), "전공 졸업학점"], [$("sMax"), "학기당 최대 학점"], [$("sMaxYear"), "학년도 최대 학점"],
    [$("sSeasonal"), "계절학기 계획 학점"], [$("sTarget"), "목표 평균 학점"]]);
  if (prob) { warn("sMsg", prob[1], prob[0]); return; }
  try {
    await api("PUT", "/api/settings", {
      total_credits_required: $("sTotal").value, major_credits_required: $("sMajor").value, max_credits_per_semester: $("sMax").value, max_credits_per_year: $("sMaxYear").value,
      remaining_semesters: semTouched || S.settings.remaining_semesters <= 7 ? 8 - semIdx() : S.settings.remaining_semesters, seasonal_plan_credits: $("sSeasonal").value, target_gpa: $("sTarget").value,
      retake_cap: $("sCap").value, retake_max_prior: $("sPrior").value,
    });
    say("sMsg", "저장했습니다.");
    await loadAll();
    renderSetupNotice();
    showTab("grades");
  } catch (err) {
    warnErr("sMsg", err, { "졸업 학점": $("sTotal"), "전공 졸업학점": $("sMajor"), "학기당 최대 학점": $("sMax"), "학년도 최대 학점": $("sMaxYear"),
      "계절학기 계획 학점": $("sSeasonal"), "목표 평균 학점": $("sTarget") });
  }
});

loadAll().then(() => { if (!S.onboarded) openIntro(); });


/* ---------- 학점 이수 계획 ---------- */

let guideBusy = null;      // 바쁜 학기 번호 목록 (null이면 서버 기본값: 4학년 학기)
let guidePlan = null;      // 보고 있는 배분안 (even / balanced / minimal)

async function renderGuide() {
  const g = await api("GET", "/api/guide" + (guideBusy === null ? "" : "?busy=" + guideBusy.join(",")));
  const p = $("guideProgress");
  p.innerHTML = "";
  p.append(progressBar("총 이수 학점", g.progress.total.done, g.progress.total.now, g.progress.total.required),
    progressBar("전공 이수 학점", g.progress.major.done, g.progress.major.now, g.progress.major.required),
    el("div", { class: "hint legend-note" }, "숫자는 '합계(취득 + 현 학기)' 순서입니다. 진한 영역은 누적 취득 학점, 연한 영역은 현 학기 수강 교과목의 학점을 모두 취득할 경우 추가되는 학점을 나타냅니다. 총학점과 전공학점 기준이며 세부 졸업 요건은 포함하지 않습니다."));

  const bz = $("guideBusy"), pl = $("guidePlans"), t = $("guideTable"), ai = $("guideAi");
  bz.innerHTML = ""; pl.innerHTML = ""; t.innerHTML = ""; ai.innerHTML = "";
  if (g.plans.length === 0) {
    t.append(el("div", { class: "empty" }, "남은 정규 학기가 없습니다. (설정의 '현 학기'가 4학년 2학기면 남은 학기는 0개입니다.)"));
  } else {
    // 바쁜 학기 선택: 1학년 1학기부터 전부 보여 주고, 지난 학기·현 학기는 바꿀 수 없게 흐리게 표시
    const years = [...new Set(g.timeline.map((f) => f.year))];
    const boxes = years.map((y) => el("div", { class: "busy-year" }, el("b", {}, `${y}학년`),
      g.timeline.filter((f) => f.year === y).map((f) => {
        const cb = el("input", { type: "checkbox", "data-idx": f.idx });
        cb.checked = g.busy.includes(f.idx);
        cb.disabled = f.kind !== "future";
        cb.addEventListener("change", () => {
          guideBusy = [...bz.querySelectorAll("input")].filter((x) => x.checked).map((x) => +x.dataset.idx);
          guidePlan = null;
          renderGuide();
        });
        return el("label", { class: "check" + (f.kind !== "future" ? " off" : "") }, cb,
          `${f.term}학기` + (f.kind === "past" ? " (이수 완료)" : f.kind === "now" ? " (현 학기)" : ""));
      })));
    bz.append(el("div", { class: "opt-title" }, "학업 부담 조정 학기 (선택한 학기의 수강 학점을 줄입니다)"),
      el("div", { class: "hint" }, "향후 학기 중 학업 부담을 조정할 학기를 선택할 수 있습니다. 이전 학기와 현 학기는 변경할 수 없습니다."),
      el("div", { class: "busy-grid" }, boxes));

    const multi = g.busy.length > 0 && g.busy.length < g.future.length;
    const plans = multi ? g.plans : [g.plans[0]];
    if (!plans.some((x) => x.key === guidePlan)) guidePlan = multi ? g.default_plan : "even";
    const cur = plans.find((x) => x.key === guidePlan);
    if (multi) {
      pl.append(el("div", { class: "seg plan-seg", role: "group" }, plans.map((x) =>
        el("button", { type: "button", class: x.key === guidePlan ? "on" : "", onclick: () => { guidePlan = x.key; renderGuide(); } },
          x.name + (x.key === g.default_plan ? " (권장)" : "")))));
      pl.append(el("div", { class: "hint plan-help" },
        { even: "잔여 학점을 학기별로 균등하게 배분합니다.", balanced: "학업 부담 조정 학기의 이수 학점을 줄이고, 나머지 학기에 분산 배분합니다.", minimal: "바쁜 학기를 졸업에 꼭 필요한 최소 학점으로 줄입니다. 나머지 학기가 가장 빡빡해집니다." }[guidePlan]));
    }
    const note = (tagText, text, now) => el("span", {}, el("span", { class: "gtag" + (now ? " now" : "") }, tagText), text);
    const grow = (cls, cells) => el("tr", { class: cls }, cells.map((c, i) => el("td", { class: i >= 1 && i <= 3 ? "num" : "" }, c)));
    const gRows = [
      ...g.past.map((r) => grow("g-past", [`${r.year}학년 ${r.term}학기`, r.entered ? r.credits : "-", r.entered ? r.major : "-", r.entered ? r.lib : "-",
        note("이수 완료", r.entered ? `입력한 성적(${r.semester}) 취득 학점` : "등록된 성적 정보 없음")])),
      ...cur.rows.map((r) => grow(r.kind === "now" ? "g-now" : "", [`${r.year}학년 ${r.term}학기` + (r.kind === "now" ? " (현 학기)" : ""), r.credits, r.major, r.lib,
        r.kind === "now" ? note("현 학기", `등록 교과목 ${S.current.length}개 기준`, true) : note("향후 학기", " 권장 이수 학점" + (r.busy ? " (학업 부담 조정 학기)" : r.cap && r.credits >= r.cap ? " (학기별 수강 학점 상한)" : ""))])),
    ];
    if (g.seasonal_plan > 0) gRows.push(grow("g-seas", ["계절학기 이수 계획 (하계·동계 합산)", g.seasonal_plan, "-", "-", note("계절학기", "설정에 입력한 계획 학점 · 정규 학기 권장 이수 학점에서 이미 뺀 값")]));
    for (const se of g.seasonal_entered) gRows.push(grow("g-past", [se.semester.replace(/(여름|겨울)학기/, "$1 계절학기"), se.credits, "-", "-", note(/여름/.test(se.semester) ? "여름 계절학기" : /겨울/.test(se.semester) ? "겨울 계절학기" : "지난 계절학기", "입력한 성적 (위 취득 학점 합계에는 포함)")]));
    t.append(el("div", { class: "scroll" }, el("table", { class: "grid-table" },
      el("thead", {}, el("tr", {}, ["이수 학기", "이수 학점", "전공 학점", "교양 및 기타 학점", "학점 산정 기준"].map((h, i) => el("th", { class: i >= 1 && i <= 3 ? "num" : "" }, h)))),
      el("tbody", {}, gRows))));
    const futSum = cur.rows.filter((r) => r.kind === "future").reduce((a, r) => a + r.credits, 0), tt = g.progress.total;
    t.append(el("div", { class: "hint g-sum" }, `졸업 기준 학점 충족 현황: 누적 취득 ${tt.done} + 현 학기 예상 ${tt.now} + 향후 학기 권장 ${futSum}` + (g.seasonal_plan > 0 ? ` + 계절학기 계획 ${g.seasonal_plan}` : "") +
      ` = ${tt.done + tt.now + futSum + g.seasonal_plan}학점 (졸업 기준 ${tt.required}학점)`));
    t.append(el("div", { class: "callout" }, cur.summary));

    const box = el("div", { class: "ai-box" });
    let opened = false;
    const btn = el("button", { class: "btn-ghost", type: "button" }, "학점 배분 근거 확인");
    const close = () => { opened = false; box.innerHTML = ""; btn.textContent = "학점 배분 근거 확인"; };
    btn.addEventListener("click", async () => {
      if (opened) { close(); return; }
      opened = true; btn.textContent = "닫기"; box.innerHTML = "";
      box.append(el("div", { class: "dim" }, "분석 결과 설명 생성 중…"));
      try {
        const r = await api("POST", "/api/explain-guide", { busy: g.busy });
        if (!opened) return;
        box.innerHTML = "";
        box.append(el("div", { class: "ai-tag" }, "배분안 설명"),
          el("ul", {}, r.text.split("\n").filter((x) => x.trim()).map((x) => el("li", {}, x.replace(/^-\s*/, "")))),
                    el("button", { class: "btn-ghost", type: "button", onclick: close }, "닫기"));
      } catch (err) { box.innerHTML = ""; box.append(el("div", { class: "msg" }, err.message)); }
    });
    ai.append(el("div", { class: "row" }, btn), box);
  }
  const n = $("guideNote");
  n.innerHTML = "";
  n.append(el("div", { class: "callout" },
    `졸업 이수 부담도: ${g.burden_label}` + (g.extra_semesters > 0 ? ` · 현재 이수 계획 기준, 졸업 요건 충족까지 정규학기 ${g.extra_semesters}학기의 추가 이수가 필요합니다.` : ""),
    g.seasonal_plan > 0 ? el("div", { class: "dim" }, `계절학기 계획 ${g.seasonal_plan}학점을 반영해 정규 학기 권장 이수 학점을 줄였습니다.`) : null));
}
$("goWithdraw").addEventListener("click", () => showTab("withdraw"));
$("goRetake").addEventListener("click", () => showTab("retake"));


/* 과목 선택형 입력: 교육과정 과목 목록에서 고르면 학점·구분·필수가 자동으로 채워짐 */
let COURSES = [];
function setPick(name) {
  const sel = $("cPick"), inCat = COURSES.some((c) => c.n === name);
  sel.value = name === "" ? "" : inCat ? name : "__custom";
  $("cName").hidden = sel.value !== "__custom";
}
function initCoursePick() {
  const sel = $("cPick");
  sel.append(el("option", { value: "" }, "과목 선택"));
  for (const t of ["교양필수", "전공필수", "전공선택"]) {
    const g = el("optgroup", { label: t });
    for (const c of COURSES.filter((x) => x.t === t)) g.append(el("option", { value: c.n }, `${c.n} (${c.c}학점)`));
    sel.append(g);
  }
  sel.append(el("option", { value: "__custom" }, "직접 입력…"));
  sel.addEventListener("change", () => {
    const v = sel.value, c = COURSES.find((x) => x.n === v);
    $("cName").hidden = v !== "__custom";
    if (c) {
      $("cName").value = c.n; $("cCredit").value = c.c;
      $("cMajor").checked = c.t !== "교양필수"; $("cRequired").checked = c.t !== "전공선택";
    } else { $("cName").value = ""; if (v === "__custom") $("cName").focus(); }
  });
}
fetch("/static/courses.json").then((r) => r.json()).then((d) => {
  // 학과별 과목 목록: {"학과명": [과목…]} — 학과를 추가하면 설정의 학과 선택지도 자동으로 늘어남
  const depts = Object.keys(d), sel = $("sDept");
  sel.innerHTML = "";
  for (const n of depts) sel.append(el("option", { value: n }, n));
  let mine = "";
  try { mine = (JSON.parse(localStorage.getItem("polarisProfile") || "{}")).dept || ""; } catch (e) {}
  sel.value = depts.includes(mine) ? mine : depts[0];
  COURSES = d[sel.value] || [];
  initCoursePick();
}).catch(() => {
  $("cPick").hidden = true; $("cName").hidden = false;
});

document.querySelector(".crumb-root").addEventListener("click", () => showTab("grades"));

(function () {   // 입학년도 선택지 + 기본 정보(대학교·학과·입학년도)는 이 브라우저에만 기억 (계산에는 쓰이지 않음)
  const y = new Date().getFullYear(), sel = $("sEntry");
  for (let v = y; v >= y - 10; v--) sel.append(el("option", { value: String(v) }, `${v}학번`));
  $("settingsForm").addEventListener("submit", () => {
    try { localStorage.setItem("polarisProfile", JSON.stringify({ univ: $("sUniv").value, dept: $("sDept").value, entry: $("sEntry").value })); } catch (e) {}
  });
})();
