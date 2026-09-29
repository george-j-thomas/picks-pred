# picks-pred

A weekly pick optimizer for **NFL confidence pools**. You pick the straight-up winner of every game, give each game a unique confidence value from 1 to N, and score those points when your pick wins.

## Quick start

```bash
uv sync
uv run picks-pred                 # current or upcoming week
uv run picks-pred --week 5        # a specific week
```

Example output:

```
 Pts  Pick        vs   Win %  Market   FPI   Kickoff            Notes
  16  BAL         TEN  84.5%   84.7%  84.0%  Sun 10/04 10:00AM
  15  MIN         MIA  84.4%   84.7%  83.2%  Sun 10/04 1:05PM
  ...
  10  SF          DEN  62.5%   58.3%  77.2%  Sun 10/04 1:25PM   FPI disagrees
   3  CIN         JAX  54.8%   57.2%  45.2%  Sun 10/04 10:00AM  coin flip, FPI picks other side
Expected score: 94.0 / 136 (sd 16.9, 80% range 72-115)
```

## Web UI

The web app is a static frontend (`public/`) backed by two Python functions: `api/games.py` for games and odds, and `api/injuries.py` for the injury report. It has:

- a week selector
- team logos and colors
- a score-distribution chart
- a blend slider that sets the market-versus-FPI weighting
- a **Goal** switch: **Max points** or **Win the week** (see below)
- injury chips on each row. Click one for both teams' report.

Each row has three controls:

- **lock**: fix a pick at a given point value
- **flip**: take the underdog instead
- **tune**: override the win probability

Every change re-optimizes in the browser instantly and is saved per week in `localStorage`. **Copy picks** copies the list to your clipboard for your pool site.

Run it locally:

```bash
uv run picks-pred-web             # http://127.0.0.1:8765
```

### Deploy to Vercel (free Hobby plan)

1. On vercel.com, click **Add New… → Project** and import `george-j-thomas/picks-pred`.
2. Leave the framework preset as **Other** and leave the build command empty. `vercel.json` already serves `public/` and deploys each `api/*.py` file as a Python function.
3. Deploy. Every later push to `main` redeploys automatically.

**Odds API key:** open **Sources** in the UI and paste your key there. It is stored only in your browser and sent with each request in a header. You can instead set an `ODDS_API_KEY` environment variable in Vercel. If you do, anyone with the URL spends your quota.

Responses without a key are edge-cached for 2 minutes. For weeks already played, the app uses ESPN's closing lines and shows how the picks would have scored.

### Win the week (contrarian picks)

**Max points** is the best plan for season totals. It is also what most of your pool plays, so in a weekly contest you finish level with the chalk and rarely come out on top. **Win the week** asks a different question: which picks most often beat *every* other entry?

- Enter your pool size. The browser simulates thousands of weeks. Each opponent reads the same lines with some noise: a shared "public lean" plus their own read. A 60% favorite gets about 74% of the picks and a 70% favorite about 90%, which is close to real pick'em splits.
- A hill-climb search (in a Web Worker) swaps points and flips picks to maximize the chance of scoring highest outright. Ties split the prize.
- The plan is then checked on a fresh set of simulations. It is used only if it really does win more often than max points. Otherwise you keep the max-points picks.
- Upsets the search chose get a red **CONTRARIAN** tag. The hero panel shows your chance to win the week against the max-points plan, the expected points you give up, and the score that usually wins.

Example (week 4, 20 entries): the search puts **LV (33%) at 16**. You give up about 7 expected points, but your chance to win the week goes from about 6.6% to 10.5%. Larger pools push harder, and small pools (5 or fewer) usually keep the chalk. Locks and flips still apply. If you flip a contrarian pick back, the search re-plans around it.

### Injuries

Each row has a chip with each team's count of Out, Doubtful, Questionable and recently placed IR players (for example `PIT 3 · CLE 1`). A starting QB on the report also gets his own tag.

