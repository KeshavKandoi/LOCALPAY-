# Contributing to LocalPay

Start with the [development guide](docs/development.md) and [architecture notes](docs/architecture.md). Use disposable projects and local receivers for examples and integration changes.

For gateway behavior changes, cite the relevant Razorpay documentation and add a contract test alongside the service or API test. For financial changes, include an invariant, a rollback check, and meaningful concurrent cases. For webhook changes, check exact signed bytes, event identity, and retry behavior.

Run `bash scripts/ci.sh` before proposing a change. Use descriptive names and place implementation explanations in Markdown. Keep secrets, screenshots containing credentials, and generated test artifacts out of the repository.

Describe configuration or migration changes in your change summary, alongside the commands you ran and what passed. See [SECURITY.md](SECURITY.md) for handling vulnerabilities.
