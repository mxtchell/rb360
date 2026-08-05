"""
Reckitt Price Index Analysis
Compare brand pricing vs category average and competition
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
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# Layout for price index trend chart
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
                "text": "Price Index Analysis",
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
                "text": "Brand Price vs Category Average (100 = Category Avg)",
                "style": {
                    "fontSize": "14px",
                    "color": "#cbd5e1"
                },
                "parentId": "CardContainer0"
            },
            {
                "name": "KPIContainer",
                "type": "FlexContainer",
                "style": {
                    "display": "flex",
                    "gap": "20px",
                    "flexWrap": "wrap"
                }
            },
            {
                "name": "KPI1",
                "type": "CardContainer",
                "style": {
                    "padding": "15px",
                    "background": "#f8fafc",
                    "borderRadius": "8px",
                    "minWidth": "150px"
                },
                "parentId": "KPIContainer"
            },
            {
                "name": "KPI1_Label",
                "type": "Paragraph",
                "text": "Current Index",
                "style": {"fontSize": "12px", "color": "#64748b"},
                "parentId": "KPI1"
            },
            {
                "name": "KPI1_Value",
                "type": "Paragraph",
                "text": "100",
                "style": {"fontSize": "28px", "fontWeight": "bold", "color": "#1e3a5f"},
                "parentId": "KPI1"
            },
            {
                "name": "KPI2",
                "type": "CardContainer",
                "style": {
                    "padding": "15px",
                    "background": "#f8fafc",
                    "borderRadius": "8px",
                    "minWidth": "150px"
                },
                "parentId": "KPIContainer"
            },
            {
                "name": "KPI2_Label",
                "type": "Paragraph",
                "text": "Index Change",
                "style": {"fontSize": "12px", "color": "#64748b"},
                "parentId": "KPI2"
            },
            {
                "name": "KPI2_Value",
                "type": "Paragraph",
                "text": "+0.0 pts",
                "style": {"fontSize": "28px", "fontWeight": "bold", "color": "#22c55e"},
                "parentId": "KPI2"
            },
            {
                "name": "KPI3",
                "type": "CardContainer",
                "style": {
                    "padding": "15px",
                    "background": "#f8fafc",
                    "borderRadius": "8px",
                    "minWidth": "150px"
                },
                "parentId": "KPIContainer"
            },
            {
                "name": "KPI3_Label",
                "type": "Paragraph",
                "text": "Category Avg Price",
                "style": {"fontSize": "12px", "color": "#64748b"},
                "parentId": "KPI3"
            },
            {
                "name": "KPI3_Value",
                "type": "Paragraph",
                "text": "$0.00",
                "style": {"fontSize": "28px", "fontWeight": "bold", "color": "#1e3a5f"},
                "parentId": "KPI3"
            },
            {
                "name": "HighchartsChart0",
                "type": "HighchartsChart",
                "minHeight": "400px",
                "options": {
                    "chart": {"type": "line", "height": 400},
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
                    "tooltip": {"shared": true, "valueSuffix": ""}
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
        {"name": "kpi1_value", "targets": [{"elementName": "KPI1_Value", "fieldName": "text"}]},
        {"name": "kpi2_value", "targets": [{"elementName": "KPI2_Value", "fieldName": "text"}]},
        {"name": "kpi2_color", "targets": [{"elementName": "KPI2_Value", "fieldName": "style.color"}]},
        {"name": "kpi3_value", "targets": [{"elementName": "KPI3_Value", "fieldName": "text"}]},
        {"name": "chart_categories", "targets": [{"elementName": "HighchartsChart0", "fieldName": "options.xAxis.categories"}]},
        {"name": "chart_data", "targets": [{"elementName": "HighchartsChart0", "fieldName": "options.series"}]},
        {"name": "data", "targets": [{"elementName": "DataTable0", "fieldName": "data"}]},
        {"name": "col_defs", "targets": [{"elementName": "DataTable0", "fieldName": "columns"}]}
    ]
}
"""


def build_filter_clause(filters: list) -> str:
    """Build SQL WHERE clause from filter list."""
    if not filters:
        return ""

    clauses = []
    for f in filters:
        dim = f.get('dim', '')
        vals = f.get('val', [])
        if dim and vals:
            escaped_vals = [v.replace("'", "''") for v in vals]
            val_str = ", ".join([f"'{v}'" for v in escaped_vals])
            clauses.append(f"{dim} IN ({val_str})")

    return " AND ".join(clauses)


