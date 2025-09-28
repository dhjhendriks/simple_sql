# Mini Append-Only SQL Engine (Python)

This project is a lightweight, append-only SQL-like database implemented in pure Python.  
It stores data in JSON (newline-delimited JSON per row), supports **versioned rows**, **soft deletes**,  
and includes a simple **CLI** for managing tables, inserting data, and querying with filters and ordering.

---

## Features

- Tables stored as JSON files inside a data directory
- System columns automatically added:
  - `id` (integer, auto-increment if not given)
  - `timestamp` (Unix epoch seconds)
  - `user` (OS user or overridden with `--user`)
  - `active` (boolean, soft delete marker)
- Append-only storage: rows are never removed, only new versions are added
- Soft delete via `deactivate` command (sets `active=false`)
- Querying with `select`, including:
  - `WHERE` filtering (`=`, `!=`, `<`, `<=`, `>`, `>=`, `LIKE`, `ILIKE`)
  - `ORDER BY` with ascending/descending order
  - `--history` flag to view all versions of rows
- Optional indexes on columns for faster lookups
- Multiple output formats:
  - JSON (default)
  - Pretty table (Unicode or ASCII borders)

---

## Installation

Clone the repository and make the script executable:

```bash
git clone https://github.com/yourname/minisql.git
cd minisql
chmod +x sql.py
Run with Python 3.8+:

bash
Copy code
./sql.py --help
Usage
Create a table
bash
Copy code
./sql.py create-table customers --cols "name:text, email:text"
Insert rows
bash
Copy code
./sql.py insert customers --values "name='Alice', email='alice@example.com'"
./sql.py insert customers --values "id=1, email='alice@newmail.com'"
Soft delete (deactivate)
bash
Copy code
./sql.py deactivate customers 1
List tables
bash
Copy code
./sql.py list-tables
Show schema
bash
Copy code
./sql.py show-schema customers
Select data
bash
Copy code
# Latest version per id
./sql.py select customers --cols "id,name,email"

# With WHERE and ORDER
./sql.py select customers --where "active = true AND id >= 1" --order "name ASC"

# Show full history
./sql.py select customers --history
Show history for one row
bash
Copy code
./sql.py show-history customers 1
Index management
bash
Copy code
./sql.py create-index customers email
./sql.py drop-index customers email
Output Formats
Default: JSON

bash
Copy code
./sql.py select customers
Pretty table output:

bash
Copy code
./sql.py select customers --output table
./sql.py select customers --output table --ascii
Example
bash
Copy code
./sql.py create-table users --cols "name:text, email:text"
./sql.py insert users --values "name='Bob', email='bob@example.com'"
./sql.py select users --output table
Result:

sql
Copy code
┌────┬─────────────┬───────────┬─────────┬───────┬─────────────────────┐
│ id │ timestamp   │ user      │ active  │ name  │ email               │
├────┼─────────────┼───────────┼─────────┼───────┼─────────────────────┤
│ 1  │ 1695908400  │ daniel    │ true    │ Bob   │ bob@example.com     │
└────┴─────────────┴───────────┴─────────┴───────┴─────────────────────┘
Notes
Data is stored in the data/ directory by default (can be changed with --data-dir)

Every insert or deactivate appends a new JSON line; no data is ever overwritten

This design makes it easy to audit history and recover past states

License
MIT License. Free to use, modify, and share.
