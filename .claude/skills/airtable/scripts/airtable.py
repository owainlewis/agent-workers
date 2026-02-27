#!/usr/bin/env python3
"""
Airtable CLI
"""

import argparse
import json
import os
import sys
import time
from urllib import error, parse, request

META_BASE_URL = "https://api.airtable.com/v0/meta"
DATA_BASE_URL = "https://api.airtable.com/v0"
RATE_LIMIT_PER_SEC = 5
MIN_INTERVAL = 1.0 / RATE_LIMIT_PER_SEC

_last_request_time = 0.0


def _print_json(obj):
    json.dump(obj, sys.stdout)
    sys.stdout.write("\n")


def _error_exit(message, code=1):
    json.dump({"error": message}, sys.stderr)
    sys.stderr.write("\n")
    sys.exit(code)


def _load_env(path=".env"):
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as exc:
        _error_exit(f"Failed to read .env: {exc}")


def _get_env(name, required=False):
    value = os.getenv(name)
    if required and not value:
        _error_exit(f"Missing environment variable: {name}")
    return value


def _resolve_base_id(base_override):
    if base_override:
        return base_override
    base_id = os.getenv("AIRTABLE_BASE_ID")
    if base_id:
        return base_id
    _error_exit(
        "Missing base ID. Run `base list` to discover bases and pass `--base BASE_ID`, "
        "or set AIRTABLE_BASE_ID in .env."
    )


def _rate_limit_sleep():
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request_time = time.time()


def _parse_api_error(body_text):
    try:
        data = json.loads(body_text)
    except json.JSONDecodeError:
        return body_text.strip() or "Unknown error"

    if isinstance(data, dict) and "error" in data:
        err = data.get("error")
        if isinstance(err, dict):
            err_type = err.get("type")
            err_msg = err.get("message")
            if err_type and err_msg:
                return f"{err_type} - {err_msg}"
            if err_msg:
                return err_msg
        if isinstance(err, str):
            return err
    return body_text.strip() or "Unknown error"


def _request(token, method, url, params=None, json_body=None):
    if params:
        url = f"{url}?{parse.urlencode(params, doseq=True)}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")

    while True:
        req = request.Request(url, method=method, headers=headers, data=data)
        try:
            _rate_limit_sleep()
            with request.urlopen(req) as resp:
                body = resp.read().decode("utf-8")
                if body:
                    return json.loads(body)
                return {}
        except error.HTTPError as exc:
            body_text = exc.read().decode("utf-8")
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else 1.0
                except ValueError:
                    wait = 1.0
                time.sleep(wait)
                continue
            message = _parse_api_error(body_text)
            _error_exit(f"Airtable API {exc.code}: {message}")
        except error.URLError as exc:
            _error_exit(f"Network error: {exc.reason}")


def _parse_json_arg(value, label):
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        _error_exit(f"Invalid JSON for {label}: {exc}")


def _chunk(items, size):
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def _get_tables(token, base_id):
    url = f"{META_BASE_URL}/bases/{base_id}/tables"
    data = _request(token, "GET", url)
    return data.get("tables", [])


def _find_table(token, base_id, table_name):
    tables = _get_tables(token, base_id)
    for table in tables:
        if table.get("name") == table_name:
            return table
    _error_exit(f"Table not found: {table_name}")


def cmd_base_list(args):
    token = _get_env("AIRTABLE_API_KEY", required=True)
    data = _request(token, "GET", f"{META_BASE_URL}/bases")
    _print_json({"bases": data.get("bases", [])})


def cmd_table_list(args):
    token = _get_env("AIRTABLE_API_KEY", required=True)
    base_id = _resolve_base_id(args.base)
    tables = _get_tables(token, base_id)
    _print_json({"base_id": base_id, "tables": tables})


def cmd_table_create(args):
    token = _get_env("AIRTABLE_API_KEY", required=True)
    base_id = _resolve_base_id(args.base)
    schema = _parse_json_arg(args.schema, "schema")
    if not isinstance(schema, list):
        _error_exit("Schema must be a JSON array of field definitions")
    url = f"{META_BASE_URL}/bases/{base_id}/tables"
    payload = {"name": args.name, "fields": schema}
    table = _request(token, "POST", url, json_body=payload)
    _print_json({"table": table})


