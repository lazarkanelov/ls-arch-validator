# Data Model: LocalStack Architecture Validator

**Date**: 2025-12-26
**Phase**: 1 - Design

## Entity Relationship Diagram

```
┌─────────────────┐       ┌─────────────────┐
│ TemplateSource  │──1:N──│   Architecture  │
└─────────────────┘       └─────────────────┘
                                   │
                                   │ 1:1
                                   ▼
                          ┌─────────────────┐
                          │    SampleApp    │
                          └─────────────────┘
                                   │
                                   │ 1:N (across runs)
                                   ▼
┌─────────────────┐       ┌─────────────────┐
│  ValidationRun  │──1:N──│ArchitectureResult│
└─────────────────┘       └─────────────────┘
                                   │
                                   │ N:1
                                   ▼
                          ┌─────────────────┐
                          │ FailureTracker  │
                          └─────────────────┘

┌─────────────────┐
│ ServiceCoverage │ (aggregated view, not stored per-run)
└─────────────────┘
```

## Core Entities

### TemplateSource

Represents a repository or registry from which infrastructure templates are mined.

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

class SourceType(Enum):
    GITHUB_REPO = "github_repo"
    TERRAFORM_REGISTRY = "terraform_registry"
    DIAGRAM = "diagram"

@dataclass
class TemplateSource:
    id: str                          # e.g., "aws-quickstart", "terraform-registry"
    name: str                        # Human-readable name
    source_type: SourceType
    url: str                         # Base URL or repo URL
    last_mined_at: Optional[datetime] = None
    last_commit_sha: Optional[str] = None  # For GitHub sources
    enabled: bool = True

    # Validation rules:
    # - id: lowercase alphanumeric with hyphens, 3-50 chars
    # - url: valid URL format
    # - last_commit_sha: 40-char hex string (if present)
```

**Storage**: `config/sources.yaml` (static config) + `cache/sources_state.json` (runtime state)

### Architecture

A normalized infrastructure template ready for validation. Unique by `source_id + template_path`.

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

class ArchitectureStatus(Enum):
    PENDING = "pending"           # Discovered, not yet processed
    NORMALIZED = "normalized"     # Successfully converted to TF
    CONVERSION_FAILED = "conversion_failed"
    GENERATION_FAILED = "generation_failed"
    READY = "ready"               # Has generated sample app

class ArchitectureSourceType(Enum):
    TEMPLATE = "template"         # From code template
    DIAGRAM = "diagram"           # From architecture diagram

@dataclass
class ArchitectureMetadata:
    services: list[str]           # AWS services used, e.g., ["lambda", "s3", "dynamodb"]
    resource_count: int           # Number of TF resources
    complexity: str               # "low", "medium", "high"
    original_format: str          # "cloudformation", "terraform", "sam", "serverless", "diagram"
    diagram_confidence: Optional[float] = None  # 0.0-1.0 for diagram-sourced

@dataclass
class Architecture:
    id: str                       # Derived: f"{source_id}/{template_path_slug}"
    source_id: str                # Reference to TemplateSource.id
    template_path: str            # Path within source (or diagram URL for diagrams)
    source_type: ArchitectureSourceType
    status: ArchitectureStatus
    terraform_content: str        # Normalized main.tf content
    variables_content: Optional[str] = None   # variables.tf
    outputs_content: Optional[str] = None     # outputs.tf
    metadata: Optional[ArchitectureMetadata] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    content_hash: str = ""        # SHA256 of terraform_content for cache invalidation
    synthesis_notes: Optional[str] = None     # For diagram-sourced: assumptions made

    # Validation rules:
    # - id: must be unique across all architectures
    # - terraform_content: must be valid HCL (validated by tflocal init)
    # - services: lowercase AWS service names from known set
    # - complexity: one of "low", "medium", "high"

    @property
    def is_diagram_sourced(self) -> bool:
        return self.source_type == ArchitectureSourceType.DIAGRAM
```

**Storage**: `cache/architectures/{id}/` directory containing:
- `main.tf`
- `variables.tf`
- `outputs.tf`
- `metadata.json`

### SampleApp

A generated application that exercises an architecture.

```python
@dataclass
class SampleApp:
    architecture_id: str          # Reference to Architecture.id
    source_code: dict[str, str]   # filename -> content mapping
    test_code: dict[str, str]     # test filename -> content mapping
    requirements: list[str]       # Python package requirements
    compile_status: str           # "success", "failed", "pending"
    compile_errors: Optional[str] = None
    generated_at: datetime = field(default_factory=datetime.utcnow)
    prompt_version: str = "1.0"   # Version of generation prompt
    token_usage: int = 0          # Tokens used for generation

    # Validation rules:
    # - source_code must include at least: src/__init__.py, src/clients.py, src/operations.py
    # - test_code must include at least: tests/conftest.py, tests/test_integration.py
    # - requirements must include: boto3, pytest, pytest-json-report
    # - compile_status validated by python -m py_compile on all .py files
```

**Storage**: `cache/apps/{content_hash}/` directory containing:
- `src/` - Application source
- `tests/` - Test files
- `requirements.txt`
- `metadata.json` - Generation metadata

### ValidationRun

A complete execution of the pipeline.

