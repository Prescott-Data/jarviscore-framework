# JarvisCore Enterprise

JarvisCore is open source (Apache 2.0). You can self-host it, run it on any cloud, and operate it entirely on your own infrastructure — forever, for free.

**JarvisCore Enterprise** is a different thing: it is a **managed deployment service**. Prescott Data runs, operates, and supports JarvisCore for you — the same way MongoDB Atlas runs MongoDB or Redis Cloud runs Redis. You get the same open-source framework, deployed and maintained by the team that built it, with the operational guarantees, security controls, and support SLAs that regulated and production-critical environments require.

---

## The model

| | JarvisCore OSS | JarvisCore Enterprise |
|---|---|---|
| **Who runs it** | You | Prescott Data |
| **Deployment** | Self-managed | Fully managed, hosted |
| **Licensing** | Apache 2.0, free | Commercial agreement |
| **SLA / uptime** | — | 99.9 % uptime guarantee |
| **Support** | Community (GitHub Issues) | Dedicated engineering, SLA response |
| **Security controls** | Framework defaults | Enterprise hardening (see below) |
| **Data isolation** | You configure it | Enforced at infrastructure layer |

---

## What Enterprise covers

### 1. Managed Deployment

Prescott Data provisions, configures, and operates the full JarvisCore stack — agents, mesh, Redis, blob storage, and observability — on your chosen cloud (AWS, Azure, GCP) or in your private network.

- Zero-ops onboarding: your team connects to a running system
- Automated patching, upgrades, and dependency management
- Capacity planning and scaling handled on your behalf
- Private networking, VPC peering, or on-premises deployment
- Kubernetes-native deployment with Helm charts and operators

### 2. Security & Authentication

- SSO / SAML / OIDC federation with your identity provider
- SCIM provisioning and automatic deprovisioning
- Role-based access control (RBAC) across agents, tools, data sources, and workflows
- Secrets management via Vault, AWS KMS, Azure Key Vault, or GCP KMS
- Encryption at rest and in transit; customer-managed key (BYOK) option
- Audit-grade event logs, exportable to your SIEM

### 3. Tenant Isolation

Multi-agent systems often serve multiple business units, customers, or environments. Enterprise enforces strict isolation at every layer:

- Workspace-level separation: each tenant's agents, workflows, and memory are fully partitioned
- Network isolation: no shared data paths between tenants
- Per-tenant encryption keys
- Separate Redis namespaces and blob storage prefixes enforced at the platform layer, not application code
- Verified separation: available on request as part of the security review pack

### 4. Data Privacy & Compliance

- PII detection and redaction controls on agent inputs, outputs, and memory writes
- Field-level encryption for sensitive workflow data
- Configurable data residency: choose the region where data is stored and processed
- Retention policies and deletion workflows (including right-to-delete / GDPR patterns)
- Lineage and provenance metadata on all memory reads and writes
- Compliance documentation: SOC 2 Type II report, architecture overview, threat model — available under NDA

### 5. Observability & Tracing

- OpenTelemetry export: metrics, traces, and logs to your existing stack (Datadog, Grafana, Splunk, etc.)
- SIEM-ready audit streams with tamper-evident event records
- Long-retention, searchable traces and workflow replay tooling
- Prometheus metrics aggregated across all nodes

### 6. Support & SLAs

| Plan | Response time | Coverage |
|------|--------------|----------|
| **Standard** | Next business day | Business hours |
| **Professional** | 4 hours | 24 × 5 |
| **Enterprise** | 1 hour | 24 × 7 × 365 |

All paid plans include a named support engineer, direct Slack or Teams channel, and quarterly architecture reviews.

---

## Who Enterprise is for

Enterprise is the right choice when one or more of these apply:

- **You don't want to run infrastructure.** Your team should build agent systems, not operate Redis clusters and blob storage.
- **You have compliance requirements.** SOC 2, GDPR, HIPAA, or internal data governance policies that require audited, isolated, documented deployments.
- **You need guaranteed uptime.** Your agent workflows are in the critical path of production systems.
- **You operate at multi-tenant scale.** Multiple business units or customers need strict separation without running separate deployments.
- **You need a support SLA.** Production incidents need a response time guarantee and a human who knows your deployment.

---

## How teams typically start

1. **Build with JarvisCore OSS.** All framework primitives are available and unrestricted. Validate your architecture on your own infrastructure.
2. **Move to Enterprise** when operational burden, compliance requirements, or uptime SLAs become the constraint — not features.
3. Onboarding typically takes **1–2 weeks** from signed agreement to a running managed environment.

---

## Talk to us

Enterprise access, pricing, and the security review pack (architecture overview, threat model, deployment reference) are available on request.

**Contact:** jarviscore-enterprise@prescottdata.io

If you have a specific compliance framework or deployment requirement, include it in your first message — it helps us prepare the right materials.
