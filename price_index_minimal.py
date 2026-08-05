"""
Reckitt Price Index Analysis - Minimal Test
"""
from skill_framework import (
    SkillInput,
    SkillVisualization,
    skill,
    SkillParameter,
    SkillOutput,
    ParameterDisplayDescription
)
from skill_framework.layouts import wire_layout
import os
import json
import logging
import pandas as pd
import numpy as np
from datetime import datetime

try:
    from ar_analytics import ArUtils
    from ar_analytics.helpers.utils import get_dataset_id
except ImportError:
    ArUtils = None
    def get_dataset_id():
        return os.environ.get('DATASET_ID')
from answer_rocket import AnswerRocketClient

logger = logging.getLogger(__name__)

def build_filter_clause(filters):
    """Build SQL WHERE clause from filter list.

    Maps dimension names to proper table aliases:
    - Product dimensions (BRAND, MARKET, CATEGORY, etc.) -> p.
    - Fact dimensions (week_ending_date, etc.) -> f.
    """
    if not filters:
        return ""

    # Dimensions that come from product table (p.)
    product_dims = {'BRAND', 'CATEGORY', 'SUBCATEGORY', 'SUB_CATEGORY', 'SEGMENT',
                    'MANUFACTURER', 'ITEM_CODE', 'UPC', 'PRODUCT_TAG'}

    # Dimensions that come from market table (m.)
    market_dims = {'MARKET', 'MARKET_NAME_LONG', 'MARKET_NAME_SHORT', 'NIELSEN_RETAILER',
                   'CHANNEL', 'SUB_CHANNEL', 'MARKET_TYPE', 'MARKET_TAG'}

    clauses = []
    for f in filters:
        dim = f.get('dim', '')
        vals = f.get('val', [])
        if dim and vals:
            # Determine table prefix
            dim_upper = dim.upper()
            if dim_upper in product_dims:
                col_ref = f"p.{dim}"
            elif dim_upper in market_dims:
                col_ref = f"m.{dim}"
            else:
                col_ref = f"f.{dim}"

            escaped_vals = [v.replace("'", "''") for v in vals]
            if len(vals) == 1:
                clauses.append(f"UPPER({col_ref}) = UPPER('{escaped_vals[0]}')")
            else:
                val_str = ", ".join([f"UPPER('{v}')" for v in escaped_vals])
                clauses.append(f"UPPER({col_ref}) IN ({val_str})")
    return " AND ".join(clauses)


def query_data(client, database_id, filters=None):
    """Query Nielsen data for price index calculation."""
    filter_clause = build_filter_clause(filters) if filters else ""
    where_clause = f"AND {filter_clause}" if filter_clause else ""

    query = f"""
    SELECT
        p.BRAND,
        f.week_ending_date,
        SUM(f.TOTAL_VALUE_SALES) as total_sales,
        SUM(f.TOTAL_UNIT_SALES) as total_units
    FROM poc_analytics.reckitt.nielsen_fact AS f
    LEFT JOIN poc_analytics.reckitt.nielsen_product AS p
        ON f.PRODUCT_TAG = p.ITEM_CODE
    LEFT JOIN poc_analytics.reckitt.nielsen_market AS m
        ON f.MARKET_TAG = m.MARKET_TAG
    WHERE 1=1
    {where_clause}
    GROUP BY p.BRAND, f.week_ending_date
    ORDER BY f.week_ending_date
    """

    result = client.data.execute_sql_query(
        database_id=database_id,
        sql_query=query,
        row_limit=100000
    )

    df = result.df if hasattr(result, 'df') else None
    if df is not None and not df.empty:
        df = df.copy()
        df['week_ending_date'] = pd.to_datetime(df['week_ending_date'])
        return df
    return pd.DataFrame()


