# picks-pred

A weekly pick optimizer for **NFL confidence pools**, hosted on Vercel at **[picks-pred.com](https://picks-pred.com)**. You pick the straight-up winner of every game, give each game a unique confidence value from 1 to N, and score those points when your pick wins.

Open [picks-pred.com](https://picks-pred.com), choose the week, and it ranks every game from live betting lines. Nothing needs to be installed.

## Using the app

- **Week selector:** jump to any regular-season or playoff week. Past weeks use ESPN's closing lines and show how the picks would have scored.
- **Blend slider:** the weighting between the betting market and ESPN FPI (default 80 / 20).
- **Goal:** **Max points** or **Win the week** (see below).
- **Refresh lines:** reload the latest odds.
- **Copy picks:** copy the list to your clipboard for your pool site.

Each game row has three controls:

- **Lock:** fix a pick at a given point value. Use this once a pick is submitted, so its points stay reserved while the rest re-optimize.
- **Flip:** take the other team.
- **Tune:** override the win probability, for example after late news such as a QB being ruled out.

Every change re-optimizes instantly and is saved per week in your browser.

### Weekly routine

1. Early in the week, check the initial ranking.
2. Before Thursday's game, refresh the lines and submit at least the Thursday pick. Then lock it.
3. Before Sunday, refresh again and submit the rest.

### Sources

Open **Sources** (top right) to configure data:

- DraftKings moneylines (via ESPN) and ESPN FPI are always on, with no key needed.
- **More sportsbooks:** paste a free [The Odds API](https://the-odds-api.com) key for a consensus across FanDuel, DraftKings, BetMGM, Caesars and more. The free tier includes 500 requests per month, and each refresh uses one. The key is stored only in your browser. You can pick specific books, or leave them all unselected to use every US book.
- **Pool rules:** set the highest point value if your pool doesn't use N = number of games.

### Row tags

| Tag | Meaning |
|---|---|
| `coin flip` | The favorite is under 55%. Few points are at stake, so don't sweat it. |
| `FPI disagrees` | FPI differs from the market by at least 10 points. Look for injury or other news. |
| `FPI picks other side` | FPI and the market favor different teams. |
| `already started` | The game has kicked off. Lock in the pick you actually made. |
| `override` | The probability was set manually. |
| `contrarian` | An upset chosen by **Win the week**. |

## Win the week (contrarian picks)

**Max points** is the best plan for season totals. It is also what most of your pool plays, so in a weekly contest you finish level with the chalk and rarely come out on top. **Win the week** asks a different question: which picks most often beat *every* other entry?

- Enter your pool size. The browser simulates thousands of weeks. Each opponent reads the same lines with some noise: a shared "public lean" plus their own read. A 60% favorite gets about 74% of the picks and a 70% favorite about 90%, which is close to real pick'em splits.
- A hill-climb search (in a Web Worker) swaps points and flips picks to maximize the chance of scoring highest outright. Ties split the prize.
- The plan is then checked on a fresh set of simulations. It is used only if it really does win more often than max points. Otherwise you keep the max-points picks.
- Upsets the search chose get a red **CONTRARIAN** tag. The top of the page shows your chance to win the week against the max-points plan, the expected points you give up, and the score that usually wins.

Example (week 4, 20 entries): the search puts **LV (33%) at 16**. You give up about 7 expected points, but your chance to win the week goes from about 6.6% to 10.5%. Larger pools push harder, and small pools (5 or fewer) usually keep the chalk. Locks and flips still apply. If you flip a contrarian pick back, the search re-plans around it.

## Injuries

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

## Hosting on Vercel

The site is a static frontend (`public/`) plus two small serverless API routes (`/api/games` and `/api/injuries`) that fetch and cache ESPN data. It runs on Vercel's free Hobby plan with the custom domain `picks-pred.com`, and every push to `main` redeploys automatically.

To set up a new deployment:

1. On vercel.com, click **Add New… → Project** and import this repository.
2. Leave the framework preset as **Other** and leave the build command empty. `vercel.json` handles the rest.
3. Deploy.

You can also set an `ODDS_API_KEY` environment variable in Vercel instead of pasting a key in the browser. If you do, anyone with the URL spends your quota.

## Development

```bash
uv sync
uv run picks-pred-web     # local copy of the site at http://127.0.0.1:8765
uv run pytest             # tests (the JS tests need node)
```

The backend is a small Python package in `src/picks_pred/`. It also exposes a `picks-pred` command-line version of the optimizer (`uv run picks-pred --help`).
