import { defaultDraft, methods, type Draft } from "./workspace";

export type Imported = { name: string; collection: string; draft: Draft };

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function string(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function localPath(value: string) {
  const path = value.replace(/^https?:\/\/[^/]+/i, "").replace(/^{{[^}]+}}/, "").replace(/(?<!\{)\{([^{}]+)\}(?!\})/g, "{{$1}}");
  if (!path.startsWith("/") || path.startsWith("//")) throw new Error("Imported requests must specify an API path.");
  return path;
}

function method(value: string): Draft["method"] {
  const found = methods.find((item) => item === value.toUpperCase());
  if (!found) throw new Error("Unsupported HTTP method.");
  return found;
}

function buildDraft(input: Partial<Draft> & { url: string; method: Draft["method"] }): Draft {
  return { ...defaultDraft, checks: "", ...input, url: localPath(input.url) };
}

function fromOpenApi(root: Record<string, unknown>): Imported[] {
  const collection = string(record(root.info).title, "OpenAPI");
  return Object.entries(record(root.paths)).flatMap(([url, path]) =>
    Object.entries(record(path)).filter(([key]) => methods.some((item) => item.toLowerCase() === key)).map(([key, raw]) => {
      const operation = record(raw);
      const schema = record(record(record(operation.requestBody).content)["application/json"]);
      const example = schema.example ?? record(schema.schema).example;
      return {
        collection,
        name: string(operation.summary, string(operation.operationId, key.toUpperCase() + " " + url)),
        draft: buildDraft({ url, method: method(key), ...(example === undefined ? {} : { format: "json", body: JSON.stringify(example, null, 2) }) }),
      };
    }),
  );
}

function fromPostman(root: Record<string, unknown>): Imported[] {
  const imported: Imported[] = [];
  function visit(entries: unknown[], collection: string, depth: number) {
    if (depth > 12) throw new Error("Collection folders are nested too deeply.");
    for (const raw of entries) {
      const entry = record(raw);
      const name = string(entry.name, "Untitled request");
      if (Array.isArray(entry.item)) {
        visit(entry.item, collection + "/" + name, depth + 1);
        continue;
      }
      if (imported.length >= 100) throw new Error("Import supports up to 100 requests.");
      const request = record(entry.request);
      const body = record(request.body);
      const language = record(record(body.options).raw).language;
      const url = string(request.url, string(record(request.url).raw));
      const headers = list(request.header).map(record).filter((header) =>
        !header.disabled && ["accept", "content-type", "x-localpay-idempotency-key", "x-refund-idempotency"].includes(string(header.key).toLowerCase()),
      ).map((header) => string(header.key) + ": " + string(header.value)).join("\n");
      const format = body.mode === "raw" ? language === "json" ? "json" : language === "xml" ? "xml" : "text" : "none";
      imported.push({ name, collection, draft: buildDraft({ url, method: method(string(request.method, "GET")), headers, format, body: format === "none" ? "" : string(body.raw) }) });
    }
  }
  visit(list(root.item), string(record(root.info).name, "Postman collection"), 0);
  return imported;
}

function fromCurl(command: string): Imported[] {
  const tokens = command.trim().match(/'(?:[^']*)'|"(?:[^"\\]|\\.)*"|[^\s'"]+/g) ?? [];
  const parts = tokens.map((token) => token.startsWith("'") || token.startsWith('"') ? token.slice(1, -1) : token);
  if (parts.shift() !== "curl") throw new Error("Choose a supported workspace JSON file or a cURL command.");
  let selectedMethod = "";
  let url = "";
  let body = "";
  let contentType = "";
  const headers: string[] = [];
  while (parts.length) {
    const token = parts.shift() ?? "";
    if (["-X", "--request"].includes(token)) selectedMethod = parts.shift() ?? "";
    else if (["--url"].includes(token)) url = parts.shift() ?? "";
    else if (["-d", "--data", "--data-raw", "--data-binary"].includes(token)) {
      body = parts.shift() ?? "";
      if (body.startsWith("@")) throw new Error("Import only accepts inline cURL bodies.");
    } else if (["-H", "--header"].includes(token)) {
      const header = parts.shift() ?? "";
      const name = header.split(":", 1)[0].trim().toLowerCase();
      if (name === "content-type") contentType = header.slice(header.indexOf(":") + 1).trim();
      if (["accept", "content-type", "x-localpay-idempotency-key", "x-refund-idempotency"].includes(name)) headers.push(header);
    } else if (["-u", "--user"].includes(token)) {
      parts.shift();
    } else if (!url && /^(\/|https?:\/\/|{{)/.test(token)) url = token;
    else throw new Error("Unsupported cURL argument.");
  }
  const format = body ? contentType.includes("json") ? "json" : "text" : "none";
  const draft = buildDraft({ url, method: method(selectedMethod || (body ? "POST" : "GET")), format, body, headers: headers.join("\n") });
  return [{ name: draft.method + " " + draft.url, collection: "cURL imports", draft }];
}

export function importPortable(input: string): Imported[] | null {
  if (input.trimStart().startsWith("curl ")) return fromCurl(input);
  const source = record(JSON.parse(input));
  if (source.version === 1) return null;
  const result = typeof source.openapi === "string" || source.swagger === "2.0" ? fromOpenApi(source) :
    string(record(source.info).schema).includes("schema.getpostman.com/json/collection/v2.") ? fromPostman(source) : [];
  if (!result.length || result.length > 100) throw new Error("Choose a supported export with 1–100 requests.");
  return result;
}
