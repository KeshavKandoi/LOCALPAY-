# API Workspace

Sign in to the dashboard, select a project, and open **API Workspace**. Enter a key ID and secret from that project’s Settings. Payment templates cover listing and creating orders, simulating payments, capturing payments, and issuing refunds. Enter amounts in the smallest currency unit.

Requests accept relative LocalPay paths and URLs on the dashboard origin. The dashboard forwards supported payment and health routes only to its configured LocalPay API address. Project routes require Basic credentials belonging to the selected project. The dashboard blocks redirects and limits request and response bodies to 512 KiB. It applies a 10-second upstream deadline, including project verification.

The **Environment** editor resolves variables such as `{{order_id}}` and `{{payment_id}}` in a URL, query field, header, or body. Use one `name=value` per line for variables, query parameters, and form fields, and one `name: value` per line for headers. Use the masked session field for sensitive variables. Keep credential literals out of saved templates and exported files. The dashboard stores saved templates, nonsecret environment variables, and the latest 100 HTTP results as metadata in browser storage scoped by project. Project credentials and session variables are held in memory while the workspace is open.

Each assertion uses one line. For example:

```text
status = 200
header.content-type exists
json.id exists
json.amount >= 500
json.error.code = "BAD_REQUEST_ERROR"
time < 1500
```

Use dot notation for nested fields and array indexes. Assertions run on the displayed response. You can copy or download the response from the viewer.

The LocalPay export is a JSON object with `version: 1` and a `requests` array. Each entry has a display name, a slash-delimited collection path, and a request draft. Exported requests can be imported into the workspace for another project. cURL copies contain template placeholders and shell environment references for credentials. Replace `{{base_url}}` with the LocalPay API origin when running the command outside the dashboard.

## Payment Simulator

Use **Payment Simulator** for guided forms covering order creation, authorization and failure scenarios, capture, and refunds. The next action pre-fills the preceding record ID when the API returns one. The lifecycle lists records returned during the current session. Use **Orders**, **Payments**, and **Refunds** to look up records after leaving the simulator. The response panel displays HTTP status alongside the payment or refund status returned by the API.

The workspace also imports OpenAPI JSON operations, Postman v2 JSON requests and nested folders, and simple cURL commands saved as text files. Imports use the URL path with the configured LocalPay gateway. Postman imports include raw bodies and supported gateway headers. cURL imports accept an inline body, headers, and the HTTP method. The importer does not execute cURL, collection scripts, or imported credentials.
