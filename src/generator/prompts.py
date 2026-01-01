"""Prompt templates for Claude-based code generation."""

from __future__ import annotations

from src.generator.analyzer import InfrastructureAnalysis

# System prompt for code generation
SYSTEM_PROMPT = """You are an expert Python developer and AWS compatibility tester.
Your task is to generate applications that PROBE FOR POTENTIAL ISSUES in LocalStack's AWS implementation.

The goal is NOT just to verify services run, but to DISCOVER GAPS in AWS API parity by testing:
- Advanced API parameters that might not be implemented
- Edge cases in service behavior
- Complex multi-service integrations
- Features that are commonly incomplete in local AWS emulators

DO NOT generate simple connectivity tests. Instead, generate applications that:

1. **Test AWS API Parity**:
   - Use advanced/optional API parameters (not just required ones)
   - Test less common operations (batch operations, conditional writes, filters)
   - Verify response formats match AWS exactly
   - Check error codes and error message formats

2. **Probe Service Edge Cases**:
   - Large payloads, special characters, unicode handling
   - Concurrent operations and race conditions
   - Timeout and retry behavior
   - Pagination with various page sizes

3. **Stress Integration Points**:
   - Event triggers between services (S3 -> Lambda, DynamoDB Streams -> Lambda)
   - IAM permission boundaries (even if LocalStack is permissive)
   - Cross-service transactions and consistency
   - Service quotas and throttling behavior

4. **Identify Common LocalStack Gaps**:
   - DynamoDB: Transactions, Streams, GSI projections, TTL
   - S3: Versioning, lifecycle rules, event notifications, multipart uploads
   - Lambda: Layers, concurrency limits, dead letter queues
   - SQS: FIFO queues, deduplication, visibility timeout
   - API Gateway: Authorizers, request validation, response templates

Generate code that would expose implementation gaps if they exist."""

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

## Issue Discovery Scenarios

Based on the infrastructure services, generate an application that PROBES FOR LOCALSTACK GAPS:

### If services include DynamoDB:
**DynamoDB Parity Probe** - Test advanced DynamoDB features:
- **Transactions**: Use TransactWriteItems with ConditionCheck, Put, Update, Delete in single transaction
- **Streams**: Enable streams and verify KEYS_ONLY, NEW_IMAGE, OLD_IMAGE, NEW_AND_OLD_IMAGES
- **GSI Projections**: Create GSIs with KEYS_ONLY, INCLUDE, ALL projections and query them
- **TTL**: Set TTL attributes and verify items expire correctly
- **Conditional Writes**: Use complex ConditionExpressions with attribute_exists, begins_with, contains
- **Batch Operations**: BatchWriteItem with 25 items, BatchGetItem with 100 keys
- **Query Filters**: FilterExpression with multiple conditions, KeyConditionExpression edge cases
- **Pagination**: Scan/Query with various Limit values, verify LastEvaluatedKey handling

### If services include S3:
**S3 Parity Probe** - Test advanced S3 features:
- **Versioning**: Enable versioning, upload multiple versions, delete markers, version listing
- **Lifecycle Rules**: Create lifecycle policies with transitions and expirations
- **Event Notifications**: Configure S3 -> Lambda/SQS/SNS triggers, verify event payloads
- **Multipart Uploads**: Initiate, upload parts, complete/abort multipart uploads
- **Object Lock**: Test governance and compliance modes, legal holds
- **Presigned URLs**: Generate presigned URLs for PUT/GET with various expirations
- **CORS**: Configure and test CORS rules with various origins
- **Server-Side Encryption**: Test SSE-S3, SSE-KMS with customer-managed keys

### If services include Lambda:
**Lambda Parity Probe** - Test advanced Lambda features:
- **Layers**: Create and attach Lambda layers, verify layer code is accessible
- **Concurrency**: Set reserved concurrency limits, test provisioned concurrency
- **Dead Letter Queues**: Configure DLQ, force failures, verify DLQ receives events
- **Event Source Mappings**: Test batch sizes, error handling, bisect on error
- **Environment Variables**: Test encrypted environment variables with KMS
- **VPC Configuration**: Lambda in VPC with security groups
- **Async Invocation**: Test MaximumRetryAttempts, MaximumEventAgeInSeconds

