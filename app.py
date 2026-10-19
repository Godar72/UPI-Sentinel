"""Local Streamlit interface for the UPI Sentinel academic proof of concept."""

from __future__ import annotations

import hashlib
from html import escape
import io
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.agents import WorkflowError, WorkflowResult, run_analysis
from src.llm_explanation import explain_finding_with_ollama
from src.rules import DISCLAIMER, RuleConfig
from src.schema import LABEL, REQUIRED_COLUMNS, SOURCE_ROW, TRANSACTION_ID
from src.visualization import create_network_figure


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_FIXTURE = PROJECT_ROOT / "data" / "samples" / "synthetic_transactions.csv"
LOGO_PATH = PROJECT_ROOT / "assets" / "upi_sentinel_logo.png"
DEFAULT_CONFIG = RuleConfig()
PAGES = ("Overview", "Investigations", "Network Explorer", "Transactions", "Methodology")
DISPLAY_NODE_LIMIT = 60
DISPLAY_EDGE_LIMIT = 100

CSS = """
<style>
:root {
  --sentinel-ink: #edf5f8; --sentinel-muted: #93a9b8; --sentinel-line: rgba(146,178,194,.17);
  --sentinel-teal: #58ddc4; --sentinel-amber: #e8bd73;
}
.stApp {
  background: radial-gradient(ellipse at 86% -12%, rgba(27,120,119,.18), transparent 38%),
              radial-gradient(ellipse at 0% 72%, rgba(32,75,112,.12), transparent 36%), #08131e;
  color: var(--sentinel-ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
h1, h2, h3 { color: var(--sentinel-ink) !important; letter-spacing: -.025em; }
h1 { font-size: 2.05rem !important; font-weight: 700 !important; }
h2 { font-size: 1.35rem !important; font-weight: 650 !important; }
h3 { font-size: 1.02rem !important; font-weight: 650 !important; }
p, label { color: #c3d1da; }
button { border-radius: 9px !important; font-weight: 620 !important; }
input, textarea { color: var(--sentinel-ink) !important; }
.sentinel-brand { display:flex; align-items:center; gap:12px; padding:5px 3px 17px; }
.sentinel-mark { width:39px; height:39px; border-radius:12px; display:grid; place-items:center;
  color:#07171b; background:linear-gradient(145deg,#83efdc,#37bea9); font:800 16px/1 system-ui;
  box-shadow:0 6px 22px rgba(48,209,179,.16); }
.sentinel-brand-title { color:#f3f8fb; font-weight:740; font-size:1.02rem; letter-spacing:-.025em; }
.sentinel-brand-sub { color:#8299aa; font-size:.66rem; margin-top:3px; letter-spacing:.11em; text-transform:uppercase; }
.sentinel-eyebrow { color:var(--sentinel-teal); font-size:.69rem; font-weight:740; letter-spacing:.15em; text-transform:uppercase; margin-bottom:.42rem; }
.sentinel-subtitle { color:var(--sentinel-muted); font-size:.91rem; line-height:1.55; }
.sentinel-banner { border:1px solid rgba(232,189,115,.31); background:rgba(105,76,35,.17); color:#f1d8aa;
  border-radius:10px; padding:.78rem 1rem; font-size:.86rem; }
.sentinel-status { display:inline-block; border:1px solid rgba(88,221,196,.27); color:#8de8d6;
  background:rgba(43,152,132,.12); border-radius:999px; padding:.25rem .64rem; font-size:.73rem; font-weight:650; }
.sentinel-section-label { color:var(--sentinel-teal); font-size:.68rem; font-weight:720; letter-spacing:.13em; text-transform:uppercase; margin-bottom:.25rem; }
.sentinel-card-title { color:#eef5f8; font-size:1rem; font-weight:670; margin:.06rem 0 .26rem; }
.sentinel-card-copy { color:#95aaba; font-size:.82rem; line-height:1.5; }
.sentinel-finding-id { color:#d9e7ed; font-family:ui-monospace, SFMono-Regular, Consolas, monospace; font-size:.82rem; overflow-wrap:anywhere; }
.sentinel-stage { border-left:2px solid #315064; padding:.1rem 0 .55rem .72rem; margin-left:.28rem; }
.sentinel-stage-name { color:#b8cbd5; font-size:.79rem; font-weight:650; }
.sentinel-stage-status { color:#7fe3cd; font-size:.72rem; margin-top:.12rem; }
.sentinel-note { color:#91a8b8; font-size:.8rem; line-height:1.5; }
</style>
"""


