"""
Reckitt Price Index Analysis - Minimal Test
"""
from skill_framework import (
    SkillInput,
    SkillVisualization,
    skill,
    SkillParameter,
    SkillOutput
)


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
