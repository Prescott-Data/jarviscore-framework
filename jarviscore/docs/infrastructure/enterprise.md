---
icon: material/shield-check-outline
title: "JarvisCore Enterprise"
description: "Compare JarvisCore OSS and Enterprise, including Nexus access controls, Maven cost efficiency, workflow improvement, deployment, and support."
---

# JarvisCore Enterprise

The JarvisCore framework is open source under Apache 2.0. You can self-host it and use it in commercial products without a revenue or user-count cap.

**JarvisCore Enterprise** adds commercially licensed capabilities for agent access control, AI cost efficiency, and workflow improvement, alongside deployment assistance and support from Prescott Data.

---

## OSS vs. Enterprise

|  | JarvisCore OSS | JarvisCore Enterprise |
|---|---|---|
| **Licensing** | Apache 2.0 | Commercial agreement for enterprise modules and services |
| **Deployment** | Self-managed | Deployment and managed operations scoped to your environment |
| **Agent runtime** | AutoAgent, CustomAgent, Mesh, memory, and HITL | Same foundation |
| **Credentials** | Public Nexus credential store and integrations | Nexus registered agent identity, OBO delegation, and session scope enforcement |
| **Cost controls** | Public model routing, caching, and budget controls | Maven cost-efficiency system |
| **Workflows** | DAG execution, planning, retries, and in-run replanning | Self-improving workflow DAGs |
| **Observability** | Framework traces, inspection, and metrics | Assistance integrating and operating your monitoring stack |
| **LLM flexibility** | Configurable providers and models | Same flexibility, with deployment assistance |
| **Model routing** | Public model configuration and routing | Task-aware selection using reasoning level, model type, size, and cost |
| **Model gateway** | Configured provider endpoints | Resource-aware routing across clouds, regions, and compatible compute |
| **Support** | Community | Commercial support with agreed coverage |
| **Professional services** | Self-service documentation | Onboarding, architecture review, integrations, and training |

The enterprise column describes the commercial offering; confirm module and version availability with Prescott Data. Code already released under Apache 2.0 retains that license, including existing public Nexus functionality.

---

## What Enterprise Covers

### Managed Deployment

Deployment engagements cover the JarvisCore stack: agents, Mesh, Redis, blob storage, and observability. Scope self-managed deployment assistance or managed operations with Prescott Data based on your environment.

- Installation, configuration, upgrades, and rollback procedures
- Capacity planning and infrastructure requirements
- Private-cloud, networking, and on-premises requirements
- Responsibility for operating each service

For self-hosted setup, see [Production Deployment](../guides/production.md). External model and API calls follow your configured providers; hosting the runtime privately does not by itself keep all processing inside your network.

---

### Uptime SLA

For managed operations, availability targets, measurement, exclusions, and any service credits are specified in the commercial agreement.

---

### Backup & Disaster Recovery

The deployment scope defines backup ownership, retention, restore testing, recovery point objectives (RPO), and recovery time objectives (RTO). These depend on the storage services and redundancy selected for your environment.

---

### Security & Authentication

Enterprise access controls extend Nexus credential handling:

- **Agent identity:** register each agent with a defined permission boundary. This credential identity is distinct from the role and capabilities used for discovery in the open-source Mesh.
- **On Behalf Of (OBO) sessions:** human-triggered agents carry the user's delegated permission through time-bound, auditable sessions without receiving the user's raw credentials. Delegation does not expand the agent's registered boundary.
- **Scope enforcement:** Nexus checks requested scopes against the agent's registered boundary at session request time. This applies to provider OAuth scopes and organization-defined permission names. Consuming services remain responsible for enforcing their resource-level permissions.

For the public credential setup, see [Nexus Credentials](../guides/nexus.md). Bring identity-provider, secrets-management, and audit requirements to the deployment review.

---

### Tenant Isolation

For deployments serving multiple business units or customers, the architecture review covers separation of credentials, agent state, storage, and network access. Isolation requirements and their verification belong in the deployment scope.

---

### Agent Governance & Policy Controls

The open-source framework already includes execution budgets, [HITL](../guides/hitl.md), and [contracts and boundaries](../concepts/contracts.md). Enterprise adds the Nexus credential identity and delegated-access controls described above. Access enforcement complements agent reasoning; it does not replace it.

---

### Maven Cost Efficiency

Maven is the enterprise cost-efficiency system for reducing AI execution costs as more work is automated. It is separate from the model configuration, routing, caching, and budget controls available in OSS.

Evaluate Maven on representative workloads using cost per successfully completed task, alongside quality and latency.

---

### Self-Improving Workflow DAGs

Agents learn from execution experience and identify changes to workflow DAGs that could deliver more value to the customer. They test candidate changes through long-running background experiments, rather than immediately applying a promising idea to the workflow.

Only after those experiments demonstrate greater customer value do the agents upgrade the DAG. The objective is better customer outcomes, not simply a different graph or faster execution.