def cmd_field_add(args):
    token = _get_env("AIRTABLE_API_KEY", required=True)
    base_id = _resolve_base_id(args.base)
    table = _find_table(token, base_id, args.table_name)
    field = {"name": args.name, "type": args.type}
    if args.options:
        field["options"] = _parse_json_arg(args.options, "options")
    url = f"{META_BASE_URL}/bases/{base_id}/tables/{table['id']}/fields"
    created = _request(token, "POST", url, json_body=field)
    _print_json({"table": args.table_name, "field": created})


def _record_url(base_id, table_name):
    safe_table = parse.quote(table_name, safe="")
    return f"{DATA_BASE_URL}/{base_id}/{safe_table}"


def _normalize_record(record):
    return {
        "id": record.get("id"),
        "fields": record.get("fields", {}),
        "created_time": record.get("createdTime"),
    }


def cmd_record_list(args):
    token = _get_env("AIRTABLE_API_KEY", required=True)
    base_id = _resolve_base_id(args.base)
    url = _record_url(base_id, args.table_name)

    params = {}
    if args.formula:
        params["filterByFormula"] = args.formula
    if args.view:
        params["view"] = args.view
    if args.max:
        params["maxRecords"] = args.max
    if args.sort:
        for idx, item in enumerate(args.sort):
            if ":" not in item:
                _error_exit("Sort must be FIELD:DIR")
            field, direction = item.split(":", 1)
            params[f"sort[{idx}][field]"] = field
            params[f"sort[{idx}][direction]"] = direction

    records = []
    while True:
        data = _request(token, "GET", url, params=params)
        for record in data.get("records", []):
            records.append(_normalize_record(record))
        offset = data.get("offset")
        if offset:
            params["offset"] = offset
            continue
        break

    _print_json({"table": args.table_name, "total_records": len(records), "records": records})


def cmd_record_get(args):
    token = _get_env("AIRTABLE_API_KEY", required=True)
    base_id = _resolve_base_id(args.base)
    url = f"{_record_url(base_id, args.table_name)}/{args.record_id}"
    record = _request(token, "GET", url)
    _print_json({"table": args.table_name, "record": _normalize_record(record)})


def cmd_record_create(args):
    token = _get_env("AIRTABLE_API_KEY", required=True)
    base_id = _resolve_base_id(args.base)
    url = _record_url(base_id, args.table_name)
    fields = _parse_json_arg(args.fields_json, "fields")

    if isinstance(fields, dict):
        records_input = [fields]
    elif isinstance(fields, list):
        records_input = fields
    else:
        _error_exit("FIELDS_JSON must be an object or array")

    created = []
    for chunk in _chunk(records_input, 10):
        payload = {
            "records": [{"fields": item} for item in chunk],
            "typecast": True,
        }
        data = _request(token, "POST", url, json_body=payload)
        for record in data.get("records", []):
            created.append(_normalize_record(record))
    _print_json({"table": args.table_name, "total_records": len(created), "records": created})


def cmd_record_update(args):
    token = _get_env("AIRTABLE_API_KEY", required=True)
    base_id = _resolve_base_id(args.base)
    url = f"{_record_url(base_id, args.table_name)}/{args.record_id}"
    fields = _parse_json_arg(args.fields_json, "fields")
    if not isinstance(fields, dict):
        _error_exit("FIELDS_JSON must be an object")
    payload = {"fields": fields, "typecast": True}
    record = _request(token, "PATCH", url, json_body=payload)
    _print_json({"table": args.table_name, "record": _normalize_record(record)})


def cmd_record_delete(args):
    token = _get_env("AIRTABLE_API_KEY", required=True)
    base_id = _resolve_base_id(args.base)
    url = _record_url(base_id, args.table_name)

    deleted = []
    for chunk in _chunk(args.record_ids, 10):
        params = [("records[]", rec_id) for rec_id in chunk]
        data = _request(token, "DELETE", url, params=params)
        for record in data.get("records", []):
            deleted.append({"id": record.get("id"), "deleted": record.get("deleted")})
    _print_json({"table": args.table_name, "total_records": len(deleted), "records": deleted})


def _format_formula(field_name, value):
    lower = value.lower()
    if lower in {"true", "false"}:
        return f"{{{field_name}}} = {lower}"
    try:
        float(value)
        return f"{{{field_name}}} = {value}"
    except ValueError:
        escaped = value.replace("'", "\\'")
        return f"{{{field_name}}} = '{escaped}'"