def calculate_competitor_metrics(df):
    """Calculate YoY metrics for all brands for threat analysis."""
    if df.empty:
        return pd.DataFrame()

    df = df.copy()

    # Get date range
    max_date = df['week_ending_date'].max()
    min_date = df['week_ending_date'].min()

    # Define current and prior periods (roughly split in half)
    mid_date = min_date + (max_date - min_date) / 2

    current_df = df[df['week_ending_date'] > mid_date]
    prior_df = df[df['week_ending_date'] <= mid_date]

    # Aggregate by brand for each period
    def agg_period(period_df):
        return period_df.groupby('BRAND').agg({
            'total_sales': 'sum',
            'total_units': 'sum'
        }).reset_index()

    current_agg = agg_period(current_df)
    prior_agg = agg_period(prior_df)

    # Calculate totals for share
    current_total_sales = current_agg['total_sales'].sum()
    prior_total_sales = prior_agg['total_sales'].sum()
    current_total_units = current_agg['total_units'].sum()

    # Merge and calculate metrics
    metrics = current_agg.merge(prior_agg, on='BRAND', suffixes=('_curr', '_prior'), how='outer').fillna(0)

    # Calculate derived metrics
    metrics['current_price'] = metrics['total_sales_curr'] / metrics['total_units_curr'].replace(0, np.nan)
    metrics['prior_price'] = metrics['total_sales_prior'] / metrics['total_units_prior'].replace(0, np.nan)
    metrics['price_change'] = ((metrics['current_price'] - metrics['prior_price']) / metrics['prior_price'].replace(0, np.nan) * 100).fillna(0)

    metrics['volume_growth'] = ((metrics['total_units_curr'] - metrics['total_units_prior']) / metrics['total_units_prior'].replace(0, np.nan) * 100).fillna(0)
    metrics['sales_growth'] = ((metrics['total_sales_curr'] - metrics['total_sales_prior']) / metrics['total_sales_prior'].replace(0, np.nan) * 100).fillna(0)

    metrics['current_share'] = (metrics['total_sales_curr'] / current_total_sales * 100) if current_total_sales > 0 else 0
    metrics['prior_share'] = (metrics['total_sales_prior'] / prior_total_sales * 100) if prior_total_sales > 0 else 0
    metrics['share_change'] = metrics['current_share'] - metrics['prior_share']

    # Threat score: volume growth (good for them) minus price change (cutting price = threat)
    metrics['threat_score'] = (metrics['volume_growth'] * 0.7) - (metrics['price_change'] * 0.3)

    return metrics


def calculate_price_index(df, target_brand, time_granularity='month'):
    """Calculate price index for target brand vs category average."""
    if df.empty:
        return pd.DataFrame()

    df = df.copy()

    # Aggregate to time granularity
    if time_granularity == 'month':
        df['period'] = df['week_ending_date'].dt.to_period('M').astype(str)
    elif time_granularity == 'quarter':
        df['period'] = df['week_ending_date'].dt.to_period('Q').astype(str)
    else:
        df['period'] = df['week_ending_date'].dt.strftime('%Y-%m-%d')

    # Calculate avg price per brand per period
    brand_prices = df.groupby(['BRAND', 'period']).agg({
        'total_sales': 'sum',
        'total_units': 'sum'
    }).reset_index()
    brand_prices['avg_price'] = brand_prices['total_sales'] / brand_prices['total_units']

    # Calculate category avg price per period
    category_avg = df.groupby('period').agg({
        'total_sales': 'sum',
        'total_units': 'sum'
    }).reset_index()
    category_avg['category_avg_price'] = category_avg['total_sales'] / category_avg['total_units']

    # Merge and calculate index
    brand_prices = brand_prices.merge(
        category_avg[['period', 'category_avg_price']],
        on='period'
    )
    brand_prices['price_index'] = (brand_prices['avg_price'] / brand_prices['category_avg_price']) * 100

    return brand_prices


