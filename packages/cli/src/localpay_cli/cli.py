import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from secrets import token_hex, token_urlsafe
from time import monotonic, sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

EXIT = {"passed": 0, "failed": 1, "error": 2, "inconclusive": 3}


class CliError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="localpay")
    root.add_argument("--api-url")
    root.add_argument("--project", type=UUID)
    root.add_argument("--compose-file", type=Path)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("up")
    commands.add_parser("down")
    commands.add_parser("health")
    scenario = commands.add_parser("scenarios").add_subparsers(
        dest="action", required=True
    )
    scenario.add_parser("list")
    launch = scenario.add_parser("run")
    launch.add_argument("type")
    launch.add_argument("--requests", type=int, default=1)
    launch.add_argument("--scenario-id", type=UUID)
    launch.add_argument("--endpoint-id", type=UUID)
    launch.add_argument("--event-id", type=UUID, action="append")
    test = commands.add_parser("test").add_subparsers(dest="action", required=True)
    run = test.add_parser("run")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--suite-id", type=UUID)
    run.add_argument("--timeout", type=int, default=120)
    report = test.add_parser("report")
    report.add_argument("run_id", type=UUID)
    report.add_argument("--format", choices=("json", "html", "junit"), default="json")
    report.add_argument("--output", type=Path)
    return root


def compose_path(configured: Path | None) -> Path:
    found = configured or next(
        (
            folder / "compose.yaml"
            for folder in (Path.cwd(), *Path.cwd().parents)
            if (folder / "compose.yaml").is_file()
        ),
        None,
    )
    if found is None or not found.is_file():
        raise CliError("Run from a LocalPay checkout or supply --compose-file.")
    return found.resolve()


def init_env(filename: Path) -> None:
    values = {
        "LOCALPAY_POSTGRES_PASSWORD": token_urlsafe(24),
        "LOCALPAY_ADMIN_TOKEN": token_hex(32),
        "LOCALPAY_WEBHOOK_ENCRYPTION_KEY": token_urlsafe(32) + "=",
        "LOCALPAY_API_PORT": "8000",
        "LOCALPAY_DASHBOARD_PORT": "3000",
    }
    try:
        fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"Using existing {filename}")
        return
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.writelines(f"{key}={value}\n" for key, value in values.items())
    print(f"Created {filename}")


def local_settings(directory: Path) -> dict[str, str]:
    path = directory / ".env"
    values = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip().startswith("LOCALPAY_"):
                values[key.strip()] = value.strip().strip("'\042")
    values.update(os.environ)
    return values


class Client:
    def __init__(self, origin: str, admin: str | None) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise CliError("Use an HTTP or HTTPS origin for --api-url.")
        self.origin = origin.rstrip("/")
        self.admin = admin
        self.opener = build_opener(NoRedirect())

    def send(self, path: str, method: str = "GET", data: object | None = None) -> bytes:
        headers = {"Content-Type": "application/json"}
        if path.startswith("/localpay/admin/"):
            if not self.admin:
                raise CliError("Set LOCALPAY_ADMIN_TOKEN to use admin commands.")
            headers["Authorization"] = "Bearer " + self.admin
        request = Request(
            self.origin + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=10) as response:
                return bytes(response.read())
        except HTTPError as exc:
            raise CliError(
                f"LocalPay returned HTTP {exc.code} for {method} {path}."
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise CliError("Unable to reach the LocalPay API.") from exc

    def json(self, path: str, method: str = "GET", data: object | None = None) -> Any:
        return json.loads(self.send(path, method, data))


def scoped_path(args: argparse.Namespace, settings: dict[str, str]) -> str:
    raw_project = args.project or settings.get("LOCALPAY_PROJECT_ID")
    if raw_project is None:
        raise CliError("Provide --project or LOCALPAY_PROJECT_ID.")
    return f"/localpay/admin/v1/projects/{UUID(str(raw_project))}"


def test_command(args: argparse.Namespace, client: Client, root: str) -> int:
    if args.action == "report":
        content = client.send(f"{root}/test-runs/{args.run_id}/report/{args.format}")
        if args.output is not None:
            with args.output.open("xb") as stream:
                stream.write(content)
        else:
            sys.stdout.buffer.write(content + b"\n")
        return 0
    if not 1 <= args.timeout <= 3600:
        raise CliError("--timeout must be between 1 and 3600 seconds.")
    suite_id = args.suite_id
    if args.file:
        with args.file.open("rb") as stream:
            contents = stream.read(65537)
        if len(contents) > 65536:
            raise CliError("Suite file exceeds 64 KiB.")
        suite = client.json(f"{root}/test-suites", "POST", {"yaml": contents.decode()})
        suite_id = UUID(suite["id"])
    run = client.json(f"{root}/test-suites/{suite_id}/runs", "POST")
    run_path = f"{root}/test-runs/{UUID(run['id'])}"
    deadline = monotonic() + args.timeout
    while monotonic() < deadline:
        run = client.json(run_path)
        if run["status"] in EXIT:
            print(json.dumps(run))
            return EXIT[run["status"]]
        sleep(0.25)
    print(json.dumps({"id": run["id"], "status": "blocked", "reason": "timeout"}))
    return 4


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command in {"init", "up", "down"}:
            compose = compose_path(args.compose_file)
            if args.command == "init":
                init_env(compose.parent / ".env")
                return 0
            flags = (
                ["up", "--build", "--detach", "--wait"]
                if args.command == "up"
                else ["down"]
            )
            return subprocess.run(
                ["docker", "compose", "--file", str(compose), *flags],
                cwd=compose.parent,
                check=False,
                timeout=600,
            ).returncode
        directory = (
            args.compose_file.resolve().parent if args.compose_file else Path.cwd()
        )
        settings = local_settings(directory)
        origin = (
            args.api_url
            or settings.get("LOCALPAY_API_URL")
            or f"http://127.0.0.1:{settings.get('LOCALPAY_API_PORT', '8000')}"
        )
        client = Client(origin, settings.get("LOCALPAY_ADMIN_TOKEN"))
        if args.command == "health":
            print(
                json.dumps(
                    {
                        "health": client.json("/health"),
                        "readiness": client.json("/ready"),
                    }
                )
            )
            return 0
        root = scoped_path(args, settings)
        if args.command == "scenarios":
            if args.action == "list":
                result = {
                    "payment": client.json(f"{root}/payment-chaos/scenarios"),
                    "webhook": client.json(f"{root}/webhook-scenarios"),
                }
            elif args.type == "webhook.chaos":
                if not args.scenario_id or not args.endpoint_id or not args.event_id:
                    raise CliError(
                        "Webhook runs require --scenario-id, --endpoint-id, and --event-id."
                    )
                result = client.json(
                    f"{root}/webhook-scenarios/{args.scenario_id}/runs",
                    "POST",
                    {
                        "endpoint_id": str(args.endpoint_id),
                        "event_ids": [str(item) for item in args.event_id],
                    },
                )
            else:
                result = client.json(
                    f"{root}/payment-chaos/runs",
                    "POST",
                    {"type": args.type, "requests": args.requests},
                )
            print(json.dumps(result))
            return 0
        return test_command(args, client, root)
    except (CliError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"localpay: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
