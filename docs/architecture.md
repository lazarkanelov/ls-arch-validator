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
