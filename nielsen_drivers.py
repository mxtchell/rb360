from __future__ import annotations
from types import SimpleNamespace

import pandas as pd
from skill_framework import SkillInput, SkillVisualization, skill, SkillParameter, SkillOutput, ParameterDisplayDescription
from skill_framework.preview import preview_skill
from skill_framework.skills import ExportData
from skill_framework.layouts import wire_layout

from ar_analytics import DriverAnalysis, DriverAnalysisTemplateParameterSetup, ArUtils
from ar_analytics.defaults import metric_driver_analysis_config, default_table_layout, get_table_layout_vars

import jinja2
import logging
import json

logger = logging.getLogger(__name__)

@skill(
    name="nielsen_drivers",
    llm_name="Nielsen Drivers",
    description="Analyze NIELSEN and SYNDICATED MARKET data drivers including retail sales, market share, distribution, pricing, and promotional metrics. Use this skill when users ask about Nielsen data drivers, what is driving sales, units, volume, distribution, TDPs, ACV, pricing changes, or promotional effectiveness. Identifies key contributors to metric changes across dimensions like brand, manufacturer, category, segment, channel, and retailer.",
    capabilities="Driver analysis for Nielsen metrics: dollar sales, unit sales, volume sales, TDPs, ACV distribution, price per unit, promo sales, non-promo sales, baseline sales, weighted/numeric distribution. Dimensional breakouts by brand, manufacturer, category, segment, channel, retailer. Y/Y and P/P growth comparisons.",
    limitations="Only works with Nielsen/syndicated data tables. Requires cpg_metric_groups and dimension_hierarchy in dataset misc_info. Not for internal finance/P&L data.",
    example_questions="What is driving dollar sales change vs last year? Show unit sales drivers by brand. What are the TDP drivers for Q2 2026? Why did volume change vs prior period? Break down distribution drivers by retailer. What is driving promo sales performance?",
    parameter_guidance=metric_driver_analysis_config.parameter_guidance,
    parameters=[
        SkillParameter(
            name="periods",
            constrained_to="date_filter",
            is_multi=True,
            description="If provided by the user, list time periods in a format 'q2 2023', '2021', 'jan 2023', 'mat nov 2022', 'mat q1 2021', 'ytd q4 2022', 'ytd 2023', 'ytd', 'mat', '<no_period_provided>' or '<since_launch>'. Use knowledge about today's date to handle relative periods and open ended periods. If given a range, for example 'last 3 quarters, 'between q3 2022 to q4 2023' etc, enumerate the range into a list of valid dates. Don't include natural language words or phrases, only valid dates like 'q3 2023', '2022', 'mar 2020', 'ytd sep 2021', 'mat q4 2021', 'ytd q1 2022', 'ytd 2021', 'ytd', 'mat', '<no_period_provided>' or '<since_launch>' etc."
        ),
        SkillParameter(
            name="metric",
            is_multi=False,
            constrained_to="metrics"
        ),
        SkillParameter(
            name="limit_n",
            description="limit the number of values by this number",
            default_value=10
        ),
        SkillParameter(
            name="breakouts",
            is_multi=True,
            constrained_to="dimensions",
            description="breakout dimension(s) for analysis."
        ),
        SkillParameter(
            name="growth_type",
            constrained_to=None,
            constrained_values=["Y/Y", "P/P"],
            description="Growth type either Y/Y or P/P",
            default_value="Y/Y"
        ),
        SkillParameter(
            name="other_filters",
            constrained_to="filters",
            is_multi=True
        ),
        SkillParameter(
            name="calculated_metric_filters",
            description='This parameter allows filtering based on computed values like growth, delta, or share. The computed values are only available for metrics selected for this analysis. The available computations are growth, delta and share. It accepts a list of conditions, where each condition is a dictionary with:  metric: The metric being filtered. computation: The computation (growth, delta, share) operator: The comparison operator (">", "<", ">=", "<=", "between", "=="). value: The numeric threshold for filtering. If using "between", provide a list [min, max]. scale: the scale of value (percentage, bps, absolute)'
        ),
        SkillParameter(
            name="include_sparklines",
            parameter_type="code",
            description="Toggle to enable / disable sparklines",
            constrained_values=["true", "false"],
            default_value="true"
        ),
        SkillParameter(
            name="max_prompt",
            parameter_type="prompt",
            description="Prompt being used for max response.",
            default_value=metric_driver_analysis_config.max_prompt
        ),
        SkillParameter(
            name="insight_prompt",
            parameter_type="prompt",
            description="Prompt being used for detailed insights.",
            default_value=metric_driver_analysis_config.insight_prompt
        ),
        SkillParameter(
            name="table_viz_layout",
            parameter_type="visualization",
            description="Table Viz Layout",
            default_value=default_table_layout
        )
    ]
)
def nielsen_drivers(parameters: SkillInput):
    param_dict = {"periods": [], "metric": "", "limit_n": 10, "breakouts": None, "growth_type": "Y/Y", "other_filters": [], "calculated_metric_filters": None, "include_sparklines":None}
    print(f"Skill received following parameters: {parameters.arguments}")
    # Update param_dict with values from parameters.arguments if they exist
    for key in param_dict:
        if hasattr(parameters.arguments, key) and getattr(parameters.arguments, key) is not None:
            param_dict[key] = getattr(parameters.arguments, key)

    env = SimpleNamespace(**param_dict)
    DriverAnalysisTemplateParameterSetup(env=env)
    env.da = DriverAnalysis.from_env(env=env)

    dfs = env.da.run_from_env()

    results = env.da.get_display_tables()

    tables = {
        "Metrics": results['viz_metric_df']
    }
    tables.update(results['viz_breakout_dfs'])

    param_info = [ParameterDisplayDescription(key=k, value=v) for k, v in env.da.paramater_display_infomation.items()]

    insights_dfs = [env.da.df_notes, env.da.breakout_facts, env.da.subject_fact.get("df", pd.DataFrame())]

    warning_messages = env.da.get_warning_messages()

    viz, insights, final_prompt, export_data = render_layout(tables,
                                                            env.da.title,
                                                            env.da.subtitle,
                                                            insights_dfs,
                                                            warning_messages,
                                                            parameters.arguments.max_prompt,
                                                            parameters.arguments.insight_prompt,
                                                            parameters.arguments.table_viz_layout)

    return SkillOutput(
        final_prompt=final_prompt,
        narrative=None,
        visualizations=viz,
        parameter_display_descriptions=param_info,
        followup_questions=[],
        export_data=[*[ExportData(name=name, data=df) for name, df in export_data.items()], *[ExportData(name=name + "- Raw", data=df) for name, df in dfs.items()]]
    )

