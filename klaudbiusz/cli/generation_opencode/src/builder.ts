import * as fs from "fs";
import * as path from "path";
import { createOpencode, type OpencodeClient, type Event } from "@opencode-ai/sdk";
import type { BuilderOptions, GenerationMetrics, OpencodeConfig } from "./types.js";

// timing helper for diagnostics
function logTiming(label: string, startMs: number): void {
  const elapsed = Date.now() - startMs;
  console.log(`⏱️  [${label}] ${elapsed}ms`);
}

const BASE_INSTRUCTIONS = `You are running in non-interactive mode. Never use the question tool - make reasonable assumptions instead.

Scaffold, build, and test the app.
Use data from Databricks when relevant.
Be concise and to the point in your responses.
Use up to 10 tools per call to speed up the process.
Never deploy the app, just scaffold and build it.`;

// 15 minutes timeout for event stream (generous for long-running generations)
const EVENT_STREAM_TIMEOUT_MS = 15 * 60 * 1000;

// per-message usage tracking (to handle multiple updates per message)
interface MessageUsage {
  cost: number;
  inputTokens: number;
  outputTokens: number;
}

export class OpencodeAppBuilder {
  private options: BuilderOptions;
  private client: OpencodeClient | null = null;
  private closeServer: (() => void) | null = null;
  private scaffoldedDir: string | null = null;
  private lastEventTime: number = Date.now();
  private messageUsage: Map<string, MessageUsage> = new Map();
  private loggedToolCalls: Set<string> = new Set(); // track logged tool calls to avoid duplicates

  constructor(options: BuilderOptions) {
    this.options = options;
  }

  private writeOpencodeConfig(configDir: string): void {
    // minimal config - model is set via config.update() after server starts
    const config: OpencodeConfig = {
      $schema: "https://opencode.ai/config.json",
    };

    fs.mkdirSync(configDir, { recursive: true });
    fs.writeFileSync(path.join(configDir, "opencode.json"), JSON.stringify(config, null, 2));
  }

