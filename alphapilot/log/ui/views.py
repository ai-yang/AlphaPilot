"""Log UI render functions."""

from __future__ import annotations

import re
import textwrap
from typing import TYPE_CHECKING

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from alphapilot.components.coder.factor_coder.evaluators import FactorSingleFeedback
from alphapilot.components.coder.factor_coder.factor import FactorFBWorkspace, FactorTask
from alphapilot.components.coder.model_coder.evaluators import ModelSingleFeedback
from alphapilot.components.coder.model_coder.model import ModelFBWorkspace, ModelTask
from alphapilot.core.proposal import Hypothesis, HypothesisFeedback
from alphapilot.log.ui.qlib_report_figure import report_figure
from alphapilot.log.ui.session import (
    LogSession,
    scenario_has_alpha158_baseline,
    scenario_is_mining,
    scenario_uses_qlib_metric_index,
)

if TYPE_CHECKING:
    pass


LOG_UI_CSS = """
<style>
.metric-card {
    border-radius: 10px;
    padding: 20px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    margin-bottom: 20px;
    background-color: transparent;
}
.metric-card:hover {
    box-shadow: 0 6px 8px rgba(0, 0, 0, 0.15);
    transform: translateY(-2px);
    transition: all 0.3s ease;
}
.metric-title {
    color: #1f77b4;
    font-size: 1.2em;
    font-weight: bold;
    margin-bottom: 10px;
    text-align: center;
}
.plotly-chart {
    width: 100%;
    height: 100%;
}
.ideas-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 20px;
    margin: 10px 0;
}
.idea-card {
    background-color: rgba(255, 255, 255, 0.05);
    border-radius: 10px;
    padding: 15px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    display: flex;
    flex-direction: column;
}
.idea-card:hover {
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.15);
    transform: translateY(-2px);
    transition: all 0.3s ease;
}
.idea-title {
    color: #1f77b4;
    font-size: 1.1em;
    font-weight: bold;
    margin-bottom: 8px;
    border-bottom: 2px solid #1f77b4;
    padding-bottom: 4px;
    text-align: center;
}
.idea-content {
    font-size: 0.95em;
    color: inherit;
    flex-grow: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 10px 5px;
}
[data-testid="column"] {
    min-height: 250px;
    display: flex;
    flex-direction: column;
}
[data-testid="column"] > div {
    height: 100%;
}
.factor-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 20px;
    margin: 10px 0;
}
.factor-card {
    background-color: rgba(255, 255, 255, 0.05);
    border-radius: 10px;
    padding: 20px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}
.factor-name {
    color: #2ca02c;
    font-size: 1.2em;
    font-weight: bold;
}
</style>
"""


def inject_log_ui_css() -> None:
    st.markdown(LOG_UI_CSS, unsafe_allow_html=True)




def evolving_feedback_window(wsf: FactorSingleFeedback | ModelSingleFeedback):
    if isinstance(wsf, FactorSingleFeedback):
        ffc, efc, cfc, vfc = st.tabs(
            ["**Final Feedback🏁**", "Execution Feedback🖥️", "Code Feedback📄", "Value Feedback🔢"]
        )
        with ffc:
            st.code(wsf.final_feedback, language="log")
        with efc:
            st.code(wsf.execution_feedback, language="log")
        with cfc:
            st.code(wsf.code_feedback, language="log")
        with vfc:
            st.code(wsf.value_feedback, language="log")
            
    elif isinstance(wsf, ModelSingleFeedback):
        ffc, efc, cfc, msfc, vfc = st.tabs(
            [
                "**Final Feedback🏁**",
                "Execution Feedback🖥️",
                "Code Feedback📄",
                "Model Shape Feedback📐",
                "Value Feedback🔢",
            ]
        )
        with ffc:
            st.markdown(wsf.final_feedback)
        with efc:
            st.code(wsf.execution_feedback, language="log")
        with cfc:
            st.markdown(wsf.code_feedback)
        with msfc:
            st.markdown(wsf.shape_feedback)
        with vfc:
            st.markdown(wsf.value_feedback)




