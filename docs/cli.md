# CLI

Install with `uv tool install ./packages/cli` and run `localpay --help`. The CLI reads exported settings and values from the local `.env` file. Set `LOCALPAY_PROJECT_ID` or pass `--project PROJECT_ID` before the command. Use `--api-url` for a configured self-hosted LocalPay origin.

```sh
localpay init
localpay up
localpay health
localpay scenarios list
localpay scenarios run payment.concurrent_capture
localpay test run --file suite.yaml
localpay test run --suite-id SUITE_ID
localpay test report RUN_ID --format junit --output report.xml
localpay down
```

Run a saved webhook case with `localpay scenarios run webhook.chaos --scenario-id ID --endpoint-id ID --event-id ID`. Repeat `--event-id` for multiple events.

Suite exit codes are 0 for passed, 1 for failed, 2 for error, 3 for inconclusive, and 4 for a blocked deadline. The CLI includes the run ID so you can inspect an unfinished run after recovery.