def cmd_record_find(args):
    token = _get_env("AIRTABLE_API_KEY", required=True)
    base_id = _resolve_base_id(args.base)
    url = _record_url(base_id, args.table_name)
    formula = _format_formula(args.field_name, args.value)
    params = {"filterByFormula": formula, "maxRecords": 1}
    data = _request(token, "GET", url, params=params)
    records = data.get("records", [])
    if not records:
        _print_json({"table": args.table_name, "found": False, "record": None})
        return
    record = _normalize_record(records[0])
    _print_json({"table": args.table_name, "found": True, "record": record})


def _add_base_arg(parser):
    parser.add_argument(
        "--base",
        dest="base",
        help="Override base ID (otherwise uses AIRTABLE_BASE_ID from .env)",
    )


def build_parser():
    parser = argparse.ArgumentParser(prog="airtable", description="Airtable CLI")
    subparsers = parser.add_subparsers(dest="group", required=True)

    base_parser = subparsers.add_parser("base", help="Base operations")
    base_sub = base_parser.add_subparsers(dest="command", required=True)
    base_list = base_sub.add_parser("list", help="List bases")
    base_list.set_defaults(func=cmd_base_list)

    table_parser = subparsers.add_parser("table", help="Table operations")
    table_sub = table_parser.add_subparsers(dest="command", required=True)

    table_list = table_sub.add_parser("list", help="List tables")
    _add_base_arg(table_list)
    table_list.set_defaults(func=cmd_table_list)

    table_create = table_sub.add_parser("create", help="Create table")
    table_create.add_argument("name", help="Table name")
    table_create.add_argument("--schema", required=True, help="JSON field schema")
    _add_base_arg(table_create)
    table_create.set_defaults(func=cmd_table_create)

    field_parser = subparsers.add_parser("field", help="Field operations")
    field_sub = field_parser.add_subparsers(dest="command", required=True)

    field_add = field_sub.add_parser("add", help="Add field")
    field_add.add_argument("table_name", help="Table name")
    field_add.add_argument("--name", required=True, help="Field name")
    field_add.add_argument("--type", required=True, help="Field type")
    field_add.add_argument("--options", help="Field options JSON")
    _add_base_arg(field_add)
    field_add.set_defaults(func=cmd_field_add)

    record_parser = subparsers.add_parser("record", help="Record operations")
    record_sub = record_parser.add_subparsers(dest="command", required=True)

    record_list = record_sub.add_parser("list", help="List records")
    record_list.add_argument("table_name", help="Table name")
    record_list.add_argument("--formula", help="Filter formula")
    record_list.add_argument("--view", help="View name")
    record_list.add_argument("--max", type=int, help="Max records")
    record_list.add_argument("--sort", action="append", help="Sort as FIELD:DIR")
    _add_base_arg(record_list)
    record_list.set_defaults(func=cmd_record_list)

    record_get = record_sub.add_parser("get", help="Get record")
    record_get.add_argument("table_name", help="Table name")
    record_get.add_argument("record_id", help="Record ID")
    _add_base_arg(record_get)
    record_get.set_defaults(func=cmd_record_get)

    record_create = record_sub.add_parser("create", help="Create record(s)")
    record_create.add_argument("table_name", help="Table name")
    record_create.add_argument("fields_json", help="Fields JSON object or array")
    _add_base_arg(record_create)
    record_create.set_defaults(func=cmd_record_create)

    record_update = record_sub.add_parser("update", help="Update record")
    record_update.add_argument("table_name", help="Table name")
    record_update.add_argument("record_id", help="Record ID")
    record_update.add_argument("fields_json", help="Fields JSON object")
    _add_base_arg(record_update)
    record_update.set_defaults(func=cmd_record_update)

    record_delete = record_sub.add_parser("delete", help="Delete record(s)")
    record_delete.add_argument("table_name", help="Table name")
    record_delete.add_argument("record_ids", nargs="+", help="Record IDs")
    _add_base_arg(record_delete)
    record_delete.set_defaults(func=cmd_record_delete)

    record_find = record_sub.add_parser("find", help="Find record by field value")
    record_find.add_argument("table_name", help="Table name")
    record_find.add_argument("field_name", help="Field name")
    record_find.add_argument("value", help="Field value")
    _add_base_arg(record_find)
    record_find.set_defaults(func=cmd_record_find)

    return parser


def main():
    _load_env()
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
