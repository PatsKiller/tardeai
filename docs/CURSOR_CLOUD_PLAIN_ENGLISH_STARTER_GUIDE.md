# Cursor Cloud Plain-English Starter Guide

Status:      ACTIVE
as_of:       2026-07-30T10:50:09-04:00
Measured at: efcc51365 / not measured

**Project:** Trade AI (`PatsKiller/tardeai`)  
**Audience:** A new Cursor user setting up the repository for the first time  
**Last reviewed:** 2026-07-30

---

## 1. Where you are right now

Cursor has already completed the main setup work for this repository.

It has:

- connected to the Trade AI GitHub repository;
- created a temporary Linux development computer in Cursor Cloud;
- installed the Python and Command Center v3 dependencies;
- tested the backend and frontend in a safe development mode;
- created a separate Git branch named `cursor/dev-environment-setup-7c8c`;
- opened draft pull request **#256**;
- proposed an `AGENTS.md` file containing instructions for future coding agents.

This has **not** deployed Trade AI. It has **not** changed the production server. It has **not** merged anything into `main`.

The work currently exists only as a proposed change on a separate branch.

---

## 2. What the screen is showing

### The repository

The repository listed on the left is `tardeai`. This is the GitHub project Cursor is working with.

### Development environment setup

This is the setup run that prepared the Cursor Cloud computer. The long initial run installed packages and checked that the application could run.

### The branch

The branch shown near the top is:

```text
cursor/dev-environment-setup-7c8c
```

A branch is a safe line of proposed changes. It is not another complete manual copy of the project, and it does not change `main` until a pull request is deliberately merged.

### PR #256

The **View PR** button opens draft pull request #256 on GitHub. A pull request is the review page where you can inspect the proposed changes before merging them.

### Changes

The Changes panel shows files added or edited on this branch. At the end of the setup run it showed one new file, `AGENTS.md`.

### Commit & Push

This button saves reviewed file changes to the current branch on GitHub. It does **not** merge the branch into `main`, and it does **not** deploy the application.

### Save Environment

This is separate from Git.

Saving the environment asks Cursor to make a reusable snapshot of the prepared cloud computer. The purpose is to avoid reinstalling every dependency for every future cloud-agent session.

The Git branch and pull request can exist successfully even when the environment snapshot is having a problem.

---

## 3. What `AGENTS.md` is

`AGENTS.md` is an instruction sheet for automated coding agents such as Cursor and Codex.

It is not application code. It does not start a service, place an order, change a database, or deploy anything.

It tells future agents practical things such as:

- how to start the backend;
- how to start the Command Center v3 frontend;
- which tests are safe to run;
- which files require a server restart after editing;
- which unusual application behavior is expected rather than a crash;
- which safety boundaries must not be crossed.

The full human documentation remains in files such as `README.txt`, `ARCHITECTURE.md`, `OPERATIONS.md`, and the `docs/` directory. `AGENTS.md` should contain only concise, durable instructions that help coding agents work safely.

---

## 4. What Cursor installed

### Python environment

Cursor created a Python virtual environment at:

```text
.venv
```

It installed the repository's Python requirements and `pytest` for testing.

### Command Center v3 packages

Cursor installed the JavaScript packages under:

```text
apps/command-center-v3
```

These packages support the Vite development server, TypeScript checks, and the frontend build.

### Backend development command

Inside Cursor Cloud, the development backend can be started with:

```bash
.venv/bin/python scripts/portfolio_server.py
```

It listens on port `7777` inside the cloud environment.

### Frontend development command

From `apps/command-center-v3`, the development frontend can be started with:

```bash
npm run dev
```

It listens on port `7789` inside the cloud environment and proxies API requests to the backend.

### Safe JSON-only mode

Most development and testing can run without the live PostgreSQL database. In JSON-only mode, Cursor can use synthetic test data inside its isolated environment.

Cursor Cloud should not receive:

- the production `.env` file;
- production database credentials;
- Bitwarden production tokens;
- broker credentials;
- TOTP or 2FA secrets;
- Telegram production tokens;
- real portfolio files;
- live-trading credentials.

Use non-secret test settings and synthetic data only.

---

## 5. Is an environment save running overnight normal?

**No. An environment save remaining on “Preparing save form” or otherwise appearing active overnight is not normal.**

The first dependency installation can be slow for a large repository. A reusable environment snapshot may also take several minutes. It should not require an entire night.

Cursor has had known Cloud Agent environment-save problems, including stuck saves and server errors. Cursor's status page currently reports Cloud Agents as operational, although Cursor and model providers have had several resolved incidents during the last few days. That makes this look more like a stuck session or stale user interface than a normal long-running save.

