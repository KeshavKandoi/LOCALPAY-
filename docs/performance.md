# Local performance verification

The Phase 15 run used macOS arm64, Docker Desktop Engine 29.7.2, eight VM CPUs, and about 7.75 GiB of VM memory. The stack ran PostgreSQL 18.7, Redis 7.4.12, and a local Express receiver. Eight client threads submitted 60 operations at each API stage.

| Operation | Throughput | p50 | p95 |
| --- | ---: | ---: | ---: |
| Create order | 162.43/s | 46.77 ms | 65.35 ms |
| Simulate payment | 104.86/s | 66.53 ms | 153.29 ms |
| Capture payment | 37.30/s | 161.52 ms | 432.08 ms |
| Refund | 11.83/s | 195.46 ms | 3,457.46 ms |
| Deliver signed webhook | 12.22/s | | |
| Deliver after injected failure | 1.89/s | | |

Combined API latency was 82.91 ms p50 and 450.93 ms p95. The interval from recorded event to attempt completion was 3,013.83 ms p50 and 3,371.34 ms p95. The benchmark's PostgreSQL count query recorded 0.351 ms planning and 0.524 ms execution. Container memory and CPU readings are point-in-time samples taken during the delivery window. [Raw measurements](performance.json)

Run the same bounded workload with `LOCALPAY_EXTENDED_VERIFY=1 bash scripts/ci.sh`. The results apply to this local workload and configuration.
