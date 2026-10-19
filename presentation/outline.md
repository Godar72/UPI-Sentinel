# UPI Sentinel — Final CA-3 presentation outline

**Deck:** `UPI_Sentinel_CA3_PPT.pptx`
**Duration:** about 5 minutes across 10 slides
**Claim boundary:** findings are investigation leads for human review, not proof of fraud or mule-account activity.

## Slide 1 — UPI Sentinel

**Purpose:** Introduce the project and its evidence-backed investigation-triage objective.

**Talk track:** UPI Sentinel connects validated UPI-like transactions into a network, applies transparent patterns, and presents evidence for a person to review.

## Slide 2 — Problem statement and domain

**Purpose:** Explain why relationships between accounts and events can be difficult to see in row-by-row review, and why graph-based FinTech investigation triage is a relevant proof-of-concept domain.

**Talk track:** The project focuses on organizing transfer evidence; it does not claim to decide whether a real transaction is fraudulent.

## Slide 3 — From transaction rows to a reviewable lead

**Purpose:** Show validation, account-network analysis, deterministic rules, evidence, and human review as the proposed solution.

**Talk track:** Invalid rows remain visible with reasons. Accepted rows enter the graph. Rule matches carry transaction IDs, times, and thresholds.

## Slide 4 — System architecture

**Purpose:** Show the Coordinator and fixed LangGraph workflow, six deterministic agents, accepted/rejected split, dashboard result, and downstream evaluation path.

**Talk track:** Evaluation runs after detection and cannot change the graph or findings. The optional local explanation path is user-triggered and isolated from detection.

## Slide 5 — What each stage receives and returns

**Purpose:** Make the structured stage inputs and outputs clear, from CSV through validation, graph, findings, explanation, evaluation, and dashboard.

**Talk track:** Highlight rejected-row provenance, evidence-bearing findings, and the one structured workflow result.

## Slide 6 — A deterministic Python team

**Purpose:** Explain the Coordinator, Data Validation, Network Analysis, Pattern Analysis, Explanation, and Evaluation responsibilities.

**Talk track:** These are ordinary deterministic Python components orchestrated by LangGraph, not autonomous LLM agents. The optional LLM does not participate in this detection pipeline.

## Slide 7 — Live Streamlit capture

**Purpose:** Show actual dashboard screenshots: the synthetic fixture overview, selected-finding evidence, and optional local Ollama explanation.

**Talk track:** The reviewer explicitly requests an explanation for a selected finding. Only whitelisted evidence for that finding is sent to local Ollama; the full CSV and unrelated transaction history are excluded.

## Slide 8 — 40 rows, checked workflow output

**Purpose:** Present the verified fixture totals, rule findings, and S1–S6 scenario outcomes.

**Talk track:** The fixture has 40 input rows, 31 accepted, 9 rejected, 37 accounts, 31 graph transactions, and 5 findings. S2 produces overlapping rapid-chain and onward findings. S3 is partial because `S3-IN-1` is four numeric time units before the onward transfer, outside the three-unit window.

## Slide 9 — Responsible use

**Purpose:** Describe synthetic-only evidence, illustrative thresholds, overlapping findings, aggregate amount limitations, bounded graph display, and need for human review.

**Talk track:** These patterns may describe legitimate activity. The onward ratio cannot identify which specific funds moved. The optional model can still produce incorrect text; verify its output against the evidence.

## Slide 10 — Conclusion and questions

**Purpose:** Summarize the contribution as a reproducible workflow for evidence-backed investigation leads.

**Talk track:** UPI Sentinel organizes transaction evidence and surfaces configured patterns. A human reviewer interprets the evidence and decides what to do.
