# Research: LocalStack Architecture Validator

**Date**: 2025-12-26
**Phase**: 0 - Research & Discovery

## Technology Decisions

### 1. CloudFormation to Terraform Conversion

**Decision**: Use `cf2tf` (hashicorp/cf2tf) for CloudFormation → Terraform conversion

**Rationale**:
- Official HashiCorp tool with active maintenance
- Handles most AWS resources correctly
- Produces idiomatic Terraform code
- CLI-based, easy to integrate into pipeline

**Alternatives Considered**:
| Tool | Rejected Because |
|------|-----------------|
| former2 | Requires AWS credentials, cloud-based |
| cloudformer | AWS native, doesn't produce Terraform |
| manual conversion | Not scalable for 50+ architectures |

**Integration Notes**:
- Run as subprocess: `cf2tf convert --input template.yaml --output main.tf`
- Handle conversion failures gracefully (mark template as "conversion-failed")
- Post-process output to fix common issues (resource naming, provider config)

### 2. Terraform LocalStack Integration

**Decision**: Use `tflocal` wrapper from LocalStack team

**Rationale**:
- Official LocalStack Terraform wrapper
- Automatically configures AWS provider endpoints
- Handles authentication (test/test credentials)
- Adds required skip_* provider flags

**Alternatives Considered**:
| Approach | Rejected Because |
|----------|-----------------|
| Manual provider override | Error-prone, requires modifying each template |
| AWS provider with env vars | Doesn't handle all edge cases |
| localstack-terraform-plugin | Deprecated, not maintained |

**Integration Notes**:
- Install via pip: `pip install terraform-local`
- Commands: `tflocal init`, `tflocal apply -auto-approve`
- Set `LOCALSTACK_HOST` environment variable per container

### 3. Claude API Integration

**Decision**: Use Anthropic Python SDK with vision capabilities

**Rationale**:
- Official SDK with async support
- Vision API for diagram parsing
- Structured output (JSON mode) for code generation
- Token counting for budget management

**Integration Pattern**:
```python
from anthropic import AsyncAnthropic

client = AsyncAnthropic()

# Text generation (app code)
response = await client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4096,
    messages=[{"role": "user", "content": prompt}]
)

# Vision (diagram parsing)
response = await client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=2048,
    messages=[{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "data": image_b64}},
            {"type": "text", "text": DIAGRAM_PARSE_PROMPT}
        ]
    }]
)
```

**Token Budget Strategy**:
- Default: 500K tokens per run
- Track usage with response.usage.input_tokens + output_tokens
- Cache generated apps by architecture hash
- Skip generation when budget exhausted (proceed with cached apps)

### 4. Architecture Diagram Sources

**Decision**: Scrape AWS and Azure Architecture Centers

**AWS Architecture Center**:
- Base URL: `https://aws.amazon.com/architecture/`
- Categories: analytics, compute, containers, databases, machine-learning, serverless, storage
- Selector: `img.architecture-diagram, img[alt*='architecture']`
- Rate limit: 1 request/second with exponential backoff

**Azure Architecture Center**:
- Base URL: `https://learn.microsoft.com/en-us/azure/architecture/`
- Sections: browse/, reference-architectures/, solution-ideas/
- Selector: `img[src*='architecture'], img[alt*='diagram']`
- Azure→AWS mapping required for service translation

**Azure to AWS Service Mapping**:
```python
AZURE_TO_AWS = {
    "Azure Functions": "lambda",
    "Cosmos DB": "dynamodb",
    "Blob Storage": "s3",
    "Service Bus": "sqs",
    "Event Grid": "eventbridge",
    "API Management": "apigateway",
    "Azure SQL": "rds",
    "Key Vault": "secretsmanager",
    "Application Insights": "cloudwatch",
    "Azure AD": "cognito",
    "Logic Apps": "stepfunctions",
    "Event Hubs": "kinesis",
}
```

### 5. LocalStack Container Management

**Decision**: Docker SDK for Python with async subprocess for commands

**Rationale**:
- Need unique ports per container for parallel execution
- Health check before Terraform apply
- Log capture on failure
- Cleanup guaranteed via context managers

**Container Configuration**:
```python
LOCALSTACK_CONFIG = {
    "image": "localstack/localstack:latest",
    "environment": {
        "DEBUG": "1",
        "SERVICES": "lambda,s3,dynamodb,sqs,sns,apigateway,events,stepfunctions",
        "LAMBDA_EXECUTOR": "docker",
    },
    "ports": {"4566/tcp": None},  # Dynamic port allocation
    "volumes": {
        "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"}
    },
}
```

**Port Strategy**:
- Use Docker's dynamic port allocation (bind to 0)
- Query assigned port after container start
- Pass to tflocal via LOCALSTACK_HOST=localhost:{port}

### 6. Parallel Execution Model

**Decision**: asyncio.Semaphore with configurable concurrency

