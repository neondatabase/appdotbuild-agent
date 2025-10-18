import { test, chromium } from "@playwright/test";
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

test("capture app screenshot", async () => {
  // ensure screenshots directory exists
  await mkdir("/screenshots", { recursive: true });

  const targetUrl = process.env.TARGET_URL || "/";
  const targetPort = process.env.TARGET_PORT || "8000";
  const timeout = parseInt(process.env.WAIT_TIME || "30000");

  // resolve hostname to IP to avoid SSL protocol errors with service binding
  const { stdout } = await execAsync("getent hosts app | awk '{ print $1 }'");
  const appIp = stdout.trim();

  console.log(`Resolved app to IP: ${appIp}`);
  console.log(`Navigating to http://${appIp}:${targetPort}${targetUrl}`);
  console.log(`Waiting for network idle with timeout of ${timeout}ms`);

  const browser = await chromium.launch({
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  const page = await browser.newPage();

  // collect browser logs
  const logs: LogEntry[] = [];

  // capture console messages
  page.on("console", (msg) => {
    logs.push({
      timestamp: new Date().toISOString(),
      type: "console",
      level: msg.type() as "log" | "warn" | "error" | "info" | "debug",
      message: msg.text(),
    });
  });

  // capture page errors (JavaScript exceptions)
  page.on("pageerror", (error) => {
    logs.push({
      timestamp: new Date().toISOString(),
      type: "pageerror",
      message: error.message,
    });
  });

  try {
    // use IP instead of hostname to avoid SSL protocol errors
    // wait for network idle (500ms of no new requests) to ensure data is loaded
    await page.goto(`http://${appIp}:${targetPort}${targetUrl}`, {
      waitUntil: "networkidle",
      timeout: timeout,
    });

    // take full page screenshot
    await page.screenshot({
      path: "/screenshots/screenshot.png",
      fullPage: true,
    });

    console.log("Screenshot saved to /screenshots/screenshot.png");

    // save browser logs as text
    const logText = logs.map((log) => {
      const prefix = log.type === "pageerror" ? "[ERROR]" : `[${log.level?.toUpperCase()}]`;
      return `${log.timestamp} ${prefix} ${log.message}`;
    }).join("\n");

    await writeFile("/screenshots/logs.txt", logText, "utf-8");

    console.log(`Captured ${logs.length} browser log entries`);
    console.log("Logs saved to /screenshots/logs.txt");
  } finally {
    await browser.close();
  }
});
