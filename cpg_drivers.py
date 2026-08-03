"""
CPG/Nielsen Drivers - Metric Group Analysis
Shows related metrics together based on metric_hierarchy config
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from skill_framework import (
    SkillInput,
    SkillVisualization,
    skill,
    SkillParameter,
    SkillOutput,
    ParameterDisplayDescription
)
from skill_framework.skills import ExportData
from skill_framework.layouts import wire_layout
import os
try:
    from ar_analytics import ArUtils
    from ar_analytics.helpers.utils import get_dataset_id
except ImportError:
    ArUtils = None
    def get_dataset_id():
        return os.environ.get('DATASET_ID')
from answer_rocket import AnswerRocketClient
import jinja2
import json
import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta
from dateutil.parser import parse

logger = logging.getLogger(__name__)


# Default prompts
DEFAULT_MAX_PROMPT = """
Based on the following CPG performance analysis:
{% for fact in facts %}
- {{ fact }}
{% endfor %}

Provide a concise executive summary (2-3 sentences) highlighting the key drivers.
"""

DEFAULT_INSIGHT_PROMPT = """
Analyze the following CPG performance data:
{% for fact in facts %}
- {{ fact }}
{% endfor %}

Provide insights based ONLY on the facts above. Cover:
1. Overall performance vs prior period
2. Key dimensional drivers
3. Notable patterns

