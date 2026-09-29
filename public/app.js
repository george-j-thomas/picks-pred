import { assign, summarize } from "./optimize.js";

const $ = (sel) => document.querySelector(sel);
const LS = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem(`pp:${k}`)) ?? d; } catch { return d; } },
  set: (k, v) => localStorage.setItem(`pp:${k}`, JSON.stringify(v)),
};
const BOOKS = [
  ["fanduel", "FanDuel"], ["draftkings", "DraftKings"], ["betmgm", "BetMGM"], ["williamhill_us", "Caesars"],
  ["betrivers", "BetRivers"], ["fanatics", "Fanatics"], ["ballybet", "Bally Bet"], ["bovada", "Bovada"],
  ["betonlineag", "BetOnline"], ["lowvig", "LowVig"],
];
const POST_ABBR = { "Wild Card": "WC", "Divisional Round": "DIV", "Conference Championship": "CONF", "Super Bowl": "SB" };
const ICONS = {
  lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/></svg>',
  flip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8h14l-4-4M20 16H6l4 4"/></svg>',
  tune: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg>',
};

const state = {
  season: null, type: 2, week: null,
  data: null, loading: false, fresh: true,
  weights: LS.get("weights", { market: 0.8, model: 0.2 }),
  apiKey: LS.get("apiKey", ""),
  books: LS.get("books", []),
  maxPoints: LS.get("maxPoints", null),
  tweaks: { locks: {}, forced: {}, overrides: {} },
  open: new Set(),
  last: null,
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const pct = (p, d = 1) => (p == null ? "—" : (p * 100).toFixed(d));
const weekKey = () => `tweaks:${state.season}-${state.type}-${state.week}`;
const logoUrl = (abbr) =>
  `https://a.espncdn.com/combiner/i?img=/i/teamlogos/nfl/500-dark/${abbr.toLowerCase()}.png&h=128&w=128`;
const logoImg = (team, cls = "logo") =>
  `<img class="${cls}" src="${logoUrl(team.abbr)}" alt="${esc(team.name)} logo" loading="lazy" onerror="this.onerror=null;this.src='${esc(team.logo)}'" />`;

function luminance(hex) {
  const n = parseInt(hex || "777777", 16);
  const [r, g, b] = [n >> 16, (n >> 8) & 255, n & 255].map((v) => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function teamColor(team) {
  const main = team.color || "888888";
  const alt = team.alt_color || "";
  const c = luminance(main) < 0.03 && alt && luminance(alt) > luminance(main) ? alt : main;
  return `#${c}`;
}

function currentFromCalendar(cal) {
  const now = Date.now();
  return cal.find((w) => new Date(w.end).getTime() > now) ?? cal[cal.length - 1];
}
const maxSeason = (() => {
  const d = new Date();
  return d.getMonth() >= 2 ? d.getFullYear() : d.getFullYear() - 1;
})();

/* ---------------- data ---------------- */
async function load({ keepTweaks = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  document.body.classList.add("loading");
  $("#runBtn").disabled = true;
  if (!state.data || !keepTweaks) renderSkeleton();

  const qs = new URLSearchParams();
  if (state.week != null) {
    qs.set("week", state.week);
    qs.set("type", state.type);
    if (state.season) qs.set("season", state.season);
  }
  if (state.apiKey && state.books.length) qs.set("books", state.books.join(","));
  const headers = state.apiKey ? { "X-Odds-Api-Key": state.apiKey } : {};

  try {
    const res = await fetch(`/api/games?${qs}`, { headers });
    const body = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    if (!res.ok) throw Object.assign(new Error(body.error || `HTTP ${res.status}`), { body });
    state.data = body;
    state.season = body.season;
    state.type = body.season_type;
    state.week = body.week;
    state.tweaks = { locks: {}, forced: {}, overrides: {}, ...LS.get(weekKey(), {}) };
    if (!keepTweaks) state.open.clear();
    history.replaceState(null, "", `?season=${state.season}&type=${state.type}&week=${state.week}`);
    state.fresh = !keepTweaks;
    render();
    if (keepTweaks) toast("Lines refreshed");
  } catch (err) {
    if (err.body?.calendar) {
      state.data = { ...err.body, games: [] };
      renderWeeks();
    }
    $("#ladder").innerHTML = "";
    showNotice(`Couldn't load week: ${err.message}`, true);
  } finally {
    state.loading = false;
    document.body.classList.remove("loading");
    $("#runBtn").disabled = false;
  }
}

function saveTweaks() {
  const t = state.tweaks;
  const empty = !Object.keys(t.locks).length && !Object.keys(t.forced).length && !Object.keys(t.overrides).length;
  empty ? localStorage.removeItem(`pp:${weekKey()}`) : LS.set(weekKey(), t);
}

/* ---------------- render ---------------- */
function render() {
  const { picks, errors } = assign(state.data.games, {
    weights: state.weights,
    maxPoints: state.maxPoints,
    locks: state.tweaks.locks,
    forced: state.tweaks.forced,
    overrides: state.tweaks.overrides,
  });
  const summary = summarize(picks);
  state.last = { picks, summary };
  renderWeeks();
  renderHero(picks, summary);
  renderDist(summary);
  renderLadder(picks);
  renderSourcesState();
  renderNotices(errors);
}

function renderSkeleton() {
  $("#ladder").innerHTML = Array.from({ length: 8 }, () => '<div class="skel"></div>').join("");
}

function renderWeeks() {
  const cal = state.data?.calendar ?? [];
  const current = currentFromCalendar(cal.length ? cal : [{}]);
  const isCurrentSeason = state.season === maxSeason;
  let html = "";
  let lastType = null;
  for (const w of cal) {
    if (lastType && w.season_type !== lastType) html += '<span class="wk-sep"></span>';
    lastType = w.season_type;
    const label = w.season_type === 3 ? POST_ABBR[w.label] ?? w.short : w.week;
    const date = (w.detail || "").split("-")[0];
    const cls = [
      "wk",
      w.week === state.week && w.season_type === state.type ? "active" : "",
      isCurrentSeason && current && w.week === current.week && w.season_type === current.season_type ? "current" : "",
    ].join(" ");
    html += `<button class="${cls}" data-week="${w.week}" data-type="${w.season_type}" title="${esc(w.label)} · ${esc(w.detail)}">${label}<small>${esc(date)}</small></button>`;
  }
  $("#weeks").innerHTML = html;
  $("#weeks .active")?.scrollIntoView({ block: "nearest", inline: "center", behavior: state.fresh ? "auto" : "smooth" });
  $("#seasonLabel").textContent = state.season ?? "—";
  $("#seasonNext").disabled = state.season >= maxSeason;
}

function renderHero(picks, s) {
  const games = state.data.games;
  const entry = (state.data.calendar || []).find((w) => w.week === state.week && w.season_type === state.type);
  const done = games.every((g) => g.completed);
  const live = games.some((g) => g.started && !g.completed);
  const started = games.some((g) => g.started);
  const eb = $("#weekEyebrow");
  eb.textContent = done ? "Final" : live ? "Live now" : started ? "In progress" : "Upcoming";
  eb.className = `eyebrow${live ? " live" : ""}`;

  const title = state.type === 3 ? esc(entry?.label ?? `Round ${state.week}`) : `Week <span class="num">${state.week}</span>`;
  $("#weekTitle").innerHTML = title;
  const books = new Set(games.flatMap((g) => g.sources.map((x) => x.label)));
  $("#weekMeta").innerHTML = `${esc(entry?.detail ?? "")} · ${games.length} games<br>${esc([...books].join(" · ") || "no sources")}`;

  const stats = [
    `<div class="stat big"><div class="k">Expected points</div><div class="v">${s.expected.toFixed(1)}<small>/ ${s.max}</small></div>
       <div class="sub">80% of outcomes: ${s.p10}–${s.p90} · σ ${s.sd.toFixed(1)}</div></div>`,
    `<div class="stat"><div class="k">Expected correct</div><div class="v">${s.expectedWins.toFixed(1)}<small>/ ${picks.length}</small></div></div>`,
  ];
  if (s.actual != null) {
    const sub = done
      ? `${s.correct}/${s.decided} correct · better than ${Math.round((1 - (s.pctAtLeast ?? 0)) * 100)}% of outcomes`
      : `${s.correct}/${s.decided} decided so far`;
    stats.push(`<div class="stat actual"><div class="k">${done ? "Actual score" : "Banked"}</div><div class="v">${s.actual}</div><div class="sub">${sub}</div></div>`);
  } else {
    const locks = picks.filter((p) => p.locked).length;
    stats.push(`<div class="stat"><div class="k">Coin flips</div><div class="v">${picks.filter((p) => p.flags.includes("coin flip")).length}</div>
      <div class="sub">${locks ? `${locks} locked` : "no locks"}</div></div>`);
  }
  $("#heroStats").innerHTML = stats.join("");
}

function renderDist(s) {
  const svg = $("#distSvg");
  const W = 600, H = 150, top = 20;
  const n = s.dist.length;
  const peak = Math.max(...s.dist);
  const bw = W / n;
  let out = "";
  s.dist.forEach((p, i) => {
    const h = (p / peak) * (H - top);
    const cls = i >= s.p10 && i <= s.p90 ? "bar-d in" : "bar-d";
    out += `<rect class="${cls}" x="${(i * bw).toFixed(2)}" y="${(H - h + top - 20).toFixed(2)}" width="${Math.max(bw - 0.6, 0.5).toFixed(2)}" height="${h.toFixed(2)}" rx="0.8"/>`;
  });
  const mark = (v, cls, label) => {
    const x = ((v + 0.5) * bw).toFixed(1);
    const anchor = v > n * 0.85 ? "end" : v < n * 0.15 ? "start" : "middle";
    return `<line class="mark ${cls}" x1="${x}" x2="${x}" y1="12" y2="${H}"/><text class="mark-label ${cls}" x="${x}" y="6" text-anchor="${anchor}">${label}</text>`;
  };
  out += mark(s.expected, "", `EXP ${s.expected.toFixed(0)}`);
  if (s.actual != null && state.data.games.every((g) => g.completed)) out += mark(s.actual, "actual", `ACTUAL ${s.actual}`);
  svg.innerHTML = out;
  $("#distAxis").innerHTML = `<span>0</span><span>${Math.round((n - 1) / 2)}</span><span>${n - 1} pts</span>`;
}

function kickoffParts(g) {
  const d = new Date(g.kickoff);
  return {
    day: d.toLocaleDateString(undefined, { weekday: "short" }),
    date: d.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    time: d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }),
  };
}

function flagClass(f) {
  if (f === "FPI picks other side" || f === "NO DATA" || f === "upset pick") return "flag hot";
  if (f === "FPI disagrees" || f === "already started") return "flag warn";
  if (f === "override") return "flag volt";
  return "flag";
}

function rowHtml(p, i, n) {
  const g = p.game;
  const color = teamColor(p.team);
  const opp = teamColor(p.opp);
  const k = kickoffParts(g);
  const decided = g.completed && g.winner;
  const won = decided && (g.winner === "home") === p.isHome;
  const rowCls = ["row", decided ? (won ? "won" : "lost") : ""].join(" ");
  const ptsCls = ["pts", p.points > n - 3 ? "top" : "", p.winProb < 0.58 ? "low" : ""].join(" ");
  const score = g.home.score != null ? `${g.away.abbr} ${g.away.score} – ${g.home.score} ${g.home.abbr}` : "";

  let when;
  if (decided) {
    when = `<div class="result ${won ? "won" : "lost"}">${won ? `+${p.points}` : "0"} pts</div><div>${esc(score)}</div>`;
  } else if (g.started) {
    when = `<div class="result live">● ${esc(g.status_detail || "Live")}</div><div>${esc(score)}</div>`;
  } else {
    when = `<b>${k.day} ${k.time}</b><div>${k.date}</div>`;
  }
  const flags = p.flags.map((f) => `<span class="${flagClass(f)}">${esc(f)}</span>`).join("");
  const srcs = g.sources
    .map((s) => `<span>${esc(s.label)} <b>${pct(p.isHome ? s.home_prob : 1 - s.home_prob)}%</b></span>`)
    .join("");
  const override = state.tweaks.overrides[g.id];
  const homeVal = Math.round((override ?? (p.isHome ? p.winProb : 1 - p.winProb)) * 100);

  return `
  <article class="${rowCls}" data-id="${g.id}" style="--team:${color};--opp:${opp}8c;--i:${i}">
    <div class="${ptsCls}">${p.points}${p.locked ? '<span class="lock-badge">●</span>' : ""}</div>
    <div class="matchup">
      ${logoImg(p.team)}
      <div class="names">
        <div class="pick-abbr">${esc(p.team.abbr)} <span class="ha">${p.isHome ? "home" : "away"}</span></div>
        <div class="pick-name">${esc(p.team.name)}</div>
        <div class="vs"><em>${p.isHome ? "vs" : "at"}</em>${logoImg(p.opp, "")}${esc(p.opp.abbr)}</div>
      </div>
    </div>
    <div class="prob">
      <div class="prob-top"><b>${pct(p.winProb)}<small>%</small></b><span class="line">${esc(g.line)}</span></div>
      <div class="bar">
        <span class="bar-fill" style="width:${(p.winProb * 100).toFixed(1)}%"></span>
        ${p.marketProb != null ? `<i class="tick m" style="left:${(p.marketProb * 100).toFixed(1)}%"></i>` : ""}
        ${p.modelProb != null ? `<i class="tick f" style="left:${(p.modelProb * 100).toFixed(1)}%"></i>` : ""}
      </div>
      <div class="prob-src"><span class="m"><i></i>Market ${pct(p.marketProb)}</span><span class="f"><i></i>FPI ${pct(p.modelProb)}</span></div>
    </div>
    <div class="when">${when}<div class="flags">${flags}</div></div>
    <div class="actions">
      <button class="act${p.locked ? " on" : ""}" data-act="lock" title="${p.locked ? "Unlock" : `Lock ${p.team.abbr} at ${p.points}`}" aria-pressed="${p.locked}">${ICONS.lock}</button>
      <button class="act${p.forced ? " on" : ""}" data-act="flip" title="Pick ${esc(p.opp.abbr)} instead" aria-pressed="${p.forced}">${ICONS.flip}</button>
      <button class="act${state.open.has(g.id) || override != null ? " on" : ""}" data-act="tune" title="Adjust win probability" aria-expanded="${state.open.has(g.id)}">${ICONS.tune}</button>
    </div>
    ${state.open.has(g.id) ? `
    <div class="tune">
      <span class="tune-team">${logoImg(g.away, "")}${esc(g.away.abbr)} <output data-away>${100 - homeVal}%</output></span>
      <input type="range" min="1" max="99" value="${homeVal}" data-tune aria-label="${esc(g.home.abbr)} win probability" style="--fill:${homeVal}%" />
      <span class="tune-team"><output data-home>${homeVal}%</output> ${esc(g.home.abbr)}${logoImg(g.home, "")}</span>
      <div class="srcs">${srcs}${override != null ? '<button class="btn ghost small" data-act="clear">Reset to model</button>' : ""}</div>
    </div>` : ""}
  </article>`;
}

function renderLadder(picks) {
  const ladder = $("#ladder");
  const before = new Map([...ladder.querySelectorAll(".row")].map((el) => [el.dataset.id, el.getBoundingClientRect().top]));
  ladder.innerHTML = picks.map((p, i) => rowHtml(p, i, picks.length)).join("");
  if (state.fresh) {
    state.fresh = false;
    return;
  }
  // FLIP: animate rows from their previous position to the new one.
  for (const el of ladder.querySelectorAll(".row")) {
    el.style.animation = "none";
    const prev = before.get(el.dataset.id);
    if (prev == null) continue;
    const dy = prev - el.getBoundingClientRect().top;
    if (Math.abs(dy) < 1) continue;
    el.style.transform = `translateY(${dy}px)`;
    el.style.transition = "none";
    requestAnimationFrame(() => {
      el.style.transition = "transform 0.55s cubic-bezier(0.2, 0.8, 0.2, 1)";
      el.style.transform = "";
    });
  }
}

function renderSourcesState() {
  const o = state.data?.odds_api ?? {};
  const dot = $("#oddsDot");
  const pill = $("#keyState");
  const status = $("#keyStatus");
  dot.className = `dot${o.error ? " err" : o.enabled ? " on" : ""}`;
  pill.className = `pill${o.error ? " err" : o.enabled ? " on" : ""}`;
  pill.textContent = o.error ? "error" : o.enabled ? "on" : "off";
  if (o.error) status.textContent = o.error;
  else if (o.skipped) status.textContent = "Key saved · not used for weeks that have already kicked off (closing lines come from ESPN).";
  else if (o.enabled)
    status.textContent = `${o.key_source === "server" ? "Server key" : "Your key"} · matched ${o.matched}/${state.data.games.length} games${o.remaining != null ? ` · ${o.remaining} requests left this month` : ""}`;
  else status.textContent = "";
}

function renderNotices(errors) {
  const o = state.data.odds_api ?? {};
  const msgs = [...errors];
  if (o.error) msgs.push(`${o.error} — showing ESPN lines only.`);
  const missing = state.data.games.filter((g) => !g.sources.length);
  if (missing.length) msgs.push(`No odds or FPI yet for ${missing.map((g) => `${g.away.abbr} @ ${g.home.abbr}`).join(", ")}.`);
  const unlockedStarted = state.last.picks.filter((p) => p.game.started && !p.locked && !p.game.completed);
  if (unlockedStarted.length && !state.data.games.every((g) => g.started))
    msgs.push(`${unlockedStarted.length} game(s) already kicked off — lock the picks you actually submitted so the rest re-optimize around them.`);
  showNotice(msgs.join(" "), Boolean(o.error || errors.length));
}

function showNotice(msg, isErr = false) {
  const el = $("#notice");
  el.hidden = !msg;
  el.textContent = msg || "";
  el.className = `notice${isErr ? " err" : ""}`;
}

let toastTimer;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 1800);
}

