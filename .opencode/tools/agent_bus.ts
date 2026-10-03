import { tool } from "@opencode-ai/plugin"
import { appendFile, mkdir, readFile, rename, writeFile } from "node:fs/promises"
import { join } from "node:path"

const tasksDir = ".im19/tasks"
const messagesFile = ".im19/messages/bus.jsonl"
const agentsDir = ".im19/agents"
const artifactsFile = ".im19/artifacts/index.jsonl"

async function ensure(root: string) {
  await mkdir(join(root, tasksDir), { recursive: true })
  await mkdir(join(root, ".im19/messages"), { recursive: true })
  await mkdir(join(root, agentsDir), { recursive: true })
  await mkdir(join(root, ".im19/artifacts"), { recursive: true })
}

function taskPath(root: string, id: string) {
  if (!/^[A-Z]+-[0-9]+$/.test(id)) throw new Error("Invalid task_id")
  return join(root, tasksDir, id + ".json")
}

async function atomicWrite(path: string, data: string) {
  const temp = path + ".tmp-" + crypto.randomUUID()
  await writeFile(temp, data, "utf8")
  await rename(temp, path)
}

export const send = tool({
  description: "Persist an event for another IM19 agent.",
  args: {
    to: tool.schema.string(),
    type: tool.schema.string(),
    message: tool.schema.string(),
    task_id: tool.schema.string().optional()
  },
  async execute(args, context) {
    const root = context.worktree
    await ensure(root)
    const event = {
      event_id: crypto.randomUUID(),
      timestamp: new Date().toISOString(),
      from: context.agent ?? "unknown",
      to: args.to,
      type: args.type,
      task_id: args.task_id ?? null,
      session_id: context.sessionID ?? null,
      message: args.message
    }
    await appendFile(join(root, messagesFile), JSON.stringify(event) + "\n")
    return JSON.stringify(event, null, 2)
  }
})

export const read_messages = tool({
  description: "Read recent IM19 agent events.",
  args: {
    limit: tool.schema.number().int().min(1).max(200).optional(),
    task_id: tool.schema.string().optional()
  },
  async execute(args, context) {
    const root = context.worktree
    await ensure(root)
    try {
      const raw = await readFile(join(root, messagesFile), "utf8")
      const rows = raw.trim() ? raw.trim().split("\n").map(JSON.parse) : []
      const filtered = args.task_id ? rows.filter((x) => x.task_id === args.task_id) : rows
      return JSON.stringify(filtered.slice(-(args.limit ?? 50)), null, 2)
    } catch {
      return "[]"
    }
  }
})

export const create_task = tool({
  description: "Create a durable IM19 task.",
  args: {
    task_id: tool.schema.string(),
    title: tool.schema.string(),
    owner: tool.schema.string(),
    objective: tool.schema.string(),
    dependencies: tool.schema.array(tool.schema.string()).optional(),
    verification: tool.schema.array(tool.schema.string())
  },
  async execute(args, context) {
    const root = context.worktree
    await ensure(root)
    const task = {
      ...args,
      dependencies: args.dependencies ?? [],
      status: "queued",
      created_by: context.agent ?? "unknown",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    }
    await atomicWrite(taskPath(root, args.task_id), JSON.stringify(task, null, 2) + "\n")
    return JSON.stringify(task, null, 2)
  }
})

export const update_task = tool({
  description: "Change an IM19 task lifecycle state.",
  args: {
    task_id: tool.schema.string(),
    status: tool.schema.string(),
    note: tool.schema.string().optional()
  },
  async execute(args, context) {
    const root = context.worktree
    const path = taskPath(root, args.task_id)
    const task = JSON.parse(await readFile(path, "utf8"))
    task.status = args.status
    task.updated_by = context.agent ?? "unknown"
    task.updated_at = new Date().toISOString()
    if (args.note) task.note = args.note
    await atomicWrite(path, JSON.stringify(task, null, 2) + "\n")
    return JSON.stringify(task, null, 2)
  }
})

export const publish_artifact = tool({
  description: "Publish an IM19 artifact record.",
  args: {
    task_id: tool.schema.string(),
    artifact_type: tool.schema.string(),
    path: tool.schema.string(),
    summary: tool.schema.string()
  },
  async execute(args, context) {
    const root = context.worktree
    await ensure(root)
    const record = {
      artifact_id: crypto.randomUUID(),
      timestamp: new Date().toISOString(),
      agent: context.agent ?? "unknown",
      ...args
    }
    await appendFile(join(root, artifactsFile), JSON.stringify(record) + "\n")
    return JSON.stringify(record, null, 2)
  }
})

export const heartbeat = tool({
  description: "Persist an agent lifecycle heartbeat.",
  args: {
    lifecycle: tool.schema.string(),
    status: tool.schema.string()
  },
  async execute(args, context) {
    const root = context.worktree
    await ensure(root)
    const agent = context.agent ?? "unknown"
    const record = {
      agent_id: agent,
      lifecycle: args.lifecycle,
      status: args.status,
      session_id: context.sessionID ?? null,
      timestamp: new Date().toISOString()
    }
    await atomicWrite(join(root, agentsDir, agent.replaceAll("/", "__") + ".json"), JSON.stringify(record, null, 2) + "\n")
    return JSON.stringify(record, null, 2)
  }
})
