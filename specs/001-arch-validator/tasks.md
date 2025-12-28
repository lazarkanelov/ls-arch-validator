# Tasks: LocalStack Architecture Validator

**Input**: Design documents from `/specs/001-arch-validator/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md

**Tests**: Not explicitly requested in specification. Unit/integration tests can be added in Polish phase if desired.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Create project structure per plan.md layout (src/, templates/, config/, tests/, docs/)
- [x] T002 Initialize Python project with pyproject.toml including all dependencies (httpx, jinja2, pyyaml, anthropic, PyGithub, beautifulsoup4, lxml, Pillow, boto3, pytest, structlog, docker)
- [x] T003 [P] Create src/__init__.py with version and package metadata
- [x] T004 [P] Create config/defaults.yaml with default settings (parallelism: 4, token_budget: 500000, retention_days: 90)
- [x] T005 [P] Create config/sources.yaml with template source configuration per research.md
- [x] T006 [P] Create config/diagram_sources.yaml with AWS/Azure Architecture Center URLs
- [x] T007 [P] Create config/timeouts.yaml with stage timeout configuration
- [x] T008 [P] Configure .gitignore for Python project (cache/, .venv/, __pycache__/, *.pyc, .env)
- [x] T009 [P] Create .env.example with required environment variables (ANTHROPIC_API_KEY, GITHUB_TOKEN, LOCALSTACK_API_KEY)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T010 Implement structured JSON logging utility in src/utils/logging.py using structlog with correlation ID support
- [x] T011 [P] Create TemplateSource dataclass in src/models/architecture.py per data-model.md
- [x] T012 [P] Create Architecture dataclass with ArchitectureStatus and ArchitectureMetadata in src/models/architecture.py
- [x] T013 [P] Create SampleApp dataclass in src/models/architecture.py
- [x] T014 [P] Create ValidationRun dataclass with RunStatistics and StageTiming in src/models/results.py
- [x] T015 [P] Create ArchitectureResult dataclass with InfrastructureResult, TestResult, LogBundle in src/models/results.py
- [x] T016 [P] Create ServiceCoverage dataclass in src/models/coverage.py
- [x] T017 [P] Create FailureTracker and FailureEntry dataclasses in src/models/coverage.py
- [x] T018 Implement file-based caching utility in src/utils/cache.py with content hashing and cache key generation
- [x] T019 [P] Implement token budget tracker in src/utils/tokens.py per research.md token budget strategy
- [x] T020 Create CLI entry point skeleton in src/cli.py with click/typer, global options per contracts/cli.md
- [x] T021 Create src/models/__init__.py exporting all models
- [x] T022 Create src/utils/__init__.py exporting all utilities

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - View Architecture Compatibility Dashboard (Priority: P1) 🎯 MVP

**Goal**: Display a public dashboard showing which real-world AWS architectures work with LocalStack

**Independent Test**: Deploy static dashboard with sample data; verify all UI components render correctly and load within 3 seconds

### Implementation for User Story 1

- [x] T023 [P] [US1] Create Jinja2 base template in templates/base.html with responsive CSS Grid layout
- [x] T024 [P] [US1] Create summary cards partial in templates/partials/summary_cards.html (total, passed, partial, failed, pass rate)
- [x] T025 [P] [US1] Create trend chart partial in templates/partials/trend_chart.html using Chart.js for 7-day history
- [x] T026 [P] [US1] Create failure list partial in templates/partials/failure_list.html with expandable entries (architecture name, source, services, error, logs link)
- [x] T027 [P] [US1] Create service coverage matrix partial in templates/partials/service_matrix.html (service name, tested count, passed, failed, visual pass rate)
- [x] T028 [P] [US1] Create passing architectures partial in templates/partials/passing_list.html with collapsible list
- [x] T029 [US1] Create main dashboard template in templates/index.html combining all partials
- [x] T030 [P] [US1] Create dashboard CSS in docs/assets/styles.css with responsive design
- [x] T031 [P] [US1] Create sample data file in docs/data/latest.json with mock validation results for testing
- [x] T032 [P] [US1] Create sample history file in docs/data/history.json with 7-day mock trend data
- [x] T033 [US1] Implement results aggregator in src/reporter/aggregator.py (collect results, compute statistics, compute pass rate)
- [x] T034 [US1] Implement service coverage computation in src/reporter/aggregator.py
- [x] T035 [US1] Implement diagram vs template architecture separation in src/reporter/aggregator.py and dashboard per FR-012 (separate sections, filter by source_type)
- [x] T036 [US1] Implement trend analysis in src/reporter/trends.py (load historical runs, compute 7-day pass rate changes)
- [x] T037 [US1] Implement static site generator in src/reporter/site.py (render Jinja2 templates with data)
- [x] T038 [US1] Create src/reporter/__init__.py exporting aggregator, trends, site modules
- [x] T039 [US1] Implement `report` command in src/cli.py per contracts/cli.md (--run-id, --skip-deploy options)
- [x] T040 [US1] Add JSON data download functionality in dashboard (link to latest.json, history.json)
- [x] T041 [US1] Implement historical run archive listing in src/reporter/site.py (docs/data/runs/ directory)

**Checkpoint**: Dashboard can be viewed with sample data; all UI components render correctly

---

## Phase 4: User Story 3 - Mine and Normalize Templates (Priority: P3)

**Goal**: Discover infrastructure templates from trusted sources and normalize them for LocalStack

**Independent Test**: Mine a single repository and verify output contains normalized templates with extracted metadata

**Note**: US3 comes before US2/US4 because mining is the first pipeline stage that produces data

### Implementation for User Story 3

- [x] T042 [P] [US3] Create abstract base source extractor in src/miner/sources/base.py with extract() interface
- [x] T043 [P] [US3] Implement AWS Quick Starts extractor in src/miner/sources/quickstart.py (clone repo, find CloudFormation templates)
- [x] T044 [P] [US3] Implement Terraform Registry extractor in src/miner/sources/terraform.py (fetch modules via API)
- [x] T045 [P] [US3] Implement AWS Solutions Library extractor in src/miner/sources/solutions.py
- [x] T046 [P] [US3] Implement Serverless Framework extractor in src/miner/sources/serverless.py
- [x] T047 [US3] Create src/miner/sources/__init__.py with source registry and factory function
- [x] T048 [US3] Implement CloudFormation to Terraform converter in src/miner/converter.py using cf2tf subprocess per research.md
- [x] T049 [US3] Implement template normalizer in src/miner/normalizer.py (LocalStack endpoints, parameterized names, no hardcoded regions/account IDs)
- [x] T050 [US3] Implement metadata extractor in src/miner/normalizer.py (services detection, resource count, complexity score calculation per spec.md)
- [x] T051 [P] [US3] Implement diagram scraper for AWS Architecture Center in src/miner/sources/diagrams.py using beautifulsoup4
- [x] T052 [P] [US3] Implement diagram scraper for Azure Architecture Center in src/miner/sources/diagrams.py
- [x] T053 [US3] Implement Claude Vision diagram parser in src/miner/diagram_parser.py (parse image, identify services and connections)
- [x] T054 [US3] Implement Azure to AWS service mapping in src/miner/diagram_parser.py per research.md AZURE_TO_AWS dict
- [x] T055 [US3] Implement Terraform synthesis from parsed diagrams in src/miner/diagram_parser.py (generate main.tf from diagram analysis)
- [x] T056 [US3] Implement confidence scoring for diagram-derived architectures in src/miner/diagram_parser.py
- [x] T057 [US3] Create src/miner/__init__.py with mine_all() orchestration function
- [x] T058 [US3] Implement architecture caching (save to cache/architectures/{id}/) in src/miner/__init__.py
- [x] T059 [US3] Implement source state tracking (last_mined_at, last_commit_sha) in cache/sources_state.json
- [x] T060 [US3] Implement `mine` command in src/cli.py per contracts/cli.md (--source, --skip-cache, --include-diagrams, --max-per-source)

**Checkpoint**: Mining produces normalized Terraform templates with metadata from all configured sources

---

## Phase 5: User Story 4 - Generate Sample Applications (Priority: P4)

**Goal**: Generate executable Python sample applications that exercise the infrastructure

**Independent Test**: Generate an app for a known template; verify it compiles and contains appropriate test assertions

### Implementation for User Story 4

- [x] T061 [US4] Implement Terraform analyzer in src/generator/analyzer.py (parse HCL, detect services, identify integration points)
- [x] T062 [US4] Create Claude prompts for app generation in src/generator/prompts.py (GENERATION_PROMPT, TEST_GENERATION_PROMPT)
- [x] T063 [US4] Implement code synthesizer in src/generator/synthesizer.py (call Claude API, generate src/ and tests/ code)
- [x] T064 [US4] Implement retry logic and timeout generation in synthesizer prompts per FR-015
- [x] T065 [US4] Implement compile validator in src/generator/validator.py (python -m py_compile on all .py files)
- [x] T066 [US4] Implement sample app caching in src/generator/synthesizer.py (cache/apps/{content_hash}/)
- [x] T067 [US4] Implement token budget enforcement in src/generator/synthesizer.py (halt generation when budget exhausted, proceed with cached apps)
- [x] T068 [US4] Create src/generator/__init__.py with generate_all() orchestration function
- [x] T069 [US4] Implement `generate` command in src/cli.py per contracts/cli.md (--architecture, --skip-cache, --token-budget, --validate-only)

**Checkpoint**: Sample applications are generated, compile successfully, and include data flow assertions

---

## Phase 6: User Story 2 - Run Full Validation Pipeline (Priority: P2)

**Goal**: Automatically mine templates, generate test applications, run validations, and produce reports

**Independent Test**: Run complete pipeline against small set of known templates; verify it produces valid result files

**Note**: US2 is the orchestration layer that ties together US3, US4, and validation execution

### Implementation for User Story 2

- [ ] T070 [US2] Implement LocalStack container lifecycle manager in src/runner/container.py (start, health check, get port, stop, cleanup)
- [ ] T071 [US2] Implement container resource limits in src/runner/container.py per plan.md CONTAINER_LIMITS (2GB mem, 1 CPU)
- [ ] T072 [US2] Implement Terraform executor in src/runner/executor.py (tflocal init, tflocal apply, capture output)
- [ ] T073 [US2] Implement pytest executor in src/runner/executor.py (run tests, capture JSON results via pytest-json-report)
- [ ] T074 [US2] Implement log capture in src/runner/executor.py (terraform.log, localstack.log, app.log, test_output)
- [ ] T075 [US2] Implement parallel orchestrator in src/runner/orchestrator.py using asyncio.Semaphore per research.md
- [ ] T076 [US2] Implement graceful degradation in orchestrator (continue on individual failures, capture partial results)
- [ ] T077 [US2] Implement timeout enforcement per architecture in src/runner/orchestrator.py
- [ ] T078 [US2] Implement container cleanup in finally block regardless of success/failure
- [ ] T079 [US2] Create src/runner/__init__.py with run_validations() function
- [ ] T080 [US2] Implement result recording in src/runner/orchestrator.py (determine status: passed/partial/failed/timeout)
- [ ] T081 [US2] Implement ArchitectureResult creation with all fields (infrastructure, tests, logs, suggested_issue_title)
- [ ] T082 [US2] Implement ValidationRun creation with timing and statistics
- [ ] T083 [US2] Implement result persistence to docs/data/runs/{run_id}/ as JSON files
- [ ] T084 [US2] Implement `validate` command in src/cli.py per contracts/cli.md (--architecture, --parallelism, --localstack-version, --timeout, --skip-cleanup)
- [ ] T085 [US2] Implement `run` command in src/cli.py as full pipeline orchestrator (mine → generate → validate → report)
- [ ] T086 [US2] Implement stage timing collection in `run` command (mining_seconds, generation_seconds, running_seconds, reporting_seconds)

**Checkpoint**: Full pipeline runs end-to-end; produces dashboard with real validation results

---

## Phase 7: User Story 5 - Automatic Issue Creation for Failures (Priority: P5)

**Goal**: Automatically create GitHub issues for persistent failures (2+ consecutive)

**Independent Test**: Simulate consecutive failures; verify issues are created with correct content and labels

### Implementation for User Story 5

- [ ] T087 [US5] Implement failure tracker persistence in src/reporter/issues.py (load/save docs/data/failure_tracker.json)
- [ ] T088 [US5] Implement failure tracking logic (increment on failure, reset on success) per data-model.md state machine
- [ ] T089 [US5] Implement GitHub issue creation using PyGithub in src/reporter/issues.py
- [ ] T090 [US5] Implement issue content formatter (architecture name, source, services, error details, logs, reproduction steps, dashboard link) per FR-041
- [ ] T091 [US5] Implement label application (arch-validator, bug, service/<service-name>) per FR-040
- [ ] T092 [US5] Implement duplicate issue prevention (check issue_number exists and issue is open) per FR-039
- [ ] T093 [US5] Implement issue auto-close when architecture passes per FR-042 (add comment, close issue)
- [ ] T094 [US5] Implement GitHub API rate limit handling (queue for next run if rate limited) per edge case
- [ ] T095 [US5] Add --create-issues flag to `report` command in src/cli.py
- [ ] T096 [US5] Integrate issue creation into `run` command when --create-issues is passed

**Checkpoint**: Issues are created for 2+ consecutive failures; closed automatically when fixed

---

## Phase 8: User Story 6 - Manual Pipeline Trigger with Options (Priority: P6)

**Goal**: Manually trigger the validation pipeline with custom options

**Independent Test**: Manually trigger with various option combinations; verify pipeline respects each setting

### Implementation for User Story 6

- [ ] T097 [US6] Implement --skip-mining flag in `run` command (use cached architectures only)
- [ ] T098 [US6] Implement --skip-generation flag in `run` command (use cached sample apps only)
- [ ] T099 [US6] Implement architecture filtering in `validate` command (--architecture ID can be repeated)
- [ ] T100 [US6] Implement architecture exclusion patterns in `validate` command (--exclude PATTERN) per FR-045
- [ ] T101 [US6] Create GitHub Actions workflow in .github/workflows/validate.yml with scheduled trigger (3 AM UTC)
- [ ] T102 [US6] Add workflow_dispatch trigger with inputs (skip_mining, parallelism, localstack_version, specific_architectures)
- [ ] T103 [US6] Implement gh-pages deployment step in workflow (push docs/ to gh-pages branch)
- [ ] T104 [US6] Implement `status` command in src/cli.py per contracts/cli.md (show cached architectures, apps, latest run, failure tracker)
- [ ] T105 [US6] Implement `clean` command in src/cli.py per contracts/cli.md (--architectures, --apps, --runs, --all)

**Checkpoint**: Pipeline can be triggered manually via CLI and GitHub Actions with custom options

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T106 [P] Implement Slack notification webhook in src/reporter/notifications.py (optional, per FR-047)
- [ ] T107 [P] Add unsupported service detection and tracking in src/miner/normalizer.py per FR-053
- [ ] T108 [P] Add unsupported services section to dashboard per FR-053
- [ ] T109 [P] Implement 90-day data retention cleanup in `clean` command per FR-052
- [ ] T110 [P] Implement 10GB storage cap enforcement in `clean` command per FR-052
- [ ] T111 [P] Add observability metrics (timing, success/failure counts per stage) to all pipeline stages per FR-048-051
- [ ] T112 [P] Add correlation ID propagation through all logging per FR-051
- [ ] T113 Validate quickstart.md scenarios work end-to-end
- [ ] T114 Code cleanup and type hint verification across all modules
- [ ] T115 Final CLI help text review and documentation

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational - Can start with mock data, no other story deps
- **User Story 3 (Phase 4)**: Depends on Foundational - Mining is first pipeline stage
- **User Story 4 (Phase 5)**: Depends on Foundational + US3 models (but can use mock architectures)
- **User Story 2 (Phase 6)**: Depends on US3 + US4 (orchestrates the full pipeline)
- **User Story 5 (Phase 7)**: Depends on US2 (needs validation results to track failures)
- **User Story 6 (Phase 8)**: Depends on US2 (enhances pipeline with options)
- **Polish (Phase 9)**: Depends on all user stories being complete

### User Story Dependencies

```
Foundational
     │
     ├──► US1 (Dashboard) ─────────────────────────────────────────┐
     │                                                              │
     ├──► US3 (Mining) ──► US4 (Generation) ──► US2 (Pipeline) ──► US5 (Issues)
     │                                               │              │
     └───────────────────────────────────────────────┴──► US6 (Manual Trigger)
