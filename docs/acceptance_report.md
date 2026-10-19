# UPI Sentinel — Step 6 Acceptance and Demo Readiness

Audit date: 2026-10-12

## Post-audit orchestration update (2026-10-13)

After the audit recorded below, the fixed deterministic workflow was migrated to a LangGraph `StateGraph`. `CoordinatorAgent.run()` now invokes the compiled route `data_validation` → `network_analysis` → `pattern_analysis` → `explanation` → `evaluation`; the existing agents, validation, graph, rules, outputs, and label-isolation behavior remain the stage implementations. LangGraph is orchestration only: there are no LLM calls or paid services. The project test suite now includes graph-topology and public-entry-point integration checks; latest result: **53 passed**. The original audit details below describe the project state as of 2026-10-12.

## Environment and verification

Environment inspected: Windows PowerShell, Python 3.12.10, pandas 2.2.3, NetworkX 3.6.1, Plotly 6.6.0, Streamlit 1.51.0, and pytest 9.1.1. The checked-in fixture is `data/samples/synthetic_transactions.csv` (40 data rows). There is no `scenarios/` directory in the current project; scenario definitions live in `src/generate_synthetic.py` and README.md.

Commands and checks executed:

```powershell
python -m pytest -q
python --version
python -m streamlit run app.py --server.headless true --server.port 8765 --browser.gatherUsageStats false
python -m streamlit run app.py --server.headless true --server.port 8766 --browser.gatherUsageStats false
```

The baseline `python -m pytest -q` run completed with **50 passed in 1.72s**. Port 8765 was already in use, so that launch attempt exited before starting a new server. The same command on port 8766 started Streamlit successfully; `Invoke-WebRequest http://localhost:8766` returned **HTTP 200**, `text/html`, 1,522 response-body bytes. The server was stopped afterward. This was a headless startup/HTTP smoke check, not browser interaction.

An audit script also loaded the bundled CSV with pandas and passed it to the same `run_analysis()` public workflow used by Streamlit. It exercised the fixture, each S1–S6 subset, empty input, missing columns, all-rejected input, no-finding input, absent labels, and nonbinary labels. It compared findings and graph summaries after changing every label. Every finding's supporting IDs were present in both its evidence and the accepted transaction IDs. Streamlit rendering code was inspected to verify that displayed counts, findings, evidence, and evaluation metrics come from `WorkflowResult`; graph caps are disclosed in the app.

## End-to-end fixture result

The checked-in fixture produced 40 input rows, 31 accepted rows, 9 rejected rows, and an accepted-only graph with 37 accounts and 31 transactions. Five findings were produced: two rapid-chain findings, one shared-intermediary finding, and two aggregate onward-transfer findings. The toy transaction-label comparison was available and reported TP=5, FP=0, TN=25, FN=1. These are fixture-specific outputs only; they are not estimates of fraud-detection performance.

All five findings linked to accepted evidence and had nonempty explanations. Finding IDs were distinct. No label value is included in graph edge evidence or read by the pattern rules. Altering all fixture labels changed evaluation availability but left the graph summary and serialized finding list unchanged.

## Scenario audit

| Scenario | Intended meaning and actual fixture records | Observed validation, rules, and findings | Status / ambiguity |
|---|---|---|---|
| **S1 — ordinary P2P** | Four records `S1-T1`–`S1-T4`, independent sender/receiver pairs at times 10, 13, 16, 19. | 4/4 accepted. No findings. | **Pass.** No adjacent transfers share a receiver-to-sender account and time window. |
| **S2 — rapid chain** | `S2-T1`: S2-A→S2-B, 500 at 100; `S2-T2`: S2-B→S2-C, 480 at 101. | 2/2 accepted. Rapid-chain evidence is exactly `S2-T1`,`S2-T2`; aggregate onward rule also uses these records at a 96% amount ratio. | **Pass.** The second lead is a separate rule match on the same two records, not independent evidence. |
| **S3 — shared intermediary** | `S3-IN-1`–`S3-IN-3` send 300, 325, 350 to S3-HUB at 200, 201, 202; `S3-OUT` sends 950 onward at 204. | 4/4 accepted. Rapid chain uses `S3-IN-3`,`S3-OUT`. Shared-intermediary and onward findings use `S3-IN-2`,`S3-IN-3`,`S3-OUT`; the shared finding reports two distinct recent senders. The first incoming record is outside the 3-unit window (204−200=4). | **Partial.** The rule correctly matches multiple recent senders and an onward transfer, but the intended “three senders” does not all qualify under the documented default threshold. The 950 onward amount exceeds the 675 recent incoming aggregate; this ratio is a heuristic and cannot establish source-of-funds linkage. |
| **S4 — invalid records** | Nine records at source rows 11–19: blank sender; missing receiver; missing amount; nonnumeric amount; negative amount; invalid time; missing sender; two records sharing `S4-DUPLICATE`. | 0/9 accepted, all nine retained with specific rejection reasons. Both duplicate-ID rows are rejected. No graph edges or findings. | **Pass.** Confirms reject-all duplicate policy. The fixture has blank/missing IDs but no explicit blank receiver or missing transaction ID; those conditions are covered in validator tests, not this scenario. |
| **S5 — legitimate high-volume merchant** | `S5-T1`–`S5-T18`: 18 customers pay S5-MERCHANT at times 400–417. | 18/18 accepted. No findings. Incoming volume alone does not trigger any configured rule. | **Pass.** It is a simple synthetic merchant control and does not model merchant behavior broadly. |
| **S6 — split payment/refund** | `S6-SPLIT-1` and `S6-SPLIT-2`: customer pays shop 60 at 500 and 40 at 501; `S6-REFUND`: shop returns 10 at 505. | 3/3 accepted. No findings. Refund is outside rapid (2-unit) and onward (3-unit) windows from the latest receipt. | **Pass.** This is one designed timing pattern; it does not establish that refunds in general avoid leads. |

