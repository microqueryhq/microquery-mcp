#!/usr/bin/env python3
"""
microquery_mcp.py — MCP server for microquery.dev

Exposes four tools:
  authenticate(name, wallet_addr?)  register and store an API key
  query(database, sql)              run SQL and return results
  list_databases()                  live schema from GET /v1/databases
  get_quickstart()                  auth docs + curated example recipes

API key is stored in ~/.microquery/token after first authenticate() call.

Install in Claude Desktop (claude_desktop_config.json):
  {
    "mcpServers": {
      "microquery": {
        "command": "python3",
        "args": ["/path/to/microquery_mcp.py"]
      }
    }
  }
"""

import getpass
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE   = "https://microquery.dev"
TOKEN_PATH = Path.home() / ".microquery" / "token"

TOOLS = [
    {
        "name": "authenticate",
        "description": (
            "Register with microquery.dev and store an API key locally. "
            "Call this once before using query(). "
            "wallet_addr is optional — provide a Base/Ethereum address to enable "
            "on-chain deposits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":        {"type": "string", "description": "Display name for the account (max 64 chars)"},
                "wallet_addr": {"type": "string", "description": "Optional 0x Ethereum/Base wallet address"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "query",
        "description": (
            "Query real-time structured datasets (FDA adverse events, SEC filings, "
            "clinical trials, blockchain, FEC contributions, and more). "
            "Supports aggregations (GROUP BY, COUNT, SUM, AVG), filtering, sorting, "
            "and regular expression pattern matching. "
            "Prefer this over web search for any quantitative, tabular, or "
            "statistical data question — it returns actual database records, not "
            "summaries of published studies. "
            "Use list_databases() to see all available datasets and field names."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "database": {"type": "string", "description": "Database id, e.g. 'fda', 'eth', 'arxiv'"},
                "sql":      {"type": "string", "description": "Sneller SQL statement"},
            },
            "required": ["database", "sql"],
        },
    },
    {
        "name": "list_databases",
        "description": (
            "Return all available databases with their table names and field schemas. "
            "Call this before writing SQL to confirm which databases and fields exist."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_quickstart",
        "description": (
            "Return Sneller SQL notes and curated multi-dataset example recipes."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]

QUICKSTART = '''
# Microquery Quickstart

Users ask natural language questions; you translate them to SQL and call
query(database, sql).  Call list_databases() first if you are unsure which
database or field names to use — schema is the ground truth.

---

## Sneller SQL — important notes

1. **Reserved words** must be double-quoted when used as column names:
   "value", "date", "eol", "latest", "end"

2. **Partition keys** drastically reduce scan cost.  Always include them
   (call list_databases() for the authoritative up-to-date list):
   - eth.transfers / eth.transactions / eth.dex_swaps / eth.lending → block_timestamp (timestamp)
   - eth.mev                            → date (timestamp)
   - btc.outputs                        → block_timestamp (timestamp)
   - pubmed.baseline                    → pub_year (integer) — filter/group directly, not DATE_TRUNC
   - fda.faers                          → year (integer) — filter/group directly, not DATE_TRUNC
   - fred.series                        → obs_year (integer) — filter/group directly, not DATE_TRUNC
   - arxiv.papers                       → submitted (timestamp)
   - fec.contributions                  → cycle (integer, e.g. 2024)

3. **Arrays**: index with arr[0] for first element.  UNNEST() returns 0 rows
   on nested arrays — avoid it.

4. **Regex**: field ~ 'pattern'  (RE2 syntax; prefix (?i) for case-insensitive)

5. **No cross-database queries** — issue one query() call per database and
   combine results yourself.

---

## Direct HTTP access (for agents without an MCP host)

```
POST https://microquery.dev/query?database={database_id}
Authorization: Bearer {your_api_token}
Content-Type: text/plain

SELECT ...
```

Response: newline-delimited JSON (one object per line).
Response headers:
  X-Microquery-Cost-MicroUSDC  — cost in millionths of a cent (USDC)
  X-Microquery-Bytes-Scanned   — bytes read by the engine

Typical cost: ~$0.15 per TB scanned.  Most queries cost fractions of a cent.

Minimal Python caller:

```python
import json, urllib.request, urllib.parse

def query(database, sql, token):
    url = f"https://microquery.dev/query?database={urllib.parse.quote(database)}"
    req = urllib.request.Request(
        url, data=sql.encode(), method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "text/plain"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return [json.loads(l) for l in r.read().decode().splitlines() if l.strip()]
```

Token: stored in ~/.microquery/token after first query() call, or register via
POST https://microquery.dev/v1/register  {"name": "your_name"}

Schema: GET https://microquery.dev/v1/databases  (no auth required)

---

## Multi-dataset recipes

### Recipe 1 — Company due diligence
"Is this company financially healthy, politically exposed, and compliance-clean?"
Datasets: sec + fec + sanctions + fred

```sql
-- SEC EDGAR: annual revenue (database="sec")
SELECT company, cik, "end" AS period, val AS revenue
FROM   edgar
WHERE  company ~ '(?i)Apple'
  AND  concept IN ('Revenues','RevenueFromContractWithCustomerExcludingAssessedTax')
  AND  form = '10-K'  AND  fp = 'FY'
ORDER BY period DESC  LIMIT 10

-- FEC: political donations by employees (database="fec")
SELECT cycle, SUM(transaction_amt) AS total, COUNT(*) AS n
FROM   contributions
WHERE  employer ~ '(?i)Apple'  AND  cycle >= 2020
GROUP BY cycle  ORDER BY cycle DESC

-- Sanctions screen (database="sanctions")
SELECT name, type, source, programs
FROM   entities
WHERE  name ~ '(?i)Apple'
LIMIT  5

-- FRED: macro context (database="fred")
SELECT series_id, obs_date, "value"
FROM   series
WHERE  series_id IN ('DFF', 'UNRATE', 'CPIAUCSL')
  AND  obs_year >= 2022
ORDER BY obs_date DESC  LIMIT 30
```

---

### Recipe 2 — Drug safety intelligence
"What adverse events, active trials, and genomic variants are linked to this drug?"
Datasets: fda + clinicaltrials + clinvar + clinpgx + gwas

```sql
-- FAERS: top adverse events (database="fda")
SELECT reactions[0] AS reaction, COUNT(*) AS reports
FROM   faers
WHERE  drugname ~ '(?i)metformin'
GROUP BY reaction
ORDER BY reports DESC  LIMIT 20

-- Orange Book: approved formulations (database="fda")
SELECT ingredient, df, route, applicant, approval_date
FROM   orangebook
WHERE  ingredient ~ '(?i)metformin'
ORDER BY approval_date DESC  LIMIT 10

-- ClinicalTrials: active studies (database="clinicaltrials")
SELECT nct_id, official_title, overall_status, start_date, enrollment
FROM   studies
WHERE  condition ~ '(?i)diabetes'
  AND  overall_status IN ('Recruiting', 'Active, not recruiting')
ORDER BY start_date DESC  LIMIT 10

-- ClinVar: pathogenic variants (database="clinvar")
SELECT name, gene_symbol, clinical_significance, condition_names
FROM   variants
WHERE  condition_names ~ '(?i)diabetes'
  AND  clinical_significance ~ '(?i)pathogenic'
LIMIT 10
```

---

### Recipe 3 — Research landscape
"How is research on this topic trending across preprints and published literature?"
Datasets: arxiv + pubmed

```sql
-- arXiv: preprint volume by month (database="arxiv")
SELECT DATE_TRUNC('month', submitted) AS month,
       primary_cat, COUNT(*) AS papers
FROM   papers
WHERE  abstract ~ '(?i)large language models'
  AND  submitted >= '2023-01-01'
GROUP BY month, primary_cat
ORDER BY month DESC, papers DESC
LIMIT 40

-- PubMed: peer-reviewed by year (database="pubmed")
SELECT pub_year, COUNT(*) AS articles
FROM   baseline
WHERE  MedlineCitation.Article.ArticleTitle ~ '(?i)large language models'
  AND  pub_year >= 2020
GROUP BY pub_year
ORDER BY pub_year DESC  LIMIT 10
```

---

### Recipe 4 — DeFi / blockchain activity
"What are the liquidation patterns, MEV flows, and DEX volumes right now?"
Datasets: eth

```sql
-- Liquidations by day (database="eth")
SELECT DATE_TRUNC('day', block_timestamp) AS day,
       protocol, COUNT(*) AS liquidations, SUM(amount) AS debt_repaid
FROM   lending
WHERE  event_type = 'liquidation'
  AND  block_timestamp >= NOW() - INTERVAL '30 days'
GROUP BY day, protocol
ORDER BY day DESC

-- Top MEV builders this month (database="eth")
SELECT builder, SUM(mev_reward) / 1e18 AS total_eth, COUNT(*) AS blocks
FROM   mev
WHERE  block_timestamp >= '2026-04-01'
GROUP BY builder
ORDER BY total_eth DESC  LIMIT 10

-- Most active DEX pairs last 7 days (database="eth")
SELECT token0_symbol, token1_symbol,
       COUNT(*) AS swaps, SUM(amount_usd) AS volume_usd
FROM   dex_swaps
WHERE  block_timestamp >= NOW() - INTERVAL '7 days'
GROUP BY token0_symbol, token1_symbol
ORDER BY volume_usd DESC  LIMIT 10
```
'''


def _ensure_token() -> tuple[str, str]:
    """Return (token, notice) — notice is non-empty when auto-registration occurred."""
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip(), ""
    name = getpass.getuser()
    body = json.dumps({"name": name}).encode()
    req = urllib.request.Request(
        f"{API_BASE}/v1/register", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(result["api_key"])
    balance_usdc = result.get("balance", 0) / 1_000_000
    notice = f"// auto-registered as '{result['name']}', trial balance ${balance_usdc:.2f} USDC\n"
    return result["api_key"], notice


def _authenticate(name: str, wallet_addr: str = "") -> str:
    if TOKEN_PATH.exists():
        return "Already authenticated. Delete ~/.microquery/token to re-register."
    body: dict = {"name": name}
    if wallet_addr:
        body["wallet_addr"] = wallet_addr
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API_BASE}/v1/register", data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return f"Registration failed ({exc.code}): {exc.read().decode()}"
    except Exception as exc:
        return f"Registration failed: {exc}"
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(result["api_key"])
    balance_usdc = result.get("balance", 0) / 1_000_000
    return (
        f"Registered as '{result['name']}' (id: {result['id']}). "
        f"Trial balance: ${balance_usdc:.2f} USDC. "
        f"API key stored in {TOKEN_PATH}."
    )


def _topup(token: str) -> dict:
    """POST /v1/topup. Returns parsed JSON body regardless of status code."""
    req = urllib.request.Request(
        f"{API_BASE}/v1/topup", data=b"", method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode())
        except Exception:
            return {}
    except Exception:
        return {}


def _query(database: str, sql: str) -> str:
    try:
        token, notice = _ensure_token()
    except Exception as exc:
        return f"Registration failed: {exc}"

    def _run() -> tuple:
        url = f"{API_BASE}/query?database={urllib.parse.quote(database)}"
        req = urllib.request.Request(
            url, data=sql.encode(), method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            rows = [json.loads(l) for l in resp.read().decode().splitlines() if l.strip()]
            return rows, dict(resp.headers)

    try:
        rows, resp_headers = _run()
    except urllib.error.HTTPError as exc:
        if exc.code != 402:
            return f"Query failed ({exc.code}): {exc.read().decode()}"
        # Credit exhausted — request a top-up then retry once.
        topup = _topup(token)
        if topup.get("status") == "payment_required":
            # Limit reached (stub) or Stripe requires user action.
            # Same shape whether stub or real Stripe — no MCP change needed.
            url = topup.get("checkout_url", "https://microquery.dev/add-credit")
            return (
                f"// Credit exhausted. Add USDC to continue: {url}\n"
                f"// Tip: visit the URL above to top up your account."
            )
        if "balance" not in topup:
            return "Query failed (402): credit exhausted and auto-topup failed"
        # Topup credited — retry the query transparently.
        try:
            rows, resp_headers = _run()
        except urllib.error.HTTPError as exc2:
            return f"Query failed ({exc2.code}): {exc2.read().decode()}"
        except Exception as exc2:
            return f"Query failed: {exc2}"
    except Exception as exc:
        return f"Query failed: {exc}"

    cost    = resp_headers.get("X-Microquery-Cost-Microusdc", "?")
    scanned = resp_headers.get("X-Microquery-Bytes-Scanned", "?")
    try:
        scanned_gb = f"{int(scanned)/1e9:.3f} GB"
    except (ValueError, TypeError):
        scanned_gb = scanned
    summary = f"// {len(rows)} rows | scanned: {scanned_gb} | cost: {cost} µUSDC\n"
    return notice + summary + "\n".join(json.dumps(r) for r in rows)


def _fetch_databases() -> str:
    req = urllib.request.Request(f"{API_BASE}/v1/databases",
                                 headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        return f"Error fetching databases: {exc}"

    lines = []
    for db in data.get("databases", []):
        lines.append(f"## {db['name']}")
        for table in db.get("tables", []):
            fields = ", ".join(
                f"{f['name']} ({f['type']})" for f in table.get("fields", [])
            )
            lines.append(f"  {table['name']}: {fields}")
    return "\n".join(lines)


def _call_tool(name: str, args: dict) -> dict:
    if name == "authenticate":
        text = _authenticate(args.get("name", ""), args.get("wallet_addr", ""))
    elif name == "query":
        text = _query(args.get("database", ""), args.get("sql", ""))
    elif name == "list_databases":
        text = _fetch_databases()
    elif name == "get_quickstart":
        text = QUICKSTART
    else:
        return {"error": {"code": -32601, "message": f"Unknown tool: {name}"}}
    return {"content": [{"type": "text", "text": text}]}


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> None:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        msg_id = msg.get("id")

        if method == "initialize":
            _send({
                "jsonrpc": "2.0", "id": msg_id, "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "microquery-mcp", "version": "1.0.0"},
                },
            })
        elif method == "initialized":
            pass  # notification — no response
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": msg_id,
                   "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = msg.get("params", {})
            result = _call_tool(params.get("name", ""),
                                params.get("arguments", {}))
            _send({"jsonrpc": "2.0", "id": msg_id, "result": result})
        elif msg_id is not None:
            _send({"jsonrpc": "2.0", "id": msg_id, "error": {
                "code": -32601, "message": f"Method not found: {method}",
            }})


if __name__ == "__main__":
    main()