```python
@dataclass
class RunStatistics:
    total_architectures: int
    passed: int
    partial: int
    failed: int
    skipped: int                  # e.g., generation failed
    pass_rate: float              # passed / (passed + partial + failed)

@dataclass
class StageTiming:
    mining_seconds: float
    generation_seconds: float
    running_seconds: float
    reporting_seconds: float
    total_seconds: float

@dataclass
class ValidationRun:
    id: str                       # Format: "run-{YYYYMMDD}-{HHMMSS}"
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str = "running"       # "running", "completed", "failed"
    trigger: str = "scheduled"    # "scheduled", "manual"
    parallelism: int = 4
    localstack_version: str = "latest"
    statistics: Optional[RunStatistics] = None
    timing: Optional[StageTiming] = None
    results: list[str] = field(default_factory=list)  # List of ArchitectureResult.id
    token_usage: int = 0          # Total Claude API tokens used
    token_budget: int = 500000    # Configured budget

    # Validation rules:
    # - id format must match pattern
    # - completed_at >= started_at
    # - pass_rate between 0.0 and 1.0
```

**Storage**: `docs/data/runs/{run_id}.json`

### ArchitectureResult

Outcome of validating a single architecture within a run.

```python
@dataclass
class InfrastructureResult:
    success: bool
    duration_seconds: float
    resources_created: list[str]  # e.g., ["aws_lambda_function.main", "aws_s3_bucket.data"]
    errors: Optional[str] = None
    terraform_output: Optional[str] = None

@dataclass
class TestResult:
    total: int
    passed: int
    failed: int
    skipped: int
    duration_seconds: float
    failures: list[dict] = field(default_factory=list)  # [{name, message, traceback}]

@dataclass
class LogBundle:
    terraform_log: str
    localstack_log: str
    app_log: str
    test_output: str

class ResultStatus(Enum):
    PASSED = "passed"             # All tests pass
    PARTIAL = "partial"           # Some tests fail
    FAILED = "failed"             # Deployment or critical failure
    SKIPPED = "skipped"           # Generation failed, no app to run
    TIMEOUT = "timeout"           # Exceeded time limit

@dataclass
class ArchitectureResult:
    id: str                       # Format: "{run_id}/{architecture_id}"
    run_id: str                   # Reference to ValidationRun.id
    architecture_id: str          # Reference to Architecture.id
    status: ResultStatus
    infrastructure: Optional[InfrastructureResult] = None
    tests: Optional[TestResult] = None
    logs: Optional[LogBundle] = None
    duration_seconds: float = 0.0
    issue_number: Optional[int] = None  # GitHub issue if created
    suggested_issue_title: Optional[str] = None

    # Validation rules:
    # - status PASSED requires tests.failed == 0
    # - status PARTIAL requires tests.failed > 0 and infrastructure.success
    # - status FAILED requires infrastructure.success == False or critical error
```

**Storage**: `docs/data/runs/{run_id}/{architecture_id}.json`

### FailureTracker

Tracks consecutive failures per architecture for issue creation logic.

```python
@dataclass
class FailureEntry:
    architecture_id: str
    consecutive_failures: int
    first_failure_run: str        # run_id of first failure in streak
    last_failure_run: str         # run_id of most recent failure
    issue_number: Optional[int] = None  # GitHub issue number if created
    issue_created_at: Optional[datetime] = None

    # State transitions:
    # - On failure: increment consecutive_failures, update last_failure_run
    # - On success: reset entry (remove from tracker)
    # - On issue creation: set issue_number, issue_created_at
```

**Storage**: `docs/data/failure_tracker.json`

### ServiceCoverage

Aggregated statistics for an AWS service. Computed, not stored per-run.

```python
@dataclass
class ServiceCoverage:
    service_name: str             # e.g., "lambda", "s3", "dynamodb"
    architectures_tested: int     # Count of architectures using this service
    architectures_passed: int
    architectures_failed: int
    pass_rate: float
    last_tested_run: str          # Most recent run_id where this service was tested

    # Computed from ArchitectureResult + Architecture.metadata.services
```

**Storage**: Computed on-demand from run results; cached in `docs/data/latest.json`

## State Transitions

### Architecture Lifecycle

```
PENDING ──[normalize]──► NORMALIZED ──[generate]──► READY
    │                        │                        │
    └──[error]──► CONVERSION_FAILED    └──[error]──► GENERATION_FAILED
```

### Validation Result Lifecycle

```
[start] ──► [deploy]──────────► [run tests]──────────► [determine status]
              │                       │
              ▼                       ▼
         FAILED (deploy error)   TIMEOUT (exceeded limit)
                                      │
                                      ▼
                              PASSED / PARTIAL / FAILED
```

### Failure Tracker State Machine

```
[no entry] ──[first failure]──► consecutive=1 ──[second failure]──► consecutive=2
                                     │                                    │
                                     │                                    ▼
                                     │                            [create issue]
                                     │                                    │
                                     ▼                                    ▼
                               [success]──► [remove entry]         issue_number set
                                                                          │
                                                                          ▼
                                                               [subsequent failures]
                                                                  (no new issue)
```

## Data Validation Rules Summary

| Entity | Field | Rule |
|--------|-------|------|
| TemplateSource | id | `^[a-z0-9-]{3,50}$` |
| Architecture | id | Unique, format `{source_id}/{path_slug}` |
| Architecture | services | Each must be in KNOWN_AWS_SERVICES set |
| Architecture | complexity | One of: low, medium, high |
| SampleApp | compile_status | Must pass `python -m py_compile` |
| ValidationRun | id | Format `run-{YYYYMMDD}-{HHMMSS}` |
| ArchitectureResult | status | Must align with test/infra results |
| FailureTracker | consecutive_failures | ≥1 for entries to exist |

## JSON Schema Locations

All schemas will be defined in `contracts/` directory:
- `contracts/architecture.schema.json`
- `contracts/validation_run.schema.json`
- `contracts/architecture_result.schema.json`
- `contracts/failure_tracker.schema.json`
