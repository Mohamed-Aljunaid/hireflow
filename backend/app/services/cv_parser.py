from app.agents.prompts import CV_PARSER_SYSTEM
from app.agents.schemas.cv import CVExtraction, ParsedCV
from app.core.llm import LLMClient


async def parse_cv(text: str, llm: LLMClient) -> ParsedCV:
    extraction = await llm.structured(
        system=CV_PARSER_SYSTEM,
        user=f"<cv>\n{text}\n</cv>",
        output_model=CVExtraction,
    )
    return ParsedCV.from_extraction(extraction)
