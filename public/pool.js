// "Win the week" strategy. Max-points picks are chalk, and so is most of your pool, so you
// rarely finish first by matching them. This simulates a pool of opponents who read the same
// lines (with noise, like real people) and searches for the picks that most often beat all
// of them. Pure functions so it runs in a Web Worker and under node tests.

import { logit } from "./optimize.js";

// Noise (log-odds) in how opponents read each game: a shared "public lean" per simulated week
// plus each person's own read. Together a 60% favorite gets ~72% of picks and a 70% favorite
// ~90%, similar to public pick'em splits. The shared part keeps the field realistically herd-like.
export const FIELD_SIGMA = 0.55;
export const FIELD_SHARED = 0.3;

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian(rand) {
  let spare = null;
  return () => {
    if (spare != null) {
      const s = spare;
      spare = null;
      return s;
    }
    let u = rand();
    while (u === 0) u = rand();
    const r = Math.sqrt(-2 * Math.log(u));
    const th = 2 * Math.PI * rand();
    spare = r * Math.sin(th);
    return r * Math.cos(th);
  };
}

export function hashSeed(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 0x01000193);
  return h >>> 0;
}

/**
 * Simulate `sims` weeks. q/m are home-win probabilities: q is what we believe (outcomes are
 * drawn from it), m is what the field sees (before our own overrides). Each opponent picks the side their noisy read
 * favors and ranks games by how confident that read is, using the same point values.
 * Returns outcomes plus the best opponent score in each sim and how many opponents hit it.
 */
export function simulateField({ q, m, values, entries, sigma = FIELD_SIGMA, shared = FIELD_SHARED, sims, seed }) {
  const n = q.length;
  const rand = mulberry32(seed);
  const gauss = gaussian(rand);
  const L = m.map((p) => logit(p));
  const lean = new Float64Array(n);
  const asc = Float64Array.from(values).sort();
  const home = new Uint8Array(sims * n);
  const best = new Float64Array(sims);
  const ties = new Int32Array(sims);
  const key = new Float64Array(n);
  const side = new Uint8Array(n);
  const idx = new Int32Array(n);

  for (let s = 0; s < sims; s++) {
    const o = s * n;
    for (let g = 0; g < n; g++) {
      home[o + g] = rand() < q[g] ? 1 : 0;
      lean[g] = L[g] + shared * gauss();
    }
    let top = -1;
    let count = 0;
    for (let k = 0; k < entries; k++) {
      for (let g = 0; g < n; g++) {
        const l = lean[g] + sigma * gauss();
        side[g] = l > 0 ? 1 : 0;
        key[g] = Math.abs(l);
        idx[g] = g;
      }
      for (let i = 1; i < n; i++) {
        const v = idx[i];
        let j = i - 1;
        while (j >= 0 && key[idx[j]] > key[v]) idx[j + 1] = idx[j--];
        idx[j + 1] = v;
      }
      let score = 0;
      for (let r = 0; r < n; r++) {
        const g = idx[r];
        if (side[g] === home[o + g]) score += asc[r];
      }
      if (score > top) {
        top = score;
        count = 1;
      } else if (score === top) count++;
    }
    best[s] = top;
    ties[s] = count;
  }
  return { n, sims, home, best, ties };
}

// Expected share of first place: outright wins count 1, ties split the prize.
function share(v, best, ties) {
  return v > best ? 1 : v === best ? 1 / (ties + 1) : 0;
}

function scoreSims(field, side, pts) {
  const { n, sims, home } = field;
  const hit = new Uint8Array(sims * n);
  const sc = new Float64Array(sims);
  for (let s = 0; s < sims; s++) {
    let total = 0;
    for (let g = 0; g < n; g++) {
      const h = home[s * n + g] === side[g] ? 1 : 0;
      hit[s * n + g] = h;
      total += h * pts[g];
    }
    sc[s] = total;
  }
  return { hit, sc };
}

export function winChance(field, side, pts) {
  const { sc } = scoreSims(field, side, pts);
  let total = 0;
  for (let s = 0; s < field.sims; s++) total += share(sc[s], field.best[s], field.ties[s]);
  return total / field.sims;
}