def _initialize_state() -> None:
    defaults = {
        "raw_dataframe": None, "input_source": None, "input_version": 0,
        "input_error": None, "last_result": None, "last_result_source": None,
        "last_result_version": None, "last_result_config": None, "last_result_time": None,
        "processed_upload_signature": None, "suppressed_upload_signature": None,
        "uploader_was_present": False, "page": "Overview", "selected_finding": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def load_bundled_fixture(path: Path = DEFAULT_FIXTURE) -> pd.DataFrame:
    return pd.read_csv(path)


def parse_uploaded_csv(payload: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(payload))


def _upload_signature(upload_name: str, payload: bytes) -> str:
    return f"{upload_name}:{hashlib.sha256(payload).hexdigest()}"


def _set_input(dataframe: pd.DataFrame | None, source: str | None, error: str | None) -> None:
    st.session_state.raw_dataframe = dataframe
    st.session_state.input_source = source
    st.session_state.input_error = error
    st.session_state.input_version += 1


def _load_input_controls() -> None:
    st.sidebar.markdown("<div class='sentinel-section-label'>Data source</div>", unsafe_allow_html=True)
    fixture_clicked = st.sidebar.button("Load synthetic fixture", width="stretch")
    upload = st.sidebar.file_uploader("Upload transaction CSV", type=["csv"], help="Read and analyzed locally.")
    clear_clicked = st.sidebar.button("Clear current input", width="stretch")
    payload = upload.getvalue() if upload is not None else None
    signature = _upload_signature(upload.name, payload) if upload is not None and payload is not None else None
    if clear_clicked:
        _set_input(None, None, None)
        st.session_state.suppressed_upload_signature = signature
        st.session_state.processed_upload_signature = None
    elif fixture_clicked:
        try:
            _set_input(load_bundled_fixture(), DEFAULT_FIXTURE.name, None)
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            _set_input(None, DEFAULT_FIXTURE.name, f"Could not load the bundled fixture: {exc}")
        st.session_state.suppressed_upload_signature = signature
        st.session_state.processed_upload_signature = None
    elif upload is not None and signature != st.session_state.suppressed_upload_signature:
        if signature != st.session_state.processed_upload_signature:
            try:
                _set_input(parse_uploaded_csv(payload), upload.name, None)
            except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError, OSError) as exc:
                _set_input(None, upload.name, f"Could not read the uploaded CSV: {exc}")
            st.session_state.processed_upload_signature = signature
    elif upload is None and st.session_state.uploader_was_present:
        st.session_state.suppressed_upload_signature = None
        st.session_state.processed_upload_signature = None
    st.session_state.uploader_was_present = upload is not None
    if st.session_state.raw_dataframe is not None:
        source = st.session_state.input_source or "CSV loaded"
        st.sidebar.markdown(f"<span class='sentinel-status'>● {escape(str(source))}</span>", unsafe_allow_html=True)
        st.sidebar.caption(f"{len(st.session_state.raw_dataframe):,} source rows")
    elif st.session_state.input_error:
        st.sidebar.error(st.session_state.input_error)
    else:
        st.sidebar.caption("No active dataset")


def _schema_help() -> None:
    st.caption("Required columns: " + ", ".join(f"`{name}`" for name in REQUIRED_COLUMNS))
    st.caption(f"Optional `{LABEL}` is evaluation-only. It is excluded from detection and graph analysis.")


def _time_unit_label(rows: pd.DataFrame) -> str:
    """Describe the actual time representation without implying hours for indices."""
    if "time" not in rows.columns:
        return "time units (datetime inputs are measured in hours)"
    values = rows["time"].dropna()
    if values.empty:
        return "time units (datetime inputs are measured in hours)"
    value = values.iloc[0]
    if isinstance(value, (datetime, pd.Timestamp)):
        return "hours from datetime timestamps"
    return "numeric time units"


def _section_intro(eyebrow: str, title: str, description: str | None = None) -> None:
    st.markdown(f"<div class='sentinel-section-label'>{eyebrow}</div>", unsafe_allow_html=True)
    st.subheader(title)
    if description:
        st.markdown(f"<div class='sentinel-note'>{description}</div>", unsafe_allow_html=True)


