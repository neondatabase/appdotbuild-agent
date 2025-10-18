import { test, chromium, Browser } from "@playwright/test";
import { mkdir, writeFile } from "fs/promises";
import { exec } from "child_process";
import { promisify } from "util";

const execAsync = promisify(exec);

interface LogEntry {
  timestamp: string;
  type: "console" | "pageerror";
  level?: "log" | "warn" | "error" | "info" | "debug";
  message: string;
}

interface AppResult {
  appIndex: number;
  success: boolean;
  logs: LogEntry[];
  error?: string;
}

async function screenshotApp(
  browser: Browser,
  appIndex: number,
  targetPort: string,
  timeout: number
): Promise<AppResult> {
  const logs: LogEntry[] = [];

  try {
    // resolve hostname to IP
    const { stdout } = await execAsync(`getent hosts app-${appIndex} | awk '{ print $1 }'`);
    const appIp = stdout.trim();

    if (!appIp) {
      throw new Error(`Service app-${appIndex} not found (build likely failed)`);
    }

    console.log(`[app-${appIndex}] Resolved to IP: ${appIp}`);
    console.log(`[app-${appIndex}] Navigating to http://${appIp}:${targetPort}/`);

    const context = await browser.newContext();
    const page = await context.newPage();

    // capture console messages
    page.on("console", (msg) => {
      logs.push({
        timestamp: new Date().toISOString(),
        type: "console",
        level: msg.type() as "log" | "warn" | "error" | "info" | "debug",
        message: msg.text(),
      });
    });

    // capture page errors
    page.on("pageerror", (error) => {
      logs.push({
        timestamp: new Date().toISOString(),
        type: "pageerror",
        message: error.message,
      });
    });

    // navigate and wait for network idle
    await page.goto(`http://${appIp}:${targetPort}/`, {
      waitUntil: "networkidle",
      timeout: timeout,
    });

    // take screenshot
    await mkdir(`/screenshots/app-${appIndex}`, { recursive: true });
    await page.screenshot({
      path: `/screenshots/app-${appIndex}/screenshot.png`,
      fullPage: true,
    });

    console.log(`[app-${appIndex}] Screenshot saved`);

    // save logs
    const logText = logs.map((log) => {
      const prefix = log.type === "pageerror" ? "[ERROR]" : `[${log.level?.toUpperCase()}]`;
      return `${log.timestamp} ${prefix} ${log.message}`;
    }).join("\n");

    await writeFile(`/screenshots/app-${appIndex}/logs.txt`, logText, "utf-8");
    console.log(`[app-${appIndex}] Captured ${logs.length} browser log entries`);

    await context.close();

    return { appIndex, success: true, logs };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    console.error(`[app-${appIndex}] Failed: ${errorMessage}`);

    return {
      appIndex,
      success: false,
      logs,
      error: errorMessage,
    };
  }
}

async function processWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  processor: (item: T) => Promise<R>
): Promise<R[]> {
  const results: R[] = [];
  let index = 0;

  async function runNext(): Promise<void> {
    const currentIndex = index++;
    if (currentIndex >= items.length) return;

    const result = await processor(items[currentIndex]);
    results.push(result);
  }

  // start initial batch
  const workers = Array.from({ length: Math.min(concurrency, items.length) }, () => runNext());

  // keep workers running until all items are processed
  await Promise.all(workers.map(async (worker) => {
    await worker;
    while (index < items.length) {
      await runNext();
    }
  }));

  return results;
}

test("batch capture app screenshots", async () => {
  await mkdir("/screenshots", { recursive: true });

  const targetPort = process.env.TARGET_PORT || "8000";
  const timeout = parseInt(process.env.WAIT_TIME || "60000");
  const concurrency = parseInt(process.env.CONCURRENCY || "3");
  const numApps = parseInt(process.env.NUM_APPS || "0");

  if (numApps === 0) {
    throw new Error("NUM_APPS environment variable must be set");
  }

  console.log(`Processing ${numApps} apps with concurrency ${concurrency}`);
  console.log(`Timeout: ${timeout}ms, Port: ${targetPort}`);

  const browser = await chromium.launch({
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  try {
    const appIndices = Array.from({ length: numApps }, (_, i) => i);

    const results = await processWithConcurrency(
      appIndices,
      concurrency,
      (appIndex) => screenshotApp(browser, appIndex, targetPort, timeout)
    );

    const successful = results.filter((r) => r.success).length;
    const failed = results.filter((r) => !r.success).length;

    console.log(`\nBatch complete: ${successful} succeeded, ${failed} failed`);

    // write summary
    const summary = results.map((r) => ({
      app: `app-${r.appIndex}`,
      success: r.success,
      error: r.error,
      logCount: r.logs.length,
    }));

    await writeFile("/screenshots/summary.json", JSON.stringify(summary, null, 2), "utf-8");
  } finally {
    await browser.close();
  }
});
