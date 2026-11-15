from app.agents.prompts import JOB_PARSER_SYSTEM
from app.agents.schemas.job import JobPosting, JobPostingExtraction
from app.core.llm import LLMClient


async def parse_job_posting(text: str, llm: LLMClient) -> JobPosting:
    extraction = await llm.structured(
        system=JOB_PARSER_SYSTEM,
        user=f"<job_posting>\n{text}\n</job_posting>",
        output_model=JobPostingExtraction,
    )
    return JobPosting.from_extraction(extraction)
