#!/usr/bin/env python3
"""Create or start the local PostgreSQL used for development, idempotently.

Safe to run repeatedly: every step checks before it acts, and nothing is ever
deleted unless --reset is given.

    1. create the container if missing, start it if stopped, else leave it
    2. wait until PostgreSQL accepts TCP connections, and check the password
    3. create the development and test databases if they do not exist
    4. keep api/.env in step: LOCAL_POSTGRES_PASSWORD and POCKETSCAN_DATABASE_URL

The password lives in api/.env as LOCAL_POSTGRES_PASSWORD. If there is none and
the container has to be created, a random one is generated and written there.
An existing container whose password is unknown is never touched; use --reset.

Usage, from api/:

    uv run python scripts/init-and-run-local-postgresql.py
    uv run python scripts/init-and-run-local-postgresql.py --reset

Requires Podman. Tests read TEST_DATABASE_URL, printed at the end.
"""

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

CONTAINER = "pocketscan-pg"
# Pinned by digest. Bump deliberately, and keep CI's service container in step.
IMAGE_DIGEST = "sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336"
IMAGE = f"docker.io/library/postgres:18@{IMAGE_DIGEST}"
HOST = "127.0.0.1"
HOST_PORT = 5433
PG_USER = "postgres"
DEV_DATABASE = "pocketscan"
TEST_DATABASE = "pocketscan_test"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
PASSWORD_KEY = "LOCAL_POSTGRES_PASSWORD"
URL_KEY = "POCKETSCAN_DATABASE_URL"


def podman(
    *args: str, check: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a podman command, exiting with its error unless check is False.

    Secrets go in env, not argv, so they do not show up in the process list.
    """
    result = subprocess.run(
        ["podman", *args],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
    )
    if check and result.returncode != 0:
        sys.exit(f"podman {args[0]} failed:\n{result.stderr.strip()}")
    return result


def database_url(database: str, password: str) -> str:
    return f"postgresql+psycopg://{PG_USER}:{password}@{HOST}:{HOST_PORT}/{database}"


def read_env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and not key.startswith("#"):
                values[key.strip()] = value.strip().strip("\"'")
    return values


def sync_env_file(password: str, replace_url: bool) -> None:
    """Make .env hold the password, and the URL if it is missing or must change.

    Other lines are preserved. An existing URL is only replaced when the
    password was just generated, since the old one would no longer work.
    """
    wanted = {PASSWORD_KEY: password}
    if replace_url or URL_KEY not in read_env_file():
        wanted[URL_KEY] = database_url(DEV_DATABASE, password)

    old_text = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    lines: list[str] = []
    written: set[str] = set()
    for line in old_text.splitlines():
        key = line.partition("=")[0].strip()
        if key in wanted:
            lines.append(f"{key}={wanted[key]}")
            written.add(key)
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in wanted.items() if key not in written)

    new_text = "\n".join(lines) + "\n"
    if new_text == old_text:
        print(f"{ENV_FILE} is up to date")
        return
    ENV_FILE.write_text(new_text)
    ENV_FILE.chmod(0o600)
    print(f"Updated {ENV_FILE} (keys: {', '.join(sorted(wanted))})")


def container_exists() -> bool:
    return podman("container", "exists", CONTAINER, check=False).returncode == 0


def container_running() -> bool:
    result = podman("inspect", "--format", "{{.State.Running}}", CONTAINER)
    return result.stdout.strip() == "true"


def ensure_container(password: str | None) -> tuple[str, bool]:
    """Create or start the container. Return (password in use, newly generated)."""
    if not container_exists():
        generated = password is None
        password = password or secrets.token_urlsafe(24)
        print(f"Creating {CONTAINER} from {IMAGE}")
        podman(
            "run",
            "-d",
            "--name",
            CONTAINER,
            "-e",
            "POSTGRES_PASSWORD",
            "-e",
            f"POSTGRES_DB={DEV_DATABASE}",
            "-p",
            f"{HOST}:{HOST_PORT}:5432",
            IMAGE,
            env={"POSTGRES_PASSWORD": password},
        )
        return password, generated

    if password is None:
        sys.exit(
            f"{CONTAINER} exists but {ENV_FILE} has no {PASSWORD_KEY}, so its password is "
            "unknown. Use --reset to recreate it with a fresh one."
        )
    image = podman("inspect", "--format", "{{.Config.Image}}", CONTAINER).stdout.strip()
    if IMAGE_DIGEST not in image:
        print(
            f"WARNING: {CONTAINER} was not created from the pinned image ({image}). "
            "Use --reset to recreate it."
        )
    if container_running():
        print(f"{CONTAINER} is already running")
    else:
        print(f"Starting {CONTAINER}")
        podman("start", CONTAINER)
    return password, False


def wait_until_ready(timeout_seconds: float = 60.0) -> None:
    """Wait for TCP connections.

    The image starts a temporary socket-only server while initialising, so a
    plain pg_isready can succeed too early; checking over TCP cannot.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        ready = podman(
            "exec", CONTAINER, "pg_isready", "-h", "127.0.0.1", "-U", PG_USER, check=False
        )
        if ready.returncode == 0:
            print("PostgreSQL is accepting connections")
            return
        time.sleep(1)
    sys.exit(f"PostgreSQL did not become ready within {timeout_seconds:.0f}s")


def check_password(password: str) -> None:
    """Log in over TCP, which needs the password, to catch a stale .env."""
    result = podman(
        "exec",
        "-e",
        "PGPASSWORD",
        CONTAINER,
        "psql",
        "-h",
        "127.0.0.1",
        "-U",
        PG_USER,
        "-d",
        "postgres",
        "-tAc",
        "SELECT 1",
        check=False,
        env={"PGPASSWORD": password},
    )
    if result.returncode != 0:
        sys.exit(
            f"The {PASSWORD_KEY} in {ENV_FILE} does not match the running container. "
            "Use --reset to recreate it."
        )
    print("Password accepted")


def database_exists(name: str) -> bool:
    query = f"SELECT 1 FROM pg_database WHERE datname = '{name}'"
    result = podman("exec", CONTAINER, "psql", "-U", PG_USER, "-tAc", query)
    return result.stdout.strip() == "1"


def ensure_databases() -> None:
    for name in (DEV_DATABASE, TEST_DATABASE):
        if database_exists(name):
            print(f"Database {name} exists")
        else:
            print(f"Creating database {name}")
            podman("exec", CONTAINER, "createdb", "-U", PG_USER, name)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or start the local PostgreSQL for development."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="remove the container and its data first, then recreate it",
    )
    args = parser.parse_args()

    if shutil.which("podman") is None:
        sys.exit("podman was not found on PATH")

    if args.reset and container_exists():
        print(f"Removing {CONTAINER} and its data")
        podman("rm", "-f", CONTAINER)

    password, generated = ensure_container(read_env_file().get(PASSWORD_KEY))
    wait_until_ready()
    check_password(password)
    ensure_databases()
    sync_env_file(password, replace_url=generated)

    print("\nFor tests, export:")
    print(f"  export TEST_DATABASE_URL={database_url(TEST_DATABASE, password)}")


if __name__ == "__main__":
    main()
