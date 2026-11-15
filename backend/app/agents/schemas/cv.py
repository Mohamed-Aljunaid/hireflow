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

    def evidence_index(self) -> dict[str, str]:
        """Every citable CV item, by ID -> its text.

        Roles, projects and bullets carry stored IDs. Summary, education, skills,
        certifications and languages get positional IDs (edu-1, skill-3, ...), which are
        stable because a stored ParsedCV never changes.
        """
        index: dict[str, str] = {}
        if self.summary:
            index["summary"] = self.summary
        for exp in self.experience:
            dates = " - ".join(d for d in (exp.start_date, exp.end_date) if d)
            index[exp.id] = f"{exp.title} at {exp.company}" + (f" ({dates})" if dates else "")
            for b in exp.bullets:
                index[b.id] = b.text
        for proj in self.projects:
            index[proj.id] = proj.name + (f": {proj.description}" if proj.description else "")
            for b in proj.bullets:
                index[b.id] = b.text
        for i, edu in enumerate(self.education, 1):
            parts = [edu.degree, edu.field_of_study, edu.institution, edu.end_date]
            index[f"edu-{i}"] = ", ".join(p for p in parts if p)
        for prefix, values in (
            ("skill", self.skills),
            ("cert", self.certifications),
            ("lang", self.languages),
        ):
            for i, value in enumerate(values, 1):
                index[f"{prefix}-{i}"] = value
        return index

    def render_with_ids(self) -> str:
        """The CV as prompt text, each citable item prefixed by its [ID]."""
        index = self.evidence_index()
        lines = [f"Candidate: {self.contact.name}"]
        if "summary" in index:
            lines += ["", "SUMMARY", f"[summary] {index['summary']}"]
        if self.experience:
            lines += ["", "EXPERIENCE"]
            for exp in self.experience:
                lines.append(f"[{exp.id}] {index[exp.id]}")
                lines += [f"  [{b.id}] {b.text}" for b in exp.bullets]
        if self.projects:
            lines += ["", "PROJECTS"]
            for proj in self.projects:
                lines.append(f"[{proj.id}] {index[proj.id]}")
                lines += [f"  [{b.id}] {b.text}" for b in proj.bullets]
        for title, prefix in (
            ("EDUCATION", "edu"),
            ("SKILLS", "skill"),
            ("CERTIFICATIONS", "cert"),
            ("LANGUAGES", "lang"),
        ):
            items = [(k, v) for k, v in index.items() if k.startswith(f"{prefix}-")]
            if items:
                lines += ["", title, *(f"[{k}] {v}" for k, v in items)]
        return "\n".join(lines)
