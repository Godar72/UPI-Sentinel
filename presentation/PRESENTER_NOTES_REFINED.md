# UPI Sentinel CA-3 | Refined Presenter Notes

**Target duration:** about 5 minutes across 10 slides.
**Framing:** every output is an investigation lead for human review, not proof of fraud or mule-account activity.

## Timed talk track

### Slide 1 · 0:00–0:18
UPI Sentinel is a classroom proof of concept for investigating suspicious UPI-style transaction networks. It connects validated transfers to transparent patterns and the evidence behind each match.

### Slide 2 · 0:18–0:50
A transaction table records separate events. An investigator may need to connect the sender of one transfer to the receiver of another, while accounting for time and malformed rows. Our demo uses synthetic data and preserves rejected rows with reasons.

### Slide 3 · 0:50–1:18
The system validates records, builds an accepted-only directed graph and applies three deterministic rules. A rapid chain must be strictly time-ordered and within 2 units. A shared intermediary needs at least two distinct senders before onward activity within 3 units. The onward rule compares outgoing amount with aggregate recent incoming and requires at least 80 percent within 3 units. This ratio does not trace specific funds. Numeric fixture times are units, not hours.

### Slide 4 · 1:18–2:00
Streamlit calls `run_analysis(data, config)`. The Coordinator runs the compiled LangGraph flow through five agents: validation, network analysis, pattern analysis, explanation and evaluation. Shared state carries each output forward. Rejected rows retain source IDs and reasons. Evaluation labels enter only after detection. Below, the separate optional branch starts only when a reviewer selects an existing finding. It sends whitelisted evidence to local Ollama, checks the response and uses a deterministic fallback when needed. It has no route back to rules or findings.

### Slide 5 · 2:00–2:25
Accounts are graph nodes and accepted transfers are directed edges keyed by transaction ID. Edges retain amount, transaction type, time and source row. Each finding carries its rule, accounts, supporting transaction IDs, times, thresholds, measured values and an explanation.

### Slide 6 · 2:25–3:00
These are deterministic Python components orchestrated by LangGraph, not autonomous LLM agents. The Coordinator orders work. Validation checks the schema and keeps rejected records. Network Analysis builds the MultiDiGraph. Pattern Analysis runs the rules. Explanation summarizes actual outputs. Evaluation runs last and compares eligible transaction labels with completed finding evidence.

### Slide 7 · 3:00–3:40
These are genuine captures from the running dashboard. Overview shows the fixture result. The Investigation view shows S2 transaction evidence and the optional explanation returned by local `qwen2.5:3b`. Only selected-finding whitelisted evidence goes to the localhost Ollama endpoint. The full CSV and unrelated transaction history are excluded. Output checks and evidence-based fallback reduce risk, but model text can still be wrong.

### Slide 8 · 3:40–4:20
The fixture contains 40 rows: 31 accepted and 9 rejected. The graph has 37 accounts and 31 transactions. Five findings comprise two rapid-chain leads, one shared-intermediary lead and two onward leads. S2’s two leads overlap on the same two transfers. S3 is partial because `S3-IN-1` is four time units before `S3-OUT`, outside the three-unit window. S1, S4, S5 and S6 behave as designed controls.

### Slide 9 · 4:20–4:50
Thresholds are illustrative and may match legitimate activity or miss relevant behavior. Findings can overlap. The aggregate onward ratio cannot identify which funds moved. Synthetic transaction labels do not establish mule accounts or real-world performance. Future work would need governed data, rule review, privacy assessment and a stronger investigation workflow.

### Slide 10 · 4:50–5:00
UPI Sentinel produces explainable leads with transaction evidence. A person reviews the evidence and decides what to do. I’m ready for questions.

## Short live-demo sequence

1. Open the Streamlit Overview and load the bundled synthetic fixture.
2. Run analysis and point to the displayed 40 input rows, 31 accepted, 9 rejected, 37 accounts, 31 graph transactions and 5 findings.
3. Open Investigations and select the S2 rapid-chain finding. Show `S2-T1` and `S2-T2`, with numeric times 100 and 101.
4. If Ollama is running, explicitly select **Generate explanation with local Ollama**. Point out `qwen2.5:3b`, the localhost request, the selected-finding evidence boundary and the returned prose. If it times out, show the deterministic fallback status instead.
5. Optionally inspect S3 and explain that `S3-IN-1` falls outside the 3-unit window. Close by stating that the result is an investigation lead, not a fraud verdict.

## Likely teacher questions

### 1. What is the project domain and problem statement?
It is a FinTech investigation-triage proof of concept for UPI-style transaction networks. Given transaction rows, it validates records, connects accepted transfers by account and applies transparent rules to surface patterns for human review.

### 2. Why is this an Agentic AI project?
It models a multi-stage workflow with specialized components coordinated through LangGraph shared state. The agents pass structured results through validation, graph analysis, detection, explanation and evaluation. These agents are deterministic Python components, not autonomous LLM agents.

### 3. What does each of the six agents do?
The Coordinator invokes the graph and returns the workflow result. Data Validation checks the canonical schema and preserves rejected rows. Network Analysis builds and summarizes the accepted-only `MultiDiGraph`. Pattern Analysis runs the rules. Explanation summarizes observed outputs. Evaluation compares eligible transaction-level labels after findings exist.

### 4. Why use an LLM if detection is deterministic?
The optional local model can make an existing finding easier to read. It does not validate data, build the graph, select thresholds, detect patterns or score accounts. Deterministic evidence remains the source of truth.

### 5. How is the LLM kept separate from detection?
A user must select an already detected finding and explicitly request an explanation. The request contains only that finding’s whitelisted evidence. The separate Ollama call cannot add, remove, reclassify or change the severity of findings, and no model output feeds back to LangGraph.

### 6. What happens if Ollama times out or returns unsupported text?
The request is local and uses a configurable timeout. The application validates basic response requirements and returns a deterministic explanation built from the finding evidence when the request fails, times out, returns empty or unsuitable output. These checks reduce risk but cannot guarantee that all generated prose is correct.

### 7. What do the five findings actually mean?
They are two rapid-chain rule matches, one shared-intermediary match and two aggregate onward-ratio matches. S2’s chain and onward leads reference the same two transactions. S3 contributes one rapid-chain, one shared-intermediary and one onward lead, with only two incoming senders inside the configured window. These are rule matches, not separate proof of five fraudulent events.

### 8. What are the project’s limitations and next steps?
The data is synthetic, thresholds are illustrative, findings can overlap and legitimate transfers can match. The onward ratio compares aggregate amounts without tracing funds. The toy transaction labels do not provide account-level mule ground truth. Next steps include governed data, privacy and provenance review, threshold calibration, better evaluation labels and investigator feedback workflows.

### 9. How does the system prevent evaluation leakage?
The LangGraph workflow generates graph summaries and findings before Evaluation runs. Labels are read only in the final evaluation stage. Tests compare findings and graph results after changing labels. The metric is transaction-level evidence overlap, not account-level mule identification.

### 10. Why are the numeric times called time units?
The fixture stores numeric indices such as 100 and 101. It does not establish that these are clock hours. Rules call elapsed differences in numeric indices time units. Datetime inputs can be measured in hours because the code computes elapsed datetime duration.

### Why are findings leads rather than verdicts?
A rule only identifies a structure in the supplied records. It does not establish intent, source of funds, account ownership, or whether the activity is legitimate. A qualified person must review the records and external context before taking action.