```

- **US1** can start immediately after Foundational with mock data
- **US3** can start immediately after Foundational
- **US4** can start with mock architectures, but depends on US3 models
- **US2** ties together US3 + US4 execution
- **US5** needs US2 results to track failures
- **US6** enhances US2 with options

### Parallel Opportunities

**Within Setup (Phase 1)**:
```
T003, T004, T005, T006, T007, T008, T009 can run in parallel
```

**Within Foundational (Phase 2)**:
```
T011, T012, T013 (architecture models) can run in parallel
T014, T015 (result models) can run in parallel
T016, T017 (coverage models) can run in parallel
```

**Within US1 (Dashboard)**:
```
T023, T024, T025, T026, T027, T028 (templates) can run in parallel
T030, T031, T032 (assets and mock data) can run in parallel
```

**Within US3 (Mining)**:
```
T041, T042, T043, T044, T045 (source extractors) can run in parallel
T050, T051 (diagram scrapers) can run in parallel
```

**Cross-Story Parallelism**:
- Once Foundational completes, US1 and US3 can start in parallel
- US1 can be completed entirely with mock data while US3/US4/US2 progress

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1 (Dashboard with mock data)
4. **STOP and VALIDATE**: Dashboard renders correctly, all UI components work
5. Deploy to GitHub Pages as proof-of-concept

### Incremental Delivery

1. **MVP**: Setup + Foundational + US1 → Dashboard with mock data
2. **+Mining**: Add US3 → Real templates mined and normalized
3. **+Generation**: Add US4 → Sample apps generated for templates
4. **+Pipeline**: Add US2 → Full validation runs producing real results
5. **+Issues**: Add US5 → Automatic issue creation for failures
6. **+Manual**: Add US6 → CLI flexibility and GitHub Actions workflow
7. **+Polish**: Phase 9 → Notifications, cleanup, observability

### Suggested MVP Scope

For fastest value delivery, implement only:
- Phase 1: Setup (T001-T009) - 9 tasks
- Phase 2: Foundational (T010-T022) - 13 tasks
- Phase 3: User Story 1 (T023-T041) - 19 tasks

**Total MVP: 41 tasks** → Delivers a visible dashboard with sample data

---

## Summary

| Phase | User Story | Task Range | Task Count |
|-------|------------|------------|------------|
| 1 | Setup | T001-T009 | 9 |
| 2 | Foundational | T010-T022 | 13 |
| 3 | US1 - Dashboard | T023-T041 | 19 |
| 4 | US3 - Mining | T042-T060 | 19 |
| 5 | US4 - Generation | T061-T069 | 9 |
| 6 | US2 - Pipeline | T070-T086 | 17 |
| 7 | US5 - Issues | T087-T096 | 10 |
| 8 | US6 - Manual Trigger | T097-T105 | 9 |
| 9 | Polish | T106-T115 | 10 |
| **Total** | | | **115** |

### Tasks Per User Story

- **US1 (Dashboard)**: 19 tasks
- **US2 (Pipeline)**: 17 tasks
- **US3 (Mining)**: 19 tasks
- **US4 (Generation)**: 9 tasks
- **US5 (Issues)**: 10 tasks
- **US6 (Manual Trigger)**: 9 tasks

### Parallel Opportunities

- 45 tasks marked [P] can run in parallel within their phase
- US1 and US3 can run in parallel after Foundational
- Models within each phase can be parallelized

### Independent Test Criteria

| Story | Test Criteria |
|-------|---------------|
| US1 | Dashboard renders with sample data; loads in <3s; all UI components visible |
| US2 | Pipeline produces valid result JSON files from known templates |
| US3 | Mining extracts normalized Terraform with metadata from one source |
| US4 | Generated app compiles; contains data flow assertions |
| US5 | Issue created after 2 consecutive failures; closed on pass |
| US6 | CLI respects all option combinations; workflow triggers correctly |
