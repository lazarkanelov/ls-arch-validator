# LocalStack Architecture Validator - System Architecture

```mermaid
flowchart TB
    subgraph Sources["📥 Architecture Sources"]
        GH["GitHub Repos<br/>(Serverless, Terraform)"]
        AWS["AWS Solutions Library<br/>(CloudFormation)"]
        TFR["Terraform Registry"]
        DIAG["Architecture Diagrams<br/>(PNG/SVG images)"]
    end

    subgraph Mining["⛏️ Mining Phase"]
        GHA["GitHub API<br/>Scraper"]
        CFNP["CloudFormation<br/>Parser"]
        TFA["Terraform Registry<br/>API"]
        VIS["Claude Vision<br/>Image Analysis"]
    end

    subgraph Processing["⚙️ Processing Phase"]
        ARCH["Architecture<br/>Extractor"]
        SVC["Service<br/>Identifier"]
        TFG["Terraform<br/>Generator"]
        APP["Probe App<br/>Generator"]
    end

    subgraph Validation["🧪 Validation Phase"]
        LS["LocalStack<br/>Container"]
        TFL["tflocal<br/>(Terraform)"]
        PYT["pytest<br/>Test Runner"]
    end

    subgraph Storage["💾 CAS Storage"]
        IDX["index.json"]
        ARCHO["objects/arch/*.json"]
        TFO["objects/tf/*.json"]
        APPO["objects/app/*.json"]
    end

    subgraph Reporting["📊 Reporting Phase"]
        DASH["Dashboard<br/>Generator"]
        GHP["GitHub Pages<br/>Deployment"]
        ISS["GitHub Issues<br/>Creator"]
    end

    subgraph Dashboard["🖥️ Dashboard UI"]
        OV["Overview Stats<br/>(Donut Chart)"]
        RES["Test Results<br/>(Pass/Fail/Partial)"]
        DET["Expandable Details<br/>(TF, Apps, Scraping)"]
        SRV["Service Coverage<br/>Table"]
    end

    %% Source to Mining connections
    GH --> GHA
    AWS --> CFNP
    TFR --> TFA
    DIAG --> VIS

    %% Mining to Processing
    GHA --> ARCH
    CFNP --> ARCH
    TFA --> ARCH
    VIS --> ARCH

    %% Processing flow
    ARCH --> SVC
    SVC --> TFG
    TFG --> APP

    %% Processing to Validation
    TFG --> TFL
    APP --> PYT
    TFL --> LS
    LS --> PYT

    %% Validation to Storage
    PYT --> IDX
    ARCH --> ARCHO
    TFG --> TFO
    APP --> APPO

    %% Storage to Reporting
    IDX --> DASH
    ARCHO --> DASH
    TFO --> DASH
    APPO --> DASH

    %% Reporting outputs
    DASH --> GHP
    PYT --> ISS

    %% Dashboard components
    GHP --> OV
    GHP --> RES
    GHP --> DET
    GHP --> SRV

    %% Styling
    classDef sources fill:#3b82f6,stroke:#1d4ed8,color:#fff
    classDef mining fill:#8b5cf6,stroke:#6d28d9,color:#fff
    classDef processing fill:#f59e0b,stroke:#d97706,color:#fff
    classDef validation fill:#ef4444,stroke:#dc2626,color:#fff
    classDef storage fill:#10b981,stroke:#059669,color:#fff
    classDef reporting fill:#ec4899,stroke:#db2777,color:#fff
    classDef dashboard fill:#06b6d4,stroke:#0891b2,color:#fff

    class GH,AWS,TFR,DIAG sources
    class GHA,CFNP,TFA,VIS mining
    class ARCH,SVC,TFG,APP processing
    class LS,TFL,PYT validation
    class IDX,ARCHO,TFO,APPO storage
    class DASH,GHP,ISS reporting
    class OV,RES,DET,SRV dashboard
```

## Data Flow

