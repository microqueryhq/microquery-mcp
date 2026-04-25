# microquery-mcp

<!-- mcp-name: io.github.microqueryhq/microquery-mcp -->

MCP server for [Microquery](https://microquery.dev) — ask research questions
about real-world data and get actual database records back. Works in Claude
Desktop, Cursor, or any MCP-compatible AI host. Claude handles the SQL; you just
ask the question.

No wallet required. Auto-registers on first query and runs on $0.10 trial credit
(~1,600 typical queries).

## See also

[microquery-agent](https://github.com/microqueryhq/microquery-agent) —
autonomous agent for pipelines and cron jobs: register → deposit USDC → query →
auto top-up. Use this if you want to run microquery unattended without an AI
host.

## Prerequisites

- Python 3.9+
- No third-party packages — stdlib only

## Installation

### Claude Desktop (recommended)

The easiest paths, in order of friction:

**1. Registry install** Find microquery in the Claude Desktop MCP marketplace or
on [smithery.ai](https://smithery.ai) and click Install. No config editing
needed.

**2. `uvx` install** Add one entry to
`~/Library/Application Support/Claude/claude_desktop_config.json` (Mac) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "microquery": {
      "command": "uvx",
      "args": ["microquery-mcp"]
    }
  }
}
```

`uvx` requires `uv` to be installed separately
([astral.sh/uv](https://astral.sh/uv)). Once installed, Claude Desktop will pick
it up automatically.

**3. Manual install** *(developers)* Download `microquery_mcp.py` from this repo
and point your host at it:

```json
{
  "mcpServers": {
    "microquery": {
      "command": "python3",
      "args": ["/path/to/microquery_mcp.py"]
    }
  }
}
```

Restart Claude Desktop after editing. The server appears in **Settings →
Developer** with a green dot when connected.

### Other MCP hosts (Cursor, etc.)

Use the same `command` / `args` pattern above. Consult your host's MCP
documentation for the exact config format.

## Tools

| Tool                               | Description                                                         |
| ---------------------------------- | ------------------------------------------------------------------- |
| `query(database, sql)`             | Run SQL against a microquery dataset. Auto-registers on first call. |
| `authenticate(name, wallet_addr?)` | Manually register or link a wallet address.                         |
| `list_databases()`                 | Show all available datasets and field schemas.                      |
| `get_quickstart()`                 | Sneller SQL notes and multi-dataset example recipes.                |

## How it works

1. On the first `query()` call the server registers an account using your OS
   username (`getpass.getuser()`) via `POST /v1/register` and stores the API key
   in `~/.microquery/token`.
1. Subsequent calls use the stored key — no configuration needed.
1. The new account starts with 100,000 µUSDC ($0.10) trial credit, covering
   roughly 1,600 typical queries.
1. When trial credit runs low the server automatically tops up the account (up
   to 10 times, $2 each). Once the free allowance is exhausted a checkout URL is
   returned — visit it to add USDC and continue querying.

## Available datasets

FDA adverse events · SEC EDGAR · clinical trials · ClinVar · arXiv · PubMed ·
Ethereum · Bitcoin · Base · DeFi TVL · FEC contributions · FRED economic series
· NVD/CVE · OSV advisories · sanctions · FHFA house prices · GWAS · ClinPGx ·
malware samples · open food facts · world bank commodities · and more — call
`list_databases()` for the full live schema.

## Example

```
User:    What were the top adverse events reported for metformin last year?
         And how does that compare to 2022 and 2023?
Claude:  [queries fda.faers for each year, builds trend table]
         GI events (diarrhoea, nausea, vomiting) were flat 2022→2024,
         then spiked sharply in 2025 — consistent with the longevity/
         obesity wave hitting FAERS with a lag. Lactic acidosis stayed
         nearly flat across all four years despite overall volume growth.

User:    Can you cross-reference that with genomic profiles?
Claude:  [queries clinpgx, clinvar, gwas — no SQL needed from user]
         SLC22A1 rs628031 has a direct ClinPGx annotation for GI toxicity —
         the strongest known genomic explanation for why diarrhoea and nausea
         dominate the FAERS signal for metformin.
```
