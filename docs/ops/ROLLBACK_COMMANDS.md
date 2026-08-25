# CURRENT rollback (exact-main phase2)

Do not run unless operator-authorized.

```bash
# Status
bash scripts/cio_phase2_exact_main_deploy.sh status

# Rollback to PREV recorded in ~/.local/state/cio-phase2-exact-main/state.env
bash scripts/cio_phase2_exact_main_deploy.sh rollback

# Verify
readlink -f /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
cat /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/SOURCE_COMMIT
curl -fsS http://localhost:7777/api/v2/health
```

R13 did not promote CURRENT. PRE_DEPLOY_SHA remains `1afb1479676aeb67b64791e58e946753a2854ddf`.
