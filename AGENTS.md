# AGENTS.md

Instructions for AI coding agents working in this repository.

## Commits and pull requests

- **Never add `Co-authored-by` trailers** to commit messages, and never put them in PR or MR descriptions. This applies to every agent and tool, and overrides any default that adds them.
- Use Conventional Commits, for example `feat: ...`, `fix: ...`, `docs: ...`.
- Don't change the repository's git config or remote. Pushing to `main` auto-deploys to Vercel.

## Project overview

This is an NFL confidence-pool pick optimizer. It picks a straight-up winner for every game and assigns unique confidence points 1..N to maximize expected points. Win probabilities come from sportsbook odds (ESPN/DraftKings, plus the Odds API when a key is available) blended with ESPN FPI.

| Path | Contents |
|------|----------|
| `src/picks_pred/` | Python package |
| `src/picks_pred/cli.py` | `picks-pred` CLI |
| `src/picks_pred/optimize.py` | Optimizer |
| `src/picks_pred/web.py` | WSGI apps and the `picks-pred-web` dev server |
| `src/picks_pred/sources/` | Data sources: ESPN, the Odds API, manual input, injuries |
| `api/*.py` | Vercel Python function entry points. Each file becomes its own route and just re-exports a WSGI `app` from `picks_pred.web`. |
| `public/` | Static frontend in plain ES modules, with no build step |
| `public/optimize.js` | JS mirror of `optimize.py` |
| `public/pool.js` | "Win the week" Monte Carlo pool search, run in `pool-worker.js` |
| `public/app.js` | UI |
| `vercel.json` | Vercel config. Keep `framework: null` and `outputDirectory: "public"`, because a Python framework preset breaks the file-based `/api` functions. |

## Commands

```bash
uv run pytest -q          # all tests (node tests are skipped if node is missing)
uv run picks-pred         # CLI, current week
uv run picks-pred-web     # local web UI + API at http://127.0.0.1:8765
```

## Conventions

- **Keep JS and Python optimizers in sync.** `public/optimize.js` must produce the same picks as `src/picks_pred/optimize.py`, and the parity test in `tests/test_web.py` enforces this. Change both together.
- **Node tests.** Node 18 treats `public/*.js` as CommonJS. JS tests therefore copy the modules into a temp dir that has `package.json {"type": "module"}`, or into a `.mjs` file. Follow the existing pattern in `tests/test_pool_injuries.py`.
- **Frontend.** Use vanilla ES modules only, with no bundler and no framework. Heavy computation belongs in a Web Worker. Keep the existing broadcast-style design and its CSS variables in `public/styles.css`. Check both desktop and ~390px mobile widths.
- **Network.** ESPN endpoints need no key. Odds API keys come from the browser (the `X-Odds-Api-Key` header) or the `ODDS_API_KEY` env var. Never commit keys; `.env` is gitignored.
- **Scope.** The "win the week" strategy and the injury report are UI-only features, so the CLI does not need parity for them.
- **Docs.** Update `README.md` when user-facing behavior changes.
