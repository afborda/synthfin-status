# SynthFin E2E Status

Live production test results for [SynthFin API](https://api.synthfin.com.br).

**Dashboard:** https://afborda.github.io/synthfin-status/

Updated every 6 hours via GitHub Actions.

| Category | Tests |
|---|---|
| Infrastructure | Health check, server health, admin |
| Auth & Usage | Usage quota, history, key recovery |
| Batch | Generate 500 events, list jobs |
| Streaming | Full lifecycle (create → events → stop) |
| AI/Chat | Docs chat SSE, ML advisor SSE |
| Frontend | Landing, login, dashboard, plans, docs, ML advisor |