def _analysis_form() -> RuleConfig | None:
    st.sidebar.markdown("<div class='sentinel-section-label'>Rule thresholds</div>", unsafe_allow_html=True)
    rapid = st.sidebar.number_input("Rapid-chain window", min_value=.1, value=float(DEFAULT_CONFIG.rapid_chain_window), step=.5,
                                    help="Numeric time-index units or hours for datetime values.")
    shared = st.sidebar.number_input("Shared-intermediary window", min_value=.1, value=float(DEFAULT_CONFIG.shared_intermediary_window), step=.5)
    senders = st.sidebar.number_input("Minimum distinct senders", min_value=2, value=int(DEFAULT_CONFIG.shared_intermediary_min_senders), step=1)
    onward = st.sidebar.number_input("Onward-transfer window", min_value=.1, value=float(DEFAULT_CONFIG.onward_window), step=.5)
    ratio = st.sidebar.number_input("Minimum onward / recent incoming", min_value=.01, max_value=1.0,
                                    value=float(DEFAULT_CONFIG.onward_min_received_proportion), step=.05, format="%.2f")
    try:
        return RuleConfig(float(rapid), float(shared), int(senders), float(onward), float(ratio))
    except ValueError as exc:
        st.sidebar.error(f"Invalid thresholds: {exc}")
        return None


def _run_analysis_if_requested(submitted: bool, config: RuleConfig | None) -> None:
    if not submitted or config is None:
        return
    try:
        result = run_analysis(st.session_state.raw_dataframe.copy(), config=config)
    except WorkflowError as exc:
        st.error(f"Analysis could not complete at {exc.stage}: {exc.args[0]}")
        st.caption("Review the input schema and validation details, then try again.")
        return
    except Exception as exc:
        st.error(f"Analysis could not complete ({type(exc).__name__}). Check the input and try again.")
        return
    st.session_state.last_result = result
    st.session_state.last_result_source = st.session_state.input_source or "loaded CSV"
    st.session_state.last_result_version = st.session_state.input_version
    st.session_state.last_result_config = config
    st.session_state.last_result_time = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")


def _header(result: WorkflowResult | None) -> bool:
    st.markdown("<div class='sentinel-eyebrow'>Transaction intelligence · local analysis</div>", unsafe_allow_html=True)
    title = st.session_state.page
    descriptions = {
        "Overview": "A clear operational summary of the latest transaction review.",
        "Investigations": "Inspect deterministic leads with source-linked transaction evidence.",
        "Network Explorer": "Explore directed account activity from the accepted transaction graph.",
        "Transactions": "Review accepted records and validation rejections in one workspace.",
        "Methodology": "Understand the workflow, thresholds, evaluation boundary, and limitations.",
    }
    left, right = st.columns([3, 1])
    left.title(title)
    left.markdown(f"<div class='sentinel-subtitle'>{descriptions[title]}</div>", unsafe_allow_html=True)
    if result is not None:
        freshness = "Current run" if st.session_state.last_result_version == st.session_state.input_version else "Previous run"
        right.markdown(f"<span class='sentinel-status'>● {freshness}</span>", unsafe_allow_html=True)
        right.caption(f"{st.session_state.last_result_source} · {st.session_state.last_result_time}")
    else:
        right.markdown("<span class='sentinel-status'>● Ready for review</span>", unsafe_allow_html=True)
    submitted = right.button("Run analysis", type="primary", width="stretch",
                             disabled=st.session_state.raw_dataframe is None)
    st.markdown("<div class='sentinel-banner'>Investigation leads for human review — not proof of fraud or mule activity.</div>", unsafe_allow_html=True)
    return submitted


def _stage_trace(result: WorkflowResult) -> None:
    _section_intro("Workflow", "Analysis stages", "Live stage outcomes from this analysis run.")
    cols = st.columns(len(result.stage_trace))
    for col, stage in zip(cols, result.stage_trace):
        status = stage.status.replace("_", " ").title()
        with col.container(border=True):
            st.markdown(
                f"<div class='sentinel-stage'><div class='sentinel-stage-name'>● {stage.stage.replace('_',' ').title()}</div>"
                f"<div class='sentinel-stage-status'>{status}</div></div>",
                unsafe_allow_html=True,
            )
            st.caption(stage.message)


def _metric_cards(result: WorkflowResult) -> None:
    values = [
        ("Input rows", result.validation_counts["input_rows"], "Source records received"),
        ("Accepted rows", result.validation_counts["accepted_rows"], "Passed schema validation"),
        ("Rejected rows", result.validation_counts["rejected_rows"], "Retained with reasons"),
        ("Accounts", result.graph_summary.account_count, "In accepted network"),
        ("Transactions", result.graph_summary.transaction_count, "Directed graph edges"),
        ("Investigation leads", len(result.findings), "Configured rules matched"),
    ]
    for row_values in (values[:3], values[3:]):
        for col, (label, value, sub) in zip(st.columns(3), row_values):
            with col.container(border=True):
                st.metric(label, f"{value:,}")
                st.caption(sub)