def render_layout(tables, title, subtitle, insights_dfs, warnings, max_prompt, insight_prompt, viz_layout):
    facts = []
    for i_df in insights_dfs:
        facts.append(i_df.to_dict(orient='records'))

    insight_template = jinja2.Template(insight_prompt).render(**{"facts": facts})
    max_response_prompt = jinja2.Template(max_prompt).render(**{"facts": facts})

    # adding insights
    ar_utils = ArUtils()
    insights = ar_utils.get_llm_response(insight_template)
    viz_list = []
    export_data = {}

    general_vars = {"headline": title if title else "Total",
                    "sub_headline": subtitle if subtitle else "Driver Analysis",
                    "hide_growth_warning": False if warnings else True,
                    "exec_summary": insights if insights else "No Insights.",
                    "warning": warnings}

    for name, table in tables.items():
        export_data[name] = table
        hide_footer = True
        table_vars = get_table_layout_vars(table, ignore_cols=["followup_nl"], sparkline_col="sparkline", followup_col="followup_nl")
        table_vars["hide_footer"] = hide_footer
        rendered = wire_layout(json.loads(viz_layout), {**general_vars, **table_vars})
        viz_list.append(SkillVisualization(title=name, layout=rendered))

    return viz_list, insights, max_response_prompt, export_data

if __name__ == '__main__':
    skill_input: SkillInput = nielsen_drivers.create_input(
        arguments={
  "breakouts": [
    "BRAND"
  ],
  "metric": "total_value_sales",
  "periods": [
    "2025",
    "2026"
  ]
})
    out = nielsen_drivers(skill_input)
    preview_skill(nielsen_drivers, out)