def display_hypotheses(hypotheses: dict[int, Hypothesis], decisions: dict[int, bool], round: int = None):
    if round is not None:
        hypotheses = {round: hypotheses.get(round)}
        decisions = {round: decisions.get(round)}
    
    name_dict = {
        "hypothesis": "RD-Agent proposes the hypothesis⬇️",
        "concise_justification": "because the reason⬇️",
        "concise_observation": "based on the observation⬇️",
        "concise_knowledge": "Knowledge⬇️ gained after practice",
    }
    
    # if success_only:
    #     shd = {k: v.__dict__ for k, v in hypotheses.items() if decisions[k]}
    # else:
    shd = {k: v.__dict__ for k, v in hypotheses.items()}
    
    df = pd.DataFrame(shd).T
    
    if "concise_observation" in df.columns and "concise_justification" in df.columns:
        df["concise_observation"], df["concise_justification"] = df["concise_justification"], df["concise_observation"]
        df.rename(
            columns={"concise_observation": "concise_justification", "concise_justification": "concise_observation"},
            inplace=True,
        )
    
    if "reason" in df.columns:
        df.drop(["reason"], axis=1, inplace=True)
    
    if "concise_reason" in df.columns:
        df.drop(["concise_reason"], axis=1, inplace=True)
    
    df.columns = df.columns.map(lambda x: name_dict.get(x, x))
    
    def style_rows(row):
        if decisions[row.name]:
            return ["color: green;"] * len(row)
        return [""] * len(row)
    
    def style_columns(col):
        if col.name != name_dict.get("hypothesis", "hypothesis"):
            return ["font-style: italic;"] * len(col)
        return ["font-weight: bold;"] * len(col)
    
    st.markdown(df.style.apply(style_rows, axis=1).apply(style_columns, axis=0).to_html(), unsafe_allow_html=True)

# def display_hypotheses(hypotheses: dict[int, Hypothesis], decisions: dict[int, bool], success_only: bool = False):
#     name_dict = {
#         "hypothesis": "RD-Agent proposes the hypothesis⬇️",
#         "concise_justification": "because the reason⬇️",
#         "concise_observation": "based on the observation⬇️",
#         "concise_knowledge": "Knowledge⬇️ gained after practice",
#     }
#     if success_only:
#         shd = {k: v.__dict__ for k, v in hypotheses.items() if decisions[k]}
#     else:
#         shd = {k: v.__dict__ for k, v in hypotheses.items()}
#     df = pd.DataFrame(shd).T

#     if "concise_observation" in df.columns and "concise_justification" in df.columns:
#         df["concise_observation"], df["concise_justification"] = df["concise_justification"], df["concise_observation"]
#         df.rename(
#             columns={"concise_observation": "concise_justification", "concise_justification": "concise_observation"},
#             inplace=True,
#         )
#     if "reason" in df.columns:
#         df.drop(["reason"], axis=1, inplace=True)
#     if "concise_reason" in df.columns:
#         df.drop(["concise_reason"], axis=1, inplace=True)

#     df.columns = df.columns.map(lambda x: name_dict.get(x, x))

#     def style_rows(row):
#         if decisions[row.name]:
#             return ["color: green;"] * len(row)
#         return [""] * len(row)

#     def style_columns(col):
#         if col.name != name_dict.get("hypothesis", "hypothesis"):
#             return ["font-style: italic;"] * len(col)
#         return ["font-weight: bold;"] * len(col)

#     # st.dataframe(df.style.apply(style_rows, axis=1).apply(style_columns, axis=0))
#     st.markdown(df.style.apply(style_rows, axis=1).apply(style_columns, axis=0).to_html(), unsafe_allow_html=True)



