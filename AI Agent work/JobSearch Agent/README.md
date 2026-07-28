# Job Search Agent (n8n)

Two scheduled n8n workflows that pull job listings, score them against an uploaded CV
with Claude, store them in Notion, and email you digests.

- **Daily** — fetch, drop anything already in Notion, score the rest, email only
  what is new.
- **Weekly** — Monday round-up of everything stored in the last 7 days.

Notion is both the store and the memory: the daily run queries it *before*
scoring, which is what makes "only new jobs" work without any separate state.

---

## Sources

| Source | Access | Notes |
|--------|--------|-------|
| Reed | Official free API | Basic auth, API key as username |
| Adzuna | Official free API | app_id + app_key as query params |

LinkedIn and Welcome to the Jungle are deliberately not included. LinkedIn
actively blocks automated access and bans accounts that scrape it; WTTJ has no
public API. Both would need a paid scraping service (Apify, Bright Data) to do
safely. Worth adding later once the pipeline works, as a deliberate second step.

---

## Setup

### 1. Start n8n

```powershell
cd "AI Agent work\Jobsearch Agent"
docker compose up -d
```

Open http://localhost:5678 and create the owner account (local only, stays on
your machine).

### 2. Get API keys

| Key | Where |
|-----|-------|
| `REED_API_KEY` | https://www.reed.co.uk/developers/jobseeker |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | https://developer.adzuna.com/ |
| `NOTION_TOKEN` | https://www.notion.so/my-integrations → new internal integration |
| `NOTION_DATABASE_ID` | From your Notion DB URL (the 32-char id before `?v=`) |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com/ |
| `RESEND_API_KEY` | https://resend.com/api-keys |

```powershell
Copy-Item .env.example .env
notepad .env
docker compose up -d
```

Use `up -d`, not `restart`. A plain `restart` restarts the existing container
process but does **not** re-read `env_file` from disk — so a key you just
added stays invisible to n8n and you get a confusing "invalid API key" from a
value that looks correct in `.env`. Same applies to any change to
`docker-compose.yml` itself.

### 3. Create the Notion database

Make a new database with **exactly** these property names — the workflows write
to them by name, so a typo means a silent failure:

| Property | Type |
|----------|------|
| Title | Title |
| Company | Text |
| External ID | Text |
| Source | Select |
| Location | Text |
| URL | URL |
| Score | Number |
| Salary Band | Select |
| Salary Min | Number |
| Salary Max | Number |
| Why | Text |

Then **share the database with your integration**: open the DB → `···` →
*Connections* → add the integration you created. Skipping this is the single
most common reason Notion writes fail with a 404.

### 4. Add your CV

Save it as plain text at `cv/cv.txt`. It is gitignored.

```powershell
# if your CV is a PDF/docx, copy the text out into cv.txt
notepad cv\cv.txt
```

### 5. Import the workflows

In n8n: **Workflows → ⋯ → Import from File**, once per file in `workflows/`.

The files in `workflows/` are the source of truth — each carries a fixed `id`,
so re-importing updates the existing workflow in place rather than creating a
duplicate. If you edit a workflow in the n8n UI instead, export it back over
the file (`n8n export:workflow --id=<id> --output=...`) and commit, or the
repo and the running instance silently drift apart.

### 6. Credentials inside n8n

One thing can't come from `.env` and must be set in the n8n UI:

- **Reed** — on the *Reed API* node, create a Basic Auth credential:
  username = your Reed API key, password = leave blank.

