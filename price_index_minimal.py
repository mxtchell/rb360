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
    name="Price Index Test",
    llm_name="Price Index Test",
    description="Test skill",
    capabilities="Test",
    limitations="Test",
    example_questions="Test?",
    parameters=[
        SkillParameter(
            name="target_brand",
            description="Brand to analyze",
            default_value="LYSOL"
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
