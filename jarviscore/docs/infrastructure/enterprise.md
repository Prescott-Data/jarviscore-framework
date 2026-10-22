---
icon: material/shield-check-outline
title: "JarvisCore Enterprise: AI Agents Within Your Boundaries"
description: "JarvisCore Enterprise: registered agent identity, delegated access, Maven cost efficiency, self-improving workflows, deployment and support on your infrastructure."
hide:
  - navigation
  - toc
videos:
  - id: 7_Uo5n9CKYw
    name: "JarvisCore Enterprise"
    description: "JarvisCore is coming to enterprise, ready to let AI agents act within institutional boundaries."
    upload_date: "2026-10-22T04:38:31-07:00"
    duration: PT2M0S
---

<section class="jcx-band jcx-band-sovereign" markdown>
<div markdown>

<span class="jcx-eyebrow">JarvisCore Enterprise</span>

<h1 class="jcx-band-title">Welcome to your sovereignty.</h1>

<p>AI agents that act within your institution's boundaries: registered identities, access delegated by each person, costs that fall as more work is automated, and workflows that improve from experience. On your infrastructure, with your keys and your choice of models.</p>

<div class="jcx-actions">
<a class="jcx-btn jcx-btn-primary" href="mailto:jarviscore-enterprise@prescottdata.io">Talk to us →</a>
<a class="jcx-btn jcx-btn-ghost" href="#oss-vs-enterprise">Compare editions</a>
</div>

</div>
<div class="jcx-video" data-yt="7_Uo5n9CKYw" data-title="JarvisCore Enterprise">
<a class="jcx-video-poster" href="https://www.youtube.com/watch?v=7_Uo5n9CKYw" target="_blank" rel="noopener" aria-label="Play the JarvisCore Enterprise film, 2 minutes">
<img src="https://i.ytimg.com/vi/7_Uo5n9CKYw/maxresdefault.jpg" alt="JarvisCore Enterprise: welcome to your sovereignty" width="1280" height="720" fetchpriority="high">
<span class="jcx-play"></span>
</a>
<div class="jcx-video-meta"><span>▶ Enterprise</span><span>2:00</span></div>
</div>
</section>

<section class="jcx-section" markdown>

<span class="jcx-kicker">Open source at the core</span>

## The same runtime, with the controls institutions need

<p class="jcx-sub">The JarvisCore framework is open source under Apache 2.0: self-host it and use it in commercial products with no revenue or user-count cap. Enterprise adds commercially licensed modules for access control, cost efficiency and workflow improvement, with deployment and support from Prescott Data.</p>

<div class="jcx-caps" markdown>

<div class="jcx-cap" markdown>
:material-badge-account-horizontal:
### Identity and delegated access
Each agent registered with a permission boundary. People delegate their access through time-bound, auditable sessions, never their raw credentials.