/* ---------------- interactions ---------------- */
$("#ladder").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const id = btn.closest(".row").dataset.id;
  const pick = state.last.picks.find((p) => p.game.id === id);
  const t = state.tweaks;
  switch (btn.dataset.act) {
    case "lock":
      if (t.locks[id]) delete t.locks[id];
      else t.locks[id] = { team: pick.team.abbr, points: pick.points };
      break;
    case "flip": {
      const other = pick.opp.abbr;
      if (t.locks[id]) t.locks[id].team = other;
      const favorite = blendFavorite(pick);
      if (other === favorite) delete t.forced[id];
      else t.forced[id] = other;
      break;
    }
    case "tune":
      state.open.has(id) ? state.open.delete(id) : state.open.add(id);
      break;
    case "clear":
      delete t.overrides[id];
      break;
  }
  saveTweaks();
  render();
});

// The team the model would pick with no forcing, so flipping back clears the tweak.
function blendFavorite(pick) {
  const { picks } = assign([pick.game], { weights: state.weights, overrides: state.tweaks.overrides });
  return picks[0].team.abbr;
}

$("#ladder").addEventListener("input", (e) => {
  if (!e.target.matches("[data-tune]")) return;
  const v = Number(e.target.value);
  const row = e.target.closest(".row");
  row.querySelector("[data-home]").textContent = `${v}%`;
  row.querySelector("[data-away]").textContent = `${100 - v}%`;
  e.target.style.setProperty("--fill", `${v}%`);
});
$("#ladder").addEventListener("change", (e) => {
  if (!e.target.matches("[data-tune]")) return;
  const id = e.target.closest(".row").dataset.id;
  state.tweaks.overrides[id] = Number(e.target.value) / 100;
  delete state.tweaks.forced[id];
  saveTweaks();
  render();
});

