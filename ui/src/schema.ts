// Schema nodes (design §12, api/nodewright/schemas.py): a text node with
// `schema: <format>` and the source in a fenced code block. The server parses
// it into fields and ports; this module holds the drawing metrics (which must
// match schemas.py), highlighting and the per-format samples.
import hljs from "highlight.js/lib/core";
import json from "highlight.js/lib/languages/json";
import protobuf from "highlight.js/lib/languages/protobuf";
import sql from "highlight.js/lib/languages/sql";
import yaml from "highlight.js/lib/languages/yaml";

hljs.registerLanguage("json", json);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("protobuf", protobuf);
hljs.registerLanguage("sql", sql);

export const HEADER = 28, PAD = 8, LINE = 18; // px, as schemas.py
export type SchemaFormat = "avro" | "protobuf" | "json" | "yaml" | "sql";

export const SCHEMA_FORMATS: { value: SchemaFormat; label: string }[] = [
  { value: "avro", label: "Avro" },
  { value: "protobuf", label: "Protobuf" },
  { value: "json", label: "JSON / JSON Schema" },
  { value: "yaml", label: "YAML / OpenAPI" },
  { value: "sql", label: "SQL" },
];

const LANG: Record<SchemaFormat, string> = { avro: "json", protobuf: "protobuf", json: "json", yaml: "yaml", sql: "sql" };
const FENCE_RE = /^\s*```[\w-]*[ \t]*\n([\s\S]*?)\n?```\s*$/;

export function unfence(text: unknown): string {
  const t = typeof text === "string" ? text : "";
  const m = FENCE_RE.exec(t);
  return m ? m[1] : t;
}

/** Highlighted HTML for the source. highlight.js escapes the text it's given. */
export function highlight(fmt: SchemaFormat, source: string): string {
  try {
    return hljs.highlight(source, { language: LANG[fmt] ?? "plaintext", ignoreIllegals: true }).value;
  } catch {
    return source.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
}

/** The schema format a dropped file holds, by extension. */
export function formatForFile(name: string): SchemaFormat | null {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  return ({ avsc: "avro", proto: "protobuf", json: "json", yaml: "yaml", yml: "yaml", sql: "sql" } as Record<string, SchemaFormat>)[ext] ?? null;
}

export const SAMPLES: Record<SchemaFormat, string> = {
  avro: `{
  "type": "record",
  "name": "Order",
  "fields": [
    {"name": "id", "type": "string"},
    {"name": "customer_id", "type": "long"},
    {"name": "total", "type": "double"},
    {"name": "placed_at", "type": {"type": "long", "logicalType": "timestamp-millis"}}
  ]
}`,
  protobuf: `syntax = "proto3";

message Order {
  string id = 1;
  int64 customer_id = 2;
  repeated LineItem items = 3;
}

message LineItem {
  string sku = 1;
  int32 quantity = 2;
}`,
  json: `{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Customer",
  "type": "object",
  "properties": {
    "id": {"type": "integer"},
    "email": {"type": "string", "format": "email"},
    "name": {"type": "string"}
  }
}`,
  yaml: `components:
  schemas:
    Customer:
      type: object
      properties:
        id:
          type: integer
        email:
          type: string`,
  sql: `CREATE TABLE orders (
  id bigserial PRIMARY KEY,
  customer_id bigint NOT NULL REFERENCES customers(id),
  total numeric(10, 2) NOT NULL,
  placed_at timestamptz DEFAULT now()
);`,
};
