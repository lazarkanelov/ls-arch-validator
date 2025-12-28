# Feature Specification: LocalStack Architecture Validator

**Feature Branch**: `001-arch-validator`
**Created**: 2025-12-26
**Status**: Draft
**Input**: Automated system that validates LocalStack's compatibility with real-world AWS architectural patterns

## Clarifications

### Session 2025-12-26

- Q: How is Architecture uniqueness determined? → A: Unique by source_repo + template_path (same path in different repos = different IDs)
- Q: What level of pipeline observability is required? → A: Structured logs with run-level metrics (JSON logs, timing per stage, success/failure counts)
- Q: How should Claude API usage be managed? → A: Per-run token budget with caching (skip generation for unchanged architectures, cap total tokens per run)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Architecture Compatibility Dashboard (Priority: P1)

As a LocalStack user or engineer, I want to view a public dashboard showing which real-world AWS architectures work with LocalStack so that I can make informed decisions about which patterns to use.

**Why this priority**: The dashboard is the primary value delivery mechanism. Without visibility into results, all validation work is invisible and unusable.

**Independent Test**: Can be tested by deploying a static dashboard with sample data and verifying all UI components render correctly and load within performance targets.

**Acceptance Scenarios**:

1. **Given** a completed validation run with mixed results, **When** I visit the dashboard URL, **Then** I see summary cards showing total architectures, passed, partial, failed, and overall pass rate.

2. **Given** historical validation data exists for 7+ days, **When** I view the dashboard, **Then** I see a trend chart showing pass rate changes over the past 7 days.

3. **Given** some architectures failed validation, **When** I expand a failure entry, **Then** I see the architecture name, source, services involved, error message, and can access full logs.

4. **Given** the dashboard is loaded, **When** I view the service coverage matrix, **Then** I see each AWS service with its tested count, passed count, failed count, and visual pass rate indicator.

5. **Given** any validation results exist, **When** I want to process data programmatically, **Then** I can download raw JSON data and access historical run archives.

---

### User Story 2 - Run Full Validation Pipeline (Priority: P2)

As an engineer maintaining LocalStack, I want the system to automatically mine templates, generate test applications, run validations, and produce reports so that I have continuous visibility into compatibility without manual effort.

**Why this priority**: The automated pipeline is the engine that produces the dashboard data. It must work end-to-end before the dashboard has meaningful content.

**Independent Test**: Can be tested by running the complete pipeline against a small set of known templates and verifying it produces valid result files.

**Acceptance Scenarios**:

1. **Given** the scheduled trigger fires at 3 AM UTC, **When** the pipeline starts, **Then** it mines templates from configured sources, generates sample apps, runs validations, and publishes results.

2. **Given** multiple architectures to validate, **When** the pipeline runs, **Then** it processes up to 4 architectures concurrently by default.

3. **Given** an individual architecture fails during validation, **When** the pipeline continues, **Then** it completes validation for all remaining architectures and reports partial results.

4. **Given** a validation completes (pass or fail), **When** results are recorded, **Then** all relevant logs are captured (infrastructure deployment, application execution, test results).

5. **Given** resources were created during validation, **When** that validation completes, **Then** all resources are cleaned up regardless of success or failure.

---

### User Story 3 - Mine and Normalize Templates (Priority: P3)

As the validation system, I need to discover infrastructure templates from trusted sources and normalize them to a consistent format so that I can generate meaningful test applications.

**Why this priority**: Template mining is the input stage. Without templates, there's nothing to validate. However, a small set of manually curated templates can bootstrap the system.

**Independent Test**: Can be tested by mining a single repository and verifying the output contains normalized templates with extracted metadata.

**Acceptance Scenarios**:

1. **Given** configured template sources (AWS Quick Starts, Terraform Registry, AWS Solutions, Serverless examples), **When** mining executes, **Then** it clones repositories and extracts infrastructure templates.

2. **Given** a CloudFormation or SAM template, **When** processing completes, **Then** it is converted to Terraform format.

3. **Given** any template, **When** normalization completes, **Then** the template uses LocalStack-compatible endpoints and credentials (no hardcoded regions, account IDs, or resource names).

4. **Given** a normalized template, **When** metadata extraction completes, **Then** the system records which AWS services are used, resource count, and complexity score.

5. **Given** a source repository has not changed since last run, **When** mining executes, **Then** cached templates are used instead of re-mining.

---

### User Story 4 - Generate Sample Applications (Priority: P4)

As the validation system, I need to generate executable sample applications that exercise the infrastructure so that I can verify services communicate correctly.

**Why this priority**: Sample apps are what make the validation meaningful. Without them, we can only verify "infrastructure deploys" not "infrastructure works."