Email goes through [Resend](https://resend.com/api-keys) via a plain HTTP
request (`RESEND_API_KEY` in `.env`) rather than SMTP — both Gmail and
Outlook now block basic-auth SMTP logins (app passwords included) on most
accounts, which makes the standard n8n Email node a dead end for personal
use. Resend's free tier needs no domain verification, but its default sender
(`onboarding@resend.dev`) can only deliver to the email address your Resend
account is registered under — so `DIGEST_EMAIL_TO` must be that same address.

### 7. Test before scheduling

Open the daily workflow and click **Execute Workflow** to run it once manually.
Check each node's output as it goes. When it looks right, toggle the workflow
**Active** — only then does the schedule start firing.

---

## Tuning what it looks for

Everything tunable is in the **Search Criteria** node at the top of the daily
workflow — search terms, location, and the two salary bands. Nothing downstream
hard-codes them, so that node is the only place to edit.

Scoring bands:
- `Target (100k+)` — gets a +5 ranking bonus
- `Viable (80-100k)` — surfaced, no bonus
- `Below floor` / `Unknown` — stored but ranked last

The bonus is deliberately small: a strong match at 95k should still outrank a
weak one at 120k. If that is the wrong trade-off for you, it's one number in
the *Rank and band* node.

Both emails show at most 20 roles (`MAX_IN_EMAIL` at the top of the *Build
digest* / *Build weekly digest* nodes), with a "N more in Notion" footer when
there are more. The cap is presentation only — every scored job is still
written to Notion, which stays the full record.

---

## How the daily "only new" logic works

```
Reed + Adzuna  →  normalise to one schema  →  collapse same job across sources
                                                        ↓
                        query Notion for everything already stored (paginated)
                                                        ↓
                drop any job matching a stored External ID OR title+company   ← the dedupe
                                                        ↓
                score survivors against CV (one batched Claude call)
                                                        ↓
                        write to Notion  →  email digest
```

Two identity checks happen, not one:

- **`External ID`** (`reed-<jobId>` / `adzuna-<id>`) catches the same posting
  reappearing from the *same* source across runs.
- **A loose `title + company` key** catches the same real-world job posted on
  *both* Reed and Adzuna — they never share an ID for it, so exact-ID dedup
  alone would let it through twice, get scored (and billed) twice, and show
  up as two rows in Notion.

The Notion "already seen" query paginates through the whole database (Notion
caps a single request at 100 rows) rather than reading just the first page —
a single-page read silently stops seeing older rows once the DB passes 100
entries, which reintroduces duplicates as "new."

---

## Why these choices

- **Notion as the memory store, not a real database.** The daily run queries
  it *before* scoring specifically so "new jobs only" needs no separate state
  file — Notion already is the state. The cost is that every run does a full
  paginated scan of the whole table; fine at hundreds of rows, would want a
  smarter filter (e.g. only rows from the last N days) at much larger scale.
- **One batched scoring call, not one call per job.** Cheaper, and the model
  can rank jobs consistently against each other when it sees them together
  instead of scoring each in isolation.
- **Salary band is a small nudge, not the ranking.** A strong CV match at 95k
  outranks a mediocre one at 120k — the +5 bonus for hitting the target band
  can't overturn a real fit gap.
- **Haiku 4.5 for scoring, not Opus.** Started on Opus 5 for the strongest
  judgment; switched to Haiku to test whether a cheaper model holds up on
  this specific task (CV-fit reasoning, not just keyword matching). Worth
  re-evaluating with a side-by-side comparison if scoring quality seems off —
  see `Rank and band`'s diagnostic error reporting below, which was added
  specifically to make a bad model response visible instead of silently
  showing "Not scored."

---

## Known limits

- **Salary banding doesn't understand contract rates.** Reed's search results
  carry no permanent/contract flag at all, and Adzuna's `contract_type` field
  is optional and often blank — so a contract role's day rate (e.g. `500`)
  gets compared directly against the annual `salaryFloor`/`salaryTarget`
  thresholds and lands in "Below floor" regardless of what the annualised
  rate would actually be. A real fix needs a heuristic (keyword detection in
  the title/description plus a sanity check on the salary figures) rather
  than a clean field lookup.
- **Cross-source dedup is a fuzzy match, not a guarantee.** It keys on
  lowercased `title + company`, so the same job with meaningfully different
  title wording between the two boards (e.g. "Sr. AI PM" vs "Senior AI
  Product Manager") won't be caught and can still appear as two rows.
- The scoring call batches all new jobs into one prompt. If a day returns very
  many, that prompt may exceed the context limit — batching in chunks would fix it.
- Reed and Adzuna both return `results`, distinguished only by field shape;
  the normalise node relies on that.
- No retry on API failures — nodes use `neverError` so a bad response flows
  through as empty rather than killing the run.