  async run(prompt: string): Promise<GenerationMetrics> {
    const startTime = Date.now();
    const appDir = path.join(this.options.outputDir, this.options.appName);

    // ensure output dir exists
    fs.mkdirSync(appDir, { recursive: true });

    // write opencode config to project directory
    this.writeOpencodeConfig(appDir);

    const metrics: GenerationMetrics = {
      cost_usd: 0,
      input_tokens: 0,
      output_tokens: 0,
      turns: 0,
    };

    // reset tracking state
    this.messageUsage.clear();
    this.loggedToolCalls.clear();

    // save original cwd and change to app directory so opencode picks up config
    const originalCwd = process.cwd();

    try {
      process.chdir(appDir);

      // start opencode server + client (without model config - set via config.update after)
      let phaseStart = Date.now();
      const { client, server } = await createOpencode({
        port: this.options.port ?? 0, // 0 = auto-assign
      });
      logTiming("createOpencode", phaseStart);

      this.client = client;
      this.closeServer = () => server.close();

      // set model via config.update (passing in createOpencode config doesn't work for some providers)
      const model = this.options.model ?? "anthropic/claude-sonnet-4-5-20250929";
      const configResult = await client.config.update({ body: { model } });
      if (configResult.error) {
        console.log(`⚠️ Failed to set model ${model}: ${JSON.stringify(configResult.error)}`);
      }

      if (this.options.verbose) {
        console.log(`OpenCode server running at ${server.url}`);
        console.log(`Model: ${model}`);
      }

      // create session
      phaseStart = Date.now();
      const sessionResult = await client.session.create({
        body: { title: this.options.appName },
      });
      logTiming("session.create", phaseStart);

      if (sessionResult.error) {
        throw new Error(`Failed to create session: ${JSON.stringify(sessionResult.error)}`);
      }

      const sessionId = sessionResult.data.id;

      if (this.options.verbose) {
        console.log(`Created session: ${sessionId}`);
      }

      // verify provider is connected
      const providerList = await client.provider.list();
      if (!providerList.error) {
        const providerName = model.split("/")[0];
        const connected = providerList.data?.connected ?? [];
        const isConnected = connected.includes(providerName);
        if (!isConnected) {
          console.log(`⚠️ Provider ${providerName} not connected. Available: ${connected.join(", ")}`);
        } else if (this.options.verbose) {
          console.log(`🔑 Provider ${providerName} connected`);
        }
      }

      // debug: check MCP status and available tools
      if (this.options.verbose) {
        const mcpStatus = await client.mcp.status();
        console.log(`\n📡 MCP Status:`);
        if (mcpStatus.error) {
          console.log(`  Error: ${JSON.stringify(mcpStatus.error)}`);
        } else {
          console.log(`  ${JSON.stringify(mcpStatus.data, null, 2)}`);
        }

        const toolIds = await client.tool.ids();
        console.log(`\n🔧 Available tool IDs:`);
        if (toolIds.error) {
          console.log(`  Error: ${JSON.stringify(toolIds.error)}`);
        } else {
          console.log(`  ${JSON.stringify(toolIds.data)}`);
        }

        console.log("");
      }

      // inject app context and send prompt
      const userPrompt = `App name: ${this.options.appName}
App directory: ${appDir}

${BASE_INSTRUCTIONS}

Task: ${prompt}`;

      // subscribe to events for progress tracking
      phaseStart = Date.now();
      const { stream: eventStream } = await client.event.subscribe();
      logTiming("event.subscribe", phaseStart);

      // send prompt (non-blocking, we'll watch events)
      phaseStart = Date.now();
      const promptPromise = client.session.prompt({
        path: { id: sessionId },
        body: {
          parts: [{ type: "text", text: userPrompt }],
        },
      });
      logTiming("session.prompt (send)", phaseStart);

      // process events with timeout protection
      const eventLoopStart = Date.now();
      this.lastEventTime = Date.now();
      let eventCount = 0;
      const timeoutChecker = setInterval(() => {
        const elapsed = Date.now() - this.lastEventTime;
        if (elapsed > EVENT_STREAM_TIMEOUT_MS) {
          console.log(`\n⚠️ Event stream timeout after ${Math.round(elapsed / 1000)}s of inactivity`);
          clearInterval(timeoutChecker);
          // force close to break out of event loop
          this.close();
        }
      }, 30000); // check every 30s

      try {
        for await (const event of eventStream) {
          this.lastEventTime = Date.now();
          eventCount++;
          this.handleEvent(event as Event, metrics);

          // check if prompt completed - we rely on session.idle
          if (event.type === "session.idle") {
            break;
          }
        }
      } finally {
        clearInterval(timeoutChecker);
        logTiming(`event loop (${eventCount} events)`, eventLoopStart);
      }

      // sum up usage from all messages
      for (const usage of this.messageUsage.values()) {
        metrics.cost_usd += usage.cost;
        metrics.input_tokens += usage.inputTokens;
        metrics.output_tokens += usage.outputTokens;
      }

      // wait for prompt to finish
      phaseStart = Date.now();
      await promptPromise;
      logTiming("promptPromise await", phaseStart);

      // get final messages to count turns and save trajectory
      phaseStart = Date.now();
      const messagesResult = await client.session.messages({
        path: { id: sessionId },
      });
      logTiming("session.messages", phaseStart);

      if (messagesResult.error) {
        console.warn(`Failed to get messages: ${JSON.stringify(messagesResult.error)}`);
      } else {
        metrics.turns = messagesResult.data.length;

        // save trajectory to app directory (jsonl format for consistency with Claude SDK)
        const trajectoryFile = path.join(this.scaffoldedDir ?? appDir, "trajectory.jsonl");
        const jsonlContent = messagesResult.data.map((msg: unknown) => JSON.stringify(msg)).join("\n");
        fs.writeFileSync(trajectoryFile, jsonlContent);
        console.log(`Trajectory saved to ${trajectoryFile}`);
      }

      metrics.generation_time_sec = (Date.now() - startTime) / 1000;
      metrics.app_dir = this.scaffoldedDir ?? appDir;

      // save metrics to app directory
      const metricsFile = path.join(metrics.app_dir, "generation_metrics.json");
      fs.writeFileSync(
        metricsFile,
        JSON.stringify(
          {
            cost_usd: metrics.cost_usd,
            input_tokens: metrics.input_tokens,
            output_tokens: metrics.output_tokens,
            turns: metrics.turns,
          },
          null,
          2
        )
      );

      return metrics;
    } finally {
      process.chdir(originalCwd);
      this.close();
    }
  }