**Independent Test**: Can be tested by generating an app for a known template and verifying it compiles and contains appropriate test assertions.

**Acceptance Scenarios**:

1. **Given** a normalized Terraform template, **When** app generation runs, **Then** an analysis identifies the services and their integration points.

2. **Given** an infrastructure analysis, **When** code generation completes, **Then** a sample application is created that triggers actual integrations (e.g., writes to S3 that fires Lambda that writes to DynamoDB).

3. **Given** a generated application, **When** test generation completes, **Then** test suites contain assertions that verify data flow, not just API call completion.

4. **Given** eventual consistency in AWS services, **When** tests are generated, **Then** they include retry logic and configurable timeouts for assertions.

5. **Given** a generated application, **When** validation step runs, **Then** the app is verified to compile successfully before proceeding to execution.

---

### User Story 5 - Automatic Issue Creation for Failures (Priority: P5)

As an engineer, I want the system to automatically create GitHub issues for persistent failures so that I can track and prioritize fixes without manually monitoring the dashboard.

**Why this priority**: Issue creation is a convenience feature that improves workflow. The system provides value without it (engineers can check the dashboard manually).

**Independent Test**: Can be tested by simulating consecutive failures and verifying issues are created with correct content and labels.

**Acceptance Scenarios**:

1. **Given** an architecture fails for the first time, **When** the run completes, **Then** no issue is created (to avoid noise from transient failures).

2. **Given** an architecture fails for 2+ consecutive runs, **When** the latest run completes, **Then** a GitHub issue is created automatically.

3. **Given** an issue is created, **When** I view it, **Then** it includes: architecture name, source, services involved, error details, relevant logs, reproduction steps, and a link to the dashboard.

4. **Given** an issue is created, **When** I view its labels, **Then** it has `arch-validator`, `bug`, and `service/<service-name>` labels applied.

5. **Given** a failure already has an open issue, **When** subsequent failures occur, **Then** no duplicate issue is created.

---

### User Story 6 - Manual Pipeline Trigger with Options (Priority: P6)

As an engineer, I want to manually trigger the validation pipeline with custom options so that I can test specific architectures or configurations.

**Why this priority**: Manual triggers are a power-user feature. The scheduled runs provide continuous value; manual runs add flexibility.

**Independent Test**: Can be tested by manually triggering with various option combinations and verifying the pipeline respects each setting.

**Acceptance Scenarios**:

1. **Given** I want to test a specific architecture, **When** I trigger manually, **Then** I can specify which architecture(s) to validate.

2. **Given** templates are already cached, **When** I trigger manually, **Then** I can skip the mining phase to save time.

3. **Given** I want faster or slower execution, **When** I trigger manually, **Then** I can specify the parallelism level (number of concurrent validations).

4. **Given** I want to test a specific LocalStack version, **When** I trigger manually, **Then** I can specify which version to use.

---

### Edge Cases

- What happens when a template source repository is unavailable or rate-limited?
  - System logs the failure, skips that source, and continues with other sources.

- What happens when CloudFormation-to-Terraform conversion fails?
  - System logs the failure with conversion errors, marks the template as "conversion failed," and continues with other templates.

- What happens when sample app generation produces code that doesn't compile?
  - System marks the architecture as "generation failed" with compiler errors, skips execution phase, and continues with other architectures.

- What happens when LocalStack container fails to start?
  - System marks the architecture as "infrastructure failed" with container logs, attempts cleanup, and continues with other architectures.

- What happens when tests hang or exceed timeout?
  - System terminates the test run at the configured timeout, captures partial results and logs, marks as "timeout," and continues with other architectures.

- What happens when the GitHub API rate limit is exceeded during issue creation?
  - System queues the issue for creation in the next run, logs the rate limit event, and completes the run successfully.

- What happens when an architecture that previously failed now passes?
  - System resets the consecutive failure counter for that architecture. If an open issue exists, system adds a comment noting the fix and closes the issue automatically.

- What happens when an architecture uses AWS services not supported by LocalStack?
  - System detects unsupported services during normalization, logs a warning, marks the architecture as "unsupported-services" with a list of problematic services, and excludes it from validation (counted separately in reporting).

- What happens when the Claude API is unavailable or returns errors?
  - System logs the error, skips generation for affected architectures (using cached apps if available), and continues with the pipeline. Multiple consecutive API failures trigger an alert in the run summary.

- What happens when tests pass sometimes and fail other times (flaky tests)?
  - System tracks test stability across runs. An architecture is only marked as "failed" for issue creation purposes if it fails consistently (2+ consecutive runs), filtering out intermittent failures.

- What happens when Claude Vision fails to parse an architecture diagram?
  - System assigns a low confidence score, logs the parsing failure with the image URL, skips that diagram, and continues with other diagrams.