[Security and access ↓](#security-and-access)
</div>

<div class="jcx-cap" markdown>
:material-cash-fast:
### Cost efficiency with Maven
Lower AI execution cost as more work is automated, measured as cost per successfully completed task.

[Maven ↓](#maven-cost-efficiency)
</div>

<div class="jcx-cap" markdown>
:material-source-branch-sync:
### Workflows that improve
Agents test candidate changes to workflow DAGs in background experiments and upgrade only what proves more valuable.

[Self-improving DAGs ↓](#self-improving-workflow-dags)
</div>

<div class="jcx-cap" markdown>
:material-routes:
### The right model, in the right place
Task-aware model routing and a resource-aware gateway across clouds, regions and GPU generations.

[Models and routing ↓](#models-and-routing)
</div>

<div class="jcx-cap" markdown>
:material-server-security:
### Deployed and operated with you
Installation, upgrades, capacity, private cloud and on-premises, with uptime and recovery targets in your agreement.

[Deployment ↓](#deployment-and-operations)
</div>

<div class="jcx-cap" markdown>
:material-lifebuoy:
### Support and services
Commercial support with agreed coverage, onboarding, architecture review, custom integrations and training.

[Services ↓](#services-and-support)
</div>

</div>

</section>

<section class="jcx-section jcx-compare" markdown>

<span class="jcx-kicker">Editions</span>

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

</section>

<section class="jcx-section" markdown>

<span class="jcx-kicker">In depth</span>

## Security and access

Enterprise access controls extend Nexus credential handling:

- **Agent identity:** register each agent with a defined permission boundary. This credential identity is distinct from the role and capabilities used for discovery in the open-source Mesh.
- **On Behalf Of (OBO) sessions:** human-triggered agents carry the user's delegated permission through time-bound, auditable sessions without receiving the user's raw credentials. Delegation does not expand the agent's registered boundary.
- **Scope enforcement:** Nexus checks requested scopes against the agent's registered boundary at session request time. This applies to provider OAuth scopes and organization-defined permission names. Consuming services remain responsible for enforcing their resource-level permissions.

For the public credential setup, see [Nexus Credentials](../guides/nexus.md). Bring identity-provider, secrets-management, and audit requirements to the deployment review.

**Governance.** The open-source framework already includes execution budgets, [HITL](../guides/hitl.md), [contracts and boundaries](../concepts/contracts.md), and, from 2.3, per-person spending caps and audit in [multiplayer rooms](../concepts/multiplayer.md). Enterprise adds the Nexus credential identity and delegated-access controls above. Access enforcement complements agent reasoning; it does not replace it.

**Tenant isolation.** For deployments serving multiple business units or customers, the architecture review covers separation of credentials, agent state, storage, and network access. Isolation requirements and their verification belong in the deployment scope.

**Data privacy and compliance.** Deployment review covers data flows to model and API providers, processing locations, retention, deletion, and access to stored agent state. Identify applicable regulatory and internal requirements before selecting the deployment architecture.

## Maven cost efficiency

Maven is the enterprise cost-efficiency system for reducing AI execution costs as more work is automated. It is separate from the model configuration, routing, caching, and budget controls available in OSS.

Evaluate Maven on representative workloads using cost per successfully completed task, alongside quality and latency.

## Self-improving workflow DAGs

Agents learn from execution experience and identify changes to workflow DAGs that could deliver more value to the customer. They test candidate changes through long-running background experiments, rather than immediately applying a promising idea to the workflow. Only after those experiments demonstrate greater customer value do the agents upgrade the DAG. The objective is better customer outcomes, not simply a different graph or faster execution.

This is distinct from ordinary DAG execution, retries, and replanning within an active task, which remain part of the open-source framework.

## Models and routing

Provider configuration and the existing model-routing capabilities remain available in OSS; see [Language Models](../concepts/language-models.md) and [Model Routing](../concepts/model-routing.md). Enterprise extends this in two ways.

**Enterprise model routing** evaluates reasoning level, model type, model size, and inference cost against the needs of the task. The objective is to meet the task's quality requirements efficiently, rather than always choosing the cheapest or largest model.

| Routing factor | What it informs |
|---|---|
| **Reasoning level** | The reasoning capability needed for the task |
| **Model type** | Suitability for the kind of work being performed |
| **Model size** | The balance between capability and resource requirements |
| **Model cost** | Execution economics alongside task quality |

**The model gateway** routes execution based on available infrastructure as well as model suitability. It supports service continuity by directing requests to compatible resources as availability changes across cloud and multi-cloud deployments, regions, and compute pools, including older and newer GPU generations, TPUs and CPUs where the model and serving runtime support them.

Together they address **which model should do the work** and **where that work can run reliably and efficiently**. Supported models, runtimes, and deployment targets are confirmed for your environment; uptime commitments are defined in the commercial agreement.

## Deployment and operations

Deployment engagements cover the JarvisCore stack: agents, Mesh, Redis, blob storage, and observability. Scope self-managed deployment assistance or managed operations with Prescott Data based on your environment:

- Installation, configuration, upgrades, and rollback procedures
- Capacity planning and infrastructure requirements
- Private-cloud, networking, and on-premises requirements
- Responsibility for operating each service

For self-hosted setup, see [Production Deployment](../guides/production.md). External model and API calls follow your configured providers; hosting the runtime privately does not by itself keep all processing inside your network.

**Uptime.** For managed operations, availability targets, measurement, exclusions, and any service credits are specified in the commercial agreement.

**Backup and disaster recovery.** The deployment scope defines backup ownership, retention, restore testing, recovery point objectives (RPO), and recovery time objectives (RTO). These depend on the storage services and redundancy selected for your environment.

**Observability.** Framework tracing, `jarviscore inspect`, and metrics are available in OSS; see [Observability](../guides/observability.md). Enterprise services can include monitoring integration, retention configuration, and incident investigation for your deployment.

## Services and support

| Service | Description |
|---|---|
| **Onboarding programme** | Environment setup, agent review, and enterprise integration |
| **Architecture review** | A senior JarvisCore engineer reviews your agent design, workflow DAGs, and memory strategy and provides a written recommendations report |
| **Custom integrations** | Prescott Data builds and maintains integrations with internal systems (data warehouses, internal APIs, observability stacks) |
| **Training** | Hands-on workshops for your engineering team covering agent design patterns, workflow modelling, and production operations |

Professional services are scoped and priced in the commercial proposal.

| Support | Access | Scope |
|---|---|---|
| **Community** | Public project channels | Questions, bug reports, and documentation |
| **Commercial** | Agreed support channel | Coverage, response targets, and escalation defined in your agreement |

Include production criticality and required support hours when discussing commercial support.

</section>

<section class="jcx-section" markdown>

<span class="jcx-kicker">Adopting</span>

## From open source to Enterprise

<div class="jcx-split" markdown>
<div markdown>

<ol class="jcx-steps">
<li><strong>Build on JarvisCore OSS.</strong>Validate your agents, integrations, and workflows on the open-source runtime.</li>
<li><strong>Evaluate Enterprise</strong>against the access-control, cost, workflow, or operational requirements of your workload.</li>
<li><strong>Agree the scope.</strong>Confirm modules, versions, licensing, deployment responsibilities, support, and delivery before adoption.</li>
</ol>

</div>
<div markdown>

**Enterprise is the right choice when:**

- **Delegated access:** agents need registered credential identities, OBO sessions, and enforced scope boundaries.
- **Automation costs:** you want to evaluate Maven for recurring AI workloads.
- **Workflow improvement:** you need DAGs that improve from execution experience across runs.
- **Production operations:** you need deployment assistance, security review, or contracted support.

</div>
</div>

### Pricing

Enterprise modules and services are covered by a commercial agreement, scoped per engagement. Factors include the enterprise modules and intended use, deployment size and workflow volume, infrastructure and support requirements, and professional services scope.

Commercial use of the Apache-licensed framework does not require an enterprise agreement merely because your business grows. Embedding or redistributing proprietary enterprise modules requires appropriate commercial terms.

**Built with JarvisCore:** product credit is optional and appreciated. Add `[Built with JarvisCore](https://developers.prescottdata.io)` to your About page, footer, or documentation. This does not replace Apache's required license, copyright, and applicable attribution notices.

### Security review pack

Ask Prescott Data for the security documentation available for the modules and deployment you are evaluating: architecture overview and data flow diagrams, threat model and mitigations, encryption key management documentation, and the shared responsibility model. Specify any required certifications or independent assessments in your request so their availability can be confirmed.

</section>

<section class="jcx-band" markdown>
<div markdown>

<span class="jcx-eyebrow">Get in touch</span>

<h2>Bring your agents inside your boundaries</h2>

<p>Tell us the enterprise capabilities you need, your intended deployment, expected workload volume, and any security or support requirements.</p>

<div class="jcx-actions">
<a class="jcx-btn jcx-btn-primary" href="mailto:jarviscore-enterprise@prescottdata.io">jarviscore-enterprise@prescottdata.io</a>
<a class="jcx-btn jcx-btn-ghost" href="../getting-started/">Start with open source</a>
</div>

</div>
<div markdown>

<ul class="jcx-ticks">
<li>Apache 2.0 framework, no revenue or user-count cap</li>
<li>Commercial modules for identity, cost and workflows</li>
<li>Deployment, uptime and recovery targets in your agreement</li>
<li>Commercial support, onboarding and training</li>
</ul>

</div>
</section>