Format using bullet points. Keep to 150-200 words.
"""


# Summary table layout (no waterfall)
SUMMARY_LAYOUT = """
{
    "layoutJson": {
        "type": "Document",
        "style": {
            "backgroundColor": "#ffffff",
            "width": "100%",
            "height": "max-content",
            "padding": "15px",
            "gap": "20px"
        },
        "children": [
            {
                "name": "CardContainer0",
                "type": "CardContainer",
                "minHeight": "80px",
                "style": {
                    "border-radius": "12px",
                    "background": "#1e3a5f",
                    "padding": "15px"
                }
            },
            {
                "name": "Header0",
                "type": "Header",
                "text": "CPG Drivers",
                "style": {
                    "fontSize": "22px",
                    "fontWeight": "700",
                    "color": "#ffffff"
                },
                "parentId": "CardContainer0"
            },
            {
                "name": "Paragraph0",
                "type": "Paragraph",
                "text": "Performance Summary",
                "style": {
                    "fontSize": "14px",
                    "color": "#cbd5e1"
                },
                "parentId": "CardContainer0"
            },
            {
                "name": "DataTable0",
                "type": "DataTable",
                "columns": [],
                "data": [],
                "styles": {"td": {"vertical-align": "middle"}}
            }
        ]
    },
    "inputVariables": [
        {"name": "headline", "targets": [{"elementName": "Header0", "fieldName": "text"}]},
        {"name": "sub_headline", "targets": [{"elementName": "Paragraph0", "fieldName": "text"}]},
        {"name": "data", "targets": [{"elementName": "DataTable0", "fieldName": "data"}]},
        {"name": "col_defs", "targets": [{"elementName": "DataTable0", "fieldName": "columns"}]}
    ]
}
"""

# Horizontal bar layout for dimensional breakouts
BAR_LAYOUT = """
{
    "layoutJson": {
        "type": "Document",
        "style": {
            "backgroundColor": "#ffffff",
            "width": "100%",
            "height": "max-content",
            "padding": "15px",
            "gap": "20px"
        },
        "children": [
            {
                "name": "CardContainer0",
                "type": "CardContainer",
                "minHeight": "80px",
                "style": {
                    "border-radius": "12px",
                    "background": "#1e3a5f",
                    "padding": "15px"
                }
            },
            {
                "name": "Header0",
                "type": "Header",
                "text": "Dimensional Breakout",
                "style": {
                    "fontSize": "22px",
                    "fontWeight": "700",
                    "color": "#ffffff"
                },
                "parentId": "CardContainer0"
            },
            {
                "name": "Paragraph0",
                "type": "Paragraph",
                "text": "Variance by Dimension",
                "style": {
                    "fontSize": "14px",
                    "color": "#cbd5e1"
                },
                "parentId": "CardContainer0"
            },
            {
                "name": "HighchartsChart0",
                "type": "HighchartsChart",
                "minHeight": "400px",
                "options": {
                    "chart": {"type": "bar"},
                    "title": {"text": ""},
                    "xAxis": {"categories": []},
                    "yAxis": {"title": {"text": ""}},
                    "series": [],
                    "credits": {"enabled": false},
                    "legend": {"enabled": true, "align": "center", "verticalAlign": "bottom"},
                    "plotOptions": {"bar": {"dataLabels": {"enabled": false}}},
                    "tooltip": {"pointFormat": "<b>{series.name}</b>: {point.y:,.0f}"}
                }
            },
            {
                "name": "DataTable0",
                "type": "DataTable",
                "columns": [],
                "data": [],
                "styles": {"td": {"vertical-align": "middle"}}
            }
        ]
    },
    "inputVariables": [
        {"name": "headline", "targets": [{"elementName": "Header0", "fieldName": "text"}]},
        {"name": "sub_headline", "targets": [{"elementName": "Paragraph0", "fieldName": "text"}]},
        {"name": "chart_categories", "targets": [{"elementName": "HighchartsChart0", "fieldName": "options.xAxis.categories"}]},
        {"name": "chart_y_axis", "targets": [{"elementName": "HighchartsChart0", "fieldName": "options.yAxis"}]},
        {"name": "chart_data", "targets": [{"elementName": "HighchartsChart0", "fieldName": "options.series"}]},
        {"name": "data", "targets": [{"elementName": "DataTable0", "fieldName": "data"}]},
        {"name": "col_defs", "targets": [{"elementName": "DataTable0", "fieldName": "columns"}]}
    ]
}
"""


def format_number(value, decimals=1):
    """Format numbers with M/K abbreviations"""
    if pd.isna(value) or not isinstance(value, (int, float)):
        return str(value)

    abs_value = abs(value)

    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.{decimals}f}B"
    elif abs_value >= 1_000_000:
        return f"{value / 1_000_000:.{decimals}f}M"
    elif abs_value >= 1_000:
        return f"{value / 1_000:.{decimals}f}K"
    else:
        return f"{value:.{decimals}f}"


def format_display_name(name):
    """Format technical names to display names"""
    if not name:
        return name
    return name.replace('_', ' ').title()


class CPGDriversAnalysis:
    """CPG Drivers Analysis - Metric Group with Dimensional Breakouts"""

    def __init__(self, client, metric, period, comparison_type, breakout_dimensions=None,
                 top_n=10, other_filters=None, table_name=None, metric_group=None):
        self.client = client
        self.metric = metric
        self.period = period
        self.comparison_type = comparison_type
        self.breakout_dimensions = breakout_dimensions or []
        self.top_n = top_n
        self.other_filters = other_filters or []
        self.table_name = table_name
        self.metric_group = metric_group or [metric]  # List of metrics to show together

        self.current_df = None
        self.prior_df = None
        self.summary_results = {}
        self.breakout_results = {}
        self.facts = []

        # Get database_id and dataset_id
        self.dataset_id = get_dataset_id()
        dataset = self.client.data.get_dataset(dataset_id=self.dataset_id)
        self.database_id = dataset.database.database_id

        if not self.table_name:
            domain_entity = next((x for x in dataset.domain_objects if x.type == "factEntity"), None)
            if domain_entity and hasattr(domain_entity, 'db_table'):
                self.table_name = domain_entity.db_table
            else:
                self.table_name = 'nielsen_fact'

        logger.info(f"CPGDriversAnalysis initialized: metric={metric}, group={self.metric_group}")

    def build_filter_clause(self):
        """Build SQL WHERE clause from filters"""
        clauses = []
        if self.other_filters:
            for f in self.other_filters:
                dim = f.get('dim')
                op = f.get('op', '=')
                val = f.get('val')
                if dim and val:
                    if isinstance(val, list):
                        if len(val) == 1:
                            clauses.append(f"UPPER({dim}) {op} UPPER('{val[0]}')")
                        else:
                            val_str = ", ".join([f"UPPER('{v}')" for v in val])
                            clauses.append(f"UPPER({dim}) IN ({val_str})")
                    else:
                        clauses.append(f"UPPER({dim}) {op} UPPER('{val}')")
        return " AND " + " AND ".join(clauses) if clauses else ""

    def parse_period_to_date_range(self, period_str):
        """Convert period string to date range"""
        if not period_str:
            raise ValueError("Period is required")

        period_lower = period_str.lower().strip()

        if period_lower.startswith('q'):
            parts = period_str.split()
            quarter = int(parts[0][1])
            year = int(parts[1])
            quarter_map = {
                1: ('01-01', '03-31'),
                2: ('04-01', '06-30'),
                3: ('07-01', '09-30'),
                4: ('10-01', '12-31')
            }
            start_md, end_md = quarter_map[quarter]
            return f"{year}-{start_md}", f"{year}-{end_md}"

        try:
            parsed = parse(period_str, fuzzy=True)
            year = parsed.year
            month = parsed.month
            if month == 12:
                last_day = 31
            elif month in [4, 6, 9, 11]:
                last_day = 30
            elif month == 2:
                last_day = 29 if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0) else 28
            else:
                last_day = 31
            return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day}"
        except:
            return period_str, period_str

    def get_prior_period_range(self, start_date, end_date):
        """Calculate prior period based on comparison type"""
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')

        if self.comparison_type == 'Y/Y':
            prior_start = (start_dt - relativedelta(years=1)).strftime('%Y-%m-%d')
            prior_end = (end_dt - relativedelta(years=1)).strftime('%Y-%m-%d')
        else:
            months_diff = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month) + 1
            prior_start = (start_dt - relativedelta(months=months_diff)).strftime('%Y-%m-%d')
            prior_end = (end_dt - relativedelta(months=months_diff)).strftime('%Y-%m-%d')

        return prior_start, prior_end

    def query_data(self):
        """Query current and prior period data"""
        logger.info(f"Querying data for period: {self.period}")

        filter_clause = self.build_filter_clause()
        start_date, end_date = self.parse_period_to_date_range(self.period)
        prior_start, prior_end = self.get_prior_period_range(start_date, end_date)

        # Build metric columns for SELECT
        metric_cols = ', '.join([f'SUM({m}) as {m}' for m in self.metric_group])

        # Query current period
        current_query = f"""
        SELECT *
        FROM {self.table_name}
        WHERE week_ending_date BETWEEN '{start_date}' AND '{end_date}'
        {filter_clause}
        """

        result = self.client.data.execute_sql_query(
            database_id=self.database_id,
            sql_query=current_query,
            row_limit=100000
        )
        self.current_df = result.df if hasattr(result, 'df') else None

        # Query prior period
        prior_query = f"""
        SELECT *
        FROM {self.table_name}
        WHERE week_ending_date BETWEEN '{prior_start}' AND '{prior_end}'
        {filter_clause}
        """

        result = self.client.data.execute_sql_query(
            database_id=self.database_id,
            sql_query=prior_query,
            row_limit=100000
        )
        self.prior_df = result.df if hasattr(result, 'df') else None

        logger.info(f"Current rows: {len(self.current_df) if self.current_df is not None else 0}")
        logger.info(f"Prior rows: {len(self.prior_df) if self.prior_df is not None else 0}")

        if self.current_df is None or self.current_df.empty:
            raise ValueError(f"No data found for period {self.period}")

    def calculate_summary(self):
        """Calculate summary for all metrics in group"""
        logger.info("Calculating summary for metric group")

        for metric in self.metric_group:
            if metric in self.current_df.columns:
                curr_val = self.current_df[metric].sum()
                prior_val = self.prior_df[metric].sum() if self.prior_df is not None and metric in self.prior_df.columns else 0
                variance = curr_val - prior_val
                var_pct = (variance / prior_val * 100) if prior_val != 0 else 0

                self.summary_results[metric] = {
                    'current': curr_val,
                    'prior': prior_val,
                    'variance': variance,
                    'variance_pct': var_pct
                }

                # Add fact for primary metric
                if metric == self.metric:
                    self.facts.append(f"{format_display_name(metric)}: {format_number(curr_val)} ({var_pct:+.1f}% vs prior)")

        logger.info(f"Summary calculated for {len(self.summary_results)} metrics")

    def calculate_dimensional_breakout(self, dimension):
        """Calculate variance by dimension for primary metric"""
        logger.info(f"Calculating breakout for {dimension}")

        if dimension not in self.current_df.columns:
            logger.warning(f"Dimension {dimension} not found")
            return None

        if self.metric not in self.current_df.columns:
            logger.warning(f"Metric {self.metric} not found")
            return None

        curr_agg = self.current_df.groupby(dimension)[self.metric].sum().reset_index()
        curr_agg.columns = [dimension, 'current']

        if self.prior_df is not None and dimension in self.prior_df.columns:
            prior_agg = self.prior_df.groupby(dimension)[self.metric].sum().reset_index()
            prior_agg.columns = [dimension, 'prior']
            merged = pd.merge(curr_agg, prior_agg, on=dimension, how='outer').fillna(0)
        else:
            merged = curr_agg
            merged['prior'] = 0

        merged['variance'] = merged['current'] - merged['prior']
        merged['variance_pct'] = merged.apply(
            lambda r: (r['variance'] / r['prior'] * 100) if r['prior'] != 0 else 0, axis=1
        )
        merged = merged.sort_values('variance', ascending=False)

        self.breakout_results[dimension] = merged.head(self.top_n)

        # Add top contributor fact
        top = merged.head(1)
        if not top.empty:
            top_row = top.iloc[0]
            self.facts.append(f"Top {format_display_name(dimension)}: {top_row[dimension]} ({format_number(top_row['variance'])} variance)")

        return self.breakout_results[dimension]

    def get_summary_table(self):
        """Create summary table with all metrics in group"""
        if not self.summary_results:
            return None

        data = []
        comparison_label = 'Prior Year' if self.comparison_type == 'Y/Y' else 'Prior Period'

        for metric in self.metric_group:
            if metric in self.summary_results:
                r = self.summary_results[metric]
                # Highlight primary metric
                name = format_display_name(metric)
                if metric == self.metric:
                    name = f"**{name}**"
                data.append([
                    name,
                    format_number(r['current']),
                    format_number(r['prior']),
                    format_number(r['variance']),
                    f"{r['variance_pct']:+.1f}%"
                ])

        columns = [
            {'name': 'Metric'},
            {'name': 'Current'},
            {'name': comparison_label},
            {'name': 'Variance'},
            {'name': 'Var %'}
        ]

        return {'data': data, 'col_defs': columns}

    def create_bar_chart_data(self, dimension):
        """Create horizontal bar chart for dimension breakout"""
        if dimension not in self.breakout_results:
            return None

        df = self.breakout_results[dimension]
        metric_display = format_display_name(self.metric)

        return {
            'chart_categories': df[dimension].tolist(),
            'chart_data': [
                {
                    'name': 'Current',
                    'data': df['current'].tolist(),
                    'color': '#3b82f6'
                },
                {
                    'name': 'Prior',
                    'data': df['prior'].tolist(),
                    'color': '#94a3b8'
                }
            ],
            'chart_y_axis': {
                'title': {'text': metric_display},
                'labels': {'format': '{value:,.0f}'}
            }
        }

    def get_breakout_table(self, dimension):
        """Create table for dimension breakout"""
        if dimension not in self.breakout_results:
            return None

        df = self.breakout_results[dimension]
        comparison_label = 'Prior Year' if self.comparison_type == 'Y/Y' else 'Prior Period'
        metric_display = format_display_name(self.metric)

        data = []
        for _, row in df.iterrows():
            data.append([
                row[dimension],
                format_number(row['current']),
                format_number(row['prior']),
                format_number(row['variance']),
                f"{row['variance_pct']:+.1f}%"
            ])

        columns = [
            {'name': format_display_name(dimension)},
            {'name': f'Current {metric_display}'},
            {'name': f'{comparison_label} {metric_display}'},
            {'name': 'Variance'},
            {'name': 'Var %'}
        ]

        return {'data': data, 'col_defs': columns}

    def run_analysis(self):
        """Run complete analysis"""
        logger.info("Starting CPG drivers analysis")

        self.query_data()
        self.calculate_summary()

        for dim in self.breakout_dimensions:
            self.calculate_dimensional_breakout(dim)

        logger.info("Analysis complete")
        return self


def get_metric_group_from_config(client, metric):
    """Look up metric's peer group from dataset misc_info"""
    try:
        dataset_id = get_dataset_id()
        dataset = client.data.get_dataset(dataset_id=dataset_id)

        misc_info = {}
        if hasattr(dataset, 'misc_info') and dataset.misc_info:
            misc_info = dataset.misc_info
            if isinstance(misc_info, str):
                misc_info = json.loads(misc_info)

        # Look for metric_hierarchy
        metric_hierarchy = misc_info.get('metric_hierarchy', [])

        for item in metric_hierarchy:
            if item.get('metric') == metric:
                peers = item.get('peer_metrics', [])
                if peers:
                    # Return metric + its peers
                    return [metric] + [p for p in peers if p != metric]

        # If no group found, just return the metric
        return [metric]

    except Exception as e:
        logger.warning(f"Could not get metric group: {e}")
        return [metric]


