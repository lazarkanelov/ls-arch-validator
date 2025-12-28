"""Prompt templates for Claude-based code generation."""

from __future__ import annotations

from src.generator.analyzer import InfrastructureAnalysis

# System prompt for code generation
SYSTEM_PROMPT = """You are an expert Python developer specializing in AWS applications.
Your task is to generate sample Python applications that exercise AWS infrastructure.
The code should:
1. Use boto3 for AWS interactions
2. Include proper error handling with retries
3. Support LocalStack endpoints via environment variables
4. Be well-structured and follow Python best practices
5. Include type hints and docstrings

Generate production-quality code that properly tests the infrastructure."""

# Main generation prompt template
GENERATION_PROMPT = """Generate a Python sample application that exercises the following AWS infrastructure:

## Infrastructure Analysis
- Services: {services}
- Lambda Functions: {lambda_functions}
- API Endpoints: {api_endpoints}
- Storage (S3): {storage_resources}
- Database Tables: {database_tables}
- Queues (SQS): {queue_resources}
- Event Sources: {event_sources}

## Terraform Configuration
```hcl
{terraform_content}
```

## Requirements

Generate a complete Python application with the following structure:

### src/app.py
Main application module that:
- Initializes boto3 clients with LocalStack endpoint support
- Provides functions to interact with each AWS service
- Includes retry logic for transient failures
- Uses environment variables for configuration

### src/config.py
Configuration module with:
- AWS endpoint URLs (supporting LocalStack)
- Timeout configurations
- Retry settings

### src/__init__.py
Package initialization

## Code Guidelines

1. **LocalStack Compatibility**:
   - Use `endpoint_url` parameter for all boto3 clients
   - Default to `http://localhost:4566` for LocalStack
   - Support `AWS_ENDPOINT_URL` environment variable

2. **Retry Logic**:
   - Implement exponential backoff for transient failures
   - Max retries: 3
   - Initial delay: 1 second

3. **Error Handling**:
   - Catch and log specific AWS exceptions
   - Raise custom exceptions for business logic errors

4. **Data Flow**:
   - If there are integrations, demonstrate the data flow between services
   - For API -> Lambda -> DynamoDB patterns, show the complete flow

Output the code as a JSON object with the following structure:
```json
{{
  "files": {{
    "src/app.py": "...",
    "src/config.py": "...",
    "src/__init__.py": "..."
  }},
  "requirements": ["boto3>=1.28.0", "..."]
}}
```"""

# Test generation prompt template
TEST_GENERATION_PROMPT = """Generate pytest tests for the following Python application that exercises AWS infrastructure:

## Application Code
```python
{app_code}
```

## Infrastructure Services
- Services: {services}
- Lambda Functions: {lambda_functions}
- Database Tables: {database_tables}
- Queues: {queue_resources}
- Storage: {storage_resources}

## Test Requirements

Generate comprehensive pytest tests with:

### tests/conftest.py
- Fixtures for boto3 clients configured for LocalStack
- Test data fixtures
- Setup/teardown for AWS resources

### tests/test_app.py
- Unit tests for each function in app.py
- Integration tests that verify data flows through the infrastructure
- Tests that verify:
  - Resources are created correctly
  - Data can be written and read
  - Events are processed
  - Error handling works correctly

### tests/test_integration.py
- End-to-end tests for complete data flows
- Tests that verify integrations between services work

## Test Guidelines

1. **LocalStack Configuration**:
   - All tests should use LocalStack endpoints
   - Use fixtures to set up test resources
   - Clean up resources after tests

2. **Assertions**:
   - Test return values and side effects
   - Verify data is persisted correctly
   - Check event processing results

3. **Data Flow Testing**:
   - For each integration point, verify data flows correctly
   - Example: API call -> Lambda invoked -> DynamoDB item created

4. **Timeout Configuration**:
   - Set appropriate timeouts for async operations
   - Use polling for eventual consistency

Output as JSON:
```json
{{
  "files": {{
    "tests/conftest.py": "...",
    "tests/test_app.py": "...",
    "tests/test_integration.py": "..."
  }},
  "requirements": ["pytest>=7.0.0", "pytest-asyncio>=0.21.0", "..."]
}}
```"""


def format_generation_prompt(
    analysis: InfrastructureAnalysis,
    terraform_content: str,
) -> str:
    """
    Format the generation prompt with infrastructure details.

    Args:
        analysis: Infrastructure analysis result
        terraform_content: Original Terraform content

    Returns:
        Formatted prompt string
    """
    return GENERATION_PROMPT.format(
        services=", ".join(sorted(analysis.services)),
        lambda_functions=", ".join(analysis.lambda_functions) or "None",
        api_endpoints=", ".join(analysis.api_endpoints) or "None",
        storage_resources=", ".join(analysis.storage_resources) or "None",
        database_tables=", ".join(analysis.database_tables) or "None",
        queue_resources=", ".join(analysis.queue_resources) or "None",
        event_sources=", ".join(analysis.event_sources) or "None",
        terraform_content=terraform_content[:4000],  # Limit size
    )


def format_test_prompt(
    analysis: InfrastructureAnalysis,
    app_code: str,
) -> str:
    """
    Format the test generation prompt.

    Args:
        analysis: Infrastructure analysis result
        app_code: Generated application code

    Returns:
        Formatted prompt string
    """
    return TEST_GENERATION_PROMPT.format(
        app_code=app_code[:6000],  # Limit size
        services=", ".join(sorted(analysis.services)),
        lambda_functions=", ".join(analysis.lambda_functions) or "None",
        database_tables=", ".join(analysis.database_tables) or "None",
        queue_resources=", ".join(analysis.queue_resources) or "None",
        storage_resources=", ".join(analysis.storage_resources) or "None",
    )