- What happens when an Azure diagram contains services with no AWS equivalent?
  - System logs a warning listing the unmapped services, attempts partial Terraform generation for mapped services only, and marks the architecture as "partial-mapping" in reports.

## Requirements *(mandatory)*

### Functional Requirements

**Template Mining**

- **FR-001**: System MUST mine infrastructure templates from AWS Quick Starts, Terraform Registry, AWS Solutions Library, and Serverless Framework examples repositories.
- **FR-002**: System MUST convert CloudFormation and SAM templates to Terraform format.
- **FR-003**: System MUST normalize all templates to use LocalStack-compatible endpoints and parameterized resource names (no hardcoded regions, account IDs, or resource names).
- **FR-004**: System MUST extract and store metadata for each template: AWS services used, resource count, and complexity indicator.
- **FR-005**: System MUST cache templates and skip re-mining for unchanged source repositories.

**Diagram Mining**

- **FR-006**: System MUST scrape architecture diagram images (PNG/JPG/SVG) from AWS Architecture Center.
- **FR-007**: System MUST scrape architecture diagram images from Azure Architecture Center as a supplementary pattern source.
- **FR-008**: System MUST parse diagram images using Claude Vision API to identify services and their connections.
- **FR-009**: System MUST map Azure services detected in diagrams to AWS equivalents (e.g., Azure Functions → Lambda, Cosmos DB → DynamoDB).
- **FR-010**: System MUST synthesize Terraform code from parsed diagram data, targeting AWS services only.
- **FR-011**: System MUST assign a confidence score to diagram-derived architectures and skip low-confidence results.
- **FR-012**: System MUST report diagram-derived architectures separately from template-derived architectures in the dashboard.

**Sample App Generation**

- **FR-013**: System MUST generate sample applications that actively use the infrastructure (trigger integrations, verify data flow).
- **FR-014**: System MUST generate test suites with assertions that verify actual data transformations, not just API call completion.
- **FR-015**: System MUST include retry logic and configurable timeouts in generated tests to handle eventual consistency.
- **FR-016**: System MUST validate that generated applications compile successfully before proceeding to execution.
- **FR-017**: System MUST cache generated sample apps and skip regeneration for unchanged architectures.
- **FR-018**: System MUST enforce a configurable per-run token budget for Claude API usage.
- **FR-019**: System MUST halt generation (not the entire pipeline) when token budget is exhausted, proceeding with already-generated apps.

**Validation Runner**

- **FR-020**: System MUST run each architecture validation in an isolated LocalStack container with unique ports.
- **FR-021**: System MUST support parallel execution of validations (default: 4 concurrent).
- **FR-022**: System MUST capture all logs for each validation: infrastructure deployment output, LocalStack container logs, application logs, and test results.
- **FR-023**: System MUST enforce configurable timeout boundaries at each pipeline stage.
- **FR-024**: System MUST clean up all containers and resources after each validation, regardless of outcome.
- **FR-025**: System MUST continue processing remaining architectures when individual validations fail.

**Result Recording**

- **FR-026**: System MUST record a status for each architecture: passed (all tests pass), partial (some tests fail), or failed (deployment or critical failures).
- **FR-027**: System MUST record infrastructure deployment details: success/failure status, duration, resources created, and any errors.
- **FR-028**: System MUST record test execution details: tests passed, tests failed, and failure messages.
- **FR-029**: System MUST bundle all logs for each architecture (terraform.log, localstack.log, app.log).
- **FR-030**: System MUST generate a suggested issue title for failures.

**Dashboard**

- **FR-031**: System MUST display summary cards: total architectures, passed, partial, failed, and pass rate percentage.
- **FR-032**: System MUST display a 7-day trend chart showing pass rate over time.
- **FR-033**: System MUST display failures in an expandable list showing architecture name, source, services, error message, logs, and linked issue.
- **FR-034**: System MUST display a service coverage matrix with each AWS service showing: tested count, passed, failed, and visual pass rate.
- **FR-035**: System MUST provide a collapsible list of passing architectures.
- **FR-036**: System MUST provide raw JSON data download.
- **FR-037**: System MUST maintain an accessible archive of historical runs.

**GitHub Integration**

- **FR-038**: System MUST create GitHub issues only after 2+ consecutive failures of the same architecture.
- **FR-039**: System MUST NOT create duplicate issues for failures that already have open issues.
- **FR-040**: System MUST apply labels to issues: `arch-validator`, `bug`, and `service/<service-name>` for each involved service.
- **FR-041**: Issues MUST include: architecture name, source, services, error details, relevant logs, reproduction steps, and dashboard link.
- **FR-042**: System MUST automatically close open issues when the corresponding architecture passes validation.
- **FR-043**: System MUST add a comment to auto-closed issues indicating which run validated the fix.

