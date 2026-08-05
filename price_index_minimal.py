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
    """Minimal test skill."""
    target_brand = getattr(parameters.arguments, 'target_brand', 'LYSOL')

    return SkillOutput(
        final_prompt=f"Testing price index for {target_brand}",
        narrative="Test narrative",
        visualizations=[]
    )