def metrics_window(sess: LogSession, df: pd.DataFrame, R: int, C: int, *, height: int = 300, colors: list[str] = None):
    if len(df.columns) > R*C and R*C <= 8:
        df = df[[
            'IC', 'ICIR', 'Rank IC', 'Rank ICIR', 
            '1day.excess_return_with_cost.mean',
            '1day.excess_return_with_cost.annualized_return', 
            '1day.excess_return_with_cost.information_ratio', 
            '1day.excess_return_with_cost.max_drawdown'
                 ][:R*C]]
    
    # 去掉前缀
    df.columns = df.columns.str.replace('1day.excess_return_without_cost.', '')
    df.columns = df.columns.str.replace('1day.excess_return_with_cost.', '')
    
    # 创建子图
    fig = make_subplots(rows=R, cols=C, subplot_titles=df.columns)

    def hypothesis_hover_text(h: Hypothesis, d: bool = False):
        color = "green" if d else "black"
        text = h.hypothesis
        lines = textwrap.wrap(text, width=60)
        return f"<span style='color: {color};'>{'<br>'.join(lines)}</span>"
    
    hover_texts = [
        hypothesis_hover_text(sess.hypotheses[int(i[6:])], sess.h_decisions[int(i[6:])])
        for i in df.index[2:]
        if (i != "alpha158" and i.startswith('Round '))
    ]
    if sess.alpha158_metrics is not None:
        hover_texts = ["Baseline: alpha158"] + hover_texts

    # 使用自定义颜色
    custom_colors = colors if colors else ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']
    
    for ci, col in enumerate(df.columns):
        row = ci // C + 1
        col_num = ci % C + 1
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df[col],
                name=col,
                mode="lines+markers",
                connectgaps=True,
                marker=dict(
                    size=10, 
                    color=custom_colors[col_num-1],
                    line=dict(width=2, color='white')
                ),
                line=dict(width=3),
            ),
            row=row,
            col=col_num,
        )

    # 更新布局
    fig.update_layout(
        showlegend=False,
        height=height,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=40, r=40, t=60, b=40),
    )

    # 更新所有子图的样式
    for i in range(1, R + 1):
        for j in range(1, C + 1):
            fig.update_xaxes(
                showgrid=True,
                gridwidth=1,
                gridcolor='rgba(128,128,128,0.2)',
                tickvals=[df.index[0]] + list(df.index[1:]),
                ticktext=[f'<span style="color:#ff7f0e; font-weight:bold">{df.index[0]}</span>'] + list(df.index[1:]),
                row=i,
                col=j,
            )
            fig.update_yaxes(
                showgrid=True,
                gridwidth=1,
                gridcolor='rgba(128,128,128,0.2)',
                row=i,
                col=j,
            )

    # 使用卡片容器显示图表
    # st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    # st.markdown('<div class="metric-title">Performance Metrics', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    # st.markdown('</div>', unsafe_allow_html=True)



def summary_window(sess: LogSession) -> None:
    if scenario_is_mining(sess.scenario):
        st.header("Runing Summary📊", divider="rainbow", anchor="_summary")
        if sess.lround == 0:
            return
        with st.container():
            # TODO: not fixed height
            with st.container():
                bc, cc = st.columns([1, 1], vertical_alignment="center")
                with bc:
                    st.subheader("Metrics📈", anchor="_metrics")
                # with cc:
                #     show_true_only = st.toggle("successful hypotheses", value=False)

            # hypotheses_c, chart_c = st.columns([2, 3])
            chart_c = st.container(border=True)
            # hypotheses_c = st.container()

            # with hypotheses_c:
            #     st.subheader("Hypotheses🏅", anchor="_hypotheses")
            #     display_hypotheses(sess.hypotheses, sess.h_decisions, show_true_only)

            with chart_c:
                if scenario_has_alpha158_baseline(sess.scenario) and sess.alpha158_metrics is not None:
                    df = pd.DataFrame([sess.alpha158_metrics] + sess.metric_series)
                else:
                    df = pd.DataFrame(sess.metric_series)
                # if show_true_only and len(sess.hypotheses) >= len(sess.metric_series):
                #     if sess.alpha158_metrics is not None:
                #         selected = ["alpha158"] + [i for i in df.index[2:] if sess.h_decisions[int(i[6:])]]
                #     else:
                #         selected = [i for i in df.index if i == "Baseline" or sess.h_decisions[int(i[6:])]]
                #     df = df.loc[selected]
                if df.shape[0] == 1:
                    st.table(df.iloc[0])
                elif df.shape[0] > 1:
                    if df.shape[1] == 1:
                        fig = px.line(df, x=df.index, y=df.columns, markers=True)
                        fig.update_layout(xaxis_title="Loop Round", yaxis_title=None)
                        st.plotly_chart(fig)
                    else:
                        metrics_window(sess, df, 2, 4, height=600, colors=["red", "blue", "orange", "green"])




def tabs_hint():
    st.markdown(
        "<p style='font-size: small; color: #888888;'>You can navigate through the tabs using ⬅️ ➡️ or by holding Shift and scrolling with the mouse wheel🖱️.</p>",
        unsafe_allow_html=True,
    )



