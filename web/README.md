# web

Next.js front end for [NFL QB Records](../README.md). See the root README for
what the project is and how the data gets here.

```bash
cp .env.example .env.local   # fill in from Supabase -> Project Settings -> API
npm install
npm run dev
```

Stat definitions in `lib/stats.generated.json` are exported from
`ingest/registry.py` -- edit the registry and rerun `python -m ingest.registry`
rather than editing the JSON.
