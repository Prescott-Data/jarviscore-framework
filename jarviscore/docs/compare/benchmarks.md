---
icon: material/chart-box-outline
title: JarvisCore Browser Agent and Elastic Pool Benchmarks
description: How the JarvisCore 2.2.0 browser agent performs on Online-Mind2Web and a hard grocery checkout, and how elastic pools change wall-clock time, with methods and limits.
---

# Benchmarks

This page reports what we measured on JarvisCore 2.2.0, how we measured it, and
what the numbers do not show. Each result names the model, the task set and the
way success was judged, because a score without those is not comparable to
anything.

All runs used Azure OpenAI `gpt-5.6-luna` for every agent role, on one laptop,
through a single network connection without an egress proxy.

## Browser automation on live websites: Online-Mind2Web

[Online-Mind2Web](https://huggingface.co/datasets/osunlp/Online-Mind2Web) is a
public benchmark of 300 everyday tasks on real, live websites, such as finding a
shipping rate, filtering job listings or comparing products. Its authors group
tasks by the length of a person's reference solution: up to 5 actions is easy,
6 to 10 is medium, and 11 or more is hard. They also publish human judgements of
whether each of several well-known web agents completed each task.

### Method

- **Tasks.** 30 tasks, 10 at each difficulty, drawn from the 300 with a fixed
  random seed so the same tasks are used for every run.
- **Agent.** The JarvisCore browser agent, started on the task's website with
  the task text. It was told it may search, filter, use calculators and add
  items to a cart, but must stop before signing in, paying or sending anything,
  and report what it found. Consequential actions would have waited for
  approval and been declined; none of these tasks reached one.
- **Judging.** Each run was judged automatically from its recorded steps and
  final answer: a model lists the task's key requirements and checks each
  against the evidence, in the style of the benchmark authors' WebJudge. The
  judge was `gpt-5.6-luna`, the same model the agent used.
- **Comparison.** The other agents' figures are the benchmark's published human
  judgements for the same 30 tasks, counting only the tasks each agent has a
  judgement for.

### Results

Share of tasks completed, by difficulty:

| Agent | Easy | Medium | Hard | All |
|---|---|---|---|---|
| **JarvisCore 2.2.0** | 70% | 60% | **50%** | **60%** |
| OpenAI Operator | 89% | 75% | 44% | 69% |
| Claude Computer Use 3.7 | 100% | 50% | 44% | 65% |
| Browser Use | 89% | 50% | 0% | 46% |
| SeeAct | 67% | 50% | 11% | 42% |
| Claude Computer Use 3.5 | 67% | 38% | 11% | 38% |
| Agent-E | 22% | 25% | 0% | 15% |

JarvisCore completed 18 of the 30 tasks: 7 easy, 6 medium and 5 hard. A typical
task took 160 seconds (median) and about 19 model calls.

Seven of the twelve failures were websites that refused or could not be reached
from our connection: StubHub, NBA.com and Drugs.com returned access-denied
pages (Drugs.com citing our region), the Better Business Bureau and Cars.com
blocked the browser, and CarMax could not be reached on two tasks.
In each case the agent reported that it could not get in rather than inventing
an answer.

### What these numbers do not show

- **The comparison is indicative, not head to head.** Our runs were judged by a
  model; the other agents were judged by people, on runs made when the
  benchmark was published in 2025. Live websites have changed since, in both
  directions.
- **The sample is small.** With 10 tasks per difficulty, one task moves a
  difficulty's score by 10 points.
- **The network matters.** Several sites block traffic they do not recognise.
  An [egress proxy](../guides/browser-automation.md#your-own-proxy) in the
  right region would likely have reached some of the refused sites; we ran
  without one.
- **The harness is not yet public.** The task selection, run and judging
  scripts are not yet in the repository.

## A hard grocery checkout

Online-Mind2Web stops short of placing orders. To test a complete purchase, we
built a local grocery shop that behaves the way real shops do, and a task that
asks the agent to order ingredients for a stir-fry:

> a pack of noodles, mixed peppers, a stir-fry sauce and a 1kg bag of basmati
> rice. Noah is allergic to peanuts, so nothing that contains them. Keep the
> total under £6.00, using any offer the shop has, and get it delivered by
> Friday. If something is unavailable, choose the closest substitute and tell
> me what you changed.

On the way, the agent meets:

- a cookie dialog that covers every page until it is answered;
- search results split across pages;
- allergens listed only on each product's own page, with a satay sauce that
  contains peanuts;
- 1 kg basmati rice out of stock, with suitable substitutes on a later results
  page;
- a promo code published on a separate offers page and valid only for weekday
  delivery;
- full delivery slots, and a slot that is taken by someone else during checkout;
- an approval before the order is placed, which the test grants.

The shop records the order it receives, and a grader checks it against eleven
requirements: exactly one order; noodles, mixed peppers and a stir-fry sauce;
no product containing peanuts; a proper rice substitute (1 kg of brown basmati,
or two 500 g bags of basmati); a total under £6.00; the promo code applied;
a weekday delivery by the deadline; an answer that names the order; and an
answer that reports the substitution.

### Results on the final 2.2.0 build

| Runs | Orders | Fully passed | Median time | Model calls |
|---|---|---|---|---|
| 5 | 5 | 3 | 367 s | 55–114 |

Every run placed exactly one order, kept it peanut-free and under budget,
applied the promo code, booked a weekday slot and said which order it placed.
The two runs that missed a check both chose a weaker rice substitute: one
bought 1 kg of long-grain rice because it was cheaper, and one bought a single
500 g bag of basmati, half the quantity asked for. Both said so in their answer.
Both had seen the correct substitutes and their prices, so these are judgement
calls by the model rather than gaps in what it could see.

Across all 14 runs of 2.2.0 release candidates, 13 placed exactly one order
and 7 passed every check. Of the seven that missed a check, one placed no
order, five chose a weaker rice substitute, and one gave an answer that still
described the approval after the order had gone through, which is fixed in
2.2.0 (see the [changelog](../changelog.md)).

## Elastic pools: one agent, many workers

A [pool](../guides/production.md#scaling-one-agent-pools) lets one logical agent
run as several members when work queues up. The workload here is Evidence
Engine, an application built on JarvisCore, verifying the claims in a matter (a
collection of documents under review): each claim is one step, checked against
the documents and the web by a verifier agent.

### 196 claims on one laptop

| Configuration | Wall clock |
|---|---|
| Fixed workers (2.1.0) | 202 min (the laptop slept for about 30 of them) |
| Pools, before the 2.2.0 event-loop fixes | 97 min |
| Pool of up to 16 members | 11.1 min |
| Pool of up to 32 members | 9.4 min |

### Claims run in parallel

On a six-claim matter, all six verifications started within two seconds of each
other, each on its own pool member. With members working in parallel, the
matter takes as long as its slowest claim rather than the sum of all six:

| Build | Claims | Wall clock | Summed claim time | Speed-up |
|---|---|---|---|---|
| Before 2.2.0 | 6 | 177 s | 773 s | 4.4× |
| 2.2.0 | 6 | 330 s | 929 s | 2.8× |

The 2.2.0 run was slower because one claim took 329 seconds. It ran while the
Azure deployment's tokens-per-minute allowance, shared by every verifier, was
nearly used up, and the [provider governor](../reference/configuration.md#provider-governor)
reduced the number of calls in flight rather than let the provider return rate
limit errors. The 2.2.0 run had no rate-limit errors and lost no claims.
