---
icon: material/office-building
---

# JarvisCore Enterprise

JarvisCore is open source under Apache 2.0. You can self-host it, run it on any cloud, and operate it entirely on your own infrastructure — forever, for free.

**JarvisCore Enterprise** is a managed deployment service. Prescott Data runs, operates, and supports the full JarvisCore stack on your behalf — the same way MongoDB Atlas runs MongoDB or Redis Cloud runs Redis. Your team builds agent systems; we handle the infrastructure that runs them.

---

## OSS vs. Enterprise

|  | JarvisCore OSS | JarvisCore Enterprise |
|---|---|---|
| **Who runs it** | You | Prescott Data |
| **Deployment** | Self-managed | Fully managed |
| **Licensing** | Apache 2.0 — free | Commercial agreement |
| **Uptime SLA** | — | 99.9% guaranteed |
| **Support** | Community (GitHub Issues) | Dedicated engineering + SLA |
| **Security hardening** | Framework defaults | Enterprise-grade (see below) |
| **Data isolation** | You configure it | Enforced at the infrastructure layer |
| **Backup & DR** | You configure it | Automated, cross-region, RPO < 1h |
| **Agent governance** | None | Policy engine, rate limits, allow/deny lists |
| **LLM flexibility** | Any provider via config | Bring-your-own LLM, on-prem model support |
| **Professional services** | — | Onboarding, architecture review, migrations |

---

## What Enterprise Covers

### Managed Deployment

Prescott Data provisions, configures, and operates the complete JarvisCore stack — agents, mesh, Redis, blob storage, and observability — on your chosen cloud (AWS, Azure, GCP) or in your private network.

- Zero-ops onboarding: your team connects to a running system, not a setup guide
- Automated patching, dependency upgrades, and rollbacks
- Capacity planning and horizontal scaling handled on your behalf
- Private networking, VPC peering, and on-premises deployment options
- Kubernetes-native deployment with Helm charts and an operator

**Typical deployment topology:**

```
Your Infrastructure (VPC / Private Network)
┌───────────────────────────────────────────────────────────┐
│                                                           │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│   │  Agent Mesh │    │  Workflow   │    │  Nexus OSS  │  │
│   │  (K8s Pods) │←───│  Engine     │    │  (Auth GW)  │  │
│   └──────┬──────┘    └─────────────┘    └─────────────┘  │
│          │                                                │
│   ┌──────▼──────┐    ┌─────────────┐    ┌─────────────┐  │
│   │  Redis      │    │  Blob       │    │  SIEM /     │  │
│   │  (HA Pair)  │    │  Storage    │    │  Observ.    │  │
│   └─────────────┘    └─────────────┘    └─────────────┘  │
│                                                           │
│   Managed by Prescott Data  ·  Your data never leaves    │
└───────────────────────────────────────────────────────────┘
```

---

### Uptime SLA

Enterprise deployments carry a **99.9% monthly uptime SLA** (≤ 43.8 minutes unplanned downtime per month), with the following terms:

| Metric | Commitment |
|---|---|
| Monthly uptime | ≥ 99.9% |
| Measurement window | Calendar month, per region |
| SLA credit | Pro-rated service credit if missed |
| Exclusions | Scheduled maintenance (pre-announced ≥ 48h), force majeure, customer-caused outages |
| Status page | Provided — real-time and historical incident data |

Full SLA terms are included in the commercial agreement.

---

### Backup & Disaster Recovery

| Parameter | Value |
|---|---|
| **Recovery Point Objective (RPO)** | < 1 hour |
| **Recovery Time Objective (RTO)** | < 4 hours |
| **Backup frequency** | Continuous (Redis AOF + hourly snapshots) |
| **Backup retention** | 30 days rolling |
| **Cross-region replication** | Available on Professional and Enterprise plans |
| **Failover** | Automated — no manual intervention required |

Backups are encrypted with your tenant key and stored in isolated, access-controlled storage separate from the primary deployment.

---

### Security & Authentication

- SSO via SAML 2.0 or OIDC, federated against your existing identity provider
- SCIM provisioning and automatic deprovisioning
- Role-based access control (RBAC) across agents, tools, data sources, and workflows
- Secrets management via HashiCorp Vault, AWS KMS, Azure Key Vault, or GCP KMS
- Encryption at rest and in transit; bring-your-own-key (BYOK) option
- Audit-grade event logs, tamper-evident, exportable to your SIEM

---

### Tenant Isolation

Enterprise enforces strict separation at every layer for multi-tenant deployments serving multiple business units or customers.

- Workspace-level partitioning: each tenant's agents, workflows, and memory are fully separated
- Network isolation: no shared data paths between tenants
- Per-tenant encryption keys
- Redis namespaces and blob storage prefixes enforced at the platform layer — not in application code
- Verified isolation documentation available as part of the security review pack

---

### Agent Governance & Policy Controls

Enterprise adds a platform-level policy engine that sits above your agent code. This gives platform and security teams controls that don't require modifying agent implementations.

- **Rate limiting** — per-agent, per-workflow, and per-tenant request caps with configurable burst allowances
- **Capability allow/deny lists** — restrict which tools, APIs, and data sources each agent role can access
- **LLM provider policy** — enforce which LLM providers and model versions agents may use; block unapproved models
- **Output filtering** — platform-level PII redaction and content policy enforcement on all agent outputs before they leave the mesh
- **Workflow approval gates** — require human sign-off before specific workflow steps execute in production
- **Cost guardrails** — per-workspace LLM token budget with configurable alerting and hard caps

