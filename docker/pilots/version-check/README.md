# Version-Check Docker Pilot

NON-PRODUCTION — NO SECRETS — NO DB — EXITS IMMEDIATELY

## Run
```bash
docker build -t tradeai-version-check docker/pilots/version-check/
docker run --rm tradeai-version-check
```

## Cleanup
```bash
docker rmi tradeai-version-check
```