```mermaid
sequenceDiagram
    participant S as Sources
    participant M as Miner
    participant G as Generator
    participant L as LocalStack
    participant T as Test Runner
    participant R as Reporter
    participant D as Dashboard

    Note over S,D: Weekly Pipeline Run (Mondays 3 AM UTC)

    S->>M: Fetch templates & diagrams
    M->>M: Parse & extract services
    M->>G: Architecture definitions

    G->>G: Generate Terraform (main.tf)
    G->>G: Generate Probe Apps (pytest)

    G->>L: Deploy infrastructure (tflocal)
    L->>L: Provision AWS resources

    L->>T: Infrastructure ready
    T->>T: Run validation tests
    T->>T: Collect pass/fail results

    T->>R: Test results + artifacts
    R->>R: Store in CAS (hash-based)
    R->>R: Generate dashboard HTML

    R->>D: Deploy to GitHub Pages

    alt Tests Failed
        R->>R: Create GitHub Issues
    end
```

## Component Details

### Mining Phase
| Component | Input | Output | Method |
|-----------|-------|--------|--------|
| GitHub API Scraper | Repo URLs | YAML/HCL files | REST API + file download |
| CloudFormation Parser | CFN templates | Resource definitions | YAML/JSON parsing |
| Terraform Registry API | Module URLs | HCL configurations | Registry API + GitHub |
| Claude Vision | PNG/SVG images | Service list + topology | AI image analysis |

### Processing Phase
| Component | Input | Output |
|-----------|-------|--------|
| Architecture Extractor | Raw configs | Normalized arch definition |
| Service Identifier | Arch definition | AWS service list |
| Terraform Generator | Service list | main.tf, variables.tf, outputs.tf |
| Probe App Generator | Arch + TF | Python pytest applications |

### Validation Phase
| Component | Purpose |
|-----------|---------|
| LocalStack | AWS-compatible local cloud |
| tflocal | Terraform wrapper for LocalStack |
| pytest | Python test framework |

### Storage (CAS)
```
docs/data/
├── index.json              # Run metadata + results index
└── objects/
    ├── arch/{hash}.json    # Architecture definitions
    ├── tf/{hash}.json      # Generated Terraform code
    └── app/{hash}.json     # Generated probe applications
```

### Dashboard Features
- **Overview**: Donut chart, pass rate, service count
- **Test Results**: Expandable cards with status badges
- **Details**: Source info, scraping steps, Terraform, probe apps
- **Service Coverage**: Per-service pass rates
- **Run History**: Previous validation runs

---

## GitHub Actions Workflow

```mermaid
flowchart TB
    subgraph Trigger["🚀 Triggers"]
        CRON["⏰ Weekly Schedule<br/>Mondays 3 AM UTC"]
        PUSH["📤 Push to main<br/>(src/templates/docs)"]
        MANUAL["🔘 Manual Dispatch<br/>(workflow_dispatch)"]
    end

    subgraph Runner["🖥️ GitHub Actions Runner (ubuntu-latest)"]
        subgraph Setup["📦 Setup Steps"]
            CHECKOUT["Checkout repo"]
            PYTHON["Setup Python 3.11"]
            DEPS["Install dependencies<br/>(pip install -e .[dev])"]
            TF["Install Terraform 1.5.0"]
            TFLOCAL["Install tflocal"]
            CACHE["Restore cache"]
        end

        subgraph Docker["🐳 Docker Environment"]
            DOCKERD["Start Docker daemon"]
            LS["LocalStack Container<br/>localstack/localstack:latest<br/>Port 4566"]
        end

        subgraph Pipeline["⚡ Validation Pipeline"]
            RUN["ls-arch-validator run<br/>--parallelism 4"]
        end

        subgraph Artifacts["📁 Artifacts"]
            RESULTS["validation-results<br/>(docs/data/, run_output.json)"]
        end

        subgraph Deploy["🌐 Deployment"]
            GHPAGES["peaceiris/actions-gh-pages<br/>Deploy to gh-pages branch"]
        end
    end

    subgraph Outputs["📊 Outputs"]
        DASHBOARD["GitHub Pages Dashboard"]
        ISSUES["GitHub Issues<br/>(for failures)"]
        SUMMARY["Job Summary<br/>(pass rate, stats)"]
    end

    CRON --> CHECKOUT
    PUSH --> CHECKOUT
    MANUAL --> CHECKOUT

    CHECKOUT --> PYTHON --> DEPS --> TF --> TFLOCAL --> CACHE
    CACHE --> DOCKERD --> LS
    LS --> RUN
    RUN --> RESULTS
    RESULTS --> GHPAGES

    GHPAGES --> DASHBOARD
    RUN --> ISSUES
    RUN --> SUMMARY

    classDef trigger fill:#8b5cf6,stroke:#6d28d9,color:#fff
    classDef setup fill:#3b82f6,stroke:#1d4ed8,color:#fff
    classDef docker fill:#0ea5e9,stroke:#0284c7,color:#fff
    classDef pipeline fill:#f59e0b,stroke:#d97706,color:#fff
    classDef output fill:#10b981,stroke:#059669,color:#fff

    class CRON,PUSH,MANUAL trigger
    class CHECKOUT,PYTHON,DEPS,TF,TFLOCAL,CACHE setup
    class DOCKERD,LS docker
    class RUN pipeline
    class DASHBOARD,ISSUES,SUMMARY output
```

