# Task Scheduler Setup — Trade AI v11

## What to schedule

There are 4 ready-to-run launcher files in the `launchers/` folder:

| File | Time (ET) | Purpose |
|---|---|---|
| `launchers\run_0400.bat` | 4:00 AM | Pre-market initial scan |
| `launchers\run_0700.bat` | 7:00 AM | Pre-market update — **main daily run** |
| `launchers\run_0900.bat` | 9:00 AM | Open prep — final pre-open view |
| `launchers\run_1000.bat` | 10:00 AM | First-hour momentum read |

Each `.bat` file:
- Activates the Python virtual environment automatically
- Runs `scripts\trade_ai_orchestrator.py` with the correct `--run-label`
- Writes a timestamped log to `logs\run_XXXX_YYYYMMDD.log`
- Handles errors gracefully (logs them, doesn't crash silently)

---

## Step-by-step: scheduling one task (repeat for each run window)

### Step 1 — Open Task Scheduler
Press `Win + S`, type **Task Scheduler**, press Enter.

### Step 2 — Create a new task
In the right panel, click **"Create Basic Task..."**

### Step 3 — Name the task
- Name: `Trade AI 0700`
- Description: `Trade AI v11 pre-market update run`
- Click **Next**

### Step 4 — Set the trigger
- Select **Daily**
- Click **Next**
- Start time: **7:00:00 AM**
- Recur every: **1** days
- Click **Next**

### Step 5 — Set the action
- Select **"Start a program"**
- Click **Next**

### Step 6 — Point to the launcher
- **Program/script:**
  ```
  C:\TradeAI\launchers\run_0700.bat
  ```
  *(use your actual project path)*

- **Add arguments:** *(leave blank — arguments are inside the .bat)*

- **Start in (optional):**
  ```
  C:\TradeAI
  ```
  *(your project root — same folder that contains the `scripts\` and `venv\` folders)*

- Click **Next**

### Step 7 — Finish
- Check **"Open the Properties dialog for this task when I click Finish"**
- Click **Finish**

### Step 8 — Set to run only on weekdays
In the Properties dialog that opens:
- Click the **Triggers** tab → **Edit**
- Under "Advanced settings" check **"Stop task if it runs longer than"**: `1 hour`
- Go to the **Conditions** tab — no changes needed
- Go back to **Triggers** → Edit → under "Advanced settings":
  - Check **"Repeat task every"** — leave blank (only run once per day)
- To limit to weekdays: in the trigger, change **Recur every 1 days** and under the weekly view check only Mon–Fri

> **Easiest weekdays-only method:** Use **"Weekly"** trigger instead of Daily. Set it to run every week on Monday, Tuesday, Wednesday, Thursday, Friday at the target time.

### Step 9 — Repeat for the other 3 runs
Repeat Steps 2–8 for `run_0400.bat` (4:00 AM), `run_0900.bat` (9:00 AM), and `run_1000.bat` (10:00 AM).

---

## Verifying the setup

After creating all 4 tasks, right-click each one and select **"Run"** to test manually.

Then check:
```
logs\run_0700_YYYYMMDD.log
```

A successful run ends with:
```
✅  Pipeline complete  |  2025-01-15 0700
📁  Output: reports\2025-01-15\0700
```

If you see `[ERROR] venv not found`, run `assets\setup_local_project.bat` first.

---

## Running manually anytime

From your project root, double-click any `.bat` file in the `launchers\` folder.
Or from a command prompt:

```cmd
cd C:\TradeAI
launchers\run_0700.bat
```

To test without alerts or LLM cost:
```cmd
cd C:\TradeAI
call venv\Scripts\activate
python scripts\trade_ai_orchestrator.py --run-label 0700 --no-alerts --no-llm --skip-market-check
```

---

## Log files

Logs are written to `logs\` automatically:
```
logs\
  run_0400_20250115.log
  run_0700_20250115.log
  run_0900_20250115.log
  run_1000_20250115.log
```

Each log contains the full console output of the pipeline including all ✅/❌ stage results.
