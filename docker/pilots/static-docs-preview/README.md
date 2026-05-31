# Static Docs Preview — Docker Pilot

DRAFT ONLY — NON-PRODUCTION — NO SECRETS — OPERATOR APPROVAL REQUIRED

## Run
```bash
cd docker/pilots/static-docs-preview
docker build -t tradeai-docs-preview .
docker run -d --name docs-preview -p 8888:80 tradeai-docs-preview
```

## Stop/Remove
```bash
docker stop docs-preview && docker rm docs-preview
docker rmi tradeai-docs-preview
```

## Safety
- No secrets
- No DB credentials
- No .env mounted
- No production service
- Port 8888 only