  private handleEvent(event: Event, metrics: GenerationMetrics): void {
    switch (event.type) {
      case "session.error": {
        const err = event.properties;
        console.log(`❌ Session error: ${JSON.stringify(err)}`);
        break;
      }
      case "session.status": {
        // log session status in verbose mode
        if (this.options.verbose) {
          console.log(`📊 Session status: ${JSON.stringify(event.properties)}`);
        }
        break;
      }
      case "message.updated": {
        // track cost and tokens from assistant messages
        // note: message.updated fires multiple times per message with cumulative values,
        // so we store latest per message and sum at the end
        const msg = event.properties.info;
        if (msg.role === "assistant") {
          this.messageUsage.set(msg.id, {
            cost: msg.cost,
            inputTokens: msg.tokens.input,
            outputTokens: msg.tokens.output,
          });
        }
        break;
      }
      case "message.part.updated": {
        const part = event.properties.part;
        const delta = event.properties.delta;

        switch (part.type) {
          case "text": {
            // show text streaming
            if (delta && this.options.verbose) {
              process.stdout.write(delta);
            }
            break;
          }
          case "tool": {
            const toolName = part.tool;
            const state = part.state;
            const partId = part.id;

            // log tool state transitions (only once per tool call)
            if ("status" in state && state.status === "running") {
              const runKey = `${partId}:running`;
              if (!this.loggedToolCalls.has(runKey)) {
                this.loggedToolCalls.add(runKey);
                const input = "input" in state ? state.input : undefined;
                const inputStr = input ? JSON.stringify(input).slice(0, 150) : "";
                console.log(`🔧 Tool: ${toolName}(${inputStr})`);
              }
            } else if ("status" in state && state.status === "completed") {
              const completeKey = `${partId}:completed`;
              if (!this.loggedToolCalls.has(completeKey)) {
                this.loggedToolCalls.add(completeKey);
                const output = "output" in state ? String(state.output).slice(0, 200) : "";
                if (this.options.verbose) {
                  console.log(`✅ Result: ${output}`);
                }
              }
            } else if ("status" in state && state.status === "error") {
              const errorKey = `${partId}:error`;
              if (!this.loggedToolCalls.has(errorKey)) {
                this.loggedToolCalls.add(errorKey);
                const error = "error" in state ? state.error : "unknown";
                console.log(`❌ Tool error: ${error}`);
              }
            }

            // detect scaffold tool to track app_dir
            if (toolName.includes("scaffold") && part.metadata) {
              const args = part.metadata as Record<string, unknown>;
              if (args.work_dir && typeof args.work_dir === "string") {
                this.scaffoldedDir = args.work_dir;
              }
            }
            break;
          }
        }
        break;
      }
      case "session.idle": {
        console.log("\n✅ Session complete");
        break;
      }
      default: {
        // log unknown events in verbose mode
        if (this.options.verbose) {
          console.log(`📨 Event: ${event.type} ${JSON.stringify(event.properties).slice(0, 200)}`);
        }
      }
    }
  }

  close(): void {
    const closeStart = Date.now();
    if (this.closeServer) {
      try {
        this.closeServer();
      } catch (e) {
        console.warn(`Warning: error closing server: ${e}`);
      }
      this.closeServer = null;
    }
    this.client = null;
    logTiming("server.close", closeStart);

    // force exit after brief delay if process hangs
    setTimeout(() => {
      console.log("Forcing process exit after cleanup timeout");
      process.exit(0);
    }, 5000).unref(); // unref allows clean exit if everything closes properly
  }
}