def query_data(client, database_id: str, filters: list = None) -> pd.DataFrame:
    """Query Nielsen data for price index calculation, joining fact to product dimension."""
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
    WHERE 1=1
    {where_clause}
    GROUP BY p.BRAND, f.week_ending_date
    ORDER BY f.week_ending_date
    """

    logger.info(f"Executing query: {query}")
    print(f"DEBUG: Executing query:\n{query}")

    result = client.data.execute_sql_query(
        database_id=database_id,
        sql_query=query,
        row_limit=100000
    )

    df = result.df if hasattr(result, 'df') else None

    if df is not None and not df.empty:
        df = df.copy()
        df['week_ending_date'] = pd.to_datetime(df['week_ending_date'])
        print(f"DEBUG: Retrieved {len(df)} rows")
        return df

    print(f"DEBUG: No data returned from query")
    return pd.DataFrame()


def calculate_price_index(df: pd.DataFrame, target_brand: str, time_granularity: str = 'month') -> pd.DataFrame:
    """
    Calculate price index for target brand vs category average.

    Price Index = (Brand Avg Price / Category Avg Price) * 100
    Where 100 = at category average
    """
    if df.empty:
        return pd.DataFrame()

    df = df.copy()

    # Aggregate to time granularity
    if time_granularity == 'month':
        df['period'] = df['week_ending_date'].dt.to_period('M').astype(str)
    elif time_granularity == 'quarter':
        df['period'] = df['week_ending_date'].dt.to_period('Q').astype(str)
    else:  # week
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


@skill(
    name="Price Index Analysis",
    description="""Analyze brand price positioning vs category average and competition.
Use this skill when the user asks about price index, price positioning, pricing vs category, or how brand pricing compares to competition.
This skill calculates Price Index where 100 = category average, >100 = premium pricing, <100 = below category average.
It shows price index trends over time and can compare multiple brands.""",
    capabilities="""Calculates price index (brand price / category avg price * 100).
Shows price index trend over time by week, month, or quarter.
Compares target brand index vs selected competitors.
Identifies if brand is gaining or losing price premium.
Can filter by segment, channel, retailer, or other dimensions.""",
    limitations="""Requires sales and units data to calculate average price.
Cannot show price index for dimensions without sufficient data.
Does not forecast future price index.""",
    example_questions="""How is Lysol's price index moving vs rest of category?
