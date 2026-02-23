# JarvisCore Enterprise

JarvisCore is open source (Apache 2.0) and built to help teams orchestrate multi-agent systems with peer-to-peer coordination, workflows, unified memory, and Nexus OSS-native auth.

JarvisCore Enterprise adds the controls, security, and operational guarantees required for regulated environments and large deployments — without restricting the OSS core.

---

## What stays open source

JarvisCore OSS includes the core framework primitives needed to build and run real multi-agent systems:

- Multi-agent orchestration and workflow execution (dependencies, retries, crash recovery)
- P2P mesh networking (agent discovery and coordination)
- Unified memory primitives (episodic and long-term patterns, pluggable backends)
- Context distillation models for shared knowledge
- Basic telemetry/tracing and local-first observability
- FastAPI integration and deployment primitives
- Nexus OSS Protocol support (protocol and SDK remain open)

If you can build your system with standard infrastructure and you do not need org-wide governance controls, JarvisCore OSS is enough.

---

## What Enterprise adds

### 1. Identity, Access & Governance (Nexus Enterprise)

Nexus OSS Protocol remains open source. Enterprise adds the identity and governance layer required by real organisations:

- SSO / SAML / OIDC federation
- SCIM provisioning and deprovisioning
- Org / workspace RBAC (agents, tools, data sources, workflows)
- Policy packs (least-privilege defaults, approval gates, environment rules)
- Audit exports (SIEM-ready) and identity event trails
- Advanced token lifecycle controls (rotation, revocation workflows, service accounts)

### 2. Infrastructure Stack Hardening

JarvisCore auto-injects the infrastructure stack for every agent at runtime. Enterprise hardens it:

- Secrets managers (Vault / KMS / HSM integrations)
- Hardened blob storage with encryption, lifecycle rules, and retention policies
- Multi-tenant isolation and environment segmentation (dev / stage / prod)
- Compliance controls (data residency options, retention policies, export controls)

### 3. UnifiedMemory Hardening

Enterprise extends memory from "works" to "safe at scale":

- PII controls (redaction, classification, field-level controls)
- Encryption at rest and in transit, with optional customer-managed keys
- Retention and deletion workflows (including right-to-delete patterns)
- Lineage and provenance metadata for memory writes and reads
- Workspace- and tenant-isolated memory partitions

### 4. Observability, Tracing & Compliance

Enterprise makes telemetry production-grade:

- OpenTelemetry export (metrics / traces / logs)
- SIEM integrations and audit-grade event streams
- Long retention, searchable traces, workflow replay tooling
- Compliance-grade logging policies and redaction controls

### 5. Deployment & Ops Controls (Docker / Kubernetes)

Enterprise adds guardrails for fleet-scale agent operations:

- RBAC for deployments and runtime operations
- Policy gates (signed images, approved tools and connectors, environment allowlists)
- Multi-cluster controls and safe rollout strategies
- Supply chain checks and break-glass operational controls

---

## Community vs Enterprise

| Capability | JarvisCore OSS | JarvisCore Enterprise |
|-----------|:--------------:|:---------------------:|
| P2P mesh + agent discovery | ✅ | ✅ |
| Workflow orchestration + crash recovery | ✅ | ✅ |
| Unified memory primitives | ✅ | ✅ |
| Nexus OSS Protocol support | ✅ | ✅ |
| Basic telemetry and local observability | ✅ | ✅ |
| SSO / SAML / SCIM | — | ✅ |
| Org / workspace RBAC + policy packs | — | ✅ |
| Secrets manager + KMS / HSM integrations | — | ✅ |
| PII controls + retention / deletion workflows | — | ✅ |
| OTel / SIEM exports + audit-grade tracing | — | ✅ |
| Deployment RBAC + policy gates | — | ✅ |

---

## How teams typically adopt

1. **Start with JarvisCore OSS** to build and validate workflows.
2. **Move to Enterprise** when you need SSO, governance, compliance controls, hardened infrastructure, or multi-team operational safety.
3. Optionally use a **managed control plane** for faster production rollout.

---

## Talk to us

If you need SSO / RBAC / audit logs, secrets management, PII controls, or deployment governance, JarvisCore Enterprise is designed for that.

**Request Enterprise access or pricing:** info@prescottdata.io

A security review pack is available on request: architecture overview, threat model, and deployment reference.