### If services include SQS:
**SQS Parity Probe** - Test advanced SQS features:
- **FIFO Queues**: MessageGroupId, MessageDeduplicationId, exactly-once processing
- **Visibility Timeout**: Change visibility timeout mid-flight, verify behavior
- **Dead Letter Queues**: Configure maxReceiveCount, verify redrive policy
- **Long Polling**: WaitTimeSeconds variations, empty queue behavior
- **Message Attributes**: String, Number, Binary attributes with filtering
- **Batch Operations**: SendMessageBatch, DeleteMessageBatch with mixed success/failure

### If services include API Gateway:
**API Gateway Parity Probe** - Test advanced API Gateway features:
- **Request Validation**: Body validation with JSON Schema, required parameters
- **Response Templates**: VTL templates for response transformation
- **Authorizers**: Lambda authorizers, JWT authorizers with claims
- **Usage Plans**: API keys, throttling limits, quota enforcement
- **CORS**: Preflight requests, custom headers
- **Binary Media**: Handle binary payloads (images, PDFs)

### If services include multiple services:
**Cross-Service Integration Probe** - Test service interactions:
- S3 -> Lambda triggers with various event types (ObjectCreated, ObjectRemoved)
- DynamoDB Streams -> Lambda with batch processing
- SQS -> Lambda with partial batch failures
- API Gateway -> Lambda with proxy integration
- SNS -> SQS fanout patterns
- Step Functions with parallel and choice states

## Required File Structure

### src/probes.py
AWS API parity probes:
- One class per AWS service being tested
- Each method tests a specific advanced feature
- Return structured results: {feature, expected, actual, passed, error_message}
- Use descriptive method names: test_dynamodb_transactions, test_s3_versioning

### src/validators.py
Response validation layer:
- Compare LocalStack responses to expected AWS behavior
- Check response structure, field names, data types
- Verify error codes match AWS error codes exactly
- Validate pagination tokens and markers

### src/fixtures.py
Test data and resource creation:
- Factory methods for creating test resources
- Realistic test data with edge cases (unicode, large payloads)
- Cleanup methods to delete resources after tests
- Idempotent setup that can run multiple times

### src/reporters.py
Issue reporting:
- Collect all probe results into structured report
- Categorize issues: NOT_IMPLEMENTED, PARTIAL_IMPLEMENTATION, BEHAVIOR_MISMATCH
- Include reproduction steps for each issue found
- Generate both human-readable and JSON output

