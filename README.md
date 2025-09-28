# Mini Append-Only SQL (Single File)

A tiny, **append-only**, SQL-ish datastore in one Python script.  
Great for quick CLI workflows, logging with **full version history**, and prototyping without running a real database.

- **Append-only:** every change is a new version; nothing is overwritten  
- **Soft-delete:** `deactivate` marks a record inactive while keeping its history  
- **Version collapsing:** `select` shows the **latest version per `id`** by default  
- **WHERE / LIKE / ILIKE / ORDER BY** support  
- **Per-column indices** (simple JSON-based)  
- **Pretty table output** (ASCII or Unicode)  
- **Zero dependencies** (Python 3.9+)

---

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Overview](#cli-overview)
- [Examples](#examples)
- [On-Disk Data Layout](#on-disk-data-layout)
- [Filters (WHERE) & Patterns](#filters-where--patterns)
- [Sorting (ORDER BY)](#sorting-order-by)
- [Versioning & Soft-Delete](#versioning--soft-delete)
- [Indices](#indices)
- [Table Output](#table-output)
- [Environment Variables](#environment-variables)
- [Limitations & Roadmap](#limitations--roadmap)
- [License](#license)
- [Maintainer](#maintainer)

---

## Requirements

- Python **3.9+**
- No external packages required

---

## Installation

```bash
git clone <your-repo-url>
cd <your-repo-folder>
# Optional: own data directory (default is ./data)
mkdir -p data
python3 --version
Quick Start
bash
Copy code
# 1) Create a table (system columns auto-added: id, timestamp, user, active)
python sql.py create-table customers --cols "name:text, email:text"

# 2) Insert a row
python sql.py insert customers --values "name='Alice', email='alice@example.com'"

# 3) View rows (JSON or table)
python sql.py select customers --cols "*"              # JSON (default)
python sql.py select customers --cols "*" --output table

# 4) Soft-delete (mark as inactive)
python sql.py deactivate customers 1

# 5) Show history of a single id
python sql.py show-history customers 1 --output table
CLI Overview
text
Copy code
usage: sql.py [-h] [--data-dir DATA_DIR] [--pretty]
              [--output {json,table}] [--ascii]
              [--max-col-width MAX_COL_WIDTH]
              {create-table,list-tables,show-schema,insert,deactivate,select,show-history,create-index,drop-index} ...
Global options

--data-dir path for storage (default data)

--pretty pretty-print JSON

--output json|table output format

--ascii use ASCII borders in table output

--max-col-width N maximum column width for table output

Subcommands

create-table <table> --cols "name:text, email:text"

list-tables

show-schema <table>

insert <table> --values "name='X', email='Y'" [--user someone]

deactivate <table> <id> [--user someone]

select <table> [--cols "*|a,b,c"] [--where "..."] [--history] [--order "..."]

show-history <table> <id>

create-index <table> <column>

drop-index <table> <column>

Examples
Filter active rows starting with “A” (case-insensitive) and sort by name:

bash
Copy code
python sql.py select customers \
  --where "active = true AND name ILIKE 'A%'" \
  --order "name ASC" \
  --output table
Select specific columns and sort by multiple keys:

bash
Copy code
python sql.py select customers \
  --cols "id,name,email" \
  --order "active DESC, timestamp DESC" \
  --output table
Insert with explicit id (creates a new version of that row):

bash
Copy code
python sql.py insert customers --values "id=5, name='Alice v2'"
Soft-delete (sets active=false):

bash
Copy code
python sql.py deactivate customers 5
History for a single id (all versions, chronological):

bash
Copy code
python sql.py show-history customers 5 --output table
On-Disk Data Layout
Each table uses the following files in --data-dir:

<table>.schema.json — schema including system columns

<table>.ndjson — one JSON object per line (append-only)

<table>.<column>.idx.json — optional per-column index

Schema example (customers.schema.json):

json
Copy code
{
  "id": "int",
  "timestamp": "int",
  "user": "text",
  "active": "bool",
  "name": "text",
  "email": "text"
}
Data line example (customers.ndjson):

json
Copy code
{"id":1,"timestamp":1727520000,"user":"daniel","active":true,"name":"Alice","email":"alice@example.com"}
Filters (WHERE) & Patterns
Supported operators: = != < <= > >= LIKE ILIKE
Combine multiple conditions with AND.

LIKE is case-sensitive

ILIKE is case-insensitive

% is the wildcard (internally translated to a regex)

Examples:

name LIKE 'Al%ce'

email ILIKE '%@example.com'

active = true AND id >= 10

bash
Copy code
python sql.py select customers --where "email ILIKE '%@example.com' AND active = true"
Sorting (ORDER BY)
Use --order "column [ASC|DESC], column2 [ASC|DESC]".

Type-aware sorting:

int, float, bool (False=0, True=1)

text uses case-insensitive ordering

None always sorts as the smallest value (NULLS FIRST)

Default: if --order is omitted and the table has an id column → ORDER BY id ASC.

Versioning & Soft-Delete
Append-only: every insert writes a new line.

If id matches a previous row, missing fields are treated as “no change” and merged with the previous version.

select (without --history) returns the latest merged version per id.

deactivate <id> writes a new version with active=false (not removed; always visible in show-history).

Indices
Create or drop a basic per-column index:

bash
Copy code
python sql.py create-index customers email
python sql.py drop-index customers email
Index files are simple JSON maps from exact value → list of line numbers.
Use indices for columns you often query with = (exact match).

Table Output
Use --output table to render a readable terminal table.
Unicode borders by default; switch to ASCII with --ascii.
Columns auto-truncate; adjust width with --max-col-width.

bash
Copy code
python sql.py select customers --cols "id,name,email" --output table --ascii --max-col-width 40
Environment Variables
SQL_USER — used for the user column (falls back to OS user).
You can also override per command with --user on insert/deactivate.

bash
Copy code
SQL_USER=robot python sql.py insert customers --values "name='Bot', email='bot@ex.com'"
Limitations & Roadmap
This project is:

A simple, transparent datastore for scripts, tools, demos

Human-readable JSON on disk, easy to back up

Append-only with full history and soft-delete

This project is not:

A transactional database (no concurrency control yet)
→ Use a single writer at a time or add OS-level locks (e.g., flock) if you need concurrent writes

A full SQL engine (WHERE is a small subset)

Featuring advanced indices (exact-match only)

Possible future work:

File locking for safe concurrent inserts

Faster select using index-aware scanning

CSV import/export

Optional compact binary storage alongside NDJSON

License
Add a LICENSE file of your choice (e.g., MIT).

Example MIT header:

php-template
Copy code
MIT License — © <year> <your name / company>
Maintainer
Daniël Hendriks — HZE B.V.