def tasks_window(tasks: list[FactorTask | ModelTask]):
    if isinstance(tasks[0], FactorTask):
        title = "Factor Agent⚙️"
        st.subheader(title, divider="blue", anchor="_factor")
        
        for ft in tasks:
            # 使用 Streamlit 容器创建卡片效果
            with st.container():
                # 添加一些上下边距
                # st.markdown("<br>", unsafe_allow_html=True)
                
                # 使用 expander 创建可展开的卡片
                with st.expander(f"### 🔍 **{ft.factor_name}**", expanded=True):
                    # Description 部分
                    st.markdown("##### Description")
                    st.code(ft.factor_description, language="plaintext")
                    
                    # Expression 部分
                    st.markdown("##### Expression")
                    # 使用 success 样式代替 info，显示为绿色背景
                    st.code(f"{ft.factor_expression}", language="python")
                
                # 添加分隔
                st.markdown("<br>", unsafe_allow_html=True)

    elif isinstance(tasks[0], ModelTask):
        st.markdown("**Model Tasks🚩**")
        tnames = [m.name for m in tasks]
        if sum(len(tn) for tn in tnames) > 100:
            tabs_hint()
        tabs = st.tabs(tnames)
        for i, mt in enumerate(tasks):
            with tabs[i]:
                st.markdown(f"**Model Type**: {mt.model_type}")
                st.markdown(f"**Description**: {mt.description}")
                st.latex("Formulation")
                st.latex(mt.formulation)

                mks = "| Variable | Description |\n| --- | --- |\n"
                if mt.variables:
                    for v, d in mt.variables.items():
                        mks += f"| ${v}$ | {d} |\n"
                    st.markdown(mks)



def research_window(sess: LogSession, round: int) -> None:
    with st.container(border=True):
        title = "Idea Agent💡"
        st.subheader(title, divider="blue", anchor="_idea")
        if scenario_is_mining(sess.scenario):
            # pdf image
            if pim := sess.msgs[round]["r.extract_factors_and_implement.load_pdf_screenshot"]:
                for i in range(min(2, len(pim))):
                    st.image(pim[i].content, use_container_width=True)

            # Hypothesis
            if hg := sess.msgs[round]["r.hypothesis generation"]:
                h: Hypothesis = hg[0].content
                
                # 创建网格布局的HTML
                cards_html = f"""
                <div class="ideas-grid">
                    <div class="idea-card">
                        <div class="idea-title">Hypothesis</div>
                        <div class="idea-content">{h.hypothesis}</div>
                    </div>
                    <div class="idea-card">
                        <div class="idea-title">Justification</div>
                        <div class="idea-content">{h.concise_justification}</div>
                    </div>
                    <div class="idea-card">
                        <div class="idea-title">Knowledge</div>
                        <div class="idea-content">{h.concise_knowledge}</div>
                    </div>
                    <div class="idea-card">
                        <div class="idea-title">Specification</div>
                        <div class="idea-content">By combining Intraday Price Velocity with volume and volatility data within a specific time window and analyzing their collective impact on short-term returns, we aim to enhance the model's predictive power and capture a more nuanced understanding of market dynamics, thereby increasing the accuracy of short-term return predictions.</div>
                    </div>
                </div>
                """
                
                st.markdown(cards_html, unsafe_allow_html=True)

            if eg := sess.msgs[round]["r.experiment generation"]:
                tasks_window(eg[0].content)