**Rationale**:
- Simple, built-in Python concurrency primitive
- Easy to configure (PARALLELISM env var)
- Works well with async container management

**Implementation Pattern**:
```python
async def run_validations(architectures: list[Architecture], parallelism: int = 4):
    semaphore = asyncio.Semaphore(parallelism)

    async def validate_with_semaphore(arch: Architecture) -> ArchitectureResult:
        async with semaphore:
            return await validate_architecture(arch)

    results = await asyncio.gather(
        *[validate_with_semaphore(a) for a in architectures],
        return_exceptions=True
    )
    return [r for r in results if not isinstance(r, Exception)]
```

### 7. Dashboard Technology

**Decision**: Static HTML + Vanilla JS + Chart.js

**Rationale**:
- No build step required
- GitHub Pages compatible
- Fast load times (<3s target)
- Simple to maintain

**Alternatives Considered**:
| Technology | Rejected Because |
|------------|-----------------|
| React/Vue SPA | Requires build step, overkill for data display |
| Jekyll | Ruby dependency, slower builds |
| Astro | Additional toolchain complexity |

**Architecture**:
- Jinja2 templates rendered at report time
- JSON data files loaded by browser
- Chart.js for trend visualization
- CSS Grid for responsive layout

### 8. GitHub Issue Creation Strategy

**Decision**: Use PyGithub with failure tracking in JSON

**Rationale**:
- Official GitHub API client
- Well-documented, stable API
- Easy label management

**Failure Tracking**:
```json
{
  "failure_tracker": {
    "arch-id-123": {
      "consecutive_failures": 2,
      "first_failure": "2025-12-25T03:00:00Z",
      "last_failure": "2025-12-26T03:00:00Z",
      "issue_number": null
    }
  }
}
```

**Issue Creation Rules**:
1. Check `consecutive_failures >= 2`
2. Check no existing open issue (`issue_number` is null or issue is closed)
3. Create issue with standardized format
4. Store `issue_number` to prevent duplicates

### 9. Caching Strategy

**Decision**: File-based cache with content hashing

**Cache Locations**:
- `cache/templates/{source_id}/` - Mined templates
- `cache/apps/{arch_hash}/` - Generated sample apps
- `cache/diagrams/{diagram_id}/` - Downloaded diagrams

**Invalidation**:
- Templates: SHA of source repo + template path
- Apps: SHA of Terraform content + generation prompt version
- Diagrams: URL + last-modified header

**Implementation**:
```python
def get_cache_key(architecture: Architecture) -> str:
    content = architecture.terraform_content + PROMPT_VERSION
    return hashlib.sha256(content.encode()).hexdigest()[:16]
```

### 10. Logging & Observability

**Decision**: structlog for structured JSON logging

**Rationale**:
- Native JSON output
- Async-compatible
- Easy to add context (correlation IDs)
- Works well with GitHub Actions log parsing

**Log Format**:
```json
{
  "timestamp": "2025-12-26T03:15:30.123Z",
  "level": "info",
  "event": "validation_started",
  "run_id": "run-20251226-030000",
  "arch_id": "quickstart/lambda-s3",
  "stage": "running"
}
```

**Metrics Collected**:
- Stage timing (mining_duration_seconds, generation_duration_seconds, etc.)
- Success/failure counts per stage
- Token usage (input_tokens, output_tokens)
- Container resource usage (optional)

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| cf2tf conversion failures | Log errors, mark as "conversion-failed", continue with other templates |
| Claude API rate limits | Token budget, exponential backoff, cached app reuse |
| Diagram parsing inaccuracy | Confidence scoring, skip low-confidence diagrams, separate reporting |
| LocalStack service gaps | Focus on well-supported services (Lambda, S3, DynamoDB, SQS, SNS); track unsupported services (FR-046) |
| GitHub Actions timeout | Matrix strategy splits work; 6-hour limit sufficient for 50 architectures |
| Docker-in-Docker complexity | LocalStack Lambda executor requires nested Docker access; use LAMBDA_EXECUTOR=docker-reuse to reduce overhead; ensure socket permissions are correct |
| Container memory exhaustion | Enforce 2GB memory limit per container (CONTAINER_LIMITS); monitor via Docker stats; kill containers exceeding limits |
| Storage growth | 10GB cap with 90-day retention (FR-045); log rotation; automatic cleanup job |
| Generated code safety | Sandbox execution; no external network access; ephemeral resources; safe generation prompts |

## Open Questions Resolved

All NEEDS CLARIFICATION items from spec have been resolved:

1. ✅ Architecture uniqueness: source_repo + template_path (clarified in spec)
2. ✅ Observability level: Structured JSON logs with run-level metrics (clarified in spec)
3. ✅ Claude API management: Per-run token budget with caching (clarified in spec)
4. ✅ Generated app language: Python 3.11+ (provided in plan input)
5. ✅ Diagram sources: AWS + Azure Architecture Centers (provided in plan input)
