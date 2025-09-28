#!/usr/bin/env python3
import json, os, re, sys, argparse, shutil, time, getpass
from typing import Any, Dict, List, Tuple, Optional

DATA_DIR_DEFAULT = "data"

# ---------- Path helpers ----------
def _p(data_dir: str, table: str, ext: str) -> str:
    return os.path.join(data_dir, f"{table}.{ext}")

def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_json(path: str, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)

# ---------- Parse & types ----------
def _parse_value(s: str) -> Any:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == "'" and s[-1] == "'") or (s[0] == '"' and s[-1] == '"')):
        return s[1:-1]
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if s.lower() in ("null", "none"):
        return None
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s

def _coerce_single_value(v: Any, typ: str) -> Any:
    if v is None:
        return None
    if typ == "int":
        return int(v)
    if typ == "float":
        return float(v)
    if typ == "bool":
        if isinstance(v, str):
            return v.lower() == "true"
        return bool(v)
    return str(v)

def _merge_versions(base: Dict[str, Any], newer: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply newer values on top of base; newer None means "no change".
    """
    out = dict(base)
    for k, v in newer.items():
        if v is not None:
            out[k] = v
    return out

# ---------- Table renderer (pure Python) ----------
def _truncate(s: str, width: int) -> str:
    s = "" if s is None else str(s)
    if width <= 3:
        return s[:width]
    return s if len(s) <= width else s[: width - 2] + "…"

def _compute_widths(headers: List[str], rows: List[List[str]], max_col_width: int, term_width: Optional[int], padding: int = 1) -> List[int]:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], len(v))
    widths = [min(w, max_col_width) for w in widths]
    total = 1
    for w in widths:
        total += padding + w + padding + 1
    if term_width and total > term_width:
        overflow = total - term_width
        candidates = [i for i, w in enumerate(widths) if w > 8]
        while overflow > 0 and candidates:
            for i in list(candidates):
                if widths[i] > 8 and overflow > 0:
                    widths[i] -= 1
                    overflow -= 1
                if widths[i] <= 8 and i in candidates:
                    candidates.remove(i)
            if not any(widths[i] > 8 for i in candidates):
                break
    return widths

def _draw_line(widths: List[int], chars: Tuple[str, str, str, str, str]) -> str:
    left, mid, cross, right, fill = chars
    parts = [left]
    for i, w in enumerate(widths):
        parts.append(fill * (w + 2))
        parts.append(cross if i < len(widths) - 1 else right)
    return "".join(parts)

def _draw_row(values: List[str], widths: List[int], padding: int, vert: str) -> str:
    out = [vert]
    for i, v in enumerate(values):
        cell = " " * padding + v.ljust(widths[i]) + " " * padding
        out.append(cell)
        out.append(vert)
    return "".join(out)

def _render_table(headers: List[str], rows: List[List[str]], max_col_width: int = 48, use_ascii: bool = False) -> str:
    if use_ascii:
        top = ("+", "+", "+", "+", "-")
        mid = ("+", "+", "+", "+", "-")
        bot = ("+", "+", "+", "+", "-")
        vert = "|"
    else:
        top = ("┌", "┬", "┬", "┐", "─")
        mid = ("├", "┼", "┼", "┤", "─")
        bot = ("└", "┴", "┴", "┘", "─")
        vert = "│"

    try:
        term_width = shutil.get_terminal_size().columns
    except Exception:
        term_width = None

    padding = 1
    raw_rows = [[str(c if c is not None else "") for c in r] for r in rows]
    widths = _compute_widths(headers, raw_rows, max_col_width, term_width, padding)

    # truncate only after measuring widths
    trunc_rows = [[_truncate(v, widths[i]) for i, v in enumerate(r)] for r in raw_rows]

    out = []
    out.append(_draw_line(widths, top))
    out.append(_draw_row(headers, widths, padding, vert))
    out.append(_draw_line(widths, mid))
    for r in trunc_rows:
        out.append(_draw_row(r, widths, padding, vert))
    out.append(_draw_line(widths, bot))
    return "\n".join(out)

def _print_table_from_dicts(dict_rows: List[Dict[str, Any]], headers: List[str], max_col_width: int, use_ascii: bool):
    rows = [[row.get(h, "") for h in headers] for row in dict_rows]
    print(_render_table(headers, rows, max_col_width=max_col_width, use_ascii=use_ascii))

# ---------- Engine ----------
SYSTEM_COLS_ORDER = ["id", "timestamp", "user", "active"]
SYSTEM_COLS_TYPES: Dict[str, str] = {
    "id": "int",
    "timestamp": "int",  # Unix epoch (seconds)
    "user": "text",
    "active": "bool",
}

def _now_epoch() -> int:
    return int(time.time())

def _current_user() -> str:
    return os.environ.get("SQL_USER") or getpass.getuser() or "unknown"

class MiniEngine:
    def __init__(self, data_dir: str = DATA_DIR_DEFAULT):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

    # -------- Table ops --------
    def create_table(self, table: str, colsdef_str: str):
        # 1) parse user columns
        user_schema: Dict[str, str] = {}
        parts = [p for p in colsdef_str.split(",") if p.strip()]
        for part in parts:
            name_type = part.strip().split(":")
            if len(name_type) != 2:
                raise ValueError(f"Invalid column definition: {part}")
            col = name_type[0].strip()
            typ = name_type[1].strip().lower()
            if typ in ("int", "integer"):
                typ = "int"
            elif typ in ("float", "real", "double"):
                typ = "float"
            elif typ in ("bool", "boolean"):
                typ = "bool"
            else:
                typ = "text"
            user_schema[col] = typ

        # 2) enforce system columns at the start with correct types
        schema: Dict[str, str] = {}
        for c in SYSTEM_COLS_ORDER:
            schema[c] = SYSTEM_COLS_TYPES[c]
        # 3) add user columns (don’t overwrite system columns)
        for col, typ in user_schema.items():
            if col in SYSTEM_COLS_TYPES:
                continue
            schema[col] = typ

        _save_json(_p(self.data_dir, table, "schema.json"), schema)
        open(_p(self.data_dir, table, "ndjson"), "a", encoding="utf-8").close()

    def show_schema(self, table: str) -> Dict[str, str]:
        schema = _load_json(_p(self.data_dir, table, "schema.json"), None)
        if schema is None:
            raise ValueError(f"Table '{table}' does not exist.")
        # Guarantee system columns (retrofit for existing tables)
        changed = False
        for c in SYSTEM_COLS_ORDER:
            if c not in schema or schema[c] != SYSTEM_COLS_TYPES[c]:
                schema[c] = SYSTEM_COLS_TYPES[c]
                changed = True
        # Restore system columns at the front
        if changed or list(schema.keys())[:4] != SYSTEM_COLS_ORDER:
            rest = [k for k in schema.keys() if k not in SYSTEM_COLS_TYPES]
            new_schema = {c: SYSTEM_COLS_TYPES[c] for c in SYSTEM_COLS_ORDER}
            for k in rest:
                new_schema[k] = schema[k]
            schema = new_schema
            _save_json(_p(self.data_dir, table, "schema.json"), schema)
        return schema

    def list_tables(self) -> List[str]:
        names = set()
        for fn in os.listdir(self.data_dir):
            if fn.endswith(".schema.json"):
                names.add(fn[:-12])
        return sorted(names)

    # -------- Insert / upsert (append-only) --------
    def insert(self, table: str, values_expr: str) -> Dict[str, Any]:
        """
        Accepts a subset of columns. If id is present, this acts as a new version for that id.
        Example: "id=1, name='John'"
        System columns are auto-filled: id (auto), timestamp (now), user (OS), active (true by default).
        """
        schema = self.show_schema(table)
        kv = self._parse_kv_list(values_expr)
        row_raw = {k: _parse_value(v) for k, v in kv.items()}

        # auto-increment id if not provided
        if "id" not in row_raw or row_raw["id"] is None or row_raw["id"] == "":
            next_id = self._next_id(table)
            row_raw["id"] = next_id

        # defaults for system columns
        row_raw.setdefault("timestamp", _now_epoch())
        row_raw.setdefault("user", _current_user())
        row_raw.setdefault("active", True)

        # type coercion + fill missing columns with None
        row: Dict[str, Any] = {}
        for col, typ in schema.items():
            if col in row_raw:
                row[col] = _coerce_single_value(row_raw[col], typ)
            else:
                row[col] = None

        ndjson = _p(self.data_dir, table, "ndjson")
        with open(ndjson, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        line_nr = self._rowcount(ndjson) - 1
        self._update_indexes_after_insert(table, row, line_nr)
        return row

    # -------- Deactivate (soft-delete) --------
    def deactivate(self, table: str, id_value: Any) -> Dict[str, Any]:
        schema = self.show_schema(table)
        act_col = "active"
        if act_col not in schema:
            raise ValueError("Table is missing required column 'active'.")

        row = {col: None for col in schema.keys()}
        row["id"] = _coerce_single_value(id_value, schema["id"]) if "id" in schema else id_value
        row[act_col] = False
        # update system fields
        row["timestamp"] = _now_epoch()
        row["user"] = _current_user()

        ndjson = _p(self.data_dir, table, "ndjson")
        with open(ndjson, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        line_nr = self._rowcount(ndjson) - 1
        self._update_indexes_after_insert(table, row, line_nr)
        return row

    # -------- Select with version collapse --------
    def select(self, table: str, cols: List[str], where: Optional[str], history: bool=False) -> List[Dict[str, Any]]:
        schema = self.show_schema(table)
        ndjson = _p(self.data_dir, table, "ndjson")
        if not os.path.exists(ndjson):
            return []

        filters = self._parse_where(where) if where else []

        rows_with_line: List[Tuple[int, Dict[str, Any]]] = []
        with open(ndjson, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if not line.strip():
                    continue
                r = json.loads(line)
                rows_with_line.append((i, r))

        if history:
            out = []
            for ln, r in rows_with_line:
                if self._row_matches_filters(r, filters):
                    out.append(self._project(r, cols))
            return out

        if "id" not in schema:
            out = []
            for ln, r in reversed(rows_with_line):
                if self._row_matches_filters(r, filters):
                    out.append(self._project(r, cols))
            return list(reversed(out))

        latest_per_id: Dict[Any, Tuple[int, Dict[str, Any]]] = {}
        for ln, r in rows_with_line:
            rid = r.get("id", None)
            if rid is None:
                continue
            ridc = _coerce_single_value(rid, schema["id"]) if "id" in schema else rid
            if ridc not in latest_per_id:
                latest_per_id[ridc] = (ln, dict(r))
            else:
                _, base = latest_per_id[ridc]
                merged = _merge_versions(base, r)
                latest_per_id[ridc] = (ln, merged)

        results = []
        for ridc, (ln, rmerged) in latest_per_id.items():
            if self._row_matches_filters(rmerged, filters):
                results.append(self._project(rmerged, cols))
        # Apply ORDER (set by CLI via eng._order_keys)
        order = getattr(self, "_order_keys", [])
        results = self._sort_rows(results, schema, order)
        return results

    # -------- Show history for a single id --------
    def show_history(self, table: str, id_value: Any) -> List[Dict[str, Any]]:
        schema = self.show_schema(table)
        ndjson = _p(self.data_dir, table, "ndjson")
        if not os.path.exists(ndjson):
            return []
        out = []
        with open(ndjson, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if not line.strip():
                    continue
                r = json.loads(line)
                if "id" in r:
                    try:
                        ridc = _coerce_single_value(r["id"], schema["id"])
                    except Exception:
                        ridc = r["id"]
                    if ridc == _coerce_single_value(id_value, schema["id"]):
                        out.append({"line": i, "row": r})
        return out

    # -------- Index ops --------
    def create_index(self, table: str, column: str):
        schema = self.show_schema(table)
        if column not in schema:
            raise ValueError(f"Column '{column}' does not exist in '{table}'.")
        ndjson = _p(self.data_dir, table, "ndjson")
        idx: Dict[str, List[int]] = {}
        if os.path.exists(ndjson):
            with open(ndjson, "r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    key = json.dumps(row.get(column, None), ensure_ascii=False)
                    idx.setdefault(key, []).append(i)
        _save_json(_p(self.data_dir, table, f"{column}.idx.json"), idx)

    def drop_index(self, table: str, column: str):
        path = _p(self.data_dir, table, f"{column}.idx.json")
        if os.path.exists(path):
            os.remove(path)

    # -------- Helpers --------
    def _parse_where(self, expr: str) -> List[Tuple[str, str, Any]]:
        parts = re.split(r"(?i)\s+AND\s+", expr.strip()) if expr else []
        filters = []
        m_re = re.compile(r"^\s*(\w+)\s*(=|!=|<=|>=|<|>|LIKE|ILIKE)\s*(.+?)\s*$", re.I)
        for p in parts:
            m = m_re.match(p)
            if not m:
                raise ValueError(f"Invalid WHERE condition: {p}")
            col, op, valraw = m.group(1), m.group(2), m.group(3)
            filters.append((col, op, _parse_value(valraw)))
        return filters

    def _row_matches_filters(self, row: Dict[str, Any], filters: List[Tuple[str, str, Any]]) -> bool:
        for col, op, val in filters:
            lv = row.get(col, None)
            if op == "=":
                if lv != val: return False
            elif op == "!=":
                if lv == val: return False
            elif op == "<":
                if not (lv is not None and lv < val): return False
            elif op == "<=":
                if not (lv is not None and lv <= val): return False
            elif op == ">":
                if not (lv is not None and lv > val): return False
            elif op == ">=":
                if not (lv is not None and lv >= val): return False
            elif op.upper() == "LIKE":
                # convert % to regex wildcard
                pattern = str(val).replace("%", ".*")
                if lv is None or not re.match("^" + pattern + "$", str(lv)):
                    return False
            elif op.upper() == "ILIKE":
                pattern = str(val).replace("%", ".*")
                if lv is None or not re.match("^" + pattern + "$", str(lv), flags=re.IGNORECASE):
                    return False
        return True

    def _parse_order(self, schema: Dict[str, str], order_expr: Optional[str]) -> List[Tuple[str, bool]]:
        """
        Parse 'column [ASC|DESC], column2 [ASC|DESC]' -> list [(column, asc_bool), ...]
        Unknown columns raise an error.
        """
        if not order_expr or not order_expr.strip():
            # default: if 'id' in schema, sort by id ASC, else no ordering
            return [("id", True)] if "id" in schema else []

        out: List[Tuple[str, bool]] = []
        parts = [p.strip() for p in order_expr.split(",") if p.strip()]
        for p in parts:
            tokens = p.split()
            col = tokens[0]
            if col not in schema:
                raise ValueError(f"ORDER BY: column '{col}' does not exist.")
            if len(tokens) >= 2:
                dirword = tokens[1].upper()
                if dirword not in ("ASC", "DESC"):
                    raise ValueError(f"ORDER BY: invalid direction in '{p}' (use ASC or DESC).")
                asc = (dirword == "ASC")
            else:
                asc = True
            out.append((col, asc))
        return out

    def _sort_rows(self, rows: List[Dict[str, Any]], schema: Dict[str, str], order: List[Tuple[str, bool]]) -> List[Dict[str, Any]]:
        """
        Sort list of dicts using schema types and order keys.
        - text -> casefold() for stable case-insensitive sorting
        - bool -> sort as int (False=0, True=1)
        - None -> always smallest value (NULLS FIRST)
        """
        if not order:
            return rows  # nothing to do

        def key_for_col(col: str, typ: str):
            def _k(v):
                if v is None:
                    if typ in ("int", "float", "bool"):
                        return (0, 0)
                    return (0, "")
                if typ == "int":
                    try:
                        return (1, int(v))
                    except Exception:
                        return (1, str(v))
                if typ == "float":
                    try:
                        return (1, float(v))
                    except Exception:
                        return (1, str(v))
                if typ == "bool":
                    try:
                        return (1, 1 if bool(v) else 0)
                    except Exception:
                        return (1, 0)
                # text/other
                return (1, str(v).casefold())
            return _k

        # Python cannot mix asc/desc per key in a single sort call reliably:
        # do stable sorts in reverse priority, one key at a time.
        out = list(rows)
        for col, asc in reversed(order):
            typ = schema.get(col, "text")
            kfunc = key_for_col(col, typ)
            out.sort(key=lambda r: kfunc(r.get(col, None)), reverse=not asc)
        return out

    def _project(self, row: Dict[str, Any], cols: List[str]) -> Dict[str, Any]:
        if cols == ["*"]:
            return row
        return {c: row.get(c, None) for c in cols}

    def _parse_kv_list(self, s: str) -> Dict[str, str]:
        items, cur, q, out = [], "", None, {}
        for ch in s:
            if q:
                cur += ch
                if ch == q:
                    q = None
            else:
                if ch in ("'", '"'):
                    q = ch
                    cur += ch
                elif ch == ",":
                    if cur.strip():
                        items.append(cur.strip())
                    cur = ""
                else:
                    cur += ch
        if cur.strip():
            items.append(cur.strip())
        for it in items:
            if "=" not in it:
                raise ValueError(f"Invalid key=value pair: {it}")
            k, v = it.split("=", 1)
            out[k.strip()] = v.strip()
        return out

    def _rowcount(self, ndjson_path: str) -> int:
        c = 0
        with open(ndjson_path, "r", encoding="utf-8") as f:
            for _ in f:
                c += 1
        return c

    def _has_index(self, table: str, column: str) -> bool:
        return os.path.exists(_p(self.data_dir, table, f"{column}.idx.json"))

    def _idx_lookup(self, table: str, column: str, value: Any) -> List[int]:
        idx = _load_json(_p(self.data_dir, table, f"{column}.idx.json"), {})
        key = json.dumps(value, ensure_ascii=False)
        return idx.get(key, [])

    def _update_indexes_after_insert(self, table: str, row: Dict[str, Any], line_nr: int):
        for fn in os.listdir(self.data_dir):
            if fn.startswith(f"{table}.") and fn.endswith(".idx.json"):
                col = fn[len(table)+1:-9]
                val = row.get(col, None)
                key = json.dumps(val, ensure_ascii=False)
                path = _p(self.data_dir, table, f"{col}.idx.json")
                idx = _load_json(path, {})
                idx.setdefault(key, []).append(line_nr)
                _save_json(path, idx)

    def _next_id(self, table: str) -> int:
        """Find highest id in the table and return +1. If empty, start at 1."""
        ndjson = _p(self.data_dir, table, "ndjson")
        max_id = 0
        if os.path.exists(ndjson):
            with open(ndjson, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        r = json.loads(line)
                        if "id" in r and r["id"] is not None:
                            rid = int(r["id"])
                            if rid > max_id:
                                max_id = rid
                    except Exception:
                        continue
        return max_id + 1

# ============ CLI ============
def main():
    parser = argparse.ArgumentParser(description="Mini append-only SQL (versioned rows + soft-delete).")
    parser.add_argument("--data-dir", default=DATA_DIR_DEFAULT, help="Directory for data files")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    # global output options
    parser.add_argument("--output", choices=["json", "table"], default="json", help="Output format")
    parser.add_argument("--ascii", action="store_true", help="ASCII borders in table")
    parser.add_argument("--max-col-width", type=int, default=48, help="Max column width in table")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ct = sub.add_parser("create-table", help="Create a table")
    p_ct.add_argument("table")
    p_ct.add_argument("--cols", required=True, help='E.g. "name:text, email:text" (system columns are auto-added)')

    sub.add_parser("list-tables", help="List tables")

    p_ss = sub.add_parser("show-schema", help="Show schema")
    p_ss.add_argument("table")

    p_ins = sub.add_parser("insert", help="Insert (or update) a row as a new version (append). id is optional (auto-increment).")
    p_ins.add_argument("table")
    p_ins.add_argument("--values", required=True, help='E.g. "name=\'John\', email=\'john@example.com\'" or "id=1, name=\'John\'"')
    p_ins.add_argument("--user", help="Override user for this insert")

    p_deact = sub.add_parser("deactivate", help="Soft-delete: append a version with active=false")
    p_deact.add_argument("table")
    p_deact.add_argument("id")
    p_deact.add_argument("--user", help="Override user for this deactivate")

    p_sel = sub.add_parser("select", help="Select (default: latest version per id)")
    p_sel.add_argument("table")
    p_sel.add_argument("--cols", default="*", help='"id,name" or "*"')
    p_sel.add_argument("--where", default=None, help='E.g. "active = true AND id >= 1"')
    p_sel.add_argument("--history", action="store_true", help="Show all versions (chronological)")
    p_sel.add_argument("--order", default=None, help='ORDER BY, e.g.: "name ASC, timestamp DESC"')

    p_hist = sub.add_parser("show-history", help="Show all versions for one id")
    p_hist.add_argument("table")
    p_hist.add_argument("id")

    p_cix = sub.add_parser("create-index", help="Create index on column")
    p_cix.add_argument("table"); p_cix.add_argument("column")
    p_dix = sub.add_parser("drop-index", help="Drop index")
    p_dix.add_argument("table"); p_dix.add_argument("column")

    args = parser.parse_args()
    eng = MiniEngine(args.data_dir)

    def print_json(obj):
        print(json.dumps(obj, ensure_ascii=False, indent=2 if args.pretty else None))

    try:
        if args.cmd == "create-table":
            eng.create_table(args.table, args.cols)
            print_json({"ok": True, "table": args.table})

        elif args.cmd == "list-tables":
            tables = eng.list_tables()
            if args.output == "table":
                rows = [{"table": t} for t in tables]
                _print_table_from_dicts(rows, ["table"], args.max_col_width, args.ascii)
            else:
                print_json(tables)

        elif args.cmd == "show-schema":
            schema = eng.show_schema(args.table)
            if args.output == "table":
                rows = [{"column": k, "type": v} for k, v in schema.items()]
                _print_table_from_dicts(rows, ["column", "type"], args.max_col_width, args.ascii)
            else:
                print_json(schema)

        elif args.cmd == "insert":
            if args.user:
                os.environ["SQL_USER"] = args.user
            row = eng.insert(args.table, args.values)
            print_json({"ok": True, "inserted": row})

        elif args.cmd == "deactivate":
            if args.user:
                os.environ["SQL_USER"] = args.user
            row = eng.deactivate(args.table, _parse_value(args.id))
            print_json({"ok": True, "deactivated": row})

        elif args.cmd == "select":
            cols = [c.strip() for c in args.cols.split(",")] if args.cols.strip() != "*" else ["*"]

            # ORDER parsing + pass to engine
            schema_for_order = eng.show_schema(args.table)
            eng._order_keys = eng._parse_order(schema_for_order, args.order)

            rows = eng.select(args.table, cols, args.where, history=args.history)
            if args.output == "table":
                # headers
                if cols == ["*"]:
                    schema = eng.show_schema(args.table)
                    headers = list(schema.keys())
                else:
                    headers = cols
                dict_rows = []
                for r in rows:
                    if cols == ["*"]:
                        schema = eng.show_schema(args.table)
                        dict_rows.append({k: r.get(k, "") for k in schema.keys()})
                    else:
                        dict_rows.append({k: r.get(k, "") for k in headers})
                _print_table_from_dicts(dict_rows, headers, args.max_col_width, args.ascii)
            else:
                print_json(rows)

        elif args.cmd == "show-history":
            idval = _parse_value(args.id)
            hist = eng.show_history(args.table, idval)
            if args.output == "table":
                schema = eng.show_schema(args.table)
                headers = ["line"] + list(schema.keys())
                dict_rows = []
                for item in hist:
                    row = {"line": item.get("line", "")}
                    raw = item.get("row", {})
                    for k in schema.keys():
                        row[k] = raw.get(k, "")
                    dict_rows.append(row)
                _print_table_from_dicts(dict_rows, headers, args.max_col_width, args.ascii)
            else:
                print_json(hist)

        elif args.cmd == "create-index":
            eng.create_index(args.table, args.column)
            print_json({"ok": True, "index": {"table": args.table, "column": args.column}})

        elif args.cmd == "drop-index":
            eng.drop_index(args.table, args.column)
            print_json({"ok": True, "dropped": {"table": args.table, "column": args.column}})

        else:
            parser.error("Unknown subcommand.")

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