PRICE_INDEX_LAYOUT = """
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
                "name": "HeaderCard",
                "type": "CardContainer",
                "minHeight": "80px",
                "style": {
                    "borderRadius": "12px",
                    "background": "linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%)",
                    "padding": "20px"
                }
            },
            {
                "name": "Header0",
                "type": "Header",
                "text": "Price Index Analysis",
                "style": {
                    "fontSize": "24px",
                    "fontWeight": "700",
                    "color": "#ffffff",
                    "margin": "0"
                },
                "parentId": "HeaderCard"
            },
            {
                "name": "SubHeader",
                "type": "Paragraph",
                "text": "Brand Price vs Category Average (100 = Category Avg)",
                "style": {
                    "fontSize": "14px",
                    "color": "#cbd5e1",
                    "marginTop": "5px"
                },
                "parentId": "HeaderCard"
            },
            {
                "name": "KPIContainer",
                "type": "FlexContainer",
                "style": {
                    "display": "flex",
                    "gap": "20px",
                    "flexWrap": "wrap",
                    "marginTop": "10px"
                }
            },
            {
                "name": "KPI1",
                "type": "CardContainer",
                "style": {
                    "padding": "20px",
                    "background": "#f8fafc",
                    "borderRadius": "12px",
                    "minWidth": "180px",
                    "boxShadow": "0 1px 3px rgba(0,0,0,0.1)"
                },
                "parentId": "KPIContainer"
            },
            {
                "name": "KPI1_Label",
                "type": "Paragraph",
                "text": "Current Index",
                "style": {"fontSize": "13px", "color": "#64748b", "fontWeight": "500"},
                "parentId": "KPI1"
            },
            {
                "name": "KPI1_Value",
                "type": "Paragraph",
                "text": "100",
                "style": {"fontSize": "32px", "fontWeight": "bold", "color": "#1e3a5f", "marginTop": "5px"},
                "parentId": "KPI1"
            },
            {
                "name": "KPI2",
                "type": "CardContainer",
                "style": {
                    "padding": "20px",
                    "background": "#f8fafc",
                    "borderRadius": "12px",
                    "minWidth": "180px",
                    "boxShadow": "0 1px 3px rgba(0,0,0,0.1)"
                },
                "parentId": "KPIContainer"
            },
            {
                "name": "KPI2_Label",
                "type": "Paragraph",
                "text": "Index Change",
                "style": {"fontSize": "13px", "color": "#64748b", "fontWeight": "500"},
                "parentId": "KPI2"
            },
            {
                "name": "KPI2_Value",
                "type": "Paragraph",
                "text": "+0.0 pts",
                "style": {"fontSize": "32px", "fontWeight": "bold", "color": "#22c55e", "marginTop": "5px"},
                "parentId": "KPI2"
            },
            {
                "name": "KPI3",
                "type": "CardContainer",
                "style": {
                    "padding": "20px",
                    "background": "#f8fafc",
                    "borderRadius": "12px",
                    "minWidth": "180px",
                    "boxShadow": "0 1px 3px rgba(0,0,0,0.1)"
                },
                "parentId": "KPIContainer"
            },
            {
                "name": "KPI3_Label",
                "type": "Paragraph",
                "text": "Category Avg Price",
                "style": {"fontSize": "13px", "color": "#64748b", "fontWeight": "500"},
                "parentId": "KPI3"
            },
            {
                "name": "KPI3_Value",
                "type": "Paragraph",
                "text": "$0.00",
                "style": {"fontSize": "32px", "fontWeight": "bold", "color": "#1e3a5f", "marginTop": "5px"},
                "parentId": "KPI3"
            },
            {
                "name": "KPI4",
                "type": "CardContainer",
                "style": {
                    "padding": "20px",
                    "background": "#f8fafc",
                    "borderRadius": "12px",
                    "minWidth": "180px",
                    "boxShadow": "0 1px 3px rgba(0,0,0,0.1)"
                },
                "parentId": "KPIContainer"
            },
            {
                "name": "KPI4_Label",
                "type": "Paragraph",
                "text": "Brand Avg Price",
                "style": {"fontSize": "13px", "color": "#64748b", "fontWeight": "500"},
                "parentId": "KPI4"
            },
            {
                "name": "KPI4_Value",
                "type": "Paragraph",
                "text": "$0.00",
                "style": {"fontSize": "32px", "fontWeight": "bold", "color": "#1e3a5f", "marginTop": "5px"},
                "parentId": "KPI4"
            },
            {
                "name": "ChartCard",
                "type": "CardContainer",
                "style": {
                    "padding": "20px",
                    "background": "#ffffff",
                    "borderRadius": "12px",
                    "boxShadow": "0 1px 3px rgba(0,0,0,0.1)",
                    "marginTop": "10px"
                }
            },
            {
                "name": "ChartTitle",
                "type": "Paragraph",
                "text": "Price Index Trend",
                "style": {"fontSize": "16px", "fontWeight": "600", "color": "#1e3a5f", "marginBottom": "15px"},
                "parentId": "ChartCard"
            },
            {
                "name": "HighchartsChart0",
                "type": "HighchartsChart",
                "minHeight": "350px",
                "parentId": "ChartCard",
                "options": {
                    "chart": {"type": "line", "height": 350},
                    "title": {"text": ""},
                    "xAxis": {"categories": [], "title": {"text": ""}},
                    "yAxis": {
                        "title": {"text": "Price Index"},
                        "plotLines": [{
                            "value": 100,
                            "color": "#94a3b8",
                            "dashStyle": "Dash",
                            "width": 2,
                            "label": {"text": "Category Avg (100)", "align": "right"}
                        }]
                    },
                    "series": [],
                    "credits": {"enabled": false},
                    "legend": {"enabled": true},
                    "tooltip": {"shared": true}
                }
            }
        ]
    },
    "inputVariables": [
        {"name": "headline", "targets": [{"elementName": "Header0", "fieldName": "text"}]},
        {"name": "kpi1_value", "targets": [{"elementName": "KPI1_Value", "fieldName": "text"}]},
        {"name": "kpi2_value", "targets": [{"elementName": "KPI2_Value", "fieldName": "text"}]},
        {"name": "kpi2_color", "targets": [{"elementName": "KPI2_Value", "fieldName": "style.color"}]},
        {"name": "kpi3_value", "targets": [{"elementName": "KPI3_Value", "fieldName": "text"}]},
        {"name": "kpi4_value", "targets": [{"elementName": "KPI4_Value", "fieldName": "text"}]},
        {"name": "chart_categories", "targets": [{"elementName": "HighchartsChart0", "fieldName": "options.xAxis.categories"}]},
        {"name": "chart_series", "targets": [{"elementName": "HighchartsChart0", "fieldName": "options.series"}]}
    ]
}
"""