### Edge-case behavior observed

- Empty input: zero accepted/rejected, empty graph, no findings; evaluation unavailable because there are no accepted transactions.
- Missing required columns: available rows are rejected with schema errors; graph and findings are empty; evaluation is unavailable.
- All-rejected S4: all nine rows retained, graph and findings empty, evaluation unavailable.
- No-finding S1: no findings; evaluation unavailable because only one reference class is present.
- Absent labels and nonbinary labels: workflow completes, evaluation explicitly reports unavailable.
- Duplicate transaction IDs: both duplicate rows are rejected before graph construction; none of their edges can support a finding.
- Label isolation: changing labels to arbitrary strings did not change graph summary or findings; evaluation became unavailable.
- Same-time and out-of-order temporal behavior is covered by existing tests: rules require strictly positive elapsed time, so these pairs do not match.
- Visualization source caps at 60 accounts and 100 transactions and returns displayed/total counts. The app says truncation is display-only; the analysis receives the full graph.

## Defects and fixes

No concrete implementation defect was confirmed during this audit, so no code behavior was changed. The S3 window exclusion described above is a test-design/documentation caveat rather than a rule defect: two distinct senders satisfy the configured minimum of two. Existing documentation already describes the threshold and correctly calls the amount comparison aggregate rather than traceable.

README.md was not changed. This report is the only file added in Step 6.

## Limitations and unresolved risks

- All records and evaluation labels are synthetic and hand-designed. The aggregate metrics must not be presented as expected real-world accuracy.
- Transaction-level labels are not account-level mule labels. The evaluator marks a transaction positive when it appears in any finding's evidence; this can mark every transaction in a multi-edge explanation and does not imply culpability.
- Rules use illustrative thresholds and simple time/amount windows. Shared-intermediary and rapid-chain matches can describe legitimate behavior.
- The onward ratio compares an outgoing amount with aggregate recent incoming amounts. Ratios can exceed 100%; no individual funds are linked or traced.
- The S3 fixture currently has only two of its three incoming senders within the shared-intermediary time window. This is visible in the evidence and should be explained during a demo.
- There is no verified public dataset integration, calibrated threshold, production data, fairness analysis, privacy/security review, or operational case-management workflow.
- The network visualization is intentionally bounded; large-network views omit nodes/edges while core analysis remains complete.
- The HTTP smoke check confirms server startup and HTML response only. Browser interaction and visual layout were not tested in this acceptance step.

## Truthful five-minute demo sequence

1. **0:00–0:35 — Problem and boundary.** Introduce the investigation-triage use case and emphasize that leads are not proof of fraud or mule activity.
2. **0:35–1:10 — Architecture.** Show the README flow: validation → graph → deterministic pattern rules → explanation → evaluation. State that these are ordinary deterministic Python agents, with no LLM or paid API.
3. **1:10–1:45 — Load and run.** Open the Streamlit app, load the bundled synthetic CSV, and explicitly submit **Run analysis**. Expected fixture counts: 40 input, 31 accepted, 9 rejected; 37 accounts and 31 transactions.
4. **1:45–2:50 — Evidence.** Select the S2 rapid-chain lead and inspect `S2-T1`,`S2-T2`. Select the S3 shared-intermediary lead and explain why only `S3-IN-2` and `S3-IN-3` are in its 3-unit window; `S3-IN-1` is four units before the onward transfer.
5. **2:50–3:35 — Validation and negative control.** Show rejected reasons for S4, then point out S5's 18 merchant receipts produce no finding solely from volume. Mention that S6's refund is outside the configured windows.
6. **3:35–4:15 — Graph and evaluation.** Show the directed network, disclose node/edge display caps if relevant, and identify evaluation as fixture-only transaction-level overlap. Do not describe the toy metric values as model performance.
7. **4:15–5:00 — Limitations.** Close with synthetic data, simple thresholds, potential legitimate matches, no account-level ground truth, and the need for human review.

## Viva preparation

1. What business challenge does UPI Sentinel address, and why is transaction-network analysis useful?
2. What are the responsibilities and inputs/outputs of the validation, network, pattern, explanation, and evaluation agents?
3. How does the Coordinator order the agents, and why are these called deterministic agents rather than autonomous LLM agents?
4. Why is the graph a directed `MultiDiGraph`, and how are parallel transfers and transaction evidence preserved?
5. What are the default rapid-chain, shared-intermediary, and onward-transfer thresholds? How are same-time and out-of-order transfers handled?
6. What does validation reject, how are rejected rows traced, and what is the duplicate-ID policy?
7. How are evaluation labels isolated from graph construction and detection? What does the demo transaction-level predicted-positive definition mean?
8. Why can the reported synthetic precision/recall/accuracy not be generalized to fraud detection or mule-account identification?
9. Why can an onward-transfer ratio exceed 100%, and why does it not prove that particular funds moved onward?
10. What additional data, validation, privacy controls, calibration, and human review would be necessary before any operational use?