---

### LLM Flexibility

Enterprise does not lock you into a single AI provider. You bring the models your team has approved.

- Use any LLM via the existing JarvisCore provider config (OpenAI, Anthropic, Mistral, Cohere, and others)
- **Bring-your-own-model** — connect to on-premises or VPC-hosted models (Ollama, vLLM, Azure OpenAI private endpoint)
- Per-agent model routing — different agent roles can use different models and providers
- Model fallback chains — if a primary provider is unavailable, agents fail over to a configured backup automatically
- All LLM calls are logged, attributable, and subject to your governance policy

---

### Data Privacy & Compliance

- PII detection and redaction on agent inputs, outputs, and memory writes
- Field-level encryption for sensitive workflow data
- Configurable data residency: choose the region where data is stored and processed
- Retention policies and deletion workflows, including right-to-delete (GDPR Art. 17)
- Full provenance metadata on all memory reads and writes
- Compliance documentation available under NDA: SOC 2 Type II report, architecture overview, threat model

---

### Observability & Tracing

- OpenTelemetry export — metrics, traces, and logs — to your existing stack (Datadog, Grafana, Splunk, and others)
- SIEM-ready audit streams with tamper-evident event records
- Long-retention, searchable workflow traces with replay tooling
- Prometheus metrics aggregated across all nodes and exportable to your monitoring platform

---

### Professional Services

Beyond the managed platform, Prescott Data offers scoped professional services for teams that need hands-on help:

| Service | Description |
|---|---|
| **Onboarding programme** | Guided migration from OSS to Enterprise: infra hand-off, agent review, integration setup (2–4 weeks) |
| **Architecture review** | A senior JarvisCore engineer reviews your agent design, workflow DAGs, and memory strategy and provides a written recommendations report |
| **Custom integrations** | Prescott Data builds and maintains integrations with internal systems (data warehouses, internal APIs, observability stacks) |
| **Training** | Hands-on workshops for your engineering team covering agent design patterns, workflow modelling, and production operations |

Professional services are scoped and priced separately from the managed platform subscription.

---

### Support Tiers

| Plan | Response time | Coverage | Included |
|---|---|---|---|
| **Standard** | Next business day | Business hours | GitHub + email, documentation |
| **Professional** | 4 hours | 24 × 5 | + Named engineer, Slack/Teams channel |
| **Enterprise** | 1 hour | 24 × 7 × 365 | + Quarterly architecture reviews, on-call escalation |

All paid plans include a named support engineer and a dedicated Slack or Teams channel.

---

## Pricing Model

JarvisCore Enterprise is priced on a **subscription basis** — a flat annual fee based on deployment size (number of active agents and workflow volume), not per-seat or per-API-call. This means your costs are predictable as you scale agent usage, and you don't get billed every time an agent completes a workflow step.

Pricing is scoped per engagement. Factors include:

- Number of active agent nodes
- Monthly workflow execution volume
- Cloud region and redundancy requirements
- Support tier
- Professional services scope

> [!NOTE]
> Contact us with your cloud provider preference, approximate agent count, and any compliance requirements. We'll prepare a scoped proposal within 2 business days.

---

## Who Enterprise Is For

Enterprise is the right choice when any of these apply:

- **You don't want to run infrastructure.** Your team should build agent systems, not operate Redis clusters, manage blob storage, or debug Kubernetes rollouts.
- **You have compliance requirements.** SOC 2, GDPR, HIPAA, or internal data governance policies require audited, isolated, documented deployments that pass security review.
- **You need a guaranteed uptime SLA.** Your agent workflows are in the critical path of production systems and cannot tolerate unplanned downtime.
- **You operate at multi-tenant scale.** Multiple business units or customers need strict data separation without the cost of running completely separate deployments.
- **You need a support SLA.** When a production incident happens, you need a guaranteed response time and an engineer who knows your deployment — not a GitHub issue queue.
- **You need model and vendor governance.** Your organisation requires policy controls over which LLMs agents can call, with auditable records of every call.

---

## How Teams Typically Adopt

1. **Build on JarvisCore OSS.** Every framework primitive — agents, memory, orchestration, HITL, Nexus — is available and unrestricted. Validate your architecture on your own infrastructure first.
2. **Move to Enterprise** when operational overhead, compliance requirements, or uptime SLAs become the constraint — not the framework's capabilities.
3. Onboarding typically takes **1–2 weeks** from a signed agreement to a fully running managed environment.

---

## Security Review Pack

The security review pack is available to qualified enterprise evaluators under NDA. It includes:

- Architecture overview and data flow diagrams
- Threat model and mitigations
- SOC 2 Type II report (latest period)
- Penetration test summary (latest annual test)
- Encryption key management documentation
- Shared responsibility model

Request the pack via the email below and reference "security review" in your subject line.

---

## Get In Touch

**Email:** jarviscore-enterprise@prescottdata.io

Include your cloud provider preference, approximate agent count, and any specific compliance framework requirements in your first message — it helps us prepare the right materials and route your enquiry to the right team.

We respond to all enterprise enquiries within **one business day**.