def feedback_window(sess: LogSession, round: int) -> None:
    if scenario_is_mining(sess.scenario):
        with st.container(border=True):
            st.subheader("Eval Agent📝", divider="orange", anchor="_eval")

            if sess.lround > 0 and scenario_uses_qlib_metric_index(sess.scenario):
                with st.expander("**Config**", expanded=True):
                    st.markdown(sess.scenario.experiment_setting, unsafe_allow_html=True)
            
            if fbr := sess.msgs[round]["ef.Quantitative Backtesting Chart"]:
                # st.markdown("<br><br>", unsafe_allow_html=True)
                st.markdown("#### PnL Figure📈")
                num_fig = len(sess.msgs[round]["ef.Quantitative Backtesting Chart"])
                if num_fig > 1:
                    for i in range(num_fig):
                        if i == 0:
                            # 使用 HTML 实现居中
                            st.markdown(
                                "<div style='text-align: center;'><strong>Baseline</strong></div>", 
                                unsafe_allow_html=True
                            )
                        fig = report_figure(fbr[i].content)
                        st.plotly_chart(fig)
                        if i < num_fig - 1:  # 在图表之间添加分割线
                            st.divider()
                else:
                    fig = report_figure(fbr[0].content)
                    st.plotly_chart(fig)
            if fbn := sess.msgs[round]["ef.runner result"]:
                # 添加空行
                st.markdown("<br><br>", unsafe_allow_html=True)
                st.markdown("#### Runner Result Backtesting Table 📌")
                # 获取结果数据
                runner_result_data = fbn[0].content
                result = runner_result_data.result
                # 将结果转化为 DataFrame
                result_df = pd.DataFrame(result) if isinstance(result, pd.Series) else pd.DataFrame(result)
                result_df = result_df.reset_index()
                result_df.columns = ["Metric", "Value"]
                
                # 添加Category列来分类指标
                def categorize_metric(metric):
                    if "without_cost" in metric:
                        return "Without Cost"
                    elif "with_cost" in metric:
                        return "With Cost"
                    else:
                        return "Other Metrics"
                
                result_df['Category'] = result_df['Metric'].apply(categorize_metric)
                
                # 清理Metric名称
                result_df['Metric'] = result_df['Metric'].apply(lambda x: x.split('.')[-1].replace('_', ' ').title())
                
                # 规范化指标名称
                metric_name_map = {
                    'Ic': 'IC',
                    'Icir': 'ICIR',
                    'Rank Ic': 'Rank IC',
                    'Rank Icir': 'Rank ICIR',
                    'Ffr': 'ffr',
                    'Pa': 'pa',
                    'Pos': 'pos'
                }
                result_df['Metric'] = result_df['Metric'].apply(lambda x: metric_name_map.get(x, x))
                
                # 设置表格样式
                st.markdown("""
                <style>
                .metric-table {
                    font-size: 1em;
                    border-collapse: collapse;
                    margin: 25px 0;
                    width: 100%;
                    box-shadow: 0 0 20px rgba(0, 0, 0, 0.1);
                    background-color: rgba(255, 255, 255, 0.05);
                    border-radius: 10px;
                    overflow: hidden;
                }
                .metric-table thead tr {
                    background-color: #1f77b4;
                    color: white;
                    text-align: left;
                    font-weight: bold;
                }
                .metric-table th,
                .metric-table td {
                    padding: 12px 15px;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                }
                .metric-table tbody tr {
                    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                }
                .metric-table tbody tr:nth-of-type(even) {
                    background-color: rgba(255, 255, 255, 0.05);
                }
                .metric-table tbody tr:last-of-type {
                    border-bottom: 2px solid #1f77b4;
                }
                .category-header {
                    background-color: rgba(31, 119, 180, 0.1) !important;
                    font-weight: bold;
                    color: #1f77b4;
                }
                </style>
                """, unsafe_allow_html=True)
                
                # 创建HTML表格
                table_html = '<table class="metric-table"><thead><tr><th>Category</th><th>Metric</th><th>Value</th></tr></thead><tbody>'
                
                # 按Category分组添加行
                for category in ['Without Cost', 'With Cost', 'Other Metrics']:
                    category_data = result_df[result_df['Category'] == category]
                    if not category_data.empty:
                        # 添加类别标题行
                        table_html += f'<tr class="category-header"><td colspan="3">{category}</td></tr>'
                        # 添加该类别的所有指标
                        for _, row in category_data.iterrows():
                            table_html += f'<tr><td></td><td>{row["Metric"]}</td><td>{row["Value"]:.4f}</td></tr>'
                
                table_html += '</tbody></table>'
                
                # 显示表格
                st.markdown(table_html, unsafe_allow_html=True)
            if fb := sess.msgs[round]["ef.feedback"]:
                st.markdown("<br><br>", unsafe_allow_html=True)
                st.markdown("#### Hypothesis Feedback🔍")
                h: HypothesisFeedback = fb[0].content
                
                # 使用网格布局显示反馈内容
                feedback_html = """
                <div class="ideas-grid">
                    <div class="idea-card">
                        <div class="idea-title">Observations</div>
                        <div class="idea-content">{}</div>
                    </div>
                    <div class="idea-card">
                        <div class="idea-title">Hypothesis Evaluation</div>
                        <div class="idea-content">{}</div>
                    </div>
                    <div class="idea-card">
                        <div class="idea-title">New Hypothesis</div>
                        <div class="idea-content">{}</div>
                    </div>
                    <div class="idea-card">
                        <div class="idea-title">Decision & Reason</div>
                        <div class="idea-content">Decision: {}<br><br>Reason: {}</div>
                    </div>
                </div>
                """.format(
                    h.observations,
                    h.hypothesis_evaluation,
                    h.new_hypothesis,
                    h.decision,
                    h.reason
                )
                st.markdown(feedback_html, unsafe_allow_html=True)

            # if isinstance(sess.scenario, KGScenario):
            #     if fbe := sess.msgs[round]["ef.runner result"]:
            #         submission_path = fbe[0].content.experiment_workspace.workspace_path / "submission.csv"
            #         st.markdown(
            #             f":green[**Exp Workspace**]: {str(fbe[0].content.experiment_workspace.workspace_path.absolute())}"
            #         )
            #         try:
            #             data = submission_path.read_bytes()
            #             st.download_button(
            #                 label="**Download** submission.csv",
            #                 data=data,
            #                 file_name="submission.csv",
            #                 mime="text/csv",
            #             )
            #         except Exception as e:
            #             st.markdown(f":red[**Download Button Error**]: {e}")



