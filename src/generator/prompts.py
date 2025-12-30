"""Prompt templates for Claude-based code generation."""

from __future__ import annotations

from src.generator.analyzer import InfrastructureAnalysis

# System prompt for code generation
SYSTEM_PROMPT = """You are an expert Python developer specializing in building production-grade AWS applications.
Your task is to generate REALISTIC sample applications that simulate REAL-WORLD business scenarios.

DO NOT generate simple "hello world" or basic client connection code. Instead, generate applications that:

1. **Simulate Real Business Logic**:
   - E-commerce: order processing, inventory management, payment workflows
   - SaaS: user management, subscription handling, multi-tenant data isolation
   - Data pipelines: ETL processes, event-driven data transformations
   - APIs: RESTful services with proper request/response handling

2. **Include Realistic Data Models**:
   - Use domain-specific entities (User, Order, Product, Transaction, etc.)
   - Include relationships between entities
   - Implement proper validation and business rules

3. **Demonstrate Service Integration Patterns**:
   - Fan-out/fan-in patterns with SQS/SNS
   - Saga patterns for distributed transactions
   - Event sourcing with DynamoDB streams
   - CQRS patterns where applicable

4. **Production-Quality Code**:
   - Use boto3 with proper error handling and retries
   - Support LocalStack endpoints via environment variables
   - Include comprehensive logging and observability
   - Follow Python best practices with type hints and docstrings

Generate code that would be representative of what a real team would deploy to production."""

# Main generation prompt template
GENERATION_PROMPT = """Generate a REALISTIC Python application that simulates a real-world business scenario using the following AWS infrastructure:

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

## Business Scenario Selection

Based on the infrastructure services, generate an application for ONE of these real-world scenarios:

### If services include DynamoDB + Lambda + API Gateway:
**E-Commerce Order API** - A complete order management system:
- Create orders with multiple line items, calculate totals with tax
- Process payments with idempotency keys to prevent double-charging
- Update inventory levels atomically using DynamoDB transactions
- Send order confirmation events to downstream services

### If services include S3 + Lambda:
**Document Processing Pipeline** - An intelligent document handler:
- Upload documents with metadata extraction (file type, size, checksums)
- Generate thumbnails/previews for images, extract text from PDFs
- Implement virus scanning simulation and content validation
- Track processing status with callbacks and retry failed jobs

### If services include SQS + Lambda + DynamoDB:
**Event-Driven Notification System** - A scalable messaging platform:
- Queue messages with priority levels and delivery scheduling
- Process messages with dead-letter queue handling for failures
- Track delivery status, implement exactly-once processing
- Support multiple channels (email, SMS, push) with templates

### If services include RDS/Aurora + VPC:
**Multi-Tenant SaaS Backend** - A B2B application platform:
- User authentication with session management and JWT tokens
- Tenant isolation with row-level security patterns
- Subscription management with usage metering and billing events
- Audit logging for compliance (GDPR, SOC2)

### If services include ECS + ALB + RDS:
**Microservices Order Fulfillment** - A distributed system:
- Service-to-service communication via HTTP with circuit breakers
- Distributed transaction coordination using saga pattern
- Health checks and graceful degradation
- Request tracing with correlation IDs across services

### If services include S3 + DynamoDB:
**Data Lake Ingestion** - An analytics data pipeline:
- Ingest data from multiple sources with schema validation
- Partition data by date/tenant for efficient querying
- Track data lineage and processing metadata
- Implement data quality checks and anomaly detection

## Required File Structure

### src/models.py
Domain models with Pydantic or dataclasses:
- Define 3-5 core business entities with proper types
- Include validation rules and business constraints
- Implement serialization for AWS services

### src/repositories.py
Data access layer:
- Repository pattern for each data store (DynamoDB, S3, RDS)
- Implement CRUD operations with proper error handling
- Include query methods for common access patterns

### src/services.py
Business logic layer:
- Implement 3-5 key business operations
- Coordinate between multiple repositories
- Include transaction management where needed

### src/handlers.py
Entry points (Lambda handlers, API routes):
- Parse and validate incoming requests
- Call appropriate service methods
- Format responses with proper status codes

### src/config.py
Configuration with:
- Environment-based settings (dev/staging/prod)
- AWS endpoint URLs (LocalStack support)
- Feature flags and timeouts

### src/__init__.py
Package initialization with logging setup

## Code Quality Requirements

1. **Realistic Data**:
   - Use realistic field names (customer_email, order_total, shipping_address)
   - Include timestamps, UUIDs, and proper ID generation
   - Implement data validation with meaningful error messages

2. **Error Handling**:
   - Custom exception hierarchy (OrderNotFoundError, InsufficientInventoryError)
   - Proper AWS error handling with retries for transient failures
   - Graceful degradation for non-critical failures

3. **Observability**:
   - Structured logging with context (request_id, user_id, operation)
   - Metrics collection points (latency, error rates, throughput)
   - Correlation IDs for distributed tracing

4. **LocalStack Compatibility**:
   - Use `endpoint_url` parameter for all boto3 clients
   - Default to `http://localhost:4566` for LocalStack
   - Support `AWS_ENDPOINT_URL` environment variable

Output the code as a JSON object with the following structure:
```json
{{
  "files": {{
    "src/models.py": "...",
    "src/repositories.py": "...",
    "src/services.py": "...",
    "src/handlers.py": "...",
    "src/config.py": "...",
    "src/__init__.py": "..."
  }},
  "requirements": ["boto3>=1.28.0", "pydantic>=2.0.0", "..."]
}}
```"""

