# Reliability suites

Create a YAML or JSON suite from the Test Runner or the project administration API. A minimal suite tests whether an order gets paid once during concurrent capture.

```yaml
name: capture-reliability
version: 1
tests:
  - name: Concurrent capture
    scenario: payment.concurrent_capture
    assertions:
      - type: scenario_passed
        expected: true
      - type: amount_paid
        expected: 600
```

For webhook cases, provide the project's `endpoint_id`, archived `event_ids`, and optional chaos `config`. Delivery and response assertions use recorded attempts.

For assertions about application state, configure a suite `verification_url` and share `LOCALPAY_VERIFICATION_TOKEN` with the test-only receiver. The worker calls that endpoint by GET with a bearer token and correlation parameters, including `run_id`, the case name, and available order or execution IDs. Return a JSON object with supported observations such as `{"application_event_count":1}`.

The runner distinguishes passed, failed, error, and inconclusive outcomes. An application assertion with unavailable evidence is inconclusive. Webhook observation has a bounded window. Keep delays and backoff within that window or inspect the delivery history separately.

In Test Runner, the visual payment suite builder adds cases to the YAML editor. Validate a draft before saving it. Run results show individual expected and observed assertion values. Reports offers downloadable JSON, HTML, and JUnit XML.

In CI, run a saved or checked-in suite and publish its JUnit report as a job artifact. Supply the administration credential, API URL, and project ID through your CI environment.

```sh
localpay test run --file suite.yaml
localpay test report RUN_ID --format junit --output localpay-report.xml
```