@skill(
    name="Pricing Analysis",
    llm_name="Pricing_Competitive_Analysis",
    description="ALWAYS use this skill for ANY question about pricing, price index, price trends, competitive pricing, price positioning, price premium, price gaps, or how a brand's price compares to category or competition. This is the go-to skill for all pricing-related questions.",
    capabilities="Calculates price index (brand price / category avg * 100). Shows price index trend over time. Identifies competitor threats based on price and volume changes. Visualizes competitive threat matrix with bubble chart. Shows top competitor threats with sales, share, volume, and price changes.",
    limitations="Requires sales and units data to calculate average price.",
    example_questions="""How is Lysol's price index trending? What is Lysol's price vs category average? Is Lysol gaining or losing price premium? How does Lysol pricing compare to competition? Which competitors are cutting prices? Show me competitive pricing threats. What's the price gap between Lysol and private label? Are competitors undercutting us on price?""",
    parameter_guidance="Select a brand to analyze pricing for. Choose time granularity (week/month/quarter) and time period. Add market or category filters as needed.",
    parameters=[
        SkillParameter(
            name="target_brand",
            description="The brand to analyze price index for",
            default_value="LYSOL"
        ),
        SkillParameter(
            name="time_granularity",
            constrained_values=["week", "month", "quarter"],
            description="Time granularity for trend analysis",
            default_value="month"
        ),
        SkillParameter(
            name="period",
            constrained_to="date_filter",
            is_multi=False,
            description="Time period to analyze"
        ),
        SkillParameter(
            name="other_filters",
            constrained_to="filters",
            is_multi=True,
            description="Additional filters"
        )
    ]
)
def price_index_minimal(parameters: SkillInput):
    """Calculate and visualize price index for brand vs category."""

    # Extract parameters
    target_brand = getattr(parameters.arguments, 'target_brand', 'LYSOL') or 'LYSOL'
    time_granularity = getattr(parameters.arguments, 'time_granularity', 'month') or 'month'
    period = getattr(parameters.arguments, 'period', 'last 52 weeks')
    other_filters = getattr(parameters.arguments, 'other_filters', []) or []

    # Initialize client
    client = AnswerRocketClient()
    dataset_id = get_dataset_id()

    # Get database_id from dataset
    dataset = client.data.get_dataset(dataset_id=dataset_id)
    database_id = dataset.database.database_id

    # Query data
    df = query_data(client, database_id, other_filters)

    if df.empty:
        return SkillOutput(
            final_prompt=f"No data found for {target_brand} price index analysis.",
            narrative=f"## {target_brand} Price Index Analysis\n\nNo data available for the selected filters.",
            visualizations=[]
        )

    # Calculate price index
    price_df = calculate_price_index(df, target_brand, time_granularity)

    # Filter to target brand
    brand_data = price_df[price_df['BRAND'] == target_brand]

    if brand_data.empty:
        return SkillOutput(
            final_prompt=f"Brand {target_brand} not found in data.",
            narrative=f"## {target_brand} Price Index Analysis\n\nBrand not found in the dataset.",
            visualizations=[]
        )

    # Get latest and earliest for summary
    brand_data = brand_data.sort_values('period')
    latest = brand_data.iloc[-1]
    earliest = brand_data.iloc[0]
    current_index = float(latest['price_index'])
    index_change = current_index - float(earliest['price_index'])
    category_avg_price = float(latest['category_avg_price'])
    brand_avg_price = float(latest['avg_price'])

    # Build narrative
    direction = "above" if current_index > 100 else "below"
    change_dir = "increased" if index_change > 0 else "decreased"

    # Calculate competitor metrics for insights
    competitor_metrics_for_insight = calculate_competitor_metrics(df)
    competitor_metrics_for_insight = competitor_metrics_for_insight[competitor_metrics_for_insight['current_share'] >= 1.0]
    competitor_metrics_for_insight = competitor_metrics_for_insight.sort_values('threat_score', ascending=False)

    # Build facts for LLM
    top_threats_text = []
    for _, row in competitor_metrics_for_insight.head(3).iterrows():
        threat_level = "HIGH THREAT" if (row['volume_growth'] > 0 and row['price_change'] <= 0) else ("WATCH" if row['volume_growth'] > 0 else "DECLINING")
        top_threats_text.append(f"- {row['BRAND']}: {threat_level}, Vol {row['volume_growth']:+.1f}%, Price {row['price_change']:+.1f}%, Share {row['current_share']:.1f}%")

    facts = f"""Brand: {target_brand}
Current Price Index: {current_index:.1f} ({direction} category avg of 100)
Index Change: {index_change:+.1f} pts over period
Brand Avg Price: ${brand_avg_price:.2f}
Category Avg Price: ${category_avg_price:.2f}
Top Competitor Threats:
{chr(10).join(top_threats_text) if top_threats_text else 'No significant threats identified'}"""

    # Generate LLM insights
    try:
        if ArUtils:
            ar_utils = ArUtils()
            insight_prompt = f"""Analyze this price index data and provide strategic insights in 3-4 sentences:

{facts}

Focus on: Is the brand maintaining premium positioning? Are competitors threatening with price cuts? What's the recommended action?"""

            narrative = ar_utils.llm_call(insight_prompt)
        else:
            narrative = f"""## {target_brand} Price Index Analysis

**Current Price Index:** {current_index:.1f} ({direction} category average of 100)

**Change over period:** {index_change:+.1f} pts ({change_dir})

The price index measures {target_brand}'s average price relative to the category average, where 100 represents the category average price."""
    except Exception as e:
        logger.warning(f"LLM call failed: {e}")
        narrative = f"""## {target_brand} Price Index Analysis

**Current Price Index:** {current_index:.1f} ({direction} category average of 100)

**Change over period:** {index_change:+.1f} pts ({change_dir})

The price index measures {target_brand}'s average price relative to the category average, where 100 represents the category average price."""

    # Build visualization data
    periods = [str(p) for p in brand_data['period'].tolist()]
    index_values = [float(v) for v in brand_data['price_index'].round(1).tolist()]

    # KPI color based on change direction
    change_color = "#22c55e" if index_change > 0 else "#ef4444"

    # Wire layout variables
    layout_vars = {
        "headline": f"{target_brand} Price Index Analysis",
        "kpi1_value": f"{current_index:.1f}",
        "kpi2_value": f"{index_change:+.1f} pts",
        "kpi2_color": change_color,
        "kpi3_value": f"${category_avg_price:.2f}",
        "kpi4_value": f"${brand_avg_price:.2f}",
        "chart_categories": periods,
        "chart_series": [{
            "name": target_brand,
            "data": index_values,
            "color": "#3b82f6",
            "lineWidth": 3
        }]
    }

    rendered_layout = wire_layout(json.loads(PRICE_INDEX_LAYOUT), layout_vars)

    viz = SkillVisualization(
        title="Price Index Trend",
        layout=rendered_layout
    )

    # Parameter display
    param_pills = [
        ParameterDisplayDescription(key="brand", value=f"Brand: {target_brand}"),
        ParameterDisplayDescription(key="period", value=f"Period: {period}"),
        ParameterDisplayDescription(key="granularity", value=f"By: {time_granularity}")
    ]

    # Add other_filters to display
    if other_filters:
        for f in other_filters:
            dim = f.get('dim', '')
            vals = f.get('val', [])
            if dim and vals:
                dim_display = dim.replace('_', ' ').title()
                val_display = ', '.join(vals) if isinstance(vals, list) else str(vals)
                param_pills.append(ParameterDisplayDescription(key=dim, value=f"{dim_display}: {val_display}"))

    # ===== TAB 2: COMPETITOR THREATS =====
    competitor_metrics = calculate_competitor_metrics(df)

    # Filter to brands with >= 1% market share
    competitor_metrics = competitor_metrics[competitor_metrics['current_share'] >= 1.0]
    competitor_metrics = competitor_metrics.sort_values('threat_score', ascending=False)

    # Build bubble chart data
    bubble_data = []
    for _, row in competitor_metrics.iterrows():
        # Color: Red = threat (volume up, price down), Yellow = watch (volume up), Green = declining
        if row['volume_growth'] > 0 and row['price_change'] <= 0:
            color = '#ef4444'  # Red - threat
        elif row['volume_growth'] > 0:
            color = '#fbbf24'  # Yellow - watch
        else:
            color = '#10b981'  # Green - declining

        bubble_data.append({
            'x': round(float(row['price_change']), 1),
            'y': round(float(row['volume_growth']), 1),
            'z': round(float(row['current_share']), 1),
            'name': str(row['BRAND']),
            'color': color
        })

    bubble_chart = {
        "chart": {"type": "bubble", "height": 450, "zoomType": "xy"},
        "title": {"text": "Competitive Threat Matrix", "style": {"fontSize": "20px", "fontWeight": "bold"}},
        "subtitle": {"text": "Bubble size = Market Share | Red = Threat | Yellow = Watch | Green = Declining", "style": {"fontSize": "13px", "color": "#666"}},
        "xAxis": {
            "title": {"text": "Price Change (%)"},
            "gridLineWidth": 1,
            "plotLines": [{"value": 0, "color": "#94a3b8", "dashStyle": "Dash", "width": 2}]
        },
        "yAxis": {
            "title": {"text": "Volume Growth (%)"},
            "gridLineWidth": 1,
            "plotLines": [{"value": 0, "color": "#94a3b8", "dashStyle": "Dash", "width": 2}]
        },
        "tooltip": {"pointFormat": "<b>{point.name}</b><br/>Volume: {point.y}%<br/>Price: {point.x}%<br/>Share: {point.z}%"},
        "plotOptions": {"bubble": {"minSize": 10, "maxSize": 50, "dataLabels": {"enabled": True, "format": "{point.name}", "style": {"fontSize": "10px"}}}},
        "series": [{"name": "Competitors", "data": bubble_data}],
        "legend": {"enabled": False},
        "credits": {"enabled": False}
    }

    # Build threat table data - use list format for DataTable
    top_threats = competitor_metrics.head(5)
    threat_table_data = []
    for _, row in top_threats.iterrows():
        threat_icon = "🔴" if (row['volume_growth'] > 0 and row['price_change'] <= 0) else ("🟡" if row['volume_growth'] > 0 else "🟢")
        sales_str = f"${float(row['total_sales_curr'])/1e6:.1f}M" if row['total_sales_curr'] >= 1e6 else f"${float(row['total_sales_curr'])/1e3:.0f}K"
        threat_table_data.append([
            str(row['BRAND']),
            sales_str,
            f"{float(row['sales_growth']):+.1f}%",
            f"{float(row['current_share']):.1f}%",
            f"{float(row['share_change']):+.1f}pp",
            f"{float(row['volume_growth']):+.1f}%",
            f"{float(row['price_change']):+.1f}%",
            threat_icon
        ])

    threat_table_cols = [
        {"name": "Brand"},
        {"name": "Sales"},
        {"name": "$ Chg"},
        {"name": "Share"},
        {"name": "Shr Chg"},
        {"name": "Vol Chg"},
        {"name": "Prc Chg"},
        {"name": "Threat"}
    ]

    threat_layout = {
        "type": "Document",
        "style": {"padding": "20px", "gap": "20px"},
        "children": [
            {"name": "BubbleChart", "type": "HighchartsChart", "minHeight": "450px", "options": bubble_chart},
            {"name": "TableTitle", "type": "Header", "text": "Top Competitor Threats", "style": {"fontSize": "18px", "fontWeight": "bold", "marginTop": "20px", "marginBottom": "15px"}},
            {"name": "ThreatTable", "type": "DataTable", "columns": threat_table_cols, "data": threat_table_data, "styles": {"td": {"vertical-align": "middle"}}}
        ]
    }

    threat_viz = SkillVisualization(
        title="Competitor Threats",
        layout=json.dumps(threat_layout)
    )

    return SkillOutput(
        final_prompt=f"{target_brand} price index is {current_index:.1f}, {change_dir} by {abs(index_change):.1f} pts over the period.",
        narrative=narrative,
        visualizations=[viz, threat_viz],
        parameter_display_descriptions=param_pills
    )