# Test generation prompt template
TEST_GENERATION_PROMPT = """Generate comprehensive pytest tests for the following REAL-WORLD Python application:

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

Generate tests that verify REAL BUSINESS SCENARIOS, not just basic connectivity:

### tests/conftest.py
Comprehensive test fixtures:
- LocalStack-configured boto3 clients
- Factory fixtures for creating test entities (users, orders, documents)
- Database seeding with realistic test data
- Cleanup fixtures with proper teardown order
- Shared test context (correlation IDs, timestamps)

### tests/test_models.py
Domain model validation:
- Test model validation rules (required fields, formats, constraints)
- Test serialization/deserialization round-trips
- Test business rule enforcement (e.g., order total calculation)
- Test edge cases (empty values, max lengths, special characters)

### tests/test_repositories.py
Data layer tests:
- CRUD operations for each repository
- Query operations with various filters
- Concurrent access handling
- Error scenarios (item not found, duplicate keys)
- Pagination and batch operations

### tests/test_services.py
Business logic tests:
- Happy path for each business operation
- Business rule enforcement (e.g., insufficient inventory, payment failures)
- Transaction rollback scenarios
- Service coordination (multiple repository calls)
- Idempotency verification

### tests/test_integration.py
End-to-end workflow tests:
- Complete user journeys (e.g., browse -> add to cart -> checkout -> confirm)
- Event-driven flows (e.g., upload -> process -> notify)
- Failure recovery scenarios
- Performance benchmarks (response times, throughput)

### tests/test_handlers.py
API/Lambda handler tests:
- Request validation (missing fields, invalid formats)
- Authentication/authorization scenarios
- Response format verification
- Error response codes and messages
- Rate limiting and throttling behavior

## Test Scenarios to Include

1. **Happy Path Scenarios**:
   - Create a new order with 3 items, verify total calculation with tax
   - Upload a document, verify metadata extraction and storage
   - Send a notification, verify delivery tracking

2. **Error Handling Scenarios**:
   - Attempt to order out-of-stock item -> verify inventory check
   - Submit duplicate payment -> verify idempotency
   - Process corrupted file -> verify graceful failure

3. **Edge Cases**:
   - Order with 100 line items (stress test)
   - Upload 50MB file (size limits)
   - Concurrent updates to same record (race conditions)

4. **Integration Verification**:
   - Data written to DynamoDB is queryable
   - Files uploaded to S3 are retrievable
   - Messages sent to SQS are received
   - Lambda functions are invoked with correct payloads

## Test Code Quality

1. **Realistic Test Data**:
   - Use faker or realistic test data factories
   - Include edge cases in test data (unicode, special chars, long strings)
   - Use meaningful variable names (test_customer, sample_order)

2. **Assertions**:
   - Assert on business outcomes, not implementation details
   - Verify side effects (database state, events published)
   - Use custom assertion helpers for complex validations

3. **Test Isolation**:
   - Each test should be independent
   - Use unique identifiers per test to avoid conflicts
   - Clean up resources in finally blocks or fixtures

4. **LocalStack Compatibility**:
   - All tests must work with LocalStack endpoints
   - Handle eventual consistency with polling/retries
   - Skip tests for unsupported LocalStack features

Output as JSON:
```json
{{
  "files": {{
    "tests/conftest.py": "...",
    "tests/test_models.py": "...",
    "tests/test_repositories.py": "...",
    "tests/test_services.py": "...",
    "tests/test_integration.py": "...",
    "tests/test_handlers.py": "..."
  }},
  "requirements": ["pytest>=7.0.0", "pytest-asyncio>=0.21.0", "faker>=18.0.0", "freezegun>=1.2.0", "..."]
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
