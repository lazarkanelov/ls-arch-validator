# Implementation Plan: LocalStack Architecture Validator

**Branch**: `001-arch-validator` | **Date**: 2025-12-26 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-arch-validator/spec.md`

## Summary

Build an automated validation system that discovers real-world AWS architecture patterns from multiple sources (GitHub repos, Terraform Registry, architecture diagrams), generates Python sample applications to exercise those patterns, runs validations against LocalStack containers, and publishes results to a GitHub Pages dashboard. The system runs daily via GitHub Actions and auto-creates issues for persistent failures.

Key innovation: Uses Claude Vision API to parse architecture diagrams from AWS/Azure Architecture Centers and synthesize Terraform from visual representations.

## Technical Context

**Language/Version**: Python 3.11+ (core pipeline and generated sample apps)
**Primary Dependencies**:
- Core: httpx, jinja2, pyyaml, anthropic, PyGithub, beautifulsoup4, lxml, Pillow
- Generated Apps: boto3, pytest, pytest-asyncio, pytest-json-report
- Infrastructure: terraform-local (tflocal), cf2tf, docker

**Storage**: File-based (JSON for results/history, cached architectures in filesystem)
**Testing**: pytest with pytest-asyncio for async tests, pytest-json-report for machine-readable output
**Target Platform**: GitHub Actions runners (Linux), LocalStack containers
**Project Type**: Single project (CLI tool + static site generator)
**Performance Goals**: Complete pipeline in <2 hours for 50+ architectures; dashboard loads <3s
**Constraints**: 4 concurrent validations default; per-run token budget for Claude API
**Scale/Scope**: 50+ architectures from 4 template sources + 2 diagram sources

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Code Quality | ✅ PASS | Python 3.11+ with type hints; async-first with httpx/asyncio; clear 4-stage separation (mining→generation→running→reporting) |
| II. Testing Standards | ✅ PASS | Generated apps verify data flow (S3→Lambda→DynamoDB); retry logic with configurable timeouts; clean LocalStack state per validation |
| III. Reliability | ✅ PASS | Pipeline continues on individual failures (FR-018); all logs captured; timeouts per stage; cleanup in finally blocks |
| IV. Reporting | ✅ PASS | Dashboard with actionable failures; trend tracking; 2+ consecutive failures before issue creation; service coverage matrix |
| V. Infrastructure as Code | ✅ PASS | All TF normalized; no hardcoded values; tflocal for LocalStack; Docker for containers; no committed state |

**Gate Status**: PASSED - All constitution principles satisfied

## Project Structure

### Documentation (this feature)

```text
specs/001-arch-validator/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (CLI interface schemas)
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
src/
├── miner/                      # Stage 1: Template Mining
│   ├── __init__.py
│   ├── sources/                # Source-specific extractors
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract base for sources
│   │   ├── quickstart.py       # AWS Quick Starts extractor
│   │   ├── terraform.py        # Terraform Registry extractor
│   │   ├── solutions.py        # AWS Solutions Library extractor
│   │   ├── serverless.py       # Serverless Framework extractor
│   │   └── diagrams.py         # Architecture diagram scraper
│   ├── converter.py            # CloudFormation → Terraform
│   ├── normalizer.py           # LocalStack compatibility transforms
│   └── diagram_parser.py       # Claude Vision diagram analysis
├── generator/                  # Stage 2: App Generation
│   ├── __init__.py
│   ├── analyzer.py             # Terraform analysis & service detection
│   ├── prompts.py              # Claude prompts for code generation
│   ├── synthesizer.py          # Code generation orchestration
│   └── validator.py            # Compile validation for generated apps
├── runner/                     # Stage 3: Validation Execution
│   ├── __init__.py
│   ├── orchestrator.py         # Parallel execution with semaphore
│   ├── container.py            # LocalStack container lifecycle
│   └── executor.py             # Terraform + pytest execution
├── reporter/                   # Stage 4: Report Generation
│   ├── __init__.py
│   ├── aggregator.py           # Results collection & statistics
│   ├── trends.py               # Historical trend analysis
│   ├── site.py                 # Static HTML generation
│   └── issues.py               # GitHub issue creation
├── models/                     # Shared data models
│   ├── __init__.py
│   ├── architecture.py         # Architecture, TemplateSource
│   ├── results.py              # ValidationRun, ArchitectureResult
│   └── coverage.py             # ServiceCoverage, FailureTracker
├── utils/                      # Shared utilities
│   ├── __init__.py
│   ├── logging.py              # Structured JSON logging
│   ├── cache.py                # Template/app caching
│   └── tokens.py               # Claude API token budgeting
└── cli.py                      # Main entry point