@skill(
    name="CPG Drivers",
    llm_name="CPG Drivers - Metric Performance Analysis",
    description="Analyze CPG/Nielsen metric performance with related metrics shown together (based on metric_hierarchy config) and dimensional breakouts.",
    capabilities="Shows metric group performance together. Y/Y and P/P comparisons. Dimensional breakouts by brand, category, etc.",
    limitations="Requires metric_hierarchy in dataset config to group related metrics.",
    example_questions="What are the dollar sales drivers for Q1 2026? Show unit sales performance by brand. Analyze market share drivers.",
    parameter_guidance="Select a metric - related metrics from its group will be shown together. Select period and comparison type.",
    parameters=[
        SkillParameter(
            name="metric",
            constrained_to="metrics",
            is_multi=False,
            description="Primary metric to analyze. Related metrics from its group will also be shown."
        ),
        SkillParameter(
            name="period",
            constrained_to="date_filter",
            is_multi=False,
            description="Time period (e.g., 'Q1 2026', 'Jan 2026', '2026')"
        ),
        SkillParameter(
            name="comparison_type",
            constrained_to=None,
            constrained_values=["Y/Y", "P/P"],
            description="Comparison type: Y/Y (year-over-year) or P/P (period-over-period)",
            default_value="Y/Y"
        ),
        SkillParameter(
            name="breakout_dimensions",
            constrained_to="dimensions",
            is_multi=True,
            description="Dimensions for breakout analysis"
        ),
        SkillParameter(
            name="top_n",
            description="Number of top contributors to display",
            default_value=10
        ),
        SkillParameter(
            name="other_filters",
            constrained_to="filters",
            is_multi=True,
            description="Additional filters"
        ),
        SkillParameter(
            name="max_prompt",
            parameter_type="prompt",
            description="Prompt for executive summary",
            default_value=DEFAULT_MAX_PROMPT
        ),
        SkillParameter(
            name="insight_prompt",
            parameter_type="prompt",
            description="Prompt for detailed insights",
            default_value=DEFAULT_INSIGHT_PROMPT
        ),
        SkillParameter(
            name="table_name",
            parameter_type="code",
            description="Table name for data query",
            default_value=""
        )
    ]
)
def cpg_drivers(parameters: SkillInput):
    """Execute CPG Drivers Analysis"""

    logger.info(f"Skill received parameters: {parameters.arguments}")

    # Extract parameters
    metric = getattr(parameters.arguments, 'metric', None)
    period = getattr(parameters.arguments, 'period', None)
    comparison_type = getattr(parameters.arguments, 'comparison_type', 'Y/Y')
    breakout_dimensions = getattr(parameters.arguments, 'breakout_dimensions', None)
    top_n = int(getattr(parameters.arguments, 'top_n', 10) or 10)
    other_filters = getattr(parameters.arguments, 'other_filters', [])
    max_prompt = parameters.arguments.max_prompt
    insight_prompt = parameters.arguments.insight_prompt
    table_name = getattr(parameters.arguments, 'table_name', None)
    if table_name == "":
        table_name = None

    # Default breakout dimensions
    if not breakout_dimensions:
        breakout_dimensions = ['BRAND', 'CATEGORY', 'SEGMENT', 'MANUFACTURER']

    # Validate
    if not metric:
        return SkillOutput(
            final_prompt="Please select a metric to analyze.",
            narrative="**Missing Parameter**: Metric is required.",
            visualizations=[]
        )

    if not period:
        return SkillOutput(
            final_prompt="Please select a time period.",
            narrative="**Missing Parameter**: Period is required.",
            visualizations=[]
        )

    # Initialize client
    try:
        client = AnswerRocketClient()
        ar_utils = ArUtils() if ArUtils else None
    except Exception as e:
        logger.error(f"Failed to initialize client: {e}")
        return SkillOutput(
            final_prompt=f"Failed to initialize: {str(e)}"
        )

    # Get metric group from config
    metric_group = get_metric_group_from_config(client, metric)
    logger.info(f"Metric group for {metric}: {metric_group}")

    # Run analysis
    analysis = CPGDriversAnalysis(
        client=client,
        metric=metric,
        period=period,
        comparison_type=comparison_type,
        breakout_dimensions=breakout_dimensions,
        top_n=top_n,
        other_filters=other_filters,
        table_name=table_name,
        metric_group=metric_group
    )

    try:
        analysis.run_analysis()
    except ValueError as e:
        logger.error(f"Analysis failed: {e}")
        return SkillOutput(
            final_prompt=f"Analysis could not be completed: {str(e)}",
            narrative=f"**Error**: {str(e)}",
            visualizations=[]
        )

    # Generate insights
    insight_template = jinja2.Template(insight_prompt).render(facts=analysis.facts)
    max_prompt_rendered = jinja2.Template(max_prompt).render(facts=analysis.facts)

    try:
        if ar_utils:
            insights = ar_utils.get_llm_response(insight_template)
        else:
            insights = "Analysis complete. Review the summary and dimensional breakouts."
    except:
        insights = "Analysis complete. Review the summary and dimensional breakouts."

    # Create visualizations
    viz_list = []
    export_data = {}
    metric_display = format_display_name(metric)
    comparison_label = 'Prior Year' if comparison_type == 'Y/Y' else 'Prior Period'

    # Tab 1: Summary Table (no waterfall)
    summary_table = analysis.get_summary_table()
    if summary_table:
        layout_vars = {
            'headline': f'{metric_display} Drivers',
            'sub_headline': f'{period} vs {comparison_label}',
            **summary_table
        }
        rendered = wire_layout(json.loads(SUMMARY_LAYOUT), layout_vars)
        viz_list.append(SkillVisualization(title='Summary', layout=rendered))
        export_data['Summary'] = pd.DataFrame(summary_table['data'], columns=['Metric', 'Current', 'Prior', 'Variance', 'Var %'])

    # Breakout tabs
    for dim in breakout_dimensions:
        bar_data = analysis.create_bar_chart_data(dim)
        table_data = analysis.get_breakout_table(dim)

        if bar_data and table_data:
            dim_display = format_display_name(dim)
            layout_vars = {
                'headline': f'{dim_display} Breakout',
                'sub_headline': f'Top {top_n} by {metric_display} Variance',
                **bar_data,
                **table_data
            }
            rendered = wire_layout(json.loads(BAR_LAYOUT), layout_vars)
            viz_list.append(SkillVisualization(title=dim_display, layout=rendered))
            export_data[dim_display] = analysis.breakout_results[dim]

    # Parameter display
    param_info = [
        ParameterDisplayDescription(key="", value=f"Metric: {metric_display}"),
        ParameterDisplayDescription(key="", value=f"Period: {period}"),
        ParameterDisplayDescription(key="", value=f"Comparison: {comparison_type}"),
        ParameterDisplayDescription(key="", value=f"Dimensions: {', '.join([format_display_name(d) for d in breakout_dimensions])}")
    ]

    if len(metric_group) > 1:
        param_info.append(ParameterDisplayDescription(key="", value=f"Group: {', '.join([format_display_name(m) for m in metric_group])}"))

    return SkillOutput(
        final_prompt=max_prompt_rendered,
        narrative=insights,
        visualizations=viz_list,
        parameter_display_descriptions=param_info,
        export_data=[ExportData(name=name, data=df) for name, df in export_data.items()]
    )


if __name__ == '__main__':
    from skill_framework.preview import preview_skill

    skill_input = cpg_drivers.create_input(
        arguments={
            "metric": "dollar_sales",
            "period": "Q1 2026",
            "comparison_type": "Y/Y",
            "breakout_dimensions": ["BRAND", "CATEGORY"]
        }
    )
    out = cpg_drivers(skill_input)
    preview_skill(cpg_drivers, out)