def _charts(result: WorkflowResult) -> None:
    _section_intro("At a glance", "Validation and findings", "Counts and rule matches generated by the current deterministic analysis.")
    chart_left, chart_right = st.columns(2)
    with chart_left:
        st.markdown("#### Validation outcome")
        fig = go.Figure(go.Bar(x=["Accepted", "Rejected"],
                               y=[result.validation_counts["accepted_rows"], result.validation_counts["rejected_rows"]],
                               marker_color=["#58ddc4", "#df8990"], textposition="outside"))
        fig.update_layout(height=260, margin=dict(l=8,r=8,t=12,b=8), paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(0,0,0,0)", font_color="#dbe5ed", showlegend=False,
                          yaxis=dict(gridcolor="rgba(160,180,200,.12)", rangemode="tozero", title="Rows"),
                          xaxis=dict(fixedrange=True))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with chart_right:
        st.markdown("#### Leads by rule")
        counts = Counter(item.rule_name.replace("_", " ").title() for item in result.findings)
        if not counts:
            st.info("No configured rules matched this input.")
        else:
            fig = go.Figure(go.Bar(x=list(counts.values()), y=list(counts.keys()), orientation="h",
                                   marker_color="#58ddc4", text=list(counts.values()), textposition="outside"))
            fig.update_layout(height=260, margin=dict(l=8,r=28,t=12,b=8), paper_bgcolor="rgba(0,0,0,0)",
                              plot_bgcolor="rgba(0,0,0,0)", font_color="#dbe5ed", showlegend=False,
                              xaxis=dict(gridcolor="rgba(160,180,200,.12)", rangemode="tozero", title="Findings"),
                              yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def _navigate_to_finding(finding_id: str) -> None:
    """Set navigation state from a button callback before the next rerun."""
    st.session_state.selected_finding = finding_id
    st.session_state.page = "Investigations"


def _finding_card(finding, index: int) -> None:
    accounts = " · ".join(map(str, finding.involved_account_ids))
    measurements = " · ".join(f"{key.replace('_',' ')}: {value:g}" for key, value in finding.measurements.items()) or "Threshold match"
    with st.container(border=True):
        st.markdown(f"<div class='sentinel-section-label'>{escape(finding.rule_name.replace('_',' '))}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='sentinel-finding-id'>{escape(str(finding.finding_id))}</div>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='sentinel-card-copy'>Accounts: {escape(accounts)}<br>{escape(measurements)}<br>"
            f"{len(finding.supporting_transaction_ids)} supporting transactions</div>",
            unsafe_allow_html=True,
        )
        st.button(
            "Inspect evidence",
            key=f"inspect_{index}",
            on_click=_navigate_to_finding,
            args=(finding.finding_id,),
        )


def _overview(result: WorkflowResult) -> None:
    _section_intro("Executive review", "Current review snapshot", "Validated activity, accepted network size, and rules that matched the current input.")
    if st.session_state.last_result_version != st.session_state.input_version:
        st.info("The active input has changed since this run. These are results from the last successful analysis.")
    _metric_cards(result)
    with st.container(border=True):
        st.markdown("#### Analyst summary")
        st.write(result.human_readable_summary)
    _charts(result)
    if result.findings:
        _section_intro("Priority review", "Finding highlights", "Select an item to inspect its source-linked evidence.")
        for i, finding in enumerate(result.findings[:3]):
            _finding_card(finding, i)
    else:
        with st.container(border=True):
            st.success("No configured patterns matched. This does not establish that activity is safe.")
    _evaluation_summary(result)
    _stage_trace(result)


def _evaluation_summary(result: WorkflowResult) -> None:
    st.markdown("#### Evaluation")
    evaluation = result.evaluation
    if evaluation.status != "available" or evaluation.metrics is None:
        st.info(f"Evaluation unavailable: {evaluation.reason}")
        return
    st.caption("Toy transaction-level comparison against optional synthetic labels; not mule-account detection or real-world performance.")
    metrics = evaluation.metrics
    cols = st.columns(5)
    for col, key, title in zip(cols, ("precision", "recall", "specificity", "f1", "accuracy"),
                               ("Precision", "Recall", "Specificity", "F1", "Accuracy")):
        value = metrics.get(key)
        col.metric(title, "N/A" if value is None else f"{value:.1%}")
    with st.expander("Confusion counts and metric definition"):
        st.dataframe(pd.DataFrame([metrics["confusion_counts"]]), width="stretch", hide_index=True)
        st.caption(evaluation.reason)


def _evidence_table(result: WorkflowResult, finding) -> None:
    accepted = result.accepted_rows
    ids = set(finding.supporting_transaction_ids)
    if TRANSACTION_ID not in accepted:
        st.info("Accepted source records do not include transaction IDs.")
        return
    rows = accepted.loc[accepted[TRANSACTION_ID].isin(ids)].copy()
    columns = [c for c in (SOURCE_ROW, *REQUIRED_COLUMNS) if c in rows]
    shown_ids = set(rows[TRANSACTION_ID].tolist())
    st.dataframe(rows.loc[:, columns], width="stretch", hide_index=True)
    absent = ids - shown_ids
    if absent:
        st.warning("Evidence IDs missing from accepted records: " + ", ".join(sorted(map(str, absent))))
    if finding.rule_name == "substantial_onward_transfer":
        st.caption("This rule compares amounts over a recent window. Aggregate amounts do not prove the same funds moved onward.")


def _investigations(result: WorkflowResult) -> None:
    _section_intro("Investigation queue", "Pattern findings", "Search findings or filter by rule and account. Each finding remains a review lead, not a fraud decision.")
    if not result.findings:
        st.info("No findings are available for this analysis. Adjust thresholds only when justified, then explicitly run analysis again.")
        return
    rules = sorted({finding.rule_name for finding in result.findings})
    accounts = sorted({account for finding in result.findings for account in finding.involved_account_ids})
    c1, c2, c3 = st.columns([2,1,1])
    query = c1.text_input("Search finding ID, rule, or account", key="finding_search").strip().lower()
    selected_rule = c2.selectbox("Rule", ["All rules", *rules], format_func=lambda v: v.replace("_", " ").title())
    selected_account = c3.selectbox("Affected account", ["All accounts", *accounts])
    matches = [f for f in result.findings if
               (not query or query in f.finding_id.lower() or query in f.rule_name.lower() or any(query in str(a).lower() for a in f.involved_account_ids))
               and (selected_rule == "All rules" or f.rule_name == selected_rule)
               and (selected_account == "All accounts" or selected_account in f.involved_account_ids)]
    if not matches:
        st.info("No findings match those filters. Clear a filter or search term to see the full list.")
        return
    st.caption(f"{len(matches):,} finding(s) match the current filters · {len(result.findings):,} total in this run")
    lookup = {f.finding_id: f for f in matches}
    default_id = st.session_state.selected_finding if st.session_state.selected_finding in lookup else matches[0].finding_id
    selected_id = st.selectbox("Finding", list(lookup), index=list(lookup).index(default_id),
                                format_func=lambda fid: f"{lookup[fid].rule_name.replace('_',' ').title()} · {fid}")
    finding = lookup[selected_id]
    st.session_state.selected_finding = selected_id
    with st.container(border=True):
        st.markdown(f"<div class='sentinel-section-label'>{escape(finding.rule_name.replace('_',' ').title())}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='sentinel-finding-id'>{escape(str(finding.finding_id))}</div>", unsafe_allow_html=True)
        st.write(finding.explanation)
        st.warning(DISCLAIMER)
        a, b, c = st.columns(3)
        a.markdown("**Accounts**")
        a.write(", ".join(map(str, finding.involved_account_ids)))
        b.markdown("**Supporting transactions**")
        b.write(", ".join(map(str, finding.supporting_transaction_ids)))
        c.markdown("**Recorded times**")
        c.write(", ".join(map(str, finding.relevant_times)))
        st.caption(f"Time representation: {_time_unit_label(result.accepted_rows)}")
        with st.expander("Configured thresholds and measured values", expanded=True):
            l, r = st.columns(2)
            l.markdown("**Configured thresholds**")
            l.json(finding.configured_thresholds or {})
            r.markdown("**Measurements**")
            r.json(finding.measurements or {})
        st.markdown("#### Source evidence")
        _evidence_table(result, finding)
        st.markdown("#### Optional local AI explanation")
        st.caption(
            "Ollama must be running locally with qwen2.5:3b available. This sends only the selected "
            "finding's whitelisted evidence to localhost; the uploaded CSV and unrelated history are not sent."
        )
        explanation_key = f"llm_explanation_{finding.finding_id}"
        if st.button("Generate explanation with local Ollama", key=f"generate_{explanation_key}"):
            response = explain_finding_with_ollama(finding)
            st.session_state[explanation_key] = response
        response = st.session_state.get(explanation_key)
        if response is not None:
            if response.status == "generated":
                st.success("Generated by local Ollama from this finding's evidence.")
            else:
                st.info(response.detail or "Using the deterministic evidence-based explanation.")
            st.write(response.text)
            st.caption(DISCLAIMER)


def _network(result: WorkflowResult) -> None:
    _section_intro(
        "Account network",
        "Directed transaction explorer",
        "Hover transfers for transaction details. Select a finding to highlight its evidence, or focus an account to inspect its activity.",
    )
    summary = result.graph_summary
    account_metric, transfer_metric = st.columns(2)
    account_metric.metric("Accounts in accepted graph", f"{summary.account_count:,}")
    transfer_metric.metric("Accepted directed transactions", f"{summary.transaction_count:,}")
    if summary.transaction_count == 0:
        st.info("No accepted transfers are available to display.")
        return
    finding_options = {"No finding highlight": None, **{f.finding_id: f for f in result.findings}}
    chosen = st.selectbox("Highlight finding evidence", list(finding_options),
                          format_func=lambda s: s if s == "No finding highlight" else finding_options[s].rule_name.replace("_", " ").title())
    selected_finding = finding_options[chosen]
    accounts = sorted(result.graph.nodes, key=str)
    selected_account = st.selectbox("Focus account", ["No account focus", *accounts])
    highlighted_ids = selected_finding.supporting_transaction_ids if selected_finding else ()
    highlighted_accounts = selected_finding.involved_account_ids if selected_finding else ()
    focus = None if selected_account == "No account focus" else selected_account
    rendered = create_network_figure(result.graph, max_nodes=DISPLAY_NODE_LIMIT, max_edges=DISPLAY_EDGE_LIMIT,
                                     highlighted_transaction_ids=highlighted_ids,
                                     highlighted_accounts=highlighted_accounts, highlighted_account=focus)
    with st.container(border=True):
        st.plotly_chart(
            rendered.figure,
            width="stretch",
            config={"displayModeBar": True, "displaylogo": False, "scrollZoom": True},
        )
        st.caption(
            f"Showing {rendered.displayed_accounts:,} of {rendered.total_accounts:,} accounts and "
            f"{rendered.displayed_transactions:,} of {rendered.total_transactions:,} transfers. "
            "Node size reflects transaction degree; highlighted edges show selected evidence. "
            "Display caps affect this view only; analysis uses the full accepted graph."
        )
    if focus is not None:
        activity = summary.account_activity[focus]
        st.markdown(f"#### Account {focus}")
        x, y, z = st.columns(3)
        x.metric("Incoming transfers", activity.incoming_transactions)
        y.metric("Outgoing transfers", activity.outgoing_transactions)
        z.metric("Incoming / outgoing amount", f"{activity.incoming_amount:g} / {activity.outgoing_amount:g}")
        relevant = result.accepted_rows.loc[
            result.accepted_rows["sender_id"].eq(focus) | result.accepted_rows["receiver_id"].eq(focus)
        ]
        st.dataframe(relevant.loc[:, [c for c in (SOURCE_ROW, *REQUIRED_COLUMNS) if c in relevant]], width="stretch", hide_index=True)


def _rejection_reasons(rows: pd.DataFrame) -> pd.DataFrame:
    counts: Counter[str] = Counter()
    for reasons in rows.get("rejection_reasons", []):
        if isinstance(reasons, (tuple, list, set)):
            counts.update(map(str, reasons))
        elif reasons:
            counts.update(piece.strip() for piece in str(reasons).split("|"))
    return pd.DataFrame([{"reason": reason, "rows": count} for reason, count in sorted(counts.items())])


def _transactions(result: WorkflowResult | None) -> None:
    _section_intro("Record review", "Transactions and validation", "Search accepted records or inspect rejected rows with their original values and rejection reasons.")
    active = st.session_state.raw_dataframe
    if active is not None:
        with st.expander("Active source preview", expanded=result is None):
            _schema_help()
            preview = active.drop(columns=[LABEL], errors="ignore")
            st.dataframe(preview.head(8), width="stretch", hide_index=True)
    if result is None:
        st.info("Run analysis to browse accepted and rejected transaction records.")
        return
    accepted, rejected = result.accepted_rows.copy(), result.rejected_rows.copy()
    stats = st.columns(3)
    stats[0].metric("Accepted", f"{len(accepted):,}")
    stats[1].metric("Rejected", f"{len(rejected):,}")
    stats[2].metric("Graph transactions", f"{result.graph_summary.transaction_count:,}")
    q = st.text_input("Search transaction ID, sender, or receiver", key="transaction_search").strip().lower()
    type_values = sorted(set(accepted.get("transaction_type", pd.Series(dtype=str)).dropna().astype(str)))
    selected_type = st.selectbox("Transaction type", ["All types", *type_values])
    tab_ok, tab_rejected = st.tabs([f"Accepted · {len(accepted)}", f"Rejected · {len(rejected)}"])
    with tab_ok:
        st.markdown("#### Accepted records")
        filtered = accepted
        if selected_type != "All types" and "transaction_type" in filtered:
            filtered = filtered.loc[filtered.transaction_type.astype(str).eq(selected_type)]
        if q:
            searchable = [c for c in (TRANSACTION_ID, "sender_id", "receiver_id") if c in filtered]
            mask = pd.Series(False, index=filtered.index)
            for col in searchable:
                mask |= filtered[col].astype(str).str.lower().str.contains(q, regex=False)
            filtered = filtered.loc[mask]
        if filtered.empty:
            st.info("No accepted transactions match the current filters.")
        else:
            st.caption(f"Showing {min(len(filtered),500):,} of {len(filtered):,} matching records · evaluation labels hidden")
            st.dataframe(filtered.drop(columns=[LABEL], errors="ignore").head(500), width="stretch", hide_index=True)
        if selected_id := st.session_state.get("selected_finding"):
            finding = next((f for f in result.findings if f.finding_id == selected_id), None)
            if finding:
                with st.expander(f"Selected investigation evidence · {selected_id}"):
                    evidence_rows = accepted.loc[accepted[TRANSACTION_ID].isin(finding.supporting_transaction_ids)]
                    evidence_cols = [c for c in (SOURCE_ROW, *REQUIRED_COLUMNS) if c in evidence_rows]
                    st.dataframe(evidence_rows.loc[:, evidence_cols], width="stretch", hide_index=True)
    with tab_rejected:
        st.markdown("#### Rejected source rows")
        if rejected.empty:
            st.success("No rows were rejected.")
        else:
            if selected_type != "All types" and "transaction_type" in rejected:
                rejected = rejected.loc[rejected.transaction_type.astype(str).eq(selected_type)]
            reasons = _rejection_reasons(rejected)
            if not reasons.empty:
                st.dataframe(reasons, width="stretch", hide_index=True)
            if q:
                fields = [c for c in (TRANSACTION_ID, "sender_id", "receiver_id", "rejection_reasons") if c in rejected]
                mask = pd.Series(False, index=rejected.index)
                for col in fields:
                    mask |= rejected[col].astype(str).str.lower().str.contains(q, regex=False)
                rejected = rejected.loc[mask]
            cols = [c for c in (*REQUIRED_COLUMNS, SOURCE_ROW, "rejection_reasons") if c in rejected]
            st.dataframe(rejected.loc[:, cols].head(500), width="stretch", hide_index=True)
            st.caption(f"Showing at most 500 rejected rows; {len(rejected):,} match the search.")


def _methodology() -> None:
    _section_intro("How it works", "Methodology and safeguards", "A deterministic analysis workflow produces evidence-linked leads. The optional language model only rewrites the explanation for a finding already selected by an analyst.")
    with st.container(border=True):
        st.markdown("#### Deterministic workflow")
        st.markdown("`CSV → Coordinator → Validation → accepted/rejected rows → account graph → pattern rules → deterministic summary → post-detection evaluation`")
        st.caption("Each agent is a normal Python component exchanging structured results. LangGraph coordinates the fixed stage order; it does not call a model.")
    llm_col, privacy_col = st.columns(2)
    with llm_col.container(border=True):
        st.markdown("#### Optional local explanation")
        st.write("When an analyst selects a finding and presses the explanation button, UPI Sentinel sends only that finding's whitelisted evidence to local Ollama (`qwen2.5:3b`). The model cannot add, remove, reclassify, or change the severity of findings.")
        st.caption("If Ollama is unavailable or its reply is invalid, the app displays the deterministic evidence-based fallback.")
    with privacy_col.container(border=True):
        st.markdown("#### Data boundaries")
        st.write("Analysis stays in the local app. The optional Ollama request contains selected-finding evidence only; it does not include the uploaded CSV, unrelated transactions, evaluation labels, or source-row metadata.")
        st.caption("Do not treat generated narrative as verified fact. Compare it with the displayed evidence.")
    config = st.session_state.last_result_config or DEFAULT_CONFIG
    rows = st.session_state.last_result.accepted_rows if st.session_state.last_result is not None else pd.DataFrame()
    unit = _time_unit_label(rows)
    st.markdown("### Rule definitions and active thresholds")
    st.dataframe(pd.DataFrame([
        {"Rule": "Rapid transfer chain", "Definition": "A→B followed by B→C; strictly later", "Threshold": f"≤ {config.rapid_chain_window:g} {unit}"},
        {"Rule": "Shared intermediary", "Definition": f"At least {config.shared_intermediary_min_senders} distinct senders pay an account that sends onward", "Threshold": f"≤ {config.shared_intermediary_window:g} {unit}"},
        {"Rule": "Substantial onward transfer", "Definition": "Outgoing amount / aggregate recent incoming amount", "Threshold": f"≥ {config.onward_min_received_proportion:.0%} within {config.onward_window:g} {unit}"},
    ]), width="stretch", hide_index=True)
    st.caption(f"Thresholds above use {unit}. Numeric times use their index units; datetime values are compared in hours. Same-time, reversed, or mixed-type time pairs do not match.")
    st.markdown("### Agent responsibilities")
    st.dataframe(pd.DataFrame([
        ("Coordinator", "Orders the stages and returns one workflow result"),
        ("Validation", "Applies canonical schema rules and retains rejection reasons"),
        ("Network analysis", "Builds accepted-only directed multi-edges and activity summaries"),
        ("Pattern analysis", "Runs configured deterministic rules without labels"),
        ("Explanation", "Summarizes actual counts and finding categories"),
        ("Evaluation", "After detection, compares evidence-linked transactions with eligible labels"),
    ], columns=["Component", "Responsibility"]), width="stretch", hide_index=True)
    safeguard_left, safeguard_right = st.columns(2)
    with safeguard_left.container(border=True):
        st.markdown("#### Evaluation boundary")
        st.write("Optional transaction labels are excluded from the graph and rules. Eligible binary labels can support a toy transaction-level comparison only after findings are complete; they do not label mule accounts or establish real-world performance.")
    with safeguard_right.container(border=True):
        st.markdown("#### Limitations")
        st.markdown("- The bundled records are synthetic; no real UPI or PaySim integration is included.\n- Thresholds are illustrative and can match legitimate activity or miss relevant patterns.\n- Findings may overlap and share evidence.\n- Aggregate onward amounts do not prove that specific funds moved onward.\n- Graph display is capped; analysis uses the complete accepted graph.\n- Every finding requires human review and is not proof of fraud or mule activity.")


def main() -> None:
    page_icon = str(LOGO_PATH) if LOGO_PATH.is_file() else "U"
    st.set_page_config(page_title="UPI Sentinel | Transaction Intelligence", page_icon=page_icon, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    _initialize_state()
    logo_col, name_col = st.sidebar.columns([1, 3.4], vertical_alignment="center")
    with logo_col:
        if LOGO_PATH.is_file():
            st.image(str(LOGO_PATH), width=52)
        else:
            st.markdown("<div class='sentinel-mark'>US</div>", unsafe_allow_html=True)
    with name_col:
        st.markdown("<div class='sentinel-brand-title'>UPI Sentinel</div><div class='sentinel-brand-sub'>Transaction intelligence</div>", unsafe_allow_html=True)
    page = st.sidebar.radio("Workspace", PAGES, key="page", label_visibility="collapsed")
    st.sidebar.divider()
    _load_input_controls()
    st.sidebar.markdown("<div class='sentinel-note'>Local processing · Uploaded records stay in this app session.</div>", unsafe_allow_html=True)
    with st.sidebar.expander("Schema and privacy"):
        _schema_help()
    st.sidebar.divider()
    config = _analysis_form()
    result: WorkflowResult | None = st.session_state.last_result
    submitted = _header(result)
    _run_analysis_if_requested(submitted, config)
    result = st.session_state.last_result
    if st.session_state.input_error:
        st.error(st.session_state.input_error)
    if result is None:
        st.markdown("### Start a review")
        st.info("Load the bundled synthetic fixture or upload a compatible CSV. Review the source preview, then use **Run analysis** in the sidebar.")
        active = st.session_state.raw_dataframe
        if active is not None and page == "Overview":
            st.markdown("#### Source preview")
            _schema_help()
            st.caption(f"{st.session_state.input_source} · {len(active):,} rows · labels omitted")
            st.dataframe(active.drop(columns=[LABEL], errors="ignore").head(8), width="stretch", hide_index=True)
        if page == "Transactions" and st.session_state.raw_dataframe is not None:
            _transactions(None)
    elif page == "Overview":
        _overview(result)
    elif page == "Investigations":
        _investigations(result)
    elif page == "Network Explorer":
        _network(result)
    elif page == "Transactions":
        _transactions(result)
    else:
        _methodology()


if __name__ == "__main__":
    main()
