# Quickstart: LocalStack Architecture Validator

**Date**: 2025-12-26
**Estimated Setup Time**: 15 minutes

## Prerequisites

- Python 3.11+
- Docker (with Docker socket access)
- Git
- Terraform 1.0+ (will be wrapped by tflocal)

## Installation

### 1. Clone and Setup Environment

```bash
# Clone the repository
git clone https://github.com/your-org/ls-arch-validator.git
cd ls-arch-validator

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"
```

### 2. Configure Environment Variables

```bash
# Required for sample app generation
export ANTHROPIC_API_KEY="sk-ant-..."

# Required for GitHub issue creation (optional for local runs)
export GITHUB_TOKEN="ghp_..."

# Optional: LocalStack Pro features
export LOCALSTACK_API_KEY="..."
```

### 3. Verify Docker Access

```bash
# Ensure Docker is running and accessible
docker ps

# Pull LocalStack image
docker pull localstack/localstack:latest
```

## Quick Validation (Single Architecture)

Test the full pipeline with a simple S3+Lambda architecture:

```bash
# Create a test architecture
mkdir -p cache/architectures/test/s3-lambda

cat > cache/architectures/test/s3-lambda/main.tf << 'EOF'
resource "aws_s3_bucket" "data" {
  bucket = "test-data-bucket"
}

resource "aws_lambda_function" "processor" {
  function_name = "data-processor"
  runtime       = "python3.11"
  handler       = "index.handler"
  role          = aws_iam_role.lambda.arn
  filename      = "lambda.zip"
}

resource "aws_iam_role" "lambda" {
  name = "lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_s3_bucket_notification" "trigger" {
  bucket = aws_s3_bucket.data.id
  lambda_function {
    lambda_function_arn = aws_lambda_function.processor.arn
    events              = ["s3:ObjectCreated:*"]
  }
}
EOF

# Generate sample app for this architecture
ls-arch-validator generate --architecture test/s3-lambda

# Validate it
ls-arch-validator validate --architecture test/s3-lambda

# Check results
ls-arch-validator status
```

## Full Pipeline Run

Run the complete pipeline against all configured sources:

```bash
# Full pipeline (mining + generation + validation + report)
ls-arch-validator run --create-issues

# Or run stages individually for debugging:
ls-arch-validator mine
ls-arch-validator generate
ls-arch-validator validate --parallelism 4
ls-arch-validator report --create-issues
```

## Configuration

### Template Sources (`config/sources.yaml`)

```yaml
sources:
  - id: aws-quickstart
    name: AWS Quick Starts
    type: github_repo
    url: https://github.com/aws-quickstart
    enabled: true
    patterns:
      - "**/*.template.yaml"
      - "**/*.template.json"

  - id: terraform-registry
    name: Terraform Registry
    type: terraform_registry
    url: https://registry.terraform.io
    enabled: true
    modules:
      - terraform-aws-modules/vpc
      - terraform-aws-modules/lambda
      - terraform-aws-modules/s3-bucket

  - id: aws-solutions
    name: AWS Solutions Library
    type: github_repo
    url: https://github.com/aws-solutions
    enabled: true
    patterns:
      - "**/template.yaml"
```

### Diagram Sources (`config/diagram_sources.yaml`)

```yaml
diagram_sources:
  - id: aws-architecture-center
    name: AWS Architecture Center
    base_url: https://aws.amazon.com/architecture/
    enabled: true
    categories:
      - serverless
      - analytics
      - containers
    max_diagrams: 30

  - id: azure-architecture-center
    name: Azure Architecture Center
    base_url: https://learn.microsoft.com/en-us/azure/architecture/
    enabled: true
    sections:
      - reference-architectures
      - solution-ideas
    max_diagrams: 20
```

### Timeouts (`config/timeouts.yaml`)

```yaml
timeouts:
  localstack_start: 120    # seconds
  terraform_apply: 300     # seconds
  test_execution: 180      # seconds
  per_architecture: 600    # total seconds per architecture
  diagram_scrape: 60       # per page
  diagram_parse: 30        # per diagram (Claude Vision)
```

## Viewing Results

### Local Dashboard

```bash
# Generate report
ls-arch-validator report

# Serve locally
python -m http.server 8000 --directory docs

# Open http://localhost:8000
```

### GitHub Pages (CI/CD)

The GitHub Action automatically deploys to `gh-pages` branch. Access at:
`https://your-org.github.io/ls-arch-validator/`

## Common Operations

### Skip Mining (Use Cached Templates)

```bash
ls-arch-validator run --skip-mining
```

### Validate Specific Architecture

```bash
ls-arch-validator validate --architecture aws-quickstart/serverless-api
```

### Increase Parallelism

```bash
ls-arch-validator validate --parallelism 8
```

### Test Specific LocalStack Version

```bash
ls-arch-validator validate --localstack-version 3.0.0
```

### Clean Cache

```bash
# Clean all cached data
ls-arch-validator clean --all

# Clean only old run results
ls-arch-validator clean --runs
```

## Troubleshooting

### Docker Permission Issues

```bash
# Add user to docker group
sudo usermod -aG docker $USER
# Log out and back in

# Or run with sudo (not recommended)
sudo ls-arch-validator validate
```

### LocalStack Container Fails to Start

```bash
# Check Docker resources
docker system df

# Increase Docker memory limit
# Docker Desktop: Preferences > Resources > Memory

# Check for port conflicts
lsof -i :4566
```

### Claude API Rate Limits

```bash
# Reduce token budget to stay within limits
ls-arch-validator generate --token-budget 100000

# Check current usage
ls-arch-validator status
```

### Terraform Errors

```bash
# Run with debug logging
ls-arch-validator validate --log-level debug

# Check specific architecture logs
cat cache/apps/{arch_id}/terraform.log
```

## Next Steps

1. **Customize Sources**: Edit `config/sources.yaml` to add/remove template sources
2. **Set Up GitHub Action**: Copy `.github/workflows/validate.yml` to enable scheduled runs
3. **Configure Notifications**: Add Slack webhook to `config/defaults.yaml`
4. **Review Dashboard**: Check the generated dashboard at `docs/index.html`

## Support

- **Issues**: [GitHub Issues](https://github.com/your-org/ls-arch-validator/issues)
- **Documentation**: [Full Docs](https://your-org.github.io/ls-arch-validator/docs)
- **LocalStack**: [LocalStack Docs](https://docs.localstack.cloud)