def evolving_window(sess: LogSession, round: int, *, key_prefix: str = "log_ui") -> None:
    title = "Debugging" if scenario_is_mining(sess.scenario) else "Development🛠️ (evolving coder)"
    st.subheader(title, divider="green", anchor="_debugging")

    # Evolving Status
    if sess.erounds[round] > 0:
        st.markdown("##### **☑️ Evolving Status**")
        es = sess.e_decisions[round]
        e_status_mks = "".join(f"| {ei} " for ei in range(1, sess.erounds[round] + 1)) + "|\n"
        e_status_mks += "|--" * sess.erounds[round] + "|\n"
        for ei, estatus in es.items():
            if not estatus:
                estatus = (0, 0, 0)
            e_status_mks += "| " + "🕙<br>" * estatus[2] + "✔️<br>" * estatus[0] + "❌<br>" * estatus[1] + " "
        e_status_mks += "|\n"
        st.markdown(e_status_mks, unsafe_allow_html=True)

    # Evolving Tabs
    if sess.erounds[round] > 0:
        if sess.erounds[round] > 1:
            evolving_round = st.radio(
                "**🔄️Evolving Rounds**",
                horizontal=True,
                options=range(1, sess.erounds[round] + 1),
                index=sess.erounds[round] - 1,
                key=f"{key_prefix}_show_eround_{round}",
            )
        else:
            evolving_round = 1

        ws: list[FactorFBWorkspace | ModelFBWorkspace] = sess.msgs[round]["d.evolving code"][
            evolving_round - 1
        ].content
        
        tab_names = [
            w.target_task.factor_name if isinstance(w.target_task, FactorTask) else w.target_task.name for w in ws
        ]
        if len(sess.msgs[round]["d.evolving feedback"]) >= evolving_round:
            for j in range(len(ws)):
                if sess.msgs[round]["d.evolving feedback"][evolving_round - 1].content[j].final_decision:
                    tab_names[j] += "✔️"
                else:
                    tab_names[j] += "❌"
                    
        if sum(len(tn) for tn in tab_names) > 100:
            tabs_hint()
            
        wtabs = st.tabs(tab_names)
        for j, w in enumerate(ws):
            with wtabs[j]:
                # if 'file_dict' in w.__dict__:
                #     for k, v in w.file_dict.items():
                #         with st.expander(f":green[`{k}`]", expanded=True):
                #             st.code(v, language="python")
                # continue


                # Evolving Code
                st.markdown(f"**Workspace Path**: {w.workspace_path}")
                expr = re.search(r"expr\s*=\s*\"(.*?)\"", w.code_dict['factor.py'], re.DOTALL).group(1)
                # 只展示表达式而不是整个代码块
                expression = w.target_task.factor_expression
                st.markdown(f"- ##### **Expression** ✨: \n```\n{expr}\n```")

                # Evolving Feedback
                if len(sess.msgs[round]["d.evolving feedback"]) >= evolving_round:
                    evolving_feedback_window(sess.msgs[round]["d.evolving feedback"][evolving_round - 1].content[j])