/**
 * Best-improvement hill climb over: swapping two games' points, flipping a pick, and flipping
 * a pick while swapping its points with another game (how an upset moves up the ladder).
 * Each move changes a sim's score by a*hit_i + b*hit_j + c, so candidates are cheap to score.
 */
function climb(field, start, fixedSide, fixedPts, { maxIter = 60, minGain = 2 } = {}) {
  const { n, sims, best, ties } = field;
  const side = Uint8Array.from(start.side);
  const pts = Float64Array.from(start.pts);
  let { hit, sc } = scoreSims(field, side, pts);

  const gain = (i, j, a, b, c) => {
    let total = 0;
    for (let s = 0; s < sims; s++) {
      const v = sc[s] + a * hit[s * n + i] + b * hit[s * n + j] + c;
      total += share(v, best[s], ties[s]) - share(sc[s], best[s], ties[s]);
    }
    return total;
  };

  for (let iter = 0; iter < maxIter; iter++) {
    let top = { g: minGain };
    for (let i = 0; i < n; i++) {
      const pi = pts[i];
      if (!fixedSide[i]) {
        const g = gain(i, i, -2 * pi, 0, pi);
        if (g > top.g) top = { g, move: "flip", i };
      }
      if (fixedPts[i]) continue;
      for (let j = 0; j < n; j++) {
        if (j === i || fixedPts[j] || pts[j] === pi) continue;
        const pj = pts[j];
        if (j > i) {
          const g = gain(i, j, pj - pi, pi - pj, 0);
          if (g > top.g) top = { g, move: "swap", i, j };
        }
        if (!fixedSide[i]) {
          const g = gain(i, j, -(pi + pj), pi - pj, pj);
          if (g > top.g) top = { g, move: "flipswap", i, j };
        }
      }
    }
    if (!top.move) break;
    const { i, j } = top;
    if (top.move !== "swap") side[i] ^= 1;
    if (top.move !== "flip") [pts[i], pts[j]] = [pts[j], pts[i]];
    ({ hit, sc } = scoreSims(field, side, pts));
  }
  return { side: [...side], pts: [...pts] };
}

const median = (arr) => {
  const s = Float64Array.from(arr).sort();
  return s.length ? s[Math.floor(s.length / 2)] : 0;
};

/**
 * games: [{id, q, m, home, points, fixedSide, fixedPoints}] where home/points is the starting
 * (max-points) plan. Searches on one set of sims and judges on a fresh set, keeping the
 * starting plan unless the new one really does win more often.
 * Returns {plan: [{id, home, points}], pWin, pWinBase, changed, winningScore, entries, sims}.
 */
export function optimizeForPool({ games, entries, sigma = FIELD_SIGMA, shared = FIELD_SHARED, seed = 1, optSims, evalSims }) {
  const k = Math.max(1, Math.round(entries));
  optSims ??= Math.round(Math.min(4000, Math.max(1500, 400000 / k)));
  evalSims ??= Math.round(Math.min(10000, Math.max(3000, 1000000 / k)));
  const base = {
    q: games.map((g) => g.q),
    m: games.map((g) => g.m),
    values: games.map((g) => g.points),
    entries: k,
    sigma,
    shared,
  };
  const start = { side: games.map((g) => (g.home ? 1 : 0)), pts: games.map((g) => g.points) };
  const fixedSide = games.map((g) => Boolean(g.fixedSide));
  const fixedPts = games.map((g) => Boolean(g.fixedPoints));

  const found = climb(simulateField({ ...base, sims: optSims, seed }), start, fixedSide, fixedPts);
  const test = simulateField({ ...base, sims: evalSims, seed: (seed ^ 0x9e3779b9) >>> 0 });
  const pWinBase = winChance(test, start.side, start.pts);
  const moved = found.side.some((s, i) => s !== start.side[i]) || found.pts.some((p, i) => p !== start.pts[i]);
  const pFound = moved ? winChance(test, found.side, found.pts) : pWinBase;
  const changed = moved && pFound > pWinBase;
  const plan = changed ? found : start;
  return {
    plan: games.map((g, i) => ({ id: g.id, home: plan.side[i] === 1, points: plan.pts[i] })),
    pWin: changed ? pFound : pWinBase,
    pWinBase,
    changed,
    winningScore: median(test.best),
    entries: k,
    sims: evalSims,
  };
}
