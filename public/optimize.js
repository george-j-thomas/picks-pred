// Mirrors src/picks_pred/optimize.py so the UI can re-optimize instantly in the browser.
// Keep the two in sync; tests/test_web.py checks parity.

export const COIN_FLIP = 0.55;
export const DISAGREE_GAP = 0.10;

const clamp = (p) => Math.min(Math.max(p, 1e-6), 1 - 1e-6);
export const logit = (p) => Math.log(clamp(p) / (1 - clamp(p)));
export const invLogit = (x) => 1 / (1 + Math.exp(-x));
const meanLogit = (ps) => (ps.length ? invLogit(ps.reduce((a, p) => a + logit(p), 0) / ps.length) : null);

/** Returns {final, market, model} home-win probabilities for a game payload. */
export function blend(game, weights, overrideHome = null) {
  const market = meanLogit(game.sources.filter((s) => s.market).map((s) => s.home_prob));
  const model = meanLogit(game.sources.filter((s) => !s.market).map((s) => s.home_prob));
  if (overrideHome != null) return { final: overrideHome, market, model };
  const parts = [[market, weights.market], [model, weights.model]].filter(([p, w]) => p != null && w > 0);
  if (!parts.length) return { final: null, market, model };
  const total = parts.reduce((a, [, w]) => a + w, 0);
  return { final: invLogit(parts.reduce((a, [p, w]) => a + logit(p) * w, 0) / total), market, model };
}

/**
 * Pick a winner and unique confidence value for each game.
 * opts: {weights, maxPoints, locks: {gameId: {team, points}}, forced: {gameId: abbr},
 *        overrides: {gameId: homeProb}, plan: {gameId: {team, points}}}
 * `plan` (from the win-the-week search) sets a pick and its points without locking it.
 * Returns {picks, errors}.
 */
export function assign(games, opts = {}) {
  const weights = opts.weights ?? { market: 0.8, model: 0.2 };
  const locks = opts.locks ?? {};
  const forced = opts.forced ?? {};
  const overrides = opts.overrides ?? {};
  const plan = opts.plan ?? {};
  const n = opts.maxPoints || games.length;
  const available = new Set(Array.from({ length: n }, (_, i) => i + 1));
  const errors = [];
  const picks = [];
  const open = [];
  const planned = [];

  for (const game of games) {
    const override = overrides[game.id] ?? null;
    let { final: homeP, market, model } = blend(game, weights, override);
    const flags = [];
    if (homeP == null) {
      homeP = 0.5;
      flags.push("NO DATA");
    }
    let lock = locks[game.id];
    if (lock && !available.has(lock.points)) {
      errors.push(`${lock.team} lock at ${lock.points} conflicts or is out of range; unlocked`);
      lock = null;
    }
    const target = lock ? null : plan[game.id];
    const chosen = lock?.team ?? target?.team ?? forced[game.id] ?? (homeP >= 0.5 ? game.home.abbr : game.away.abbr);
    const isHome = chosen === game.home.abbr;
    const side = (p) => (p == null ? null : isHome ? p : 1 - p);
    const winProb = side(homeP);

    if (Math.max(winProb, 1 - winProb) < COIN_FLIP) flags.push("coin flip");
    if (market != null && model != null) {
      if ((market - 0.5) * (model - 0.5) < 0) flags.push("FPI picks other side");
      else if (Math.abs(market - model) >= DISAGREE_GAP) flags.push("FPI disagrees");
    }
    if (override != null) flags.push("override");
    if (!lock && forced[game.id] && winProb < 0.5) flags.push("upset pick");
    else if (target && winProb < 0.5) flags.push("contrarian");

    const pick = {
      game,
      team: isHome ? game.home : game.away,
      opp: isHome ? game.away : game.home,
      isHome,
      winProb,
      marketProb: side(market),
      modelProb: side(model),
      points: 0,
      locked: Boolean(lock),
      forced: Boolean(forced[game.id]),
      flags,
    };
    if (lock) {
      available.delete(lock.points);
      pick.points = lock.points;
    } else {
      if (game.started && !game.completed) flags.push("already started");
      (target ? planned : open).push([pick, target]);
    }
    picks.push(pick);
  }

  // Planned points go after every lock has claimed its value.
  for (const [pick, target] of planned) {
    if (available.has(target.points)) {
      available.delete(target.points);
      pick.points = target.points;
    } else open.push([pick]);
  }

  const points = [...available].sort((a, b) => b - a);
  if (points.length < open.length) errors.push(`not enough point values for ${open.length} games`);
  open
    .map(([pick]) => pick)
    .sort((a, b) => b.winProb - a.winProb)
    .forEach((pick, i) => (pick.points = points[i] ?? 0));

  return { picks: picks.sort((a, b) => b.points - a.points), errors };
}

/** Exact probability of each total score (index = points). */
export function distribution(picks) {
  let dist = [1];
  for (const p of picks) {
    const next = new Array(dist.length + p.points).fill(0);
    dist.forEach((prob, s) => {
      if (!prob) return;
      next[s + p.points] += prob * p.winProb;
      next[s] += prob * (1 - p.winProb);
    });
    dist = next;
  }
  return dist;
}

export function summarize(picks) {
  const dist = distribution(picks);
  const mean = dist.reduce((a, p, s) => a + s * p, 0);
  const sd = Math.sqrt(dist.reduce((a, p, s) => a + (s - mean) ** 2 * p, 0));
  const pct = (q) => {
    let acc = 0;
    for (let s = 0; s < dist.length; s++) if ((acc += dist[s]) >= q) return s;
    return dist.length - 1;
  };
  const decided = picks.filter((p) => p.game.completed && p.game.winner);
  const actual = decided.length
    ? decided.reduce((a, p) => a + ((p.game.winner === "home") === p.isHome ? p.points : 0), 0)
    : null;
  const pctAtLeast = actual == null ? null : dist.slice(actual).reduce((a, p) => a + p, 0);
  return {
    dist,
    max: picks.reduce((a, p) => a + p.points, 0),
    expected: mean,
    sd,
    p10: pct(0.1),
    p50: pct(0.5),
    p90: pct(0.9),
    expectedWins: picks.reduce((a, p) => a + p.winProb, 0),
    actual,
    decided: decided.length,
    correct: decided.filter((p) => (p.game.winner === "home") === p.isHome).length,
    pctAtLeast,
  };
}
