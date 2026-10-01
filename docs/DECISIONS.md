# Architecture decision records

Each decision uses the format below. ADRs are never renumbered; a later ADR supersedes an earlier one.

```markdown
## ADR-NNN — <decision>

- **Status:** proposed | accepted | superseded by ADR-NNN
- **Date:** YYYY-MM-DD

### Context
### Decision
### Alternatives considered
### Consequences
```

## Index

| ADR | Topic | Status |
|---|---|---|
| ADR-001 | The component we build (the real-time quiz service: server and client) and the mocks (identity and tickets, question bank, quiz admin) | proposed |
| ADR-002 | Quiz model: self-paced; the integer scoring rule | proposed |
| ADR-003 | Transport: raw WebSocket on FastAPI and uvicorn | proposed |
| ADR-004 | Wire protocol, standings policy and the 200 ms coalescing tick | proposed |
| ADR-005 | Redis sorted set and Lua scripts for scoring; AOF `everysec` | proposed |
| ADR-006 | No owner per quiz: the `dirty` gate and a tick token | proposed |
| ADR-007 | Backplane: Redis pub/sub, `seq` and resync (Streams as the next step) | proposed |
| ADR-008 | One Redis schema for scoring and fan-out | proposed |
| ADR-009 | Repository layout: `api/`, `web/`, generated `contracts/` | proposed |
