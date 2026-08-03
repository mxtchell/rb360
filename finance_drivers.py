"""
Reckitt Finance Drivers - Revenue-to-Margin Walkdown Analysis
Y/Y or P/P comparison (no budget/forecast data)
"""
from __future__ import annotations
from types import SimpleNamespace
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
Based on the following finance variance analysis:
{% for fact in facts %}
- {{ fact }}
{% endfor %}

Provide a concise executive summary (2-3 sentences) highlighting the most significant drivers of margin change.
"""

DEFAULT_INSIGHT_PROMPT = """
Analyze the following finance variance data:
{% for fact in facts %}
- {{ fact }}
{% endfor %}

Provide detailed insights based ONLY on the facts provided above.

Cover:
1. Overall margin performance vs prior period
2. Key drivers of revenue and margin change
3. Notable dimensional patterns worth monitoring

Format using bullet points only. Keep response to 150-200 words.
"""


# Waterfall layout for P&L walkdown
WATERFALL_LAYOUT = """
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
                "text": "Finance Drivers",
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
                "text": "Revenue-to-Margin Walkdown",
                "style": {
                    "fontSize": "14px",
                    "color": "#cbd5e1"
                },
                "parentId": "CardContainer0"
            },
            {
                "name": "HighchartsChart0",
                "type": "HighchartsChart",
                "minHeight": "500px",
                "options": {
                    "chart": {"type": "waterfall", "height": 500},
                    "title": {"text": ""},
                    "xAxis": {"categories": [], "title": {"text": ""}},
                    "yAxis": {"title": {"text": ""}},
                    "series": [],
                    "credits": {"enabled": false},
                    "legend": {"enabled": false},
                    "tooltip": {"pointFormat": "<b>{point.name}</b>: {point.formatted}"}
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
                    "tooltip": {"pointFormat": "<b>{series.name}</b>: ${point.y:,.0f}"}
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


def format_number(value, is_currency=True, decimals=1):
    """Format numbers with M/K abbreviations"""
    if pd.isna(value) or not isinstance(value, (int, float)):
        return str(value)

    abs_value = abs(value)

    if abs_value >= 1_000_000_000:
        formatted = f"{value / 1_000_000_000:.{decimals}f}B"
    elif abs_value >= 1_000_000:
        formatted = f"{value / 1_000_000:.{decimals}f}M"
    elif abs_value >= 1_000:
        formatted = f"{value / 1_000:.{decimals}f}K"
    else:
        formatted = f"{value:.{decimals}f}"

    if is_currency:
        formatted = f"${formatted}"

    return formatted


def format_display_name(name):
    """Format technical names to display names"""
    if not name:
        return name

    special_cases = {
        'gross_sales_act': 'Gross Sales',
        'net_revenue_act': 'Net Revenue',
        'gross_margin_act': 'Gross Margin',
        'power_brand_name': 'Brand',
        'category_description': 'Category',
        'sub_category_description': 'Sub-Category',
        'segment_description': 'Segment',
    }

    if name.lower() in special_cases:
        return special_cases[name.lower()]
    if name in special_cases:
        return special_cases[name]

    return name.replace('_', ' ').title()


class FinanceDriversAnalysis:
    """Finance Drivers Analysis - Revenue-to-Margin Walkdown"""

    def __init__(self, client, period, comparison_type, breakout_dimensions=None,
                 top_n=10, other_filters=None, table_name=None, breakout_metric='gross_margin_act'):
        self.client = client
        self.period = period
        self.comparison_type = comparison_type  # 'Y/Y' or 'P/P'
        self.breakout_dimensions = breakout_dimensions or []
        self.top_n = top_n
        self.other_filters = other_filters or []
        self.table_name = table_name
        self.breakout_metric = breakout_metric  # Metric to use for dimensional breakouts

        self.current_df = None
        self.prior_df = None
        self.walkdown_results = None
        self.breakout_results = {}
        self.facts = []

        # Get database_id and dataset_id
        self.dataset_id = get_dataset_id()
        dataset = self.client.data.get_dataset(dataset_id=self.dataset_id)
        self.database_id = dataset.database.database_id

        if not self.table_name:
            self.table_name = 'finance_data_poc_extract_clean'

        logger.info(f"FinanceDriversAnalysis initialized: database_id={self.database_id}, table={self.table_name}")

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

        # Handle quarters
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

        # Handle months
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
            # Prior year
            prior_start = (start_dt - relativedelta(years=1)).strftime('%Y-%m-%d')
            prior_end = (end_dt - relativedelta(years=1)).strftime('%Y-%m-%d')
        else:
            # Prior period (previous month/quarter)
            months_diff = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month) + 1
            prior_start = (start_dt - relativedelta(months=months_diff)).strftime('%Y-%m-%d')
            prior_end = (end_dt - relativedelta(months=months_diff)).strftime('%Y-%m-%d')

        return prior_start, prior_end

    def query_data(self):
        """Query current and prior period data"""
        logger.info(f"Querying data for period: {self.period}, comparison: {self.comparison_type}")

        filter_clause = self.build_filter_clause()
        start_date, end_date = self.parse_period_to_date_range(self.period)
        prior_start, prior_end = self.get_prior_period_range(start_date, end_date)

        logger.info(f"Current period: {start_date} to {end_date}")
        logger.info(f"Prior period: {prior_start} to {prior_end}")

        # Query current period
        current_query = f"""
        SELECT *
        FROM {self.table_name}
        WHERE date BETWEEN '{start_date}' AND '{end_date}'
        {filter_clause}
        """

        result = self.client.data.execute_sql_query(
            database_id=self.database_id,
            sql_query=current_query,
            row_limit=50000
        )
        self.current_df = result.df if hasattr(result, 'df') else None

        # Query prior period
        prior_query = f"""
        SELECT *
        FROM {self.table_name}
        WHERE date BETWEEN '{prior_start}' AND '{prior_end}'
        {filter_clause}
        """

        result = self.client.data.execute_sql_query(
            database_id=self.database_id,
            sql_query=prior_query,
            row_limit=50000
        )
        self.prior_df = result.df if hasattr(result, 'df') else None

        logger.info(f"Current rows: {len(self.current_df) if self.current_df is not None else 0}")
        logger.info(f"Prior rows: {len(self.prior_df) if self.prior_df is not None else 0}")

        if self.current_df is None or self.current_df.empty:
            raise ValueError(f"No data found for period {self.period}")
        if self.prior_df is None or self.prior_df.empty:
            raise ValueError(f"No prior period data found for comparison")

    def calculate_walkdown(self):
        """Calculate Revenue-to-Margin walkdown with variances"""
        logger.info("Calculating walkdown")

        # Current period totals
        curr_gross_sales = self.current_df['gross_sales_act'].sum()
        curr_net_revenue = self.current_df['net_revenue_act'].sum()
        curr_gross_margin = self.current_df['gross_margin_act'].sum()
        curr_trade_ded = curr_gross_sales - curr_net_revenue
        curr_cogs = curr_net_revenue - curr_gross_margin

        # Prior period totals
        prior_gross_sales = self.prior_df['gross_sales_act'].sum()
        prior_net_revenue = self.prior_df['net_revenue_act'].sum()
        prior_gross_margin = self.prior_df['gross_margin_act'].sum()
        prior_trade_ded = prior_gross_sales - prior_net_revenue
        prior_cogs = prior_net_revenue - prior_gross_margin

        # Variances
        var_gross_sales = curr_gross_sales - prior_gross_sales
        var_trade_ded = curr_trade_ded - prior_trade_ded
        var_net_revenue = curr_net_revenue - prior_net_revenue
        var_cogs = curr_cogs - prior_cogs
        var_gross_margin = curr_gross_margin - prior_gross_margin

        self.walkdown_results = {
            'current': {
                'gross_sales': curr_gross_sales,
                'trade_deductions': curr_trade_ded,
                'net_revenue': curr_net_revenue,
                'cogs': curr_cogs,
                'gross_margin': curr_gross_margin
            },
            'prior': {
                'gross_sales': prior_gross_sales,
                'trade_deductions': prior_trade_ded,
                'net_revenue': prior_net_revenue,
                'cogs': prior_cogs,
                'gross_margin': prior_gross_margin
            },
            'variance': {
                'gross_sales': var_gross_sales,
                'trade_deductions': var_trade_ded,
                'net_revenue': var_net_revenue,
                'cogs': var_cogs,
                'gross_margin': var_gross_margin
            }
        }

        # Add facts
        pct_gross_sales = (var_gross_sales / prior_gross_sales * 100) if prior_gross_sales else 0
        pct_margin = (var_gross_margin / prior_gross_margin * 100) if prior_gross_margin else 0

        self.facts.append(f"Gross Sales: {format_number(curr_gross_sales)} ({pct_gross_sales:+.1f}% vs prior)")
        self.facts.append(f"Net Revenue: {format_number(curr_net_revenue)} ({(var_net_revenue/prior_net_revenue*100) if prior_net_revenue else 0:+.1f}% vs prior)")
        self.facts.append(f"Gross Margin: {format_number(curr_gross_margin)} ({pct_margin:+.1f}% vs prior)")
        self.facts.append(f"Margin rate: {(curr_gross_margin/curr_net_revenue*100) if curr_net_revenue else 0:.1f}% (vs {(prior_gross_margin/prior_net_revenue*100) if prior_net_revenue else 0:.1f}% prior)")

        logger.info(f"Walkdown calculated: {self.walkdown_results}")
        return self.walkdown_results

    def calculate_dimensional_breakout(self, dimension, metric='gross_margin_act'):
        """Calculate variance by dimension"""
        logger.info(f"Calculating breakout for {dimension}")

        if dimension not in self.current_df.columns:
            logger.warning(f"Dimension {dimension} not found in data")
            return None

        # Aggregate by dimension
        curr_agg = self.current_df.groupby(dimension)[metric].sum().reset_index()
        curr_agg.columns = [dimension, 'current']

        prior_agg = self.prior_df.groupby(dimension)[metric].sum().reset_index()
        prior_agg.columns = [dimension, 'prior']

        merged = pd.merge(curr_agg, prior_agg, on=dimension, how='outer').fillna(0)
        merged['variance'] = merged['current'] - merged['prior']
        merged['variance_pct'] = merged.apply(
            lambda r: (r['variance'] / r['prior'] * 100) if r['prior'] != 0 else 0, axis=1
        )
        merged = merged.sort_values('variance', ascending=False)

        self.breakout_results[dimension] = merged.head(self.top_n)

        # Add top contributor facts
        top = merged.head(1)
        if not top.empty:
            top_row = top.iloc[0]
            self.facts.append(f"Top {format_display_name(dimension)}: {top_row[dimension]} ({format_number(top_row['variance'])} variance)")

        return self.breakout_results[dimension]

    def create_waterfall_chart_data(self):
        """Create waterfall chart for P&L walkdown showing variance bridge"""
        if not self.walkdown_results:
            return None

        var = self.walkdown_results['variance']
        prior = self.walkdown_results['prior']
        curr = self.walkdown_results['current']

        # Waterfall: Prior GM -> +/- components -> Current GM
        categories = [
            'Prior Gross Margin',
            'Gross Sales Δ',
            'Trade Deductions Δ',
            'COGS Δ',
            'Current Gross Margin'
        ]

        def get_color(val):
            return '#4ade80' if val >= 0 else '#ef4444'

        data_series = [{
            'name': 'Gross Margin Walkdown',
            'data': [
                {
                    'name': 'Prior Gross Margin',
                    'y': prior['gross_margin'] / 1_000_000,
                    'color': '#3b82f6',
                    'formatted': format_number(prior['gross_margin'])
                },
                {
                    'name': 'Gross Sales Δ',
                    'y': var['gross_sales'] / 1_000_000,
                    'color': get_color(var['gross_sales']),
                    'formatted': format_number(var['gross_sales'])
                },
                {
                    'name': 'Trade Deductions Δ',
                    'y': -var['trade_deductions'] / 1_000_000,  # Negative = good for margin
                    'color': get_color(-var['trade_deductions']),
                    'formatted': format_number(-var['trade_deductions'])
                },
                {
                    'name': 'COGS Δ',
                    'y': -var['cogs'] / 1_000_000,  # Negative = good for margin
                    'color': get_color(-var['cogs']),
                    'formatted': format_number(-var['cogs'])
                },
                {
                    'name': 'Current Gross Margin',
                    'isSum': True,
                    'y': curr['gross_margin'] / 1_000_000,
                    'color': '#3b82f6',
                    'formatted': format_number(curr['gross_margin'])
                }
            ],
            'dataLabels': {
                'enabled': True,
                'format': '{point.formatted}',
                'style': {'fontWeight': 'bold', 'color': '#000', 'textOutline': 'none'}
            }
        }]

        return {
            'chart_categories': categories,
            'chart_data': data_series,
            'chart_y_axis': {
                'title': {'text': 'Gross Margin ($M)'},
                'labels': {'format': '${value:,.0f}M'}
            }
        }

    def create_bar_chart_data(self, dimension, metric_display='Gross Margin'):
        """Create horizontal bar chart for dimension breakout"""
        if dimension not in self.breakout_results:
            return None

        df = self.breakout_results[dimension]

        return {
            'chart_categories': df[dimension].tolist(),
            'chart_data': [
                {
                    'name': 'Current',
                    'data': [x / 1_000_000 for x in df['current'].tolist()],
                    'color': '#3b82f6'
                },
                {
                    'name': 'Prior',
                    'data': [x / 1_000_000 for x in df['prior'].tolist()],
                    'color': '#94a3b8'
                }
            ],
            'chart_y_axis': {
                'title': {'text': f'{metric_display} ($M)'},
                'labels': {'format': '${value:,.1f}M'}
            }
        }

    def get_summary_table(self):
        """Create summary table for walkdown"""
        if not self.walkdown_results:
            return None

        curr = self.walkdown_results['current']
        prior = self.walkdown_results['prior']
        var = self.walkdown_results['variance']

        rows = [
            ('Gross Sales', curr['gross_sales'], prior['gross_sales'], var['gross_sales']),
            ('  Trade Deductions', curr['trade_deductions'], prior['trade_deductions'], var['trade_deductions']),
            ('Net Revenue', curr['net_revenue'], prior['net_revenue'], var['net_revenue']),
            ('  COGS', curr['cogs'], prior['cogs'], var['cogs']),
            ('Gross Margin', curr['gross_margin'], prior['gross_margin'], var['gross_margin']),
        ]

        data = []
        for name, curr_val, prior_val, var_val in rows:
            var_pct = (var_val / prior_val * 100) if prior_val != 0 else 0
            data.append([
                name,
                format_number(curr_val),
                format_number(prior_val),
                format_number(var_val),
                f"{var_pct:+.1f}%"
            ])

        comparison_label = 'Prior Year' if self.comparison_type == 'Y/Y' else 'Prior Period'
        columns = [
            {'name': ''},
            {'name': 'Current'},
            {'name': comparison_label},
            {'name': 'Variance'},
            {'name': 'Var %'}
        ]

        return {'data': data, 'col_defs': columns}

    def get_breakout_table(self, dimension, metric_display='Gross Margin'):
        """Create table for dimension breakout"""
        if dimension not in self.breakout_results:
            return None

        df = self.breakout_results[dimension]

        data = []
        for _, row in df.iterrows():
            data.append([
                row[dimension],
                format_number(row['current']),
                format_number(row['prior']),
                format_number(row['variance']),
                f"{row['variance_pct']:+.1f}%"
            ])

        comparison_label = 'Prior Year' if self.comparison_type == 'Y/Y' else 'Prior Period'
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
        logger.info("Starting finance drivers analysis")

        self.query_data()
        self.calculate_walkdown()

        for dim in self.breakout_dimensions:
            self.calculate_dimensional_breakout(dim, metric=self.breakout_metric)

        logger.info("Analysis complete")
        return self


@skill(
    name="Finance Drivers",
    llm_name="Finance Drivers - Revenue to Margin Walkdown",
    description="Analyze finance drivers showing the Revenue-to-Margin walkdown (Gross Sales -> Trade Deductions -> Net Revenue -> COGS -> Gross Margin) with Y/Y or P/P comparison and dimensional breakouts by the selected metric.",
    capabilities="Revenue-to-margin walkdown analysis. Y/Y and P/P comparisons. Dimensional breakouts by brand, category, segment, country. User can select which metric to analyze in breakouts.",
    limitations="Requires gross_sales_act, net_revenue_act, gross_margin_act columns.",
    example_questions="What are the margin drivers for Q1 2026? Show net revenue drivers by brand. Analyze gross sales variance vs prior year.",
    parameter_guidance="Select a metric for breakout analysis, a period, and comparison type (Y/Y or P/P). The walkdown always shows the full P&L context, but breakout tabs use your selected metric.",
    parameters=[
        SkillParameter(
            name="metric",
            constrained_to=None,
            constrained_values=["gross_margin_act", "net_revenue_act", "gross_sales_act"],
            description="Metric to analyze in dimensional breakouts: Gross Margin, Net Revenue, or Gross Sales",
            default_value="gross_margin_act"
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
def finance_drivers(parameters: SkillInput):
    """Execute Finance Drivers Analysis"""

    logger.info(f"Skill received parameters: {parameters.arguments}")

    # Extract parameters
    metric = getattr(parameters.arguments, 'metric', 'gross_margin_act') or 'gross_margin_act'
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

    # Map metric to display name
    metric_display_map = {
        'gross_margin_act': 'Gross Margin',
        'net_revenue_act': 'Net Revenue',
        'gross_sales_act': 'Gross Sales'
    }
    metric_display = metric_display_map.get(metric, 'Gross Margin')

    # Default breakout dimensions if not specified
    if not breakout_dimensions:
        breakout_dimensions = ['power_brand_name', 'category_description', 'segment_description', 'country']

    # Validate
    if not period:
        return SkillOutput(
            final_prompt="Please select a time period (e.g., Q1 2026, Jan 2026).",
            narrative="**Missing Parameter**: Period is required.",
            visualizations=[],
            warnings=["Period parameter is required"]
        )

    # Initialize client
    try:
        client = AnswerRocketClient()
        ar_utils = ArUtils() if ArUtils else None
    except Exception as e:
        logger.error(f"Failed to initialize client: {e}")
        return SkillOutput(
            final_prompt=f"Failed to initialize: {str(e)}",
            warnings=[str(e)]
        )

    # Run analysis
    analysis = FinanceDriversAnalysis(
        client=client,
        period=period,
        comparison_type=comparison_type,
        breakout_dimensions=breakout_dimensions,
        top_n=top_n,
        other_filters=other_filters,
        table_name=table_name,
        breakout_metric=metric
    )

    try:
        analysis.run_analysis()
    except ValueError as e:
        logger.error(f"Analysis failed: {e}")
        return SkillOutput(
            final_prompt=f"Analysis could not be completed: {str(e)}",
            narrative=f"**Error**: {str(e)}",
            visualizations=[],
            warnings=[str(e)]
        )

    # Generate insights
    insight_template = jinja2.Template(insight_prompt).render(facts=analysis.facts)
    max_prompt_rendered = jinja2.Template(max_prompt).render(facts=analysis.facts)

    try:
        if ar_utils:
            insights = ar_utils.get_llm_response(insight_template)
        else:
            insights = "Finance analysis complete. Review the walkdown and dimensional breakouts."
    except:
        insights = "Finance analysis complete. Review the walkdown and dimensional breakouts."

    # Create visualizations
    viz_list = []
    export_data = {}

    # Tab 1: Waterfall + Summary Table
    waterfall_data = analysis.create_waterfall_chart_data()
    summary_table = analysis.get_summary_table()

    if waterfall_data and summary_table:
        comparison_label = 'Prior Year' if comparison_type == 'Y/Y' else 'Prior Period'
        layout_vars = {
            'headline': 'Finance Drivers',
            'sub_headline': f'{period} vs {comparison_label}',
            **waterfall_data,
            **summary_table
        }
        rendered = wire_layout(json.loads(WATERFALL_LAYOUT), layout_vars)
        viz_list.append(SkillVisualization(title='Margin Walkdown', layout=rendered))
        export_data['Summary'] = pd.DataFrame(summary_table['data'], columns=['Metric', 'Current', 'Prior', 'Variance', 'Var %'])

    # Breakout tabs
    for dim in breakout_dimensions:
        bar_data = analysis.create_bar_chart_data(dim, metric_display)
        table_data = analysis.get_breakout_table(dim, metric_display)

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

    return SkillOutput(
        final_prompt=max_prompt_rendered,
        narrative=insights,
        visualizations=viz_list,
        parameter_display_descriptions=param_info,
        export_data=[ExportData(name=name, data=df) for name, df in export_data.items()]
    )


if __name__ == '__main__':
    # Local testing
    from skill_framework.preview import preview_skill

    skill_input = finance_drivers.create_input(
        arguments={
            "period": "Q1 2026",
            "comparison_type": "Y/Y",
            "breakout_dimensions": ["power_brand_name", "category_description"]
        }
    )
    out = finance_drivers(skill_input)
    preview_skill(finance_drivers, out)