- The chip turns red when *your* pick has a key injury: a starter who is Out, Doubtful or on IR, or any QB starter listed.
- It turns amber when only the opponent has one.
- Click the chip to see both teams' report.

The data is ESPN's current league-wide injury report (`/api/injuries`, cached for 15 minutes). Betting lines already move on this news, so the report is for context and does not change the picks. The "starter" tag comes from ESPN depth charts, where injured players often drop down, so it is best-effort.

## How it works

1. **Schedule and odds** come from ESPN's public scoreboard API, which includes the DraftKings moneyline for every game. You don't need an API key for this.
2. **Win probabilities**
   - Moneylines are converted to implied probabilities and **de-vigged**, meaning the two sides are normalized to sum to 100% so the sportsbook's margin is removed.
   - If a game has a spread but no moneyline, the spread is converted with a normal model (σ ≈ 13.45 points).
   - **ESPN FPI**, ESPN's model-based game projection, is added as a second, independent signal.
3. **Blend.** Market probabilities are averaged across books, then combined with FPI in log-odds space. The default weights are 80% market and 20% FPI, because betting markets are generally the sharpest public predictor.
4. **Optimize.** Expected score is Σ points × P(win). By the rearrangement inequality, that sum is maximized by:
   - picking the favorite in every game, and
   - giving the highest points to the highest win probabilities.

   The expected score and 80% range come from the exact score distribution, not from a simulation.

### Notes column

| Flag | Meaning |
|---|---|
| `coin flip` | The favorite is under 55%. Few points are at stake, so don't sweat it. |
| `FPI disagrees` | FPI differs from the market by at least 10 points. Look for injury or other news. |
| `FPI picks other side` | FPI and the market favor different teams. |
| `already started - use --lock` | The game has kicked off. Lock in the pick you actually made. |
| `override` | The probability was set manually. |

## Weekly workflow

1. **Early in the week:** run `uv run picks-pred` to see the initial ranking.
2. **Before Thursday's game:** run it again, then submit at least the Thursday pick.
3. **Before Sunday:** lock the picks you already submitted so their points are reserved, and re-optimize the rest with updated lines:
   ```bash
   uv run picks-pred --lock PIT=4
   ```
4. **Late news, such as a QB ruled out:** override a team's probability:
   ```bash
   uv run picks-pred --override KC=0.62            # also accepts 62 or 62%
   uv run picks-pred --overrides-file overrides.csv  # rows of team,win_prob
   ```

## More sportsbooks (FanDuel, DraftKings, BetMGM, Caesars, ...)

For a multi-book consensus, get a free key from [The Odds API](https://the-odds-api.com). The free tier includes 500 requests per month, and each run uses one. Put the key in `.env`:

```bash
cp .env.example .env   # then set ODDS_API_KEY=...
uv run picks-pred                                  # all US books
uv run picks-pred --books fanduel,draftkings       # specific books
```

When the key is set, each book is de-vigged separately and the results are averaged. This replaces the ESPN/DraftKings line.

## Options

```
--season / --week / --postseason   choose the week (default: current or upcoming)
--market-weight / --fpi-weight     blend weights (default 0.8 / 0.2; --fpi-weight 0 = market only)
--no-fpi                           skip ESPN FPI lookups
--max-points N                     if your pool doesn't use N = number of games
--format table|markdown|csv|json   output format
-o FILE                            also save output (e.g. picks/2026-wk04.md)
```

## Strategy notes

- These picks **maximize expected points**, which is the right goal for season-long totals.
- If you're chasing a *weekly* prize in a large pool, use **Win the week** in the web UI. It simulates your pool and picks the upsets that most improve your odds of finishing first.
- Games are treated as independent, and ties are ignored.

## Development

```bash
uv run pytest
```

`public/optimize.js` mirrors `src/picks_pred/optimize.py`. The parity tests in `tests/test_web.py` require `node` and are skipped when it isn't installed.
