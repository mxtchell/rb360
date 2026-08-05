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
        "style": {"padding": "15px"},
        "children": [
            {
                "name": "Header0",
                "type": "Header",
                "text": "Price Index Analysis"
            }
        ]
    },
    "inputVariables": []
}
"""


@skill(
    name="Price Index Analysis",
    llm_name="Price Index - Brand vs Category Pricing Analysis",
    description="Analyze brand price positioning vs category average. Use this skill when users ask about price index, pricing vs category, price positioning, or how brand pricing compares to competition.",
    capabilities="Calculates price index (brand price / category avg price * 100). Shows price index trend over time.",
    limitations="Requires sales and units data to calculate average price.",
    example_questions="How is Lysol's price index moving vs rest of category? Is Lysol gaining or losing price premium?",
    parameter_guidance="Select a brand to analyze price index for. Choose time granularity and time period.",
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
    current_index = latest['price_index']
    index_change = current_index - earliest['price_index']

    # Build narrative
    direction = "above" if current_index > 100 else "below"
    change_dir = "increased" if index_change > 0 else "decreased"

    narrative = f"""## {target_brand} Price Index Analysis

**Current Price Index:** {current_index:.1f} ({direction} category average of 100)

**Change over period:** {index_change:+.1f} pts ({change_dir})

The price index measures {target_brand}'s average price relative to the category average, where 100 represents the category average price.
"""

    # Build visualization
    periods = brand_data['period'].tolist()
    index_values = brand_data['price_index'].round(1).tolist()
    category_avg_price = latest['category_avg_price']

    chart_options = {
        "chart": {"type": "line", "height": 400},
        "title": {"text": ""},
        "xAxis": {"categories": periods, "title": {"text": ""}},
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
        "series": [{
            "name": target_brand,
            "data": index_values,
            "color": "#3b82f6",
            "lineWidth": 3
        }],
        "credits": {"enabled": False},
        "legend": {"enabled": True},
        "tooltip": {"shared": True}
    }

    # KPI color based on change direction
    change_color = "#22c55e" if index_change > 0 else "#ef4444"

    viz_layout = {
        "type": "Document",
        "style": {"padding": "15px", "gap": "20px"},
        "children": [
            {
                "name": "Header0",
                "type": "Header",
                "text": f"{target_brand} Price Index Analysis",
                "style": {"fontSize": "20px", "fontWeight": "bold"}
            },
            {
                "name": "KPIContainer",
                "type": "FlexContainer",
                "style": {"display": "flex", "gap": "20px", "flexWrap": "wrap"}
            },
            {
                "name": "KPI1",
                "type": "CardContainer",
                "style": {"padding": "15px", "background": "#f8fafc", "borderRadius": "8px", "minWidth": "150px"},
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
                "text": f"{current_index:.1f}",
                "style": {"fontSize": "28px", "fontWeight": "bold", "color": "#1e3a5f"},
                "parentId": "KPI1"
            },
            {
                "name": "KPI2",
                "type": "CardContainer",
                "style": {"padding": "15px", "background": "#f8fafc", "borderRadius": "8px", "minWidth": "150px"},
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
                "text": f"{index_change:+.1f} pts",
                "style": {"fontSize": "28px", "fontWeight": "bold", "color": change_color},
                "parentId": "KPI2"
            },
            {
                "name": "KPI3",
                "type": "CardContainer",
                "style": {"padding": "15px", "background": "#f8fafc", "borderRadius": "8px", "minWidth": "150px"},
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
                "text": f"${category_avg_price:.2f}",
                "style": {"fontSize": "28px", "fontWeight": "bold", "color": "#1e3a5f"},
                "parentId": "KPI3"
            },
            {
                "name": "Chart0",
                "type": "HighchartsChart",
                "minHeight": "400px",
                "options": chart_options
            },
            {
                "name": "DataTable0",
                "type": "DataTable",
                "columns": [
                    {"field": "period", "headerName": "Period"},
                    {"field": "brand_price", "headerName": f"{target_brand} Avg Price"},
                    {"field": "category_avg", "headerName": "Category Avg Price"},
                    {"field": "price_index", "headerName": "Price Index"}
                ],
                "data": [
                    {
                        "period": str(row['period']),
                        "brand_price": f"${float(row['avg_price']):.2f}",
                        "category_avg": f"${float(row['category_avg_price']):.2f}",
                        "price_index": f"{float(row['price_index']):.1f}"
                    }
                    for _, row in brand_data.iterrows()
                ]
            }
        ]
    }

    viz = SkillVisualization(
        title="Price Index Trend",
        layout=json.dumps(viz_layout)
    )

    return SkillOutput(
        final_prompt=f"{target_brand} price index is {current_index:.1f}, {change_dir} by {abs(index_change):.1f} pts over the period.",
        narrative=narrative,
        visualizations=[viz]
    )
