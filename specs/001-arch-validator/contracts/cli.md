# CLI Interface Contract

**Version**: 1.0.0
**Date**: 2025-12-26

## Overview

The `ls-arch-validator` CLI provides a single entry point for all pipeline operations. Commands can be run individually for debugging or chained together for full pipeline execution.

## Global Options

```
ls-arch-validator [OPTIONS] COMMAND [ARGS]

Options:
  --config PATH       Path to config directory (default: ./config)
  --cache PATH        Path to cache directory (default: ./cache)
  --output PATH       Path to output directory (default: ./docs)
  --log-level LEVEL   Logging level: debug, info, warn, error (default: info)
  --log-format FORMAT Log format: json, text (default: json)
  --dry-run           Show what would be done without executing
  --version           Show version and exit
  --help              Show help and exit
```

## Commands

### `mine` - Mine Templates from Sources

```
ls-arch-validator mine [OPTIONS]

Options:
  --source ID         Mine only this source (can be repeated)
  --skip-cache        Force re-mining even if cache is valid
  --include-diagrams  Include diagram sources (default: true)
  --max-per-source N  Maximum templates per source (default: unlimited)

Output:
  - architectures written to cache directory
  - JSON summary to stdout

Exit Codes:
  0 - Success (at least one architecture mined)
  1 - No architectures mined
  2 - Configuration error
```

**Example**:
```bash
ls-arch-validator mine --source aws-quickstart --source terraform-registry
```

**stdout (JSON)**:
```json
{
  "status": "success",
  "architectures_mined": 45,
  "by_source": {
    "aws-quickstart": 20,
    "terraform-registry": 15,
    "aws-solutions": 10
  },
  "failed_sources": [],
  "duration_seconds": 120.5
}
```

### `generate` - Generate Sample Applications

```
ls-arch-validator generate [OPTIONS]

Options:
  --architecture ID   Generate for specific architecture (can be repeated)
  --skip-cache        Force regeneration even if cached
  --token-budget N    Maximum Claude API tokens (default: 500000)
  --validate-only     Check if generated code compiles, don't save

Output:
  - sample apps written to cache directory
  - JSON summary to stdout

Exit Codes:
  0 - Success (at least 90% generated successfully)
  1 - Partial success (<90% generated)
  2 - No architectures to process
  3 - Token budget exhausted before completion
```

**Example**:
```bash
ls-arch-validator generate --token-budget 100000
```

**stdout (JSON)**:
```json
{
  "status": "success",
  "total": 45,
  "generated": 42,
  "cached": 3,
  "failed": 0,
  "tokens_used": 85000,
  "tokens_remaining": 415000,
  "duration_seconds": 300.2
}
```

### `validate` - Run Validation Pipeline

```
ls-arch-validator validate [OPTIONS]

Options:
  --architecture ID      Validate specific architecture (can be repeated)
  --parallelism N        Concurrent validations (default: 4)
  --localstack-version V LocalStack image tag (default: latest)
  --timeout SECONDS      Per-architecture timeout (default: 600)
  --skip-cleanup         Don't remove containers after validation

Output:
  - results written to output directory
  - JSON summary to stdout

Exit Codes:
  0 - Success (all validations completed, regardless of pass/fail)
  1 - Some validations could not complete (infrastructure errors)
  2 - Configuration error
```

**Example**:
```bash
ls-arch-validator validate --parallelism 8 --localstack-version 3.0
```

**stdout (JSON)**:
```json
{
  "status": "success",
  "run_id": "run-20251226-030000",
  "total": 45,
  "passed": 35,
  "partial": 5,
  "failed": 3,
  "skipped": 2,
  "pass_rate": 0.778,
  "duration_seconds": 1800.5
}
```

### `report` - Generate Dashboard Report

```
ls-arch-validator report [OPTIONS]

Options:
  --run-id ID         Generate report for specific run (default: latest)
  --create-issues     Create GitHub issues for failures (default: false)
  --skip-deploy       Generate but don't deploy to gh-pages

Output:
  - HTML report written to output directory
  - JSON data files written to output/data
  - Issues created in GitHub (if --create-issues)

Exit Codes:
  0 - Success
  1 - No run data to report
  2 - GitHub API error (when creating issues)
```

**Example**:
```bash
ls-arch-validator report --create-issues
```

**stdout (JSON)**:
```json
{
  "status": "success",
  "run_id": "run-20251226-030000",
  "report_path": "./docs/index.html",
  "issues_created": 2,
  "issues_skipped": 1,
  "duration_seconds": 15.3
}
```

### `run` - Full Pipeline Execution

```
ls-arch-validator run [OPTIONS]

Options:
  --skip-mining       Use cached architectures only
  --skip-generation   Use cached sample apps only
  --create-issues     Create GitHub issues for failures
  --parallelism N     Concurrent validations (default: 4)
  --localstack-version V LocalStack image tag (default: latest)

Output:
  - Combines output of all stages
  - Final JSON summary to stdout

Exit Codes:
  0 - Pipeline completed successfully
  1 - Pipeline completed with failures
  2 - Pipeline could not complete
```

**Example**:
```bash
ls-arch-validator run --skip-mining --create-issues
```

### `status` - Show Current State

```
ls-arch-validator status [OPTIONS]

Options:
  --format FORMAT     Output format: table, json (default: table)

Output:
  - Summary of cached architectures, apps, and latest run
```

**Example**:
```bash
ls-arch-validator status --format json
```

**stdout (JSON)**:
```json
{
  "cached_architectures": 45,
  "cached_apps": 42,
  "latest_run": {
    "id": "run-20251226-030000",
    "status": "completed",
    "pass_rate": 0.778
  },
  "failure_tracker": {
    "tracked_failures": 5,
    "pending_issues": 2
  }
}
```

### `clean` - Clean Cache and State

```
ls-arch-validator clean [OPTIONS]

Options:
  --architectures     Clean cached architectures
  --apps              Clean cached sample apps
  --runs              Clean old run results (keeps last 7 days)
  --all               Clean everything

Exit Codes:
  0 - Success
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Claude API key (required for generate) | - |
| `GITHUB_TOKEN` | GitHub token for issue creation | - |
| `LOCALSTACK_API_KEY` | LocalStack Pro API key (optional) | - |
| `PARALLELISM` | Default parallelism level | 4 |
| `TOKEN_BUDGET` | Default Claude API token budget | 500000 |
| `LOG_LEVEL` | Default log level | info |

## Exit Code Summary

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Partial success or recoverable error |
| 2 | Configuration or infrastructure error |
| 3 | Resource exhaustion (tokens, time) |

## JSON Output Contract

All commands output JSON to stdout when `--log-format json` is set (default). The structure always includes:

```json
{
  "status": "success" | "partial" | "failed",
  "duration_seconds": <float>,
  // Command-specific fields...
}
```

Errors are written to stderr in the same JSON format:

```json
{
  "level": "error",
  "message": "Description of error",
  "details": { /* optional context */ }
}
```