---

## Probe App Generation Detail

```mermaid
flowchart LR
    subgraph Input["📥 Input"]
        ARCH["Architecture Definition<br/>{services: [lambda, s3, dynamodb]}"]
        TF["Generated Terraform<br/>main.tf"]
    end

    subgraph Claude["🤖 Claude API"]
        PROMPT["Prompt Engineering"]
        GEN["Code Generation"]
    end

    subgraph ProbeTypes["🧪 Probe Types"]
        API["api_parity<br/>AWS API compatibility"]
        EDGE["edge_cases<br/>Error handling"]
        INT["integration<br/>Cross-service flows"]
        STRESS["stress<br/>Load testing"]
    end

    subgraph Output["📤 Generated Files"]
        subgraph SrcFiles["src/probes/"]
            SRC1["lambda_parity_probe.py"]
            SRC2["s3_integration_probe.py"]
            SRC3["dynamodb_edge_probe.py"]
        end
        subgraph TestFiles["tests/"]
            TST1["test_lambda_parity.py"]
            TST2["test_s3_integration.py"]
            TST3["test_dynamodb_edge.py"]
        end
        REQ["requirements.txt<br/>boto3, pytest, localstack-client"]
    end

    ARCH --> PROMPT
    TF --> PROMPT
    PROMPT --> GEN

    GEN --> API --> SRC1 --> TST1
    GEN --> EDGE --> SRC3 --> TST3
    GEN --> INT --> SRC2 --> TST2

    SRC1 --> REQ
    SRC2 --> REQ
    SRC3 --> REQ

    classDef input fill:#3b82f6,stroke:#1d4ed8,color:#fff
    classDef claude fill:#8b5cf6,stroke:#6d28d9,color:#fff
    classDef probe fill:#f59e0b,stroke:#d97706,color:#fff
    classDef output fill:#10b981,stroke:#059669,color:#fff

    class ARCH,TF input
    class PROMPT,GEN claude
    class API,EDGE,INT,STRESS probe
    class SRC1,SRC2,SRC3,TST1,TST2,TST3,REQ output
```

---

## Terraform ↔ LocalStack ↔ Pytest Interaction

```mermaid
sequenceDiagram
    box rgb(59, 130, 246) Terraform Layer
        participant TF as tflocal
        participant HCL as main.tf
    end

    box rgb(14, 165, 233) LocalStack Container
        participant LS as LocalStack:4566
        participant S3 as S3 Service
        participant LAM as Lambda Service
        participant DDB as DynamoDB Service
    end

    box rgb(16, 185, 129) Test Layer
        participant PY as pytest
        participant PROBE as Probe App
        participant BOTO as boto3 client
    end

    Note over TF,BOTO: Phase 1: Infrastructure Provisioning

    TF->>HCL: Read main.tf
    HCL-->>TF: Resource definitions

    TF->>LS: terraform init<br/>(provider: localstack)
    LS-->>TF: Provider initialized

    TF->>LS: terraform apply

    LS->>S3: CreateBucket
    S3-->>LS: Bucket created

    LS->>LAM: CreateFunction
    LAM-->>LS: Function created

    LS->>DDB: CreateTable
    DDB-->>LS: Table created

    LS-->>TF: Apply complete<br/>Outputs: endpoints, ARNs

    Note over TF,BOTO: Phase 2: Test Execution

    TF->>PY: Pass TF outputs as env vars<br/>LAMBDA_ARN, S3_BUCKET, etc.

    PY->>PROBE: Run test_lambda_parity.py

    PROBE->>BOTO: Create client<br/>endpoint=localhost:4566

    BOTO->>LAM: lambda.invoke()
    LAM-->>BOTO: Response payload
    BOTO-->>PROBE: Validate response

    PROBE->>BOTO: s3.put_object()
    BOTO->>S3: Store object
    S3-->>BOTO: Success
    BOTO-->>PROBE: Validate storage

    PROBE->>BOTO: dynamodb.put_item()
    BOTO->>DDB: Store item
    DDB-->>BOTO: Success
    BOTO-->>PROBE: Validate persistence

    PROBE-->>PY: Test results (pass/fail)

    Note over TF,BOTO: Phase 3: Cleanup

    TF->>LS: terraform destroy
    LS->>S3: DeleteBucket
    LS->>LAM: DeleteFunction
    LS->>DDB: DeleteTable
    LS-->>TF: Destroy complete
```

