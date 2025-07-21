import uuid
import dagger
from core.workspace import Workspace, ExecResult
from core.postgres_utils import create_postgres_service, pg_health_check_cmd

_BASE_PACKAGES = [
    "nginx",
    "supervisor",
    "postgresql-dev",
    "oniguruma-dev",
    "libzip-dev",
    "freetype-dev",
    "libjpeg-turbo-dev",
    "libpng-dev",
    "curl-dev",
    "libxml2-dev",
    "composer",
    "nodejs",
    "npm",
]

_DOCKER_EXT_PACKAGES = [
    "pdo",
    "pdo_pgsql",
    "pdo_mysql",
    "mysqli",
    "mbstring",
    "zip",
    "exif",
    "pcntl",
    "gd",
    "bcmath",
    "opcache",
    "curl",
    "xml",
    "soap",
]

async def create_workspace(client: dagger.Client, context: dagger.Directory, protected: list[str] = [], allowed: list[str] = []):
    ctr = (
        client
        .container()
        .from_("php:8.2-fpm-alpine")
        # Install packages in smaller groups to avoid I/O errors
        .with_exec(["apk", "update"])
        .with_exec(["apk", "add", "--no-cache", "nginx", "supervisor"])
        .with_exec(["apk", "add", "--no-cache", "postgresql-dev", "oniguruma-dev", "libzip-dev"])
        .with_exec(["apk", "add", "--no-cache", "freetype-dev", "libjpeg-turbo-dev", "libpng-dev"])
        .with_exec(["apk", "add", "--no-cache", "curl-dev", "libxml2-dev"])
        .with_exec(["apk", "add", "--no-cache", "nodejs", "npm"])
        .with_exec(["docker-php-ext-configure", "gd", "--with-freetype", "--with-jpeg"])
        .with_exec(["docker-php-ext-install", *_DOCKER_EXT_PACKAGES])
        .with_file("/usr/bin/composer", client.container().from_("composer:2").file("/usr/bin/composer"))
    )
    ctr = (
        ctr
        .with_workdir("/var/www/html")
        .with_directory("/var/www/html", context)
        .with_exec(["composer", "install", "--optimize-autoloader", "--no-interaction"])
        .with_exec(["npm", "install"])
    )
    ctr = ctr.with_env_variable("INSTANCE_ID", uuid.uuid4().hex)
    return Workspace(
        client=client,
        ctr=ctr,
        start=context,
        protected=set(protected),
        allowed=set(allowed),
    )

async def run_tests(ctr: dagger.Container) -> ExecResult:
    """Run the project test-suite inside the given container.

    We wrap the execution in a try / except block so that any
    `dagger.TransportError` or `dagger.QueryError` raised by the
    underlying engine is converted into a *failed* `ExecResult` rather
    than bubbling up and breaking the surrounding `anyio.TaskGroup`.
    This prevents opaque
    "unhandled errors in a TaskGroup (1 sub-exception)" messages from
    propagating to higher-level code.
    """

    try:
        # First run npm build - this modifies the container with built assets
        build_ctr = ctr.with_exec(["npm", "run", "build"], expect=dagger.ReturnType.ANY)
        build_result = await ExecResult.from_ctr(build_ctr)
        
        if build_result.exit_code != 0:
            # Return detailed npm build errors
            return ExecResult(
                exit_code=build_result.exit_code,
                stdout=f"NPM Build Failed:\n{build_result.stdout}",
                stderr=f"NPM Build Errors:\n{build_result.stderr}"
            )
        
        # If build succeeds, run tests in the same container that has the built assets
        test_ctr = build_ctr.with_exec(["composer", "test"], expect=dagger.ReturnType.ANY)
        test_result = await ExecResult.from_ctr(test_ctr)
        
        # If tests fail but build succeeded, include build output for context
        if test_result.exit_code != 0 and build_result.stdout:
            test_result.stdout = f"Build Output:\n{build_result.stdout}\n\nTest Output:\n{test_result.stdout}"
        
        return test_result
        
    except (dagger.TransportError, dagger.QueryError) as exc:
        # Map transport issues to a non-zero ExecResult so callers can
        # surface the error context without crashing the task-group.
        return ExecResult(exit_code=1, stdout="", stderr=str(exc))

async def run_migrations(client: dagger.Client, ctr: dagger.Container, postgresdb: dagger.Service | None = None):
    if postgresdb is None:
        postgresdb = create_postgres_service(client)

    # Override template defaults to match exec_with_pg TODO: Maybe alter template .env
    push_ctr = (
        ctr
        .with_env_variable("DB_HOST", "postgres")
        .with_env_variable("DB_DATABASE", "postgres")
        .with_env_variable("DB_USERNAME", "postgres")
        .with_env_variable("DB_PASSWORD", "postgres")
        .with_exec(["apk", "add", "postgresql-client"])
        .with_service_binding("postgres", postgresdb)
        .with_exec(pg_health_check_cmd())
        .with_exec(["php", "/var/www/html/artisan", "migrate", "--force"])
    )

    try:
        return await ExecResult.from_ctr(push_ctr)
    except (dagger.TransportError, dagger.QueryError) as exc:
        # Similar to the test helper above, convert transport failures
        # into a regular ExecResult so that callers receive a concrete
        # error payload instead of an uncaught exception.
        return ExecResult(exit_code=1, stdout="", stderr=str(exc))
