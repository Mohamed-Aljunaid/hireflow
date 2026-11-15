"""CV models.

`CVExtraction` is what the LLM returns. `ParsedCV` is the same content plus stable IDs on
every experience, project and bullet, assigned in code (not by the model). Later phases
cite those IDs as `source_cv_refs`, so every tailored claim can be traced back to the CV.
"""

from pydantic import BaseModel, Field

# ---------- LLM output (no IDs) ----------


class ContactInfo(BaseModel):
    name: str = Field(description="Full name as written on the CV.")
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = Field(default_factory=list, description="LinkedIn, GitHub, portfolio...")


class ExperienceExtraction(BaseModel):
    title: str
    company: str
    location: str | None = None
    start_date: str | None = Field(None, description="As written, e.g. 'Jan 2021'.")
    end_date: str | None = Field(None, description="As written, or 'Present'.")
    bullets: list[str] = Field(
        default_factory=list, description="Each achievement/responsibility, verbatim."
    )


class ProjectExtraction(BaseModel):
    name: str
    description: str | None = None
    bullets: list[str] = Field(default_factory=list)


class EducationExtraction(BaseModel):
    institution: str
    degree: str | None = None
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class CVExtraction(BaseModel):
    contact: ContactInfo
    summary: str | None = None
    experience: list[ExperienceExtraction] = Field(default_factory=list)
    projects: list[ProjectExtraction] = Field(default_factory=list)
    education: list[EducationExtraction] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


# ---------- Stored / downstream model (with IDs) ----------


class Bullet(BaseModel):
    id: str
    text: str


class Experience(BaseModel):
    id: str
    title: str
    company: str
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    bullets: list[Bullet] = Field(default_factory=list)


class Project(BaseModel):
    id: str
    name: str
    description: str | None = None
    bullets: list[Bullet] = Field(default_factory=list)


class ParsedCV(BaseModel):
    contact: ContactInfo
    summary: str | None = None
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[EducationExtraction] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)

    @classmethod
    def from_extraction(cls, extraction: CVExtraction) -> "ParsedCV":
        """Assign deterministic IDs: exp-1, exp-1.b1, proj-1, proj-1.b1 ..."""
        experience = [
            Experience(
                id=f"exp-{i}",
                **exp.model_dump(exclude={"bullets"}),
                bullets=[Bullet(id=f"exp-{i}.b{j}", text=b) for j, b in enumerate(exp.bullets, 1)],
            )
            for i, exp in enumerate(extraction.experience, 1)
        ]
        projects = [
            Project(
                id=f"proj-{i}",
                **proj.model_dump(exclude={"bullets"}),
                bullets=[
                    Bullet(id=f"proj-{i}.b{j}", text=b) for j, b in enumerate(proj.bullets, 1)
                ],
            )
            for i, proj in enumerate(extraction.projects, 1)
        ]
        return cls(
            **extraction.model_dump(exclude={"experience", "projects"}),
            experience=experience,
            projects=projects,
        )

    def bullet_index(self) -> dict[str, Bullet]:
        """All bullets by ID, for evidence lookups in later phases."""
        index: dict[str, Bullet] = {}
        for item in [*self.experience, *self.projects]:
            for bullet in item.bullets:
                index[bullet.id] = bullet
        return index