### src/config.py
Configuration with:
- LocalStack endpoint URLs (default: http://localhost:4566)
- AWS region and credentials (dummy for LocalStack)
- Timeouts and retry settings
- Feature flags to enable/disable specific probes

### src/__init__.py
Package initialization with logging setup

## Code Quality Requirements

1. **Issue Discovery Focus**:
   - Test advanced API parameters, not just required ones
   - Probe edge cases: empty values, max lengths, special characters, unicode
   - Verify exact response structure matches AWS documentation
   - Check error codes and error message formats

2. **Comprehensive Probing**:
   - Test each feature in isolation for clear issue identification
   - Include both success and expected failure scenarios
   - Verify side effects (items written, events triggered, streams updated)
   - Test concurrent operations for race condition detection

3. **Clear Issue Reporting**:
   - Each test returns: feature_name, expected_behavior, actual_behavior, passed, details
   - Categorize issues: NOT_IMPLEMENTED, WRONG_RESPONSE, MISSING_FIELD, WRONG_ERROR_CODE
   - Include boto3 call that triggered the issue for reproduction
   - Suggest workarounds where applicable

4. **LocalStack Compatibility**:
   - Use `endpoint_url` parameter for all boto3 clients
   - Default to `http://localhost:4566` for LocalStack
   - Support `AWS_ENDPOINT_URL` environment variable
   - Handle LocalStack-specific quirks gracefully (don't crash on missing features)

Output the code as a JSON object with the following structure:
```json
{{
  "files": {{
    "src/probes.py": "...",
    "src/validators.py": "...",
    "src/fixtures.py": "...",
    "src/reporters.py": "...",
    "src/config.py": "...",
    "src/__init__.py": "..."
  }},
  "requirements": ["boto3>=1.28.0", "pydantic>=2.0.0", "..."],
  "probed_features": ["dynamodb_transactions", "s3_versioning", "..."]
}}
```"""

# Test generation prompt template
TEST_GENERATION_PROMPT = """Generate pytest tests that DISCOVER LOCALSTACK IMPLEMENTATION GAPS for the following probe application:

## Probe Application Code
```python
{app_code}
```

## Infrastructure Services Being Tested
- Services: {services}
- Lambda Functions: {lambda_functions}
- Database Tables: {database_tables}
- Queues: {queue_resources}
- Storage: {storage_resources}

## Test Requirements

Generate tests that EXPOSE LOCALSTACK ISSUES, not just verify basic functionality:

### tests/conftest.py
Test infrastructure:
- LocalStack-configured boto3 clients with endpoint_url
- Resource creation fixtures with unique names per test run
- Cleanup fixtures that handle partial failures
- Markers for categorizing tests: @pytest.mark.localstack_gap, @pytest.mark.aws_parity
- Skip decorators for known unsupported features

### tests/test_dynamodb_parity.py (if DynamoDB in services)
DynamoDB API parity tests:
- test_transact_write_items_with_condition_check - Verify transactions work
- test_transact_write_items_rollback - Verify atomic rollback on condition failure
- test_stream_view_types - Test all StreamViewType options
- test_gsi_projection_types - Verify GSI with KEYS_ONLY, INCLUDE, ALL
- test_ttl_expiration - Verify items are deleted after TTL
- test_conditional_expressions - Complex ConditionExpression evaluation
- test_batch_write_25_items - Maximum batch size handling
- test_query_pagination - Verify LastEvaluatedKey is correct
- test_filter_expression_with_reserved_words - Reserved word handling

### tests/test_s3_parity.py (if S3 in services)
S3 API parity tests:
- test_versioning_enabled - Upload versions, list versions
- test_delete_marker_creation - Delete versioned object
- test_multipart_upload_complete - Full multipart flow
- test_multipart_upload_abort - Abort and cleanup
- test_presigned_url_put - Generate and use presigned PUT
- test_presigned_url_expiration - Verify URL expires correctly
- test_lifecycle_rule_expiration - Objects deleted after rule
- test_event_notification_to_lambda - Verify trigger fires
- test_cors_preflight - OPTIONS request handling

### tests/test_lambda_parity.py (if Lambda in services)
Lambda API parity tests:
- test_layer_attachment - Layer code accessible in function
- test_reserved_concurrency - Throttling when limit reached
- test_dead_letter_queue - Failed invocations go to DLQ
- test_async_invocation_retry - Verify retry behavior
- test_event_source_mapping_batch - Batch processing from SQS/DynamoDB
- test_environment_variable_encryption - KMS encrypted env vars

### tests/test_sqs_parity.py (if SQS in services)
SQS API parity tests:
- test_fifo_message_ordering - MessageGroupId ordering
- test_fifo_deduplication - MessageDeduplicationId works
- test_visibility_timeout_extension - ChangeMessageVisibility
- test_dead_letter_redrive - Message moves after maxReceiveCount
- test_long_polling_empty_queue - WaitTimeSeconds behavior
- test_message_attributes_filtering - Attribute-based subscription

### tests/test_api_gateway_parity.py (if API Gateway in services)
API Gateway parity tests:
- test_request_body_validation - JSON Schema validation
- test_required_parameter_validation - Missing required params
- test_response_template_transformation - VTL template rendering
- test_lambda_authorizer - Custom authorizer invocation
- test_cors_headers - Access-Control-* headers

### tests/test_cross_service.py
Cross-service integration tests:
- test_s3_lambda_trigger_payload - Verify event structure matches AWS
- test_dynamodb_stream_lambda_payload - Stream record format
- test_sqs_lambda_batch_failure - Partial batch failure handling
- test_api_gateway_lambda_proxy - Proxy integration format

## Issue Detection Patterns

Each test should:
1. **Document Expected AWS Behavior**: Comment with AWS documentation reference
2. **Make API Call**: Use exact parameters as documented
3. **Capture Response**: Store full response for analysis
4. **Compare to Expected**: Check structure, fields, values, error codes
5. **Report Issue**: Clear failure message with reproduction steps

Example test pattern:
```python
def test_dynamodb_transact_write_rollback(dynamodb_client, test_table):
    \"\"\"
    AWS Behavior: TransactWriteItems is atomic - all succeed or all fail.
    If any ConditionCheck fails, entire transaction rolls back.
    AWS Docs: https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html
    \"\"\"
    # Setup: Create item that will cause condition to fail
    dynamodb_client.put_item(TableName=test_table, Item={{'pk': {{'S': 'existing'}}}})

    # Action: Transaction with one valid write and one failing condition
    with pytest.raises(ClientError) as exc_info:
        dynamodb_client.transact_write_items(TransactItems=[
            {{'Put': {{'TableName': test_table, 'Item': {{'pk': {{'S': 'new-item'}}}}}}}},
            {{'ConditionCheck': {{
                'TableName': test_table,
                'Key': {{'pk': {{'S': 'existing'}}}},
                'ConditionExpression': 'attribute_not_exists(pk)'  # Will fail
            }}}}
        ])

    # Verify: Correct error code
    assert exc_info.value.response['Error']['Code'] == 'TransactionCanceledException'

    # Verify: First item was NOT written (rollback worked)
    result = dynamodb_client.get_item(TableName=test_table, Key={{'pk': {{'S': 'new-item'}}}})
    assert 'Item' not in result, "Transaction should have rolled back - item should not exist"
```

## Test Output Format

Tests should output structured results for reporting:
- Feature being tested
- Expected AWS behavior
- Actual LocalStack behavior
- Pass/Fail status
- Reproduction command

Output as JSON:
```json
{{
  "files": {{
    "tests/conftest.py": "...",
    "tests/test_dynamodb_parity.py": "...",
    "tests/test_s3_parity.py": "...",
    "tests/test_lambda_parity.py": "...",
    "tests/test_sqs_parity.py": "...",
    "tests/test_api_gateway_parity.py": "...",
    "tests/test_cross_service.py": "..."
  }},
  "requirements": ["pytest>=7.0.0", "pytest-asyncio>=0.21.0", "moto>=4.0.0", "..."],
  "tested_features": ["dynamodb_transactions", "s3_versioning", "lambda_dlq", "..."]
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


# Import ProbeType for type hints - avoid circular import
from src.models.architecture import ProbeType


# Probe-specific prompt configurations
PROBE_CONFIGS = {
    ProbeType.API_PARITY: {
        "name": "API Parity Probe",
        "description": "Tests advanced AWS API parameters and response format accuracy",
        "focus": """
Focus on AWS API PARITY - testing that LocalStack implements AWS APIs correctly:

1. **Advanced API Parameters**: Use optional parameters that are often not implemented
   - DynamoDB: ProjectionExpression, ExpressionAttributeNames, ReturnConsumedCapacity
   - S3: VersionId, RequestPayer, ExpectedBucketOwner
   - Lambda: Qualifier, LogType, ClientContext
   - SQS: MessageDeduplicationId, MessageGroupId, MessageAttributes

2. **Response Format Accuracy**: Verify responses match AWS exactly
   - Check all expected fields are present
   - Verify data types match (strings vs numbers)
   - Check error code formats and messages

3. **Pagination**: Test pagination with various page sizes
   - Verify NextToken/LastEvaluatedKey format
   - Test edge cases (empty pages, single item pages)

4. **Error Handling**: Verify correct error codes
   - ResourceNotFoundException, ValidationException
   - Conditional check failures, throttling errors
""",
    },
    ProbeType.EDGE_CASES: {
        "name": "Edge Cases Probe",
        "description": "Tests boundary conditions, special characters, and limits",
        "focus": """
Focus on EDGE CASES - testing boundary conditions and unusual inputs:

1. **Large Payloads**: Test size limits
   - S3: Upload 5MB+ files, multipart uploads for 100MB+
   - DynamoDB: Items approaching 400KB limit
   - SQS: Messages at 256KB limit
   - Lambda: Payloads at 6MB sync / 256KB async limits

2. **Special Characters & Unicode**: Test handling of unusual data
   - Emoji in strings: 🎉 📧 ✅
   - Unicode: Chinese (中文), Arabic (العربية), Thai (ไทย)
   - Special chars: null bytes, newlines in keys, control characters
   - Reserved characters in S3 keys: spaces, &, ?, #

3. **Boundary Values**: Test numeric and temporal limits
   - TTL values at boundaries (0, negative, far future)
   - Timestamps at epoch, far past, far future
   - Empty strings vs null values
   - Maximum key lengths

4. **Empty/Null Handling**: Test missing data scenarios
   - Empty lists in batch operations
   - Null values in JSON
   - Missing optional fields
""",
    },
    ProbeType.INTEGRATION: {
        "name": "Cross-Service Integration Probe",
        "description": "Tests event triggers and cross-service data flow",
        "focus": """
Focus on CROSS-SERVICE INTEGRATION - testing how services interact:

1. **Event Triggers**: Verify events fire correctly
   - S3 -> Lambda: ObjectCreated, ObjectRemoved events
   - DynamoDB Streams -> Lambda: INSERT, MODIFY, REMOVE
   - SQS -> Lambda: Message polling and batch processing
   - SNS -> SQS: Fanout subscription delivery

2. **Event Payload Format**: Verify event structures match AWS
   - S3 event: Records[].s3.bucket.name, object.key
   - DynamoDB stream: Records[].dynamodb.NewImage, OldImage
   - SQS event: Records[].body, messageAttributes

3. **Error Handling in Integrations**: Test failure scenarios
   - Lambda timeout during S3 trigger
   - DLQ behavior when Lambda fails
   - Partial batch failures in SQS->Lambda

4. **Event Ordering & Delivery**: Test reliability
   - FIFO ordering in SQS
   - At-least-once delivery guarantees
   - Event deduplication
""",
    },
    ProbeType.STRESS: {
        "name": "Concurrent Operations Probe",
        "description": "Tests race conditions, concurrency, and throttling",
        "focus": """
Focus on CONCURRENT OPERATIONS - testing race conditions and throughput:

1. **Race Conditions**: Test concurrent access
   - Multiple writers to same DynamoDB item
   - Concurrent S3 uploads to same key
   - Parallel Lambda invocations updating shared state

2. **Optimistic Locking**: Test conditional operations
   - DynamoDB ConditionExpression with version numbers
   - S3 conditional PUT with ETag matching
   - Transaction conflicts in TransactWriteItems

3. **Throttling Behavior**: Test rate limiting
   - DynamoDB provisioned throughput limits
   - Lambda reserved concurrency limits
   - API Gateway throttling responses

4. **Batch Operation Limits**: Test maximum batch sizes
   - BatchWriteItem with 25 items
   - BatchGetItem with 100 keys
   - SQS batch of 10 messages
   - S3 delete of 1000 objects
""",
    },
}


# Probe-specific generation prompt template
PROBE_GENERATION_TEMPLATE = """Generate a Python probe application to test {probe_name} for the following AWS infrastructure:

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

## Probe Focus
{probe_focus}

## Required File Structure

### src/probes/{probe_type}_probe.py
Main probe class with test methods:
- Each method tests one specific feature
- Methods return ProbeResult with: feature, expected, actual, passed, error
- Use descriptive names: test_dynamodb_transactions, test_s3_versioning

### src/fixtures.py
Test data and resource creation:
- Factory methods for test resources
- Realistic test data with the focus areas above
- Cleanup methods for teardown

### src/config.py
Configuration:
- LocalStack endpoint URL (default: http://localhost:4566)
- AWS credentials (test/test for LocalStack)
- Timeouts and retries

### src/__init__.py
Package initialization

## Output Format
```json
{{
  "files": {{
    "src/probes/{probe_type}_probe.py": "...",
    "src/fixtures.py": "...",
    "src/config.py": "...",
    "src/__init__.py": "..."
  }},
  "requirements": ["boto3>=1.28.0", "pytest>=7.0.0", "..."],
  "probed_features": ["feature1", "feature2", "..."],
  "probe_name": "{probe_name}"
}}
```"""


def get_probe_prompt(
    probe_type: "ProbeType",
    analysis: InfrastructureAnalysis,
    terraform_content: str,
) -> str:
    """
    Get the probe-specific generation prompt.

    Args:
        probe_type: Type of probe to generate
        analysis: Infrastructure analysis result
        terraform_content: Original Terraform content

    Returns:
        Formatted prompt string for the specific probe type
    """
    config = PROBE_CONFIGS.get(probe_type, PROBE_CONFIGS[ProbeType.API_PARITY])

    return PROBE_GENERATION_TEMPLATE.format(
        probe_name=config["name"],
        probe_type=probe_type.value,
        probe_focus=config["focus"],
        services=", ".join(sorted(analysis.services)),
        lambda_functions=", ".join(analysis.lambda_functions) or "None",
        api_endpoints=", ".join(analysis.api_endpoints) or "None",
        storage_resources=", ".join(analysis.storage_resources) or "None",
        database_tables=", ".join(analysis.database_tables) or "None",
        queue_resources=", ".join(analysis.queue_resources) or "None",
        event_sources=", ".join(analysis.event_sources) or "None",
        terraform_content=terraform_content[:4000],
    )
