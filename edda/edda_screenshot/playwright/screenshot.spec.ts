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
  const maxHeight = 10000;
  const format = "png";

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

  let screenshotError: string | undefined;

  try {
    // use IP instead of hostname to avoid SSL protocol errors
    // wait for network idle (500ms of no new requests) to ensure data is loaded
    try {
      await page.goto(`http://${appIp}:${targetPort}${targetUrl}`, {
        waitUntil: "networkidle",
        timeout: timeout,
      });

      // take full page screenshot with height limit
      const screenshotOptions: any = {
        path: `/screenshots/screenshot.${format}`,
        fullPage: true,
        type: format as "png" | "jpeg",
      };

      // clip to max height if needed
      const bodyHandle = await page.$("body");
      const boundingBox = await bodyHandle?.boundingBox();
      if (boundingBox && boundingBox.height > maxHeight) {
        screenshotOptions.clip = {
          x: 0,
          y: 0,
          width: boundingBox.width,
          height: maxHeight,
        };
        screenshotOptions.fullPage = false;
        console.log(`Height limited: ${boundingBox.height}px → ${maxHeight}px`);
      }

      await page.screenshot(screenshotOptions);

      // compress PNG with oxipng (lossless, ~20-40% reduction)
      const screenshotPath = `/screenshots/screenshot.${format}`;
      console.log(`Compressing ${screenshotPath} with oxipng...`);
      await execAsync(`oxipng -o 2 --strip all ${screenshotPath}`);

      console.log(`Screenshot saved to ${screenshotPath}`);
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      console.error(`Failed to screenshot app: ${errorMessage}`);
      screenshotError = errorMessage;

      // write error to separate file
      await writeFile("/screenshots/error.txt", errorMessage, "utf-8");
      console.log("Error details saved to /screenshots/error.txt");
    }

    // save browser logs as text (always, regardless of screenshot success)
    const logText = logs
      .map((log) => {
        const prefix =
          log.type === "pageerror"
            ? "[ERROR]"
            : `[${log.level?.toUpperCase()}]`;
        return `${log.timestamp} ${prefix} ${log.message}`;
      })
      .join("\n");

    await writeFile("/screenshots/logs.txt", logText, "utf-8");

    console.log(`Captured ${logs.length} browser log entries`);
    console.log("Logs saved to /screenshots/logs.txt");
  } finally {
    await browser.close();
  }
});
