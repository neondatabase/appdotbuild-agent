/**
 * Screenshot sidecar for web applications
 *
 * A reusable Dagger module that captures screenshots of running web applications
 * using Playwright. Assumes the app has a Dockerfile.
 */
import { dag, Directory, Service, object, func } from "@dagger.io/dagger"

@object()
export class ScreenshotSidecar {
  /**
   * Capture a screenshot of a running web service
   *
   * @param appService The running web application service to screenshot
   * @param url The URL path to navigate to (default: "/")
   * @param port The port the service is listening on (default: 8000)
   * @param waitTime Maximum timeout to wait for network idle in ms (default: 30000)
   * @returns Directory containing screenshot.png and logs.txt
   */
  @func()
  async screenshot(
    appService: Service,
    url?: string,
    port?: number,
    waitTime?: number
  ): Promise<Directory> {
    const targetUrl = url || "/"
    const targetPort = port || 8000
    const wait = waitTime || 30000

    // load playwright source from module root (source is now "." in dagger.json)
    const playwrightSource = dag.currentModule().source().directory("playwright")

    // build base playwright container (cached across all runs)
    const playwrightBase = dag
      .container()
      .from("mcr.microsoft.com/playwright:v1.40.0-jammy")
      .withWorkdir("/tests")
      .withDirectory("/tests", playwrightSource, {
        exclude: ["node_modules"]
      })
      .withExec(["npm", "install"])
      .withMountedCache("/ms-playwright", dag.cacheVolume("playwright-browsers"))
      .withExec(["npx", "playwright", "install", "chromium"])

    // add app-specific configuration (invalidates only from here)
    const playwrightContainer = playwrightBase
      .withServiceBinding("app", appService)
      .withEnvVariable("TARGET_URL", targetUrl)
      .withEnvVariable("TARGET_PORT", targetPort.toString())
      .withEnvVariable("WAIT_TIME", wait.toString())
      .withEnvVariable("CACHE_BUST", Date.now().toString())
      .withExec(["npx", "playwright", "test", "--config=playwright.single.config.ts"])

    return playwrightContainer.directory("/screenshots")
  }

  /**
   * Build and screenshot an app from a directory with a Dockerfile
   *
   * @param appSource Directory containing the app source and Dockerfile
   * @param envVars Optional environment variables as comma-separated KEY=VALUE pairs (e.g., "PORT=8000,DEBUG=true")
   * @param waitTime Maximum timeout to wait for network idle in ms (default: 60000)
   * @param port Port the app listens on (default: 8000)
   * @returns Directory containing screenshot.png and logs.txt
   */
  @func()
  async screenshotApp(
    appSource: Directory,
    envVars?: string,
    waitTime?: number,
    port?: number
  ): Promise<Directory> {
    const targetPort = port || 8000

    // build container from Dockerfile
    let appContainer = appSource.dockerBuild()

    // parse and apply environment variables
    if (envVars) {
      const pairs = envVars.split(",")
      for (const pair of pairs) {
        const [key, value] = pair.split("=")
        if (key && value) {
          appContainer = appContainer.withEnvVariable(key.trim(), value.trim())
        }
      }
    }

    const appService = appContainer.withExposedPort(targetPort).asService()

    return this.screenshot(appService, "/", targetPort, waitTime || 60000)
  }

  /**
   * Build and screenshot multiple apps with one Playwright instance
   *
   * @param appSources Array of directories containing app source and Dockerfile
   * @param envVars Optional environment variables shared across all apps (comma-separated KEY=VALUE pairs)
   * @param port Port all apps listen on (default: 8000)
   * @param waitTime Maximum timeout to wait for network idle in ms (default: 60000)
   * @param concurrency Number of apps to process in parallel (default: 3)
   * @returns Directory with subdirectories app-0/, app-1/, etc. each containing screenshot.png and logs.txt
   */
  @func()
  async screenshotApps(
    appSources: Directory[],
    envVars?: string,
    port?: number,
    waitTime?: number,
    concurrency?: number
  ): Promise<Directory> {
    const targetPort = port || 8000
    const wait = waitTime || 60000
    const parallelism = concurrency || 3

    // build all app containers and track successes/failures
    const appServices: (Service | null)[] = []
    const buildResults: boolean[] = []

    for (let i = 0; i < appSources.length; i++) {
      try {
        let appContainer = appSources[i].dockerBuild()

        // parse and apply environment variables
        if (envVars) {
          const pairs = envVars.split(",")
          for (const pair of pairs) {
            const [key, value] = pair.split("=")
            if (key && value) {
              appContainer = appContainer.withEnvVariable(key.trim(), value.trim())
            }
          }
        }

        // force evaluation by syncing - this will throw if build fails
        await appContainer.sync()

        appServices.push(appContainer.withExposedPort(targetPort).asService())
        buildResults.push(true)
        console.log(`[app-${i}] Build successful`)
      } catch (error) {
        console.error(`[app-${i}] Build failed: ${error instanceof Error ? error.message : String(error)}`)
        appServices.push(null)
        buildResults.push(false)
      }
    }

    // load playwright source
    const playwrightSource = dag.currentModule().source().directory("playwright")

    // build base playwright container (cached across all runs)
    const playwrightBase = dag
      .container()
      .from("mcr.microsoft.com/playwright:v1.40.0-jammy")
      .withWorkdir("/tests")
      .withDirectory("/tests", playwrightSource, {
        exclude: ["node_modules"]
      })
      .withExec(["npm", "install"])
      .withMountedCache("/ms-playwright", dag.cacheVolume("playwright-browsers"))
      .withExec(["npx", "playwright", "install", "chromium"])

    // bind only successful app services
    let playwrightContainer = playwrightBase
    for (let i = 0; i < appServices.length; i++) {
      if (appServices[i] !== null) {
        playwrightContainer = playwrightContainer.withServiceBinding(`app-${i}`, appServices[i]!)
      }
    }

    // add configuration
    playwrightContainer = playwrightContainer
      .withEnvVariable("TARGET_PORT", targetPort.toString())
      .withEnvVariable("WAIT_TIME", wait.toString())
      .withEnvVariable("CONCURRENCY", parallelism.toString())
      .withEnvVariable("NUM_APPS", appServices.length.toString())
      .withEnvVariable("CACHE_BUST", Date.now().toString())
      .withExec(["npx", "playwright", "test", "--config=playwright.batch.config.ts"])

    return playwrightContainer.directory("/screenshots")
  }
}
