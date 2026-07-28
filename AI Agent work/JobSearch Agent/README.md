# Job Search Agent (n8n)

Two scheduled n8n workflows that pull job listings, score them against your CV
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

```powershell
Copy-Item .env.example .env
notepad .env
docker compose restart
```

Restart is required — n8n reads `.env` at boot.

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

### 6. Credentials inside n8n

Two things can't come from `.env` and must be set in the n8n UI:

- **Reed** — on the *Reed API* node, create a Basic Auth credential:
  username = your Reed API key, password = leave blank.
- **Email** — on the *Email digest* node, create an SMTP credential.
  For Gmail use an [app password](https://myaccount.google.com/apppasswords),
  not your normal password.

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

---

## How the daily "only new" logic works

```
Reed + Adzuna  →  normalise to one schema
                        ↓
        query Notion for everything already stored
                        ↓
        drop any job whose External ID is present   ← the dedupe
                        ↓
        score survivors against CV (one batched Claude call)
                        ↓
        write to Notion  →  email digest
```

The `External ID` is `reed-<jobId>` or `adzuna-<id>`, so the same posting from
one source is stable across runs. Note the Notion query is capped at 100 rows —
once the DB grows past that, this needs pagination or a filter on recent rows,
otherwise old jobs start reappearing as "new".

---

## Known limits

- Notion query returns max 100 rows without pagination (see above).
- The scoring call batches all new jobs into one prompt. If a day returns very
  many, that prompt may exceed the context limit — batching in chunks would fix it.
- Reed and Adzuna both return `results`, distinguished only by field shape;
  the normalise node relies on that.
- No retry on API failures — nodes use `neverError` so a bad response flows
  through as empty rather than killing the run.
