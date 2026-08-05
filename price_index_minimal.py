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

    # Build summary
    final_prompt = f"{target_brand} price index analysis requested for {period}."
    narrative = f"## {target_brand} Price Index Analysis\n\nAnalysis pending implementation."

    return SkillOutput(
        final_prompt=final_prompt,
        narrative=narrative,
        visualizations=[]
    )