$("#weeks").addEventListener("click", (e) => {
  const b = e.target.closest(".wk");
  if (!b) return;
  state.week = Number(b.dataset.week);
  state.type = Number(b.dataset.type);
  load();
});
function stepWeek(dir) {
  const cal = state.data?.calendar ?? [];
  const i = cal.findIndex((w) => w.week === state.week && w.season_type === state.type);
  const next = cal[i + dir];
  if (!next) return;
  state.week = next.week;
  state.type = next.season_type;
  load();
}
document.addEventListener("keydown", (e) => {
  if (e.target.closest("input, textarea") || e.metaKey || e.ctrlKey) return;
  if (e.key === "ArrowLeft") stepWeek(-1);
  if (e.key === "ArrowRight") stepWeek(1);
  if (e.key === "Escape") closeDrawer();
});
$("#seasonPrev").addEventListener("click", () => { state.season -= 1; state.week ??= 1; load(); });
$("#seasonNext").addEventListener("click", () => { state.season += 1; state.week ??= 1; load(); });

const weight = $("#weight");
function syncWeight() {
  const m = Math.round(state.weights.market * 100);
  weight.value = m;
  weight.style.setProperty("--fill", `${m}%`);
  $("#weightOut").textContent = `${m} / ${100 - m}`;
}
weight.addEventListener("input", () => {
  const m = Number(weight.value) / 100;
  state.weights = { market: m, model: Math.round((1 - m) * 100) / 100 };
  LS.set("weights", state.weights);
  syncWeight();
  if (state.data?.games.length) render();
});