---

## Parallel Validation Architecture

```mermaid
flowchart TB
    subgraph Orchestrator["🎯 Validation Orchestrator"]
        QUEUE["Architecture Queue<br/>(5 architectures)"]
        POOL["Thread Pool<br/>(parallelism=4)"]
    end

    subgraph Workers["👷 Parallel Workers"]
        subgraph W1["Worker 1"]
            LS1["LocalStack #1<br/>Port 4566"]
            TF1["tflocal"]
            PY1["pytest"]
        end
        subgraph W2["Worker 2"]
            LS2["LocalStack #2<br/>Port 4567"]
            TF2["tflocal"]
            PY2["pytest"]
        end
        subgraph W3["Worker 3"]
            LS3["LocalStack #3<br/>Port 4568"]
            TF3["tflocal"]
            PY3["pytest"]
        end
        subgraph W4["Worker 4"]
            LS4["LocalStack #4<br/>Port 4569"]
            TF4["tflocal"]
            PY4["pytest"]
        end
    end

    subgraph Architectures["📦 Architectures Being Validated"]
        A1["aws-quickstart-vpc-3tier"]
        A2["terraform-aws-lambda-api"]
        A3["serverless-rest-api"]
        A4["aws-diagram-microservices"]
        A5["aws-solutions-serverless-image<br/>(skipped: Rekognition)"]
    end

    subgraph Results["📊 Results Aggregator"]
        COLLECT["Collect Results"]
        CAS["Store in CAS"]
        REPORT["Generate Report"]
    end

    QUEUE --> POOL

    POOL --> W1
    POOL --> W2
    POOL --> W3
    POOL --> W4

    A1 --> W1
    A2 --> W2
    A3 --> W3
    A4 --> W4
    A5 -.->|"Skipped"| COLLECT

    TF1 --> LS1 --> PY1 --> COLLECT
    TF2 --> LS2 --> PY2 --> COLLECT
    TF3 --> LS3 --> PY3 --> COLLECT
    TF4 --> LS4 --> PY4 --> COLLECT

    COLLECT --> CAS --> REPORT

    classDef orchestrator fill:#8b5cf6,stroke:#6d28d9,color:#fff
    classDef worker fill:#3b82f6,stroke:#1d4ed8,color:#fff
    classDef arch fill:#f59e0b,stroke:#d97706,color:#fff
    classDef result fill:#10b981,stroke:#059669,color:#fff
    classDef skipped fill:#ef4444,stroke:#dc2626,color:#fff

    class QUEUE,POOL orchestrator
    class LS1,LS2,LS3,LS4,TF1,TF2,TF3,TF4,PY1,PY2,PY3,PY4 worker
    class A1,A2,A3,A4 arch
    class A5 skipped
    class COLLECT,CAS,REPORT result
```

---

## Test Result States

```mermaid
stateDiagram-v2
    [*] --> Queued: Architecture discovered

    Queued --> Mining: Start processing
    Mining --> ServiceCheck: Extract services

    ServiceCheck --> Skipped: Unsupported service<br/>(e.g., Rekognition)
    ServiceCheck --> TerraformGen: All services supported

    TerraformGen --> ProbeGen: main.tf generated
    ProbeGen --> Provisioning: Probe apps ready

    Provisioning --> ProvisionFailed: tflocal apply failed
    Provisioning --> Testing: Infrastructure ready

    Testing --> Passed: All tests pass ✅
    Testing --> Partial: Some tests fail ⚠️
    Testing --> Failed: Critical failure ❌

    Passed --> Cleanup
    Partial --> Cleanup
    Failed --> Cleanup
    ProvisionFailed --> Cleanup

    Cleanup --> [*]: Results stored

    Skipped --> [*]: Marked as failed<br/>(no TF generated)
```
