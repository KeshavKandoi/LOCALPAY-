import argparse
import json
import math
import platform
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from subprocess import run
from time import monotonic, sleep
from typing import Any
from uuid import UUID

from ci_suites import api
from resilience import compose, setup


def percentile(values: list[float], fraction: float) -> float:
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 3)


def timing(values: list[float]) -> dict[str, float]:
    return {"p50_ms": percentile(values, 0.5), "p95_ms": percentile(values, 0.95)}


def stage(
    executor: ThreadPoolExecutor,
    data: list[Any],
    operation: Callable[[Any], Any],
) -> tuple[list[Any], dict[str, Any], list[float]]:
    def measured(item: Any) -> tuple[Any, float]:
        started = monotonic()
        result = operation(item)
        return result, (monotonic() - started) * 1000

    start = monotonic()
    completed = list(executor.map(measured, data))
    elapsed = monotonic() - start
    values = [duration for _, duration in completed]
    return (
        [result for result, _ in completed],
        {
            "operations": len(data),
            "elapsed_seconds": round(elapsed, 3),
            "operations_per_second": round(len(data) / elapsed, 2),
            **timing(values),
        },
        values,
    )


def wait_deliveries(root: str, expected: int) -> list[dict[str, Any]]:
    deadline = monotonic() + 65
    while monotonic() < deadline:
        rows = api(root + "/webhook-deliveries?count=100")
        if len(rows) == expected and all(row["status"] == "delivered" for row in rows):
            return list(rows)
        sleep(0.15)
    raise TimeoutError("Benchmark deliveries did not complete")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--operations", type=int, choices=range(20, 81), default=60)
    parser.add_argument("--concurrency", type=int, choices=range(1, 17), default=8)
    args = parser.parse_args()
    root, auth = setup()
    stages = {}
    latencies = []
    identifiers = list(range(args.operations))

    def post(path: str, body: dict[str, object]) -> Any:
        return api(path, body, auth)

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        orders, stages["orders"], times = stage(
            executor,
            identifiers,
            lambda index: post(
                "/v1/orders",
                {"amount": 900, "currency": "INR", "receipt": f"load-{index}"},
            ),
        )
        latencies.extend(times)
        payments, stages["simulate"], times = stage(
            executor,
            orders,
            lambda order: post(
                "/localpay/v1/simulations/payments", {"order_id": order["id"]}
            ),
        )
        latencies.extend(times)
        dispatch_started = monotonic()
        captured, stages["capture"], times = stage(
            executor,
            payments,
            lambda payment: post(
                f"/v1/payments/{payment['id']}/capture",
                {"amount": 900, "currency": "INR"},
            ),
        )
        latencies.extend(times)
        names = compose(
            "ps", "--quiet", "api", "worker", "postgres", "redis"
        ).splitlines()
        stats = run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}", *names],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        resource_samples = [
            {
                "service": row["Name"].rsplit("-", 2)[-2],
                "cpu": row["CPUPerc"],
                "memory": row["MemUsage"],
            }
            for row in map(json.loads, stats.stdout.splitlines())
        ]
        normal = wait_deliveries(root, args.operations)
        event_times = {
            row["id"]: row["created_at"]
            for row in api(root + "/webhook-events?count=100")
        }
        assert all(row["event_id"] in event_times for row in normal)
        timestamps = list(
            executor.map(
                lambda delivery: api(
                    f"{root}/webhook-deliveries/{delivery['id']}/attempts"
                )[0],
                normal,
            )
        )
        observed_end = max(
            datetime.fromisoformat(row["created_at"]) for row in timestamps
        )
        observed_start = min(
            datetime.fromisoformat(event_times[row["event_id"]]) for row in normal
        )
        delivery_seconds = max((observed_end - observed_start).total_seconds(), 0.001)
        stages["webhooks"] = {
            "delivered": len(normal),
            "operations_per_second": round(len(normal) / delivery_seconds, 2),
            "recorded_seconds": round(delivery_seconds, 3),
            "observed_wall_seconds": round(monotonic() - dispatch_started, 3),
        }
        queue_latencies = [
            (
                datetime.fromisoformat(attempt["created_at"])
                - datetime.fromisoformat(event_times[delivery["event_id"]])
            ).total_seconds()
            * 1000
            for delivery, attempt in zip(normal, timestamps, strict=True)
        ]
        _, stages["refund"], times = stage(
            executor,
            captured,
            lambda payment: post(
                f"/v1/payments/{payment['id']}/refund", {"amount": 100}
            ),
        )
        latencies.extend(times)
    scenario = api(
        root + "/webhook-scenarios",
        {
            "name": "retry measurement",
            "config": {
                "duplicate_count": 12,
                "failure_mode": "http_500",
                "failure_attempts": 1,
                "retry_limit": 2,
            },
        },
    )
    retry_start = monotonic()
    retry = api(
        f"{root}/webhook-scenarios/{scenario['id']}/runs",
        {
            "endpoint_id": normal[0]["endpoint_id"],
            "event_ids": [normal[0]["event_id"]],
        },
    )
    all_rows = wait_deliveries(root, len(normal) + 12)
    retry_elapsed = monotonic() - retry_start
    assert (
        sum(
            row["execution_id"] == retry["id"] and row["attempt_count"] == 2
            for row in all_rows
        )
        == 12
    )
    stages["retries"] = {
        "delivered": 12,
        "seconds": round(retry_elapsed, 3),
        "operations_per_second": round(12 / retry_elapsed, 2),
    }
    project_id = UUID(root.rsplit("/", 1)[-1])
    query = f"EXPLAIN (ANALYZE, FORMAT JSON) SELECT count(*) FROM orders WHERE project_id = '{project_id}'"
    [explain] = json.loads(
        compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "localpay",
            "-d",
            "localpay",
            "-Atc",
            query,
        )
    )
    environment = run(
        [
            "docker",
            "info",
            "--format",
            "{{.OperatingSystem}}; {{.Architecture}}; CPUs={{.NCPU}}; memory={{.MemTotal}} bytes; engine={{.ServerVersion}}",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    ).stdout.strip()
    result = {
        "host": f"{platform.system()} {platform.release()} {platform.machine()}",
        "docker": environment,
        "concurrency": args.concurrency,
        "stage_results": stages,
        "api_latency": timing(latencies),
        "queue_to_attempt_completion_latency": timing(queue_latencies),
        "postgresql": {
            "planning_ms": explain["Planning Time"],
            "execution_ms": explain["Execution Time"],
        },
        "container_resource_samples": resource_samples,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
