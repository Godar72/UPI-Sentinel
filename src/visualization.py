"""Plotly network visualization helpers for the Streamlit dashboard."""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import plotly.graph_objects as go


@dataclass
class NetworkFigure:
    figure: go.Figure
    displayed_accounts: int
    total_accounts: int
    displayed_transactions: int
    total_transactions: int


def create_network_figure(
    graph: nx.MultiDiGraph,
    max_nodes: int = 60,
    max_edges: int = 100,
    highlighted_transaction_ids: tuple[str, ...] | list[str] = (),
    highlighted_account: str | None = None,
    highlighted_accounts: tuple[str, ...] | list[str] = (),
) -> NetworkFigure:
    """Render accepted directed transfers with optional evidence highlighting.

    Node size represents directed transaction degree. The visualization is
    deterministically capped; this does not alter the graph or analysis.
    """
    if max_nodes < 1 or max_edges < 1:
        raise ValueError("max_nodes and max_edges must be positive")

    total_nodes, total_edges = graph.number_of_nodes(), graph.number_of_edges()
    ranked_nodes = sorted(graph.nodes, key=lambda node: (-graph.degree(node), str(node)))
    displayed_nodes = ranked_nodes[:max_nodes]
    node_set = set(displayed_nodes)
    edge_records = [
        (sender, receiver, key, data)
        for sender, receiver, key, data in graph.edges(keys=True, data=True)
        if sender in node_set and receiver in node_set
    ]
    edge_records.sort(key=lambda edge: str(edge[3].get("transaction_id", edge[2])))
    edge_records = edge_records[:max_edges]
    positions_graph = nx.Graph()
    positions_graph.add_nodes_from(displayed_nodes)
    positions_graph.add_edges_from((s, r) for s, r, _, _ in edge_records)
    positions = nx.spring_layout(positions_graph, seed=23, weight=None) if displayed_nodes else {}
    selected_ids = set(highlighted_transaction_ids)
    selected_accounts = set(highlighted_accounts)
    if highlighted_account is not None:
        selected_accounts.add(highlighted_account)

    base_x: list[float | None] = []
    base_y: list[float | None] = []
    selected_x: list[float | None] = []
    selected_y: list[float | None] = []
    midpoint_x: list[float] = []
    midpoint_y: list[float] = []
    hover: list[str] = []
    marker_colors: list[str] = []
    annotations = []
    for sender, receiver, key, data in edge_records:
        x0, y0 = positions[sender]
        x1, y1 = positions[receiver]
        tx_id = data.get("transaction_id", key)
        is_selected = tx_id in selected_ids or (
            highlighted_account is not None and highlighted_account in (sender, receiver)
        )
        xs, ys = (selected_x, selected_y) if is_selected else (base_x, base_y)
        xs.extend([float(x0), float(x1), None])
        ys.extend([float(y0), float(y1), None])
        midpoint_x.append(float((x0 + x1) / 2))
        midpoint_y.append(float((y0 + y1) / 2))
        hover.append(
            f"{sender} → {receiver}<br>Transaction: {tx_id}"
            f"<br>Amount: {data.get('amount', 'unavailable')}"
            f"<br>Type: {data.get('transaction_type', 'unavailable')}"
            f"<br>Time: {data.get('time', 'unavailable')}"
        )
        marker_colors.append("#56e0c0" if is_selected else "#506b83")
        annotations.append({
            "x": float(x1), "y": float(y1), "ax": float(x0), "ay": float(y0),
            "xref": "x", "yref": "y", "axref": "x", "ayref": "y",
            "showarrow": True, "arrowhead": 2, "arrowsize": 1,
            "arrowwidth": 1.4 if is_selected else 1,
            "arrowcolor": "#56e0c0" if is_selected else "#526b80",
            "opacity": .9 if is_selected else .38,
        })

    figure = go.Figure()
    figure.add_trace(go.Scatter(x=base_x, y=base_y, mode="lines",
                                line={"width": 1, "color": "#526b80"},
                                hoverinfo="skip", name="Other transfers"))
    if selected_x:
        figure.add_trace(go.Scatter(x=selected_x, y=selected_y, mode="lines",
                                    line={"width": 2.8, "color": "#56e0c0"},
                                    hoverinfo="skip", name="Selected evidence"))
    if edge_records:
        figure.add_trace(go.Scatter(
            x=midpoint_x, y=midpoint_y, mode="markers",
            marker={"size": 9, "color": marker_colors, "opacity": .78}, text=hover,
            hovertemplate="%{text}<extra></extra>", name="Transaction evidence",
        ))

    degrees = [int(graph.degree(node)) for node in displayed_nodes]
    figure.add_trace(go.Scatter(
        x=[float(positions[node][0]) for node in displayed_nodes],
        y=[float(positions[node][1]) for node in displayed_nodes],
        mode="markers+text",
        textposition="top center", textfont={"size": 10, "color": "#e1eaf1"},
        marker={
            "size": [max(12, min(28, 12 + degree * 1.5)) for degree in degrees],
            "color": ["#f0bd68" if node in selected_accounts else "#51cdb5" for node in displayed_nodes],
            "line": {"width": [3 if node in selected_accounts else 1.2 for node in displayed_nodes], "color": "#dce8ef"},
        },
        text=[str(node) if degrees[index] >= 3 or node in selected_accounts else ""
              for index, node in enumerate(displayed_nodes)],
        hovertemplate="Account: %{customdata[1]}<br>Transactions: %{customdata[0]}<extra></extra>",
        customdata=[[degree, str(node)] for node, degree in zip(displayed_nodes, degrees)],
        name="Accounts",
    ))
    figure.update_layout(
        height=560, margin={"l": 12, "r": 12, "t": 12, "b": 12},
        paper_bgcolor="#0f1b27", plot_bgcolor="#0f1b27",
        showlegend=bool(selected_x), legend={"font": {"color": "#d5e0e9"}, "bgcolor": "rgba(0,0,0,0)"},
        hovermode="closest", annotations=annotations,
        xaxis={"visible": False, "showgrid": False, "zeroline": False},
        yaxis={"visible": False, "showgrid": False, "zeroline": False},
    )
    return NetworkFigure(figure, len(displayed_nodes), total_nodes, len(edge_records), total_edges)
