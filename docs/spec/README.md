<!-- AI-ASSISTED: index of the specs, drafted with Claude Code from their intros. -->
# Specs

- [domain.md](domain.md): the quiz rules, the scoring and the C1–C6 consistency contract
- [protocol.md](protocol.md): the WebSocket and HTTP messages, the errors and the sequence diagrams
- [redis.md](redis.md): the keys, the Lua scripts and the coalescing across nodes
- [ui.md](ui.md): the screens, their states, accessibility and the design tokens
- [display-names.json](display-names.json): the display-name cases the server and the client share

Where two specs disagree, the domain spec wins and the other one is fixed; the UI spec also
yields to the protocol spec.
