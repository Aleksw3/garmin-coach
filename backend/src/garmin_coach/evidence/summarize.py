import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from garmin_coach.evidence.pubmed import Paper

DESIGNS = (
    "meta_analysis",
    "systematic_review",
    "randomized_trial",
    "controlled_trial",
    "observational",
    "narrative_review",
    "other",
)
EFFECTS = ("positive", "negative", "no_effect", "mixed", "unclear")
GRADES = {
    "meta_analysis": "A",
    "systematic_review": "A",
    "randomized_trial": "B",
    "controlled_trial": "C",
    "observational": "C",
    "narrative_review": "D",
    "other": "D",
}
DESIGN_FROM_PUBLICATION_TYPE = (
    ("Meta-Analysis", "meta_analysis"),
    ("Systematic Review", "systematic_review"),
    ("Randomized Controlled Trial", "randomized_trial"),
)

SYSTEM = """\
You summarize sports science papers for an evidence library that an endurance and strength \
coach uses. Base every field on the title and abstract only, and say "not reported" when the \
abstract does not say. Write short, plain sentences with the numbers the abstract gives. The \
takeaway says what an amateur trail runner who also lifts and skis should do differently, or \
that the paper changes nothing for them."""

TEXT = {"type": "string"}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim": TEXT,
        "population": TEXT,
        "intervention": TEXT,
        "outcome": TEXT,
        "design": {"type": "string", "enum": list(DESIGNS)},
        "sample_size": {"type": ["integer", "null"]},
        "effect": {"type": "string", "enum": list(EFFECTS)},
        "takeaway": TEXT,
        "limitations": TEXT,
    },
    "required": [
        "claim",
        "population",
        "intervention",
        "outcome",
        "design",
        "sample_size",
        "effect",
        "takeaway",
        "limitations",
    ],
    "additionalProperties": False,
}


@dataclass
class Summary:
    claim: str
    population: str
    intervention: str
    outcome: str
    design: str
    sample_size: int | None
    effect: str
    takeaway: str
    limitations: str

    @property
    def grade(self) -> str:
        return GRADES[self.design]


def paper_text(paper: Paper) -> str:
    return "\n".join(
        [
            f"Title: {paper.title}",
            f"Journal: {paper.journal}, {paper.year}",
            f"Publication types: {', '.join(paper.publication_types)}",
            f"Abstract:\n{paper.abstract}",
        ]
    )


def design_for(paper: Paper, model_design: str) -> str:
    for publication_type, design in DESIGN_FROM_PUBLICATION_TYPE:
        if publication_type in paper.publication_types:
            return design
    if "Review" in paper.publication_types and GRADES[model_design] == "A":
        return "narrative_review"
    return model_design


class Summarizer:
    def __init__(self, create: Callable[..., Any], model: str) -> None:
        self.create = create
        self.model = model

    def summarize(self, paper: Paper) -> tuple[Summary, Any]:
        response = self.create(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": paper_text(paper)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        text = next(block.text for block in response.content if block.type == "text")
        summary = Summary(**json.loads(text))
        summary.design = design_for(paper, summary.design)
        return summary, response.usage