$("#runBtn").addEventListener("click", () => load({ keepTweaks: true }));
$("#resetBtn").addEventListener("click", () => {
  state.tweaks = { locks: {}, forced: {}, overrides: {} };
  state.open.clear();
  saveTweaks();
  render();
  toast("Tweaks cleared");
});
$("#copyBtn").addEventListener("click", async () => {
  if (!state.last) return;
  const lines = state.last.picks.map(
    (p) => `${String(p.points).padStart(2)}  ${p.team.abbr.padEnd(4)} ${p.isHome ? "vs" : "@ "} ${p.opp.abbr.padEnd(4)} ${pct(p.winProb, 0)}%`,
  );
  const title = state.type === 3 ? "Postseason" : `Week ${state.week}`;
  const text = `${state.season} ${title} picks\n${lines.join("\n")}\nExpected ${state.last.summary.expected.toFixed(1)} / ${state.last.summary.max}`;
  try {
    await navigator.clipboard.writeText(text);
    toast("Picks copied");
  } catch {
    toast("Clipboard unavailable");
  }
});

/* ---------------- drawer ---------------- */
function openDrawer() {
  $("#drawer").hidden = false;
  $("#scrim").hidden = false;
  $("#settingsBtn").setAttribute("aria-expanded", "true");
  $("#apiKey").value = state.apiKey;
  $("#maxPoints").value = state.maxPoints ?? "";
  renderBooks();
}
function closeDrawer() {
  $("#drawer").hidden = true;
  $("#scrim").hidden = true;
  $("#settingsBtn").setAttribute("aria-expanded", "false");
}
function renderBooks() {
  $("#books").innerHTML = BOOKS.map(
    ([k, label]) => `<button class="chip${state.books.includes(k) ? " on" : ""}" data-book="${k}" aria-pressed="${state.books.includes(k)}">${label}</button>`,
  ).join("");
}
$("#settingsBtn").addEventListener("click", openDrawer);
$("#drawerClose").addEventListener("click", closeDrawer);
$("#scrim").addEventListener("click", closeDrawer);
$("#books").addEventListener("click", (e) => {
  const b = e.target.closest("[data-book]");
  if (!b) return;
  const k = b.dataset.book;
  state.books = state.books.includes(k) ? state.books.filter((x) => x !== k) : [...state.books, k];
  renderBooks();
});
$("#keyToggle").addEventListener("click", () => {
  const input = $("#apiKey");
  input.type = input.type === "password" ? "text" : "password";
  $("#keyToggle").textContent = input.type === "password" ? "Show" : "Hide";
});
$("#saveSources").addEventListener("click", () => {
  state.apiKey = $("#apiKey").value.trim();
  const mp = parseInt($("#maxPoints").value, 10);
  state.maxPoints = Number.isFinite(mp) && mp > 0 ? mp : null;
  LS.set("apiKey", state.apiKey);
  LS.set("books", state.books);
  LS.set("maxPoints", state.maxPoints);
  closeDrawer();
  load({ keepTweaks: true });
});

/* ---------------- boot ---------------- */
const params = new URLSearchParams(location.search);
if (params.get("week")) {
  state.week = Number(params.get("week"));
  state.type = Number(params.get("type") || 2);
  state.season = Number(params.get("season")) || null;
}
syncWeight();
load();