The important point is that draft PR #256 and its Git commit already exist on GitHub. The stuck environment-save display does not mean the branch or pull request has been lost.

---

## 6. What to do about the stuck save

Follow these steps in order.

### Step 1 — Do not keep waiting overnight

After a practical waiting period of roughly 15–20 minutes with no visible progress, treat the save as stuck. This is operating guidance, not an official Cursor time guarantee.

### Step 2 — Confirm the Git work is safe

Open **View PR** and confirm draft PR #256 exists. Check the **Files changed** tab. The branch and committed files are stored on GitHub independently of the environment snapshot.

### Step 3 — Reload Cursor

Use the Command Palette:

```text
Ctrl+Shift+P
```

Run:

```text
Developer: Reload Window
```

You can also close and reopen Cursor. This should not delete a GitHub branch or pull request.

### Step 4 — Check the environment dashboard

Open Cursor's Cloud Agents dashboard and look under **Environments** for the Trade AI repository.

- If an active environment is listed, the spinner in the desktop window was probably stale.
- If no saved environment is listed, the snapshot did not complete.
- If duplicate environments are listed, do not keep creating more. Duplicate or stale entries have been associated with save and startup problems.

### Step 5 — Retry once

Retry the environment save once from the Cloud Agents web dashboard. For an individual Pro account, use a personal environment unless you deliberately need a shared team environment.

Do not repeatedly click Save. Each retry can create another pending operation or duplicate environment entry.

### Step 6 — Stop if it hangs or returns an error

If it hangs again or returns an error such as `500` or `504`, record:

- the full error message;
- the Cursor cloud-agent run ID;
- whether the save was Personal or Team;
- the repository name;
- the time of the failure;
- any request or correlation ID shown in the application or browser developer tools.

Then report it through Cursor support or the Cursor community bug-report channel.

### Step 7 — Use declarative setup later if snapshots remain unreliable

A more repeatable option is to store a versioned `.cursor/environment.json` in the repository, optionally with a `.cursor/Dockerfile`. This tells Cursor how to build the environment from code rather than relying only on a saved live snapshot.

That is the more durable long-term setup, but it is not necessary for your first beginner session. Do not add it until the current setup instructions have been reviewed and the required commands are understood.

---

## 7. Review before merging PR #256

Before merging, confirm the pull request contains only expected documentation and setup files.

Pay particular attention to two safety points in `AGENTS.md`:

1. It must clearly say that Cursor Cloud never receives the production `.env` or production secrets.
2. It should describe synthetic holdings requirements without including unnecessary real portfolio values or copying production holdings into the cloud environment.

A safe pull request at this stage should not modify:

- broker adapters;
- order handling;
- live-trading authorization;
- portfolio state;
- production configuration;
- database migrations;
- cron;
- systemd services;
- feature flags;
- secrets.

---

## 8. Your first real Cursor task

After the environment issue is resolved, begin with a read-only repository tour.

Paste this into a new Cursor Agent conversation:

```text
Read AGENTS.md and the important repository documentation.

Do not edit files.
Do not run commands yet.

Explain this repository to me as a new operator:

1. What are the major folders?
2. How is Command Center v3 started?
3. How are tests run?
4. Which files are most important?
5. What are the five most important rules I must not violate?
```

Then ask Cursor to plan one small documentation or test task. Do not begin with broker code, live trading, secrets, database writes, cron, systemd, production state, or feature flags.

---

## 9. The simple mental model

```text
Cursor Cloud environment
    = an isolated temporary development computer

Saved environment
    = a reusable snapshot of that computer

Git branch
    = an isolated line of proposed file changes

Pull request
    = the GitHub review page for those changes

Commit & Push
    = save reviewed changes to the branch

Merge
    = deliberately copy approved branch changes into main

Deploy
    = a separate production action that is not happening here
```

---

## 10. One rule for Cursor and Codex together

Never allow Cursor and Codex to write to the same branch at the same time.

For example:

```text
Codex staged implementation:
feat/active-trader-next

Cursor setup and beginner work:
cursor/dev-environment-setup-7c8c
cursor/<one-small-task>
```

One task should have one writing tool and one branch. Other tools may review the work read-only.

---

## Sources checked

This guide was written from:

- the actual state of Trade AI draft pull request #256;
- the Cursor screen captured during the environment setup;
- Cursor Cloud Agent documentation;
- Cursor's public status page on 2026-07-30;
- recent Cursor community support reports about stuck or failed environment saves.
