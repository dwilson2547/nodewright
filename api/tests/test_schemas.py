import pytest

from nodewright import schemas

AVRO = """{
  "type": "record", "name": "Order",
  "fields": [
    {"name": "id", "type": "string"},
    {"name": "customer", "type": {"type": "record", "name": "Customer", "fields": [
      {"name": "email", "type": ["null", "string"]}
    ]}},
    {"name": "lines", "type": {"type": "array", "items": "string"}}
  ]
}"""

PROTO = """syntax = "proto3";
// an order
message Order {
  string id = 1;
  repeated Line lines = 2;
  map<string, int32> tags = 3 [deprecated = true];
  message Line { int64 sku = 1; }
  oneof payment { string card = 4; }
  enum Status { NEW = 0; }
  reserved 9;
}
message Empty {}
"""

SQL = """-- orders
CREATE TABLE IF NOT EXISTS public.orders (
  id bigserial PRIMARY KEY,
  customer_id bigint NOT NULL REFERENCES customers(id),
  total numeric(10, 2) DEFAULT 0,
  CONSTRAINT positive CHECK (total >= 0)
);
create table "customers" ("id" bigint primary key, email text);
"""

JSON_SCHEMA = """{
\t"$schema": "https://json-schema.org/draft/2020-12/schema",
\t"title": "User",
\t"type": "object",
\t"properties": {
\t\t"id": {"type": "string", "format": "uuid"},
\t\t"address": {"type": "object", "properties": {"city": {"type": "string"}}},
\t\t"roles": {"type": "array", "items": {"$ref": "#/$defs/Role"}}
\t}
}"""

OPENAPI = """openapi: 3.0.0
components:
  schemas:
    Pet:
      type: object
      properties:
        name:
          type: string
        tag: {type: string}
"""

EXAMPLE = """name: api
replicas: 3
ports:
  - port: 80
"""


def fields(fmt, src):
    r = schemas.parse(fmt, src)
    assert r["error"] is None, r["error"]
    return r["name"], [(f["path"], f["type"], f["line"]) for f in r["fields"]]


def test_avro():
    name, f = fields("avro", AVRO)
    assert name == "Order"
    assert f == [("id", "string", 3), ("customer", "Customer", 4), ("customer.email", "null|string", 5),
                 ("lines", "array<string>", 7)]


def test_protobuf():
    name, f = fields("protobuf", PROTO)
    assert name == "Order"
    assert f == [("Order.id", "string", 3), ("Order.lines", "Line", 4), ("Order.tags", "map<string,int32>", 5),
                 ("Order.Line.sku", "int64", 6), ("Order.card", "string", 7)]


def test_sql():
    name, f = fields("sql", SQL)
    assert name == "orders"
    assert f == [("orders.id", "bigserial", 2), ("orders.customer_id", "bigint", 3),
                 ("orders.total", "numeric(10, 2)", 4), ("customers.id", "bigint", 7),
                 ("customers.email", "text", 7)]


def test_json_schema_with_tabs_and_refs():
    name, f = fields("json", JSON_SCHEMA)
    assert name == "User"
    assert f == [("id", "string (uuid)", 5), ("address", "object", 6), ("address.city", "string", 6),
                 ("roles", "array<Role>", 7)]


def test_openapi_and_plain_yaml():
    assert fields("yaml", OPENAPI) == ("Pet", [("Pet.name", "string", 6), ("Pet.tag", "string", 8)])
    assert fields("yaml", EXAMPLE)[1] == [("name", "string", 0), ("replicas", "integer", 1),
                                         ("ports", "array", 2), ("ports.port", "integer", 3)]


def test_errors_are_reported_not_raised():
    r = schemas.parse("json", '{"a": ')
    assert r["fields"] == [] and "line" in r["error"]
    assert schemas.parse("sql", "select 1")["error"] == "no CREATE TABLE found"
    with pytest.raises(schemas.SchemaError):
        schemas.parse("xml", "<a/>")


def test_derive_fences_sizes_and_ports():
    node = {"schema": "sql", "text": SQL, "width": 100}
    schemas.derive(node)
    assert node["text"].startswith("```sql\n") and schemas.unfence(node["text"]) == SQL.rstrip()
    assert node["height"] == schemas.HEADER + 2 * schemas.PAD + 8 * schemas.LINE
    assert node["width"] == schemas.MIN_WIDTH
    ids = [p["id"] for p in node["ports"]]
    assert ids[:2] == ["orders.id", "orders.id@left"]
    assert node["ports"][0]["side"] == "right" and node["ports"][1]["side"] == "left"
    assert node["ports"][0]["at"] == schemas.port_at(2, node["height"])
    schemas.derive(node)  # idempotent on fenced text
    assert schemas.unfence(node["text"]) == SQL.rstrip()


def test_agents_add_schema_nodes_and_wire_fields(client):
    from nodewright import canvas_format, ops
    from .conftest import H
    d = {"nodes": [], "edges": []}
    r = ops.add_elements(
        [{"id": "o", "schema": "sql", "text": SQL}, {"id": "c", "schema": "avro", "text": AVRO}],
        [{"fromNode": "o", "fromPort": "orders.customer_id", "toNode": "c", "toPort": "customer.email@left"}])(d)
    assert r["schemas"]["o"]["name"] == "orders" and "orders.total: numeric(10, 2)" in r["schemas"]["o"]["fields"]
    e = d["edges"][0]
    assert (e["fromSide"], e["toSide"]) == ("right", "left")
    assert all("_parsed" not in n for n in d["nodes"])
    canvas_format.validate(d)
    # Editing the source re-derives; a broken one empties the ports and the edge dangles.
    r = ops.update_elements([{"id": "c", "set": {"text": '{"type": '}}])(d)
    assert r["schemas"]["c"]["error"] and d["nodes"][1]["ports"] == []
    with pytest.raises(ops.OpError, match="schema goes on a text node"):
        ops.add_elements([{"type": "group", "schema": "sql"}], [])(d)
    d["nodes"][0]["schema"] = "xml"
    with pytest.raises(canvas_format.CanvasError):
        canvas_format.validate(d)

    p = client.post("/api/schemas/parse", json={"format": "protobuf", "source": PROTO}, headers=H).json()
    assert p["name"] == "Order" and p["text"].startswith("```protobuf\n")
    assert {"id": "Order.id@left", "side": "left", "at": schemas.port_at(3, p["height"])} in p["ports"]
    assert client.post("/api/schemas/parse", json={"format": "xml", "source": ""}, headers=H).status_code == 422
