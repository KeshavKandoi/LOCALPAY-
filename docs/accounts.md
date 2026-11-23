# LocalPay accounts

Open the dashboard and choose **Sign up**. LocalPay accepts case-insensitive usernames of 3–32 ASCII letters, numbers, underscores, or hyphens, starting with a letter or number. Use a password of 12–128 characters. Signing up opens a private workspace where you can create and rename projects and issue or revoke their test keys. Account Settings lets you change your password, revoke other sessions, or sign out.

FastAPI stores Argon2id password hashes and SHA-256 digests of random session tokens in PostgreSQL. Sessions expire after eight hours. The dashboard stores the opaque token in an HttpOnly, SameSite Strict cookie and checks request origin before mutations. Use HTTPS and set `LOCALPAY_DASHBOARD_SECURE_COOKIE=true` in production. The dashboard sends only the account session to its account API. Project Basic credentials still authenticate the Razorpay-compatible APIs. The operator token still authenticates the operator API and CLI.

The instance-wide signup and login budgets and the username-specific login budget are stored in Redis. Excess attempts return a retry deadline. In a hosted deployment, put additional abuse controls at the trusted reverse proxy. LocalPay currently uses one owner per project and does not provide team access or verified self-service recovery.

## Associate an existing project

Start LocalPay normally to apply the migration. Existing projects and their test keys remain intact. Register the intended account, then use the local Docker operator shell.

```sh
docker compose exec api python -m app.account_operator list-unowned-projects
docker compose exec api python -m app.account_operator claim-project PROJECT_SLUG USERNAME
```

Find the row labeled **LocalPay Demo Store** and use its slug in the second command. The command refuses to assign a project already owned by another account. Refresh the dashboard after claiming the project.

## Recover an account

A trusted operator with access to the server can reset a password from an interactive terminal. Enter the replacement password at the two hidden prompts.

```sh
docker compose exec api python -m app.account_operator reset-password USERNAME
```

This resets the password and revokes all existing sessions for that account. For hosted installations, use a trusted administrator process to verify the requester’s identity before running recovery. Provide the replacement password through a private channel, and ask the user to change it after signing in.
