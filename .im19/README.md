# IM19 Agent Runtime v0.1

Lifecycle:
PLAN -> CODE -> BUILD -> TEST -> RELEASE -> DEPLOY -> OPERATE -> MONITOR -> LEARN -> PLAN

Agents:
orchestrator, architect, backend, rag, mcp, memory, testing, security, reviewer, integrator

Shared runtime:
.im19/state
.im19/tasks
.im19/messages
.im19/artifacts
.im19/decisions
.im19/runs
.im19/agents

The first implementation is filesystem-backed. SQLite/Redis can replace the storage backend later without changing the agent protocol.
