#!/usr/bin/env node

import * as path from "path";
import { program } from "commander";
import chalk from "chalk";
import { OpencodeAppBuilder } from "./builder.js";

program
  .name("generate-opencode")
  .description("Generate Databricks apps using OpenCode SDK")
  .requiredOption("--app-name <name>", "Name of the app to generate")
  .requiredOption("--prompt <text>", "Generation prompt")
  .requiredOption("--mcp-binary <path>", "Path to MCP binary")
  .option("--mcp-args <json>", "MCP server args as JSON array", "[]")
  .option("--output-dir <path>", "Output directory", "./app")
  .option("--model <name>", "Model to use", "anthropic/claude-sonnet-4-20250514")
  .option("--port <number>", "OpenCode server port (0 = auto)")
  .option("--verbose", "Show detailed output", false)
  .action(async (opts) => {
    const mcpArgs: string[] = JSON.parse(opts.mcpArgs);
    const port = opts.port ? parseInt(opts.port, 10) : undefined;

    console.log("\n" + "=".repeat(60));
    console.log("OPENCODE APP GENERATION");
    console.log("=".repeat(60));
    console.log(`App: ${opts.appName}`);
    console.log(`Model: ${opts.model}`);
    console.log(`Output: ${path.resolve(opts.outputDir)}`);
    console.log(`MCP binary: ${opts.mcpBinary}`);
    if (opts.verbose) {
      console.log("Verbose: ON");
    }
    console.log();

    const builder = new OpencodeAppBuilder({
      appName: opts.appName,
      outputDir: path.resolve(opts.outputDir),
      mcpBinary: opts.mcpBinary,
      mcpArgs,
      model: opts.model,
      port,
      verbose: opts.verbose,
    });

    try {
      const metrics = await builder.run(opts.prompt);

      console.log("\n" + "=".repeat(60));
      console.log(chalk.green("GENERATION COMPLETE"));
      console.log("=".repeat(60));
      console.log(`App directory: ${metrics.app_dir}`);
      console.log(`Turns: ${metrics.turns}`);
      console.log(`Time: ${metrics.generation_time_sec?.toFixed(1)}s`);
      if (metrics.cost_usd > 0) {
        console.log(`Cost: $${metrics.cost_usd.toFixed(4)}`);
      }
    } catch (e) {
      console.error(chalk.red("\nGeneration failed:"), e);
      process.exit(1);
    }
  });

program.parse();
