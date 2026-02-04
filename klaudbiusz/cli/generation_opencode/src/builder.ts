import * as fs from "fs";
import * as path from "path";
import { createOpencode, type OpencodeClient, type Event } from "@opencode-ai/sdk";
import type { BuilderOptions, GenerationMetrics, OpencodeConfig } from "./types.js";

// timing helper for diagnostics
function logTiming(label: string, startMs: number): void {
  const elapsed = Date.now() - startMs;
  console.log(`⏱️  [${label}] ${elapsed}ms`);
}

const BASE_INSTRUCTIONS = `Scaffold, build, and test the app.
Use data from Databricks when relevant.
Be concise and to the point in your responses.
Use up to 10 tools per call to speed up the process.
Never deploy the app, just scaffold and build it.`;

// 15 minutes timeout for event stream (generous for long-running generations)
const EVENT_STREAM_TIMEOUT_MS = 15 * 60 * 1000;

export class OpencodeAppBuilder {
  private options: BuilderOptions;
  private client: OpencodeClient | null = null;
  private closeServer: (() => void) | null = null;
  private scaffoldedDir: string | null = null;
  private lastEventTime: number = Date.now();

  constructor(options: BuilderOptions) {
    this.options = options;
  }

  private writeOpencodeConfig(configDir: string): void {
    const model = this.options.model ?? "anthropic/claude-sonnet-4-5-20250929";

    const config: OpencodeConfig = {
      $schema: "https://opencode.ai/config.json",
      model,
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

    // save original cwd and change to app directory so opencode picks up config
    const originalCwd = process.cwd();

    try {
      process.chdir(appDir);

      // start opencode server + client
      let phaseStart = Date.now();
      const { client, server } = await createOpencode({
        port: this.options.port ?? 0, // 0 = auto-assign
        config: {
          model: this.options.model ?? "anthropic/claude-sonnet-4-5-20250929",
        },
      });
      logTiming("createOpencode", phaseStart);

      this.client = client;
      this.closeServer = () => server.close();

      if (this.options.verbose) {
        console.log(`OpenCode server running at ${server.url}`);
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

        // get full tool list with provider to see MCP tools
        const model = this.options.model ?? "anthropic/claude-sonnet-4-5-20250929";
        const providerName = model.split("/")[0];
        const modelName = model.split("/").slice(1).join("/");
        const toolList = await client.tool.list({ query: { provider: providerName, model: modelName } });
        console.log(`\n🔧 Full tool list (provider=${providerName}, model=${modelName}):`);
        if (toolList.error) {
          console.log(`  Error: ${JSON.stringify(toolList.error)}`);
        } else {
          // show full tool objects, not just names
          console.log(`  Count: ${toolList.data.length}`);
          for (const t of toolList.data) {
            console.log(`  - ${JSON.stringify(t)}`);
          }
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
          this.handleEvent(event as Event);

          // check if prompt completed - we rely on session.idle
          if (event.type === "session.idle") {
            break;
          }
        }
      } finally {
        clearInterval(timeoutChecker);
        logTiming(`event loop (${eventCount} events)`, eventLoopStart);
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

  private handleEvent(event: Event): void {
    switch (event.type) {
      case "session.error": {
        const err = event.properties;
        console.log(`❌ Session error: ${JSON.stringify(err)}`);
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

            // log tool state transitions
            if ("status" in state && state.status === "running") {
              const input = "input" in state ? state.input : undefined;
              const inputStr = input ? JSON.stringify(input).slice(0, 150) : "";
              console.log(`🔧 Tool: ${toolName}(${inputStr})`);
            } else if ("status" in state && state.status === "completed") {
              const output = "output" in state ? String(state.output).slice(0, 200) : "";
              if (this.options.verbose) {
                console.log(`✅ Result: ${output}`);
              }
            } else if ("status" in state && state.status === "error") {
              const error = "error" in state ? state.error : "unknown";
              console.log(`❌ Tool error: ${error}`);
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
