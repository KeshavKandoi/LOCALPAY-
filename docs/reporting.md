# Reliability reports

The Reports page and the run's `/report/json` and `/report/html` routes show case counts, failed assertions, relevant payment and delivery timelines, and available latency data. A summary pass rate uses the number of passed cases divided by all cases, including inconclusive cases.

Diagnostics use the recorded inputs and the evidence attached to the run. For example, a duplicate-processing finding requires a known duplicate scenario and a verification endpoint reporting repeated business processing for one logical event. A receiver's HTTP 200 response proves that the request was acknowledged.

Export JUnit through `/report/junit` or the CLI. An inconclusive case is represented as skipped. Reports use the data available to the installation at export time. [CLI](cli.md)
