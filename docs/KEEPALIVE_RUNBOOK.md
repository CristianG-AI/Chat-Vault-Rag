# VaultChat Keep-Alive Runbook

**What this is:** the robust *free-tier* fix for the demo
(`https://chat-vault-demo.streamlit.app`) going to sleep on Streamlit Community
Cloud. It replaces the old HTTP-ping keep-alive with a GitHub Action that drives
a **real headless browser** and clicks the wake button.

**What this is NOT:** a guarantee the app never sleeps. It is a strong,
zero-cost mitigation that self-heals a sleeping app within roughly one cron
interval — not an ironclad "never again." The only way to *never* sleep is a
host that doesn't sleep, and those cost money (see [Escalation](#5-escalation--truly-never-sleep-costs-money)).

Companion doc: `docs/RELAUNCH_RUNBOOK.md` covers the *boot-failure* path
(missing `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `DEMO_MODE` Secrets). This
runbook only covers the *inactivity-sleep* path. Both can be true at once —
keep-alive is useless if the app also crashes on boot, so clear the relaunch
runbook's Secrets checks first.

---

## 1. The root cause (why the ping never worked)

A plain HTTP `GET` against a **sleeping** Community Cloud app returns the
"Zzzz — this app has gone to sleep" HTML page (HTTP 200) and stops there. Waking
the app requires a human-style **click** on the **"Yes, get this app back up!"**
button — a plain request never clicks it.

So the two behaviours are different:

- **A ping keeps an already-*awake* app warm.** Fine as far as it goes, but it
  cannot recover a slept app.
- **Only a real browser click *wakes* a slept app.** That's what this workflow
  does.

That's why the previous `curl` cron and the UptimeRobot HTTP monitor kept
"succeeding" (200 responses) while the demo sat asleep — they were pinging the
sleep page itself.

---

## 2. The fix that's now staged

`.github/workflows/keepalive.yml` — a GitHub Action that, on a schedule and
on-demand:

1. Spins up `ubuntu-latest`, installs **Playwright** + **headless Chromium**
   (`actions/setup-python@v5`, Python 3.12).
2. Navigates to the app URL and waits for the page to settle.
3. Looks for the wake button **by its text** (`"get this app back up"`, falling
   back to `"back up"`). If found, it **clicks** it and waits ~30s for boot.
4. Confirms the real app actually rendered by waiting for
   `[data-testid='stAppViewContainer']` (falling back to `.stApp`).
5. Logs a clear `STATUS: SUCCESS` / `STATUS: WARNING` line and exits `0`.

**Schedule:** `cron: "*/12 * * * *"` (every 12 minutes) plus a
`workflow_dispatch` manual trigger. It exits `0` even when it can't confirm a
render, on purpose: the next run retries in ~12 minutes and a transient CI/network
blip shouldn't spam you with failure emails. **Read the run logs**, not just the
green check, to see whether a given run woke the app or found it already awake.

This upgrades the keep-alive described in `RELAUNCH_RUNBOOK.md` §2 (which was the
plain `curl` ping). The browser-click version supersedes it.

---

## 3. Caveats (read these — they're the honest limits)

- **GitHub disables scheduled workflows after 60 days of repository inactivity.**
  If nobody pushes a commit to the repo for ~60 days, GitHub automatically
  **stops the schedule** (it emails the repo admin first). The keep-alive then
  silently stops running and the app can sleep again. Fix: commit *something*
  occasionally, or re-enable the workflow from the **Actions** tab when
  prompted. This is the single most likely way this quietly breaks.
- **Cron timing is best-effort, not exact.** GitHub's scheduler runs in UTC and
  can be delayed several minutes (sometimes more) under platform load. `*/12`
  means "about every 12 minutes," not "precisely." There can be a window where
  the app is asleep between a sleep event and the next successful wake — a
  visitor who lands in that gap sees the sleep screen until the next run (or
  their own click) wakes it.
- **The selector depends on Streamlit's button text.** Detection keys off the
  wake button reading **"Yes, get this app back up!"**. If Streamlit changes that
  copy, the `WAKE_BUTTON_TEXTS` list near the top of the embedded script in
  `keepalive.yml` needs updating. Symptom: runs go green but log
  `No wake button found` while the app is visibly asleep.
- **Free-tier resource limits still apply.** Keep-alive addresses *inactivity*
  sleep, not a resource ceiling under a real concurrent-traffic spike. Under
  load, the durable answer is a non-sleeping host (see below).

---

## 4. UptimeRobot

You can leave the existing UptimeRobot HTTP monitor on — it's a useful
"is the URL reachable / is it up" signal and costs nothing. **But it is not
sufficient on its own**: like the old `curl` ping, an HTTP monitor gets a 200
from the sleep page and cannot click the wake button. Treat UptimeRobot as
monitoring, and this workflow as the actual wake mechanism.

---

## 5. Escalation — truly never-sleep costs money

If "usually awake within ~12 minutes" isn't good enough (e.g. a launch push
where a first-time visitor must never hit a sleep screen), the only real fix is
a host that doesn't sleep. These are the escalation options, all paid:

- **Streamlit paid** — a paid Streamlit tier removes the Community Cloud
  inactivity sleep.
- **Render** — deploy the app as a web service on a paid (non-free) instance
  that stays running.
- **Fly.io** — run it on an always-on machine (paid; free allowances don't
  guarantee always-on).
- **Hugging Face Spaces upgrade** — an upgraded (paid) Space avoids the free
  Space sleep behaviour.

Pick one only if the free keep-alive's residual gap is unacceptable for your
use case. For a demo, the free path here is usually enough.

---

## 6. Deploy steps (Cristian)

Committing, pushing, and enabling Actions are your actions — the files are only
**staged** locally. To activate:

> **Repo target — confirm first.** This local clone's remote is
> **`CristianG-AI/Chat-Vault-Rag`** (per `git remote -v` and
> `RELAUNCH_RUNBOOK.md`). If your live GitHub repo is actually
> `CristianG-AI/Chat-Vault-Rag`, push there instead — deploy to **whichever repo
> Streamlit Cloud actually deploys the demo from**, otherwise the Action runs
> against a repo that isn't serving the app.

1. **Commit both staged files** to your Chat-Vault-Rag repo:
   - `.github/workflows/keepalive.yml`
   - `docs/KEEPALIVE_RUNBOOK.md`

   ```bash
   git add .github/workflows/keepalive.yml docs/KEEPALIVE_RUNBOOK.md
   git commit -m "keepalive: wake sleeping Streamlit demo via Playwright browser click"
   git push
   ```

2. **Enable Actions.** On GitHub → the repo → **Actions** tab. If prompted
   ("Workflows aren't being run on this repository"), click **I understand my
   workflows, go ahead and enable them**. Scheduled workflows only run once the
   workflow file is on the repo's **default branch**.

3. **Run it once manually.** Actions → **keepalive** (left sidebar) →
   **Run workflow** → **Run workflow** (this is the `workflow_dispatch`
   trigger). Wait for the run to go green.

4. **Verify it actually woke the app.**
   - First, force the app to sleep or catch it asleep (open
     `https://chat-vault-demo.streamlit.app` and confirm the "Zzzz" screen),
     then trigger the workflow.
   - Open the run → the **"Wake the app if it is asleep"** step logs. You want
     `App is asleep - wake button matched ...` followed by
     `Confirmed app rendered ...` and `STATUS: SUCCESS`.
   - Reload the app URL in a browser and confirm the real **💬 VaultChat** UI
     loads (cross-check against `RELAUNCH_RUNBOOK.md` §3 if in doubt).

Once that's confirmed, the schedule takes over every ~12 minutes. Re-read
[Caveats](#3-caveats--read-these--theyre-the-honest-limits) so you know how this
can quietly stop (the 60-day inactivity disable is the big one).