This enterprise capability is distinct from ordinary DAG execution, retries, and replanning within an active task, which remain part of the open-source framework.

---

### LLM Flexibility

Provider configuration and the existing model-routing capabilities remain available in OSS. See [Language Models](../concepts/language-models.md) and [Model Routing](../concepts/model-routing.md). Enterprise extends this with task-aware model selection and a resource-aware model gateway.

#### Enterprise Model Routing

Enterprise routing evaluates the reasoning level, model type, model size, and inference cost against the needs of the task. The objective is to meet the task's quality requirements efficiently, rather than always choosing the cheapest or largest model.

| Routing factor | What it informs |
|---|---|
| **Reasoning level** | The reasoning capability needed for the task |
| **Model type** | Suitability for the kind of work being performed |
| **Model size** | The balance between capability and resource requirements |
| **Model cost** | Execution economics alongside task quality |

#### Model Gateway

The enterprise model gateway routes execution based on available infrastructure as well as model suitability. It supports service continuity by directing requests to compatible resources as availability changes across cloud and multi-cloud deployments, regions, and compute pools.

Resource-aware routing accounts for different GPU generations, including older and newer GPUs, as well as TPUs and CPUs where the model and serving runtime support them. This lets teams use suitable capacity across their infrastructure rather than depend on a single hardware class or region.

Together, model routing and the gateway address both **which model should do the work** and **where that work can run reliably and efficiently**. Supported models, runtimes, and deployment targets are confirmed for your environment; uptime commitments are defined in the commercial agreement.

---

### Data Privacy & Compliance

Deployment review covers data flows to model and API providers, processing locations, retention, deletion, and access to stored agent state. Identify applicable regulatory and internal requirements before selecting the deployment architecture.

---

### Observability & Tracing

Framework tracing, `jarviscore inspect`, and metrics are available in OSS. See [Observability](../guides/observability.md). Enterprise services can include monitoring integration, retention configuration, and incident investigation for your deployment.

---

### Professional Services

Prescott Data offers scoped professional services for teams that need hands-on help:

| Service | Description |
|---|---|
| **Onboarding programme** | Environment setup, agent review, and enterprise integration |
| **Architecture review** | A senior JarvisCore engineer reviews your agent design, workflow DAGs, and memory strategy and provides a written recommendations report |
| **Custom integrations** | Prescott Data builds and maintains integrations with internal systems (data warehouses, internal APIs, observability stacks) |
| **Training** | Hands-on workshops for your engineering team covering agent design patterns, workflow modelling, and production operations |

Professional services are scoped and priced in the commercial proposal.

---

### Support Tiers

| Support | Access | Scope |
|---|---|---|
| **Community** | Public project channels | Questions, bug reports, and documentation |
| **Commercial** | Agreed support channel | Coverage, response targets, and escalation defined in your agreement |

Include production criticality and required support hours when discussing commercial support.

---

## Pricing Model

Enterprise modules and services are covered by a commercial agreement. Contact Prescott Data for pricing based on the capabilities, deployment, and support you need.

Pricing is scoped per engagement. Factors include:

- Enterprise modules and intended use
- Deployment size and workflow volume
- Infrastructure and support requirements
- Professional services scope

Commercial use of the Apache-licensed framework does not require an enterprise agreement merely because your business grows. Embedding or redistributing proprietary enterprise modules requires appropriate commercial terms.

**Built with JarvisCore:** product credit is optional and appreciated. Add `[Built with JarvisCore](https://developers.prescottdata.io)` to your About page, footer, or documentation. This does not replace Apache's required license, copyright, and applicable attribution notices.

---

## Who Enterprise Is For

Enterprise is the right choice when any of these apply:

- **Delegated access:** agents need registered credential identities, OBO sessions, and enforced scope boundaries.
- **Automation costs:** you want to evaluate Maven for recurring AI workloads.
- **Workflow improvement:** you need DAGs that improve from execution experience across runs.
- **Production operations:** you need deployment assistance, security review, or contracted support.

---

## How Teams Typically Adopt

1. **Build on JarvisCore OSS.** Validate your agents, integrations, and workflows on the open-source runtime.
2. **Evaluate Enterprise** against the access-control, cost, workflow, or operational requirements of your workload.
3. **Agree the scope.** Confirm modules, versions, licensing, deployment responsibilities, support, and delivery before adoption.

---

## Security Review Pack

Ask Prescott Data for the security documentation available for the modules and deployment you are evaluating. Relevant review topics include:

- Architecture overview and data flow diagrams
- Threat model and mitigations
- Encryption key management documentation
- Shared responsibility model

Specify any required certifications or independent assessments in your request so their availability can be confirmed.

---

## Get In Touch

**Email:** [jarviscore-enterprise@prescottdata.io](mailto:jarviscore-enterprise@prescottdata.io)

Include the enterprise capabilities you need, your intended deployment, expected workload volume, and any security or support requirements.
