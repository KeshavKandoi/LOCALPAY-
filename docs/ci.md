# Continuous integration

The [GitHub Actions workflow](../.github/workflows/verify.yml) installs locked dependencies, runs dependency and secret scans, and executes `bash scripts/ci.sh`. It retains suite JSON, HTML, JUnit, and relevant logs as workflow artifacts.

To run it locally after [installing development dependencies](development.md):

```sh
LOCALPAY_CI_API_PORT=8007 LOCALPAY_CI_DASHBOARD_PORT=3007 bash scripts/ci.sh
```

The script chooses a unique Compose project, generates disposable credentials, starts an Express receiver, and configures its pinned local address. It checks duplicate delivery and the receiver's independent processing count. It also exercises every CLI status and removes the test project's volume and networks on exit.

Use `LOCALPAY_EXTENDED_VERIFY=1` to add restart recovery and load measurement. Retain the resulting benchmark and resilience JSON from the output directory for comparisons across environments.
