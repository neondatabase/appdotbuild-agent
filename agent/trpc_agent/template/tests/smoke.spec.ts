import { test } from "@playwright/test";
import fs from "fs";
import path from "path";

test("take screenshot of the main page and save console logs", async ({
  page,
}) => {
  // create logs directory if it doesn't exist
  const logsDir = path.join(process.cwd(), "./test_results");
  if (!fs.existsSync(logsDir)) {
    fs.mkdirSync(logsDir, { recursive: true });
  }

  // array to store console logs
  const logs: string[] = [];

  // listen for console messages
  page.on("console", (message) => {
    const text = `[${message.type()}] ${message.text()}`;
    logs.push(text);
  });

  // navigate to the base URL defined in config
  await page.goto("/");

  let browserName =
    page.context().browser()?.browserType()?.name() || "unknown";

  // take screenshot
  await page.screenshot({
    path: "test_results/" + browserName + "-screenshot.png",
    fullPage: true,
  });

  // save console logs to file
  fs.writeFileSync(
    path.join(logsDir, browserName + "-console.log"),
    logs.join("\n"),
  );
});
