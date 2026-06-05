#!/usr/bin/env python3
"""Phase 204H — backup-cadence output diff (READ-ONLY). Verifies the backup cadence produced its
expected artifacts: a fresh, reasonably-sized DB dump + a successful encrypted secrets-env upload.
Exits 0 on PASS."""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
def newest(dirp, suf):
    if not os.path.isdir(dirp): return None
    fs=[os.path.join(dirp,f) for f in os.listdir(dirp) if f.endswith(suf)]
    return max(fs,key=os.path.getmtime) if fs else None
def main():
    bad=[]; ok=[]
    # 1. DB backup
    p=newest(os.path.join(HOME,"db_backups"),".sql.gz")
    if not p: bad.append(("db_backup","no .sql.gz found"))
    else:
        sz=os.path.getsize(p); age=(time.time()-os.path.getmtime(p))/3600
        if sz<100_000_000: bad.append(("db_backup",f"too small {sz}B (<100MB)"))
        elif age>26: bad.append(("db_backup",f"stale {age:.1f}h"))
        else: ok.append(("db_backup",f"{sz//1_000_000}MB fresh {age:.2f}h: {os.path.basename(p)}"))
    # 2. backup cadence summary: pg + secrets-env ok (secrets-data is weekly cadence, not here)
    sp=os.path.join(ROOT,"data/runtime/portfolio_maintenance_backup_last_run.json")
    if not os.path.exists(sp): bad.append(("summary","no backup cadence apply summary"))
    elif json.load(open(sp)).get("dry_run") is True:
        bad.append(("summary","latest summary is a DRY_RUN, not an --apply (re-run --cadence backup --apply)"))
    else:
        d=json.load(open(sp)); st={s["name"]:s["status"] for s in d["steps"]}
        for step in ("portfolio_backup","secrets_backup_env"):
            if st.get(step)=="ok": ok.append((step,"ok"))
            else: bad.append((step,f"status={st.get(step,'MISSING')}"))
        for x in ("price_cache","db_retention"):
            (ok if st.get(x)=="EXCLUDED_NOT_RUN" else bad).append((f"excluded:{x}", st.get(x,"?")))
    v="PASS" if not bad else "FAIL"
    print(f"BACKUP CADENCE OUTPUT DIFF: {v} ({len(bad)} unacceptable)")
    for k,m in ok: print(f"  OK   {k}: {m}")
    for k,m in bad: print(f"  FAIL {k}: {m}")
    return 0 if v=="PASS" else 1
if __name__=="__main__": sys.exit(main())