What is Lysol's price positioning vs competition?
Is Lysol gaining or losing price premium?
Show me price index trend for Lysol by month
Compare Lysol price index vs Clorox"""
)
def price_index_analysis(
    input: SkillInput,
    target_brand: SkillParameter(
        name="target_brand",
        description="The brand to analyze price index for",
        default="LYSOL"
    ) = "LYSOL",
    compare_brands: SkillParameter(
        name="compare_brands",
        description="Additional brands to compare against (optional)",
        param_type="multi_select",
        default=[]
    ) = [],
    time_granularity: SkillParameter(
        name="time_granularity",
        description="Time granularity for trend analysis",
        param_type="constrained",
        allowed_values=["week", "month", "quarter"],
        default="month"
    ) = "month",
    period: SkillParameter(
        name="period",
        description="Time period to analyze (e.g., 'last 52 weeks', 'YTD', '2024')",
        param_type="date_filter",
        default="last 52 weeks"
    ) = "last 52 weeks",
    other_filters: SkillParameter(
        name="other_filters",
        description="Additional filters (segment, channel, retailer)",
        param_type="multi_filter",
        default=[]
    ) = []
) -> SkillOutput:
    """Calculate and visualize price index for brand vs category."""

    # Initialize client
    client = AnswerRocketClient()
    dataset_id = get_dataset_id()

    print(f"DEBUG: Starting price index analysis for {target_brand}")
    print(f"DEBUG: Dataset ID: {dataset_id}")

    # Get database_id from dataset
    dataset = client.data.get_dataset(dataset_id=dataset_id)
    database_id = dataset.database.database_id
    print(f"DEBUG: Database ID: {database_id}")

    # Query data
    df = query_data(client, database_id, other_filters)

    if df.empty:
        return SkillOutput(
            final_prompt="No data found for the specified filters.",
            narrative="Unable to calculate price index - no data returned from query.",
            visualizations=[]
        )

    # Calculate price index
    price_df = calculate_price_index(df, target_brand, time_granularity)

    if price_df.empty:
        return SkillOutput(
            final_prompt="Unable to calculate price index for the specified brand.",
            narrative="No pricing data available for the target brand.",
            visualizations=[]
        )

    # Get target brand data
    target_data = price_df[price_df['BRAND'].str.upper() == target_brand.upper()].sort_values('period')

    if target_data.empty:
        return SkillOutput(
            final_prompt=f"No data found for brand: {target_brand}",
            narrative=f"The brand '{target_brand}' was not found in the data.",
            visualizations=[]
        )

    # Calculate KPIs
    current_index = target_data['price_index'].iloc[-1]
    prior_index = target_data['price_index'].iloc[0] if len(target_data) > 1 else current_index
    index_change = current_index - prior_index
    current_category_avg = target_data['category_avg_price'].iloc[-1]

    # Determine change color
    change_color = "#22c55e" if index_change >= 0 else "#ef4444"
    change_sign = "+" if index_change >= 0 else ""

    # Build chart series
    periods = target_data['period'].tolist()
    series = [{
        "name": target_brand,
        "data": target_data['price_index'].round(1).tolist(),
        "color": "#3b82f6",
        "lineWidth": 3
    }]

    # Add comparison brands if specified
    if compare_brands:
        colors = ["#ef4444", "#22c55e", "#f59e0b", "#8b5cf6"]
        for i, brand in enumerate(compare_brands[:4]):
            brand_data = price_df[price_df['BRAND'].str.upper() == brand.upper()].sort_values('period')
            if not brand_data.empty:
                # Align to same periods
                brand_series = []
                for p in periods:
                    val = brand_data[brand_data['period'] == p]['price_index'].values
                    brand_series.append(round(val[0], 1) if len(val) > 0 else None)
                series.append({
                    "name": brand,
                    "data": brand_series,
                    "color": colors[i % len(colors)],
                    "lineWidth": 2
                })

    # Build data table
    table_data = []
    for _, row in target_data.iterrows():
        table_data.append({
            "Period": row['period'],
            "Brand Price": f"${row['avg_price']:.2f}",
            "Category Avg": f"${row['category_avg_price']:.2f}",
            "Price Index": f"{row['price_index']:.1f}"
        })

    col_defs = [
        {"field": "Period", "headerName": "Period"},
        {"field": "Brand Price", "headerName": f"{target_brand} Avg Price"},
        {"field": "Category Avg", "headerName": "Category Avg Price"},
        {"field": "Price Index", "headerName": "Price Index"}
    ]

    # Wire layout
    layout_vars = {
        "headline": f"{target_brand} Price Index Analysis",
        "sub_headline": f"Price positioning vs category average (100 = Category Avg)",
        "kpi1_value": f"{current_index:.1f}",
        "kpi2_value": f"{change_sign}{index_change:.1f} pts",
        "kpi2_color": change_color,
        "kpi3_value": f"${current_category_avg:.2f}",
        "chart_categories": periods,
        "chart_data": series,
        "data": table_data,
        "col_defs": col_defs
    }

    layout = json.loads(PRICE_INDEX_LAYOUT)
    html = wire_layout(layout, layout_vars)

    # Build summary
    position = "premium to" if current_index > 100 else "below" if current_index < 100 else "at"
    trend = "gaining" if index_change > 0 else "losing" if index_change < 0 else "maintaining"

    final_prompt = f"{target_brand} is currently {position} category average with a price index of {current_index:.1f}, {trend} {abs(index_change):.1f} points over the period."

    narrative = f"""## {target_brand} Price Index Analysis

**Current Position:**
- Price Index: {current_index:.1f} (Category Avg = 100)
- {target_brand} is priced {abs(current_index - 100):.1f}% {'above' if current_index > 100 else 'below'} category average
- Category average price: ${current_category_avg:.2f}

**Trend:**
- Index change: {change_sign}{index_change:.1f} points
- {target_brand} is {trend} price premium vs category

**Interpretation:**
- Index > 100: Brand commands premium pricing vs category
- Index < 100: Brand is priced below category average
- Index = 100: Brand is priced at category average
"""

    # Parameter pills
    param_pills = [
        ParameterDisplayDescription(key="brand", value=f"Brand: {target_brand}"),
        ParameterDisplayDescription(key="period", value=f"Period: {period}"),
        ParameterDisplayDescription(key="granularity", value=f"By: {time_granularity}")
    ]

    if compare_brands:
        param_pills.append(ParameterDisplayDescription(key="compare", value=f"vs: {', '.join(compare_brands)}"))

    return SkillOutput(
        final_prompt=final_prompt,
        narrative=narrative,
        visualizations=[
            SkillVisualization(title="Price Index Trend", layout=html)
        ],
        parameter_display_descriptions=param_pills
    )


if __name__ == '__main__':
    from skill_framework.preview import preview_skill

    skill_input = price_index_analysis.create_input(
        arguments={
            "target_brand": "LYSOL",
            "compare_brands": [],
            "time_granularity": "month",
            "period": "last 52 weeks"
        }
    )
    out = price_index_analysis(skill_input)
    preview_skill(price_index_analysis, out)