**Automation**

- **FR-044**: System MUST run automatically on a daily schedule at 3 AM UTC.
- **FR-045**: System MUST support manual triggering with options: specific architectures, architecture exclusion patterns, skip mining, parallelism level, LocalStack version.
- **FR-046**: System MUST deploy the updated dashboard after each run.
- **FR-047**: System MUST support optional notifications on run completion.

**Observability**

- **FR-048**: System MUST emit structured logs in JSON format for all pipeline operations.
- **FR-049**: System MUST record timing metrics for each pipeline stage (mining, generation, running, reporting).
- **FR-050**: System MUST track and report success/failure counts per stage at the end of each run.
- **FR-051**: System MUST include correlation identifiers in logs to trace individual architecture validations.

**Data Management**

- **FR-052**: System MUST retain historical run data and logs for 90 days with a maximum storage cap of 10GB.
- **FR-053**: System MUST track which AWS services are unsupported by LocalStack and report them separately in the dashboard.

### Key Entities

- **TemplateSource**: A repository or registry from which infrastructure templates are mined. Has URL, type (GitHub/Registry), and last-mined timestamp.

- **Architecture**: A normalized infrastructure template ready for validation. Has unique identifier (derived from source_repo + template_path), source reference, Terraform files, extracted metadata (services, resource count, complexity). The same template path in different source repositories is treated as distinct architectures.
  - **Complexity Score Calculation**: Low (1-5 resources), Medium (6-15 resources OR 3+ services), High (16+ resources OR 5+ services OR nested Terraform modules).

- **SampleApp**: A generated application that exercises an architecture. Has source code, test files, dependency manifest, and compile status.

- **ValidationRun**: A complete execution of the pipeline. Has timestamp, duration, list of results, and overall statistics.

- **ArchitectureResult**: Outcome of validating a single architecture. Has status (passed/partial/failed), infrastructure details, test results, log bundle, and optional issue reference.

- **ServiceCoverage**: Aggregated statistics for an AWS service. Has service name, count of architectures tested, passed, failed, and computed pass rate.

- **FailureTracker**: Tracks consecutive failures per architecture. Has architecture ID, failure count, and linked issue ID if created.

## Assumptions

The following reasonable defaults and assumptions have been made:

1. **Validation target is AWS only**: All architectures are validated against LocalStack (AWS emulator). Azure Architecture Center diagrams are scraped as a supplementary source of architectural patterns, but are translated to AWS equivalents before validation. LocalStack for Azure is not supported.

2. **Generated apps use Python 3.11+**: Aligned with the core pipeline stack; provides boto3 for AWS SDK support and pytest for testing.

3. **cf2tf is available for CloudFormation conversion**: This is a known open-source tool for CloudFormation-to-Terraform conversion.

4. **tflocal wraps Terraform for LocalStack**: This is the official LocalStack Terraform wrapper.

5. **GitHub Pages hosts the dashboard**: Standard static site hosting for GitHub projects, implied by "gh-pages branch."

6. **GitHub Actions is the CI/CD platform**: Explicitly stated in the requirements.

7. **Slack notifications use webhook integration**: Standard pattern for CI/CD notifications.

8. **Historical data retention is 90 days**: Standard retention period for CI/CD artifacts, balancing storage costs with useful historical analysis.

9. **Dashboard uses client-side rendering**: Simpler deployment model for static hosting; JSON data loaded and rendered in browser.

10. **Diagram parsing uses Claude Vision API**: Architecture diagrams (PNG/JPG/SVG) are parsed using Claude's vision capabilities to extract services and connections, then synthesized into Terraform.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: System discovers and normalizes at least 50 distinct architectural patterns from configured sources.
- **SC-002**: Sample application generation succeeds for at least 90% of normalized templates.
- **SC-003**: Complete validation pipeline (mining through reporting) completes within 2 hours.
- **SC-004**: Dashboard page loads and becomes interactive within 3 seconds on standard broadband connection.
- **SC-005**: GitHub issues are created within 5 minutes of run completion for architectures meeting the consecutive failure threshold.
- **SC-006**: Engineers can identify the root cause of a failure from the dashboard without re-running the validation (logs and errors are sufficient).
- **SC-007**: Service coverage matrix accurately reflects which AWS services have been tested and their success rates.
- **SC-008**: Trend data correctly shows pass rate changes over the 7-day window.
- **SC-009**: No manual intervention required for scheduled daily runs under normal operation.
- **SC-010**: Pipeline resilience: completion of 90%+ of validations even when 10% of individual architectures fail.