templates/                      # Jinja2 templates for dashboard
├── base.html
├── index.html
├── architecture_card.html
├── service_matrix.html
└── trend_chart.html

config/
├── sources.yaml                # Template source configuration
├── diagram_sources.yaml        # Diagram URLs to scrape
├── timeouts.yaml               # Stage timeout configuration
└── defaults.yaml               # Default settings

tests/
├── unit/
│   ├── test_converter.py
│   ├── test_normalizer.py
│   ├── test_analyzer.py
│   └── test_aggregator.py
├── integration/
│   ├── test_mining_pipeline.py
│   ├── test_generation_pipeline.py
│   ├── test_validation_pipeline.py
│   └── test_full_pipeline.py
└── conftest.py                 # Shared fixtures

.github/
└── workflows/
    └── validate.yml            # Main GitHub Action

docs/                           # Generated dashboard (gh-pages)
├── index.html
├── data/
│   ├── latest.json
│   └── history.json
└── assets/
    ├── styles.css
    └── chart.js
```

**Structure Decision**: Single project with clear stage separation in `src/`. Each pipeline stage is a subpackage (miner, generator, runner, reporter) with its own modules. Shared models and utilities are separate packages. This enables independent testing per stage while maintaining a cohesive CLI interface.

## Complexity Tracking

No constitution violations requiring justification. The design directly maps to constitution requirements:
- 4-stage pipeline matches Pipeline Architecture section
- Async execution satisfies Code Quality principle
- Generated apps with retry logic satisfy Testing Standards
- Graceful degradation satisfies Reliability principle

## Security Considerations

### Docker Socket Access

The system requires Docker socket access (`/var/run/docker.sock`) for container management. This is a privileged operation with security implications:

**Risks**:
- Container escape potential if generated code is malicious
- Docker-in-Docker pattern (LocalStack Lambda executor) adds complexity

**Mitigations**:
- Generated sample apps run inside isolated containers
- LocalStack containers have no network access to host services
- No sensitive credentials stored in container environment
- GitHub Actions runners provide ephemeral isolation

### API Credentials

| Credential | Storage | Exposure Risk | Mitigation |
|------------|---------|---------------|------------|
| ANTHROPIC_API_KEY | GitHub Secrets | Low | Only used during generation stage, not passed to containers |
| GITHUB_TOKEN | GitHub Actions OIDC | Low | Scoped to repository, auto-rotated |
| LOCALSTACK_API_KEY | GitHub Secrets (optional) | Low | Only for Pro features, not required for core functionality |

### Generated Code Safety

Generated sample applications could theoretically contain malicious code since they're produced by an LLM. Mitigations:

1. **Sandboxed Execution**: All generated code runs inside LocalStack containers with no network access to external services
2. **No Credential Access**: Container environment contains only LocalStack test credentials
3. **Ephemeral Resources**: All resources destroyed after each validation
4. **Code Review Prompts**: Generation prompts explicitly request safe, deterministic test code

### Container Resource Limits

To prevent resource exhaustion:

```python
CONTAINER_LIMITS = {
    "mem_limit": "2g",          # 2GB memory per container
    "memswap_limit": "2g",      # No swap
    "cpu_period": 100000,
    "cpu_quota": 100000,        # 1 CPU core max
    "pids_limit": 256,          # Process limit
}
```

### Storage Quotas

- Maximum 10GB for historical run data (FR-045)
- Automatic cleanup of runs older than 90 days
- Log rotation for container output
