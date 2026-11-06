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
You summarize sports science papers for an evidence library that amateur athletes read to \
plan their own training. They train for endurance sports and also lift. Base every field on \
the title and abstract only. Write short, plain sentences with the numbers the abstract gives. \
When the abstract does not give the population, intervention or outcome, write "not reported" \
in that field.

The takeaway tells the reader what to learn from the paper and what to do with it in their \
training, in two or three sentences. First give the lesson: what works, what does not, or what \
a measure can and cannot tell you, with the size of the effect and the dose behind it, such as \
sessions per week, intensity, duration and weeks, if the abstract gives them. Then give the \
advice as one or two instructions that start with a verb. If the paper gives no reason to \
change how anyone trains, say that in one short sentence. Never describe the reader or name \
their sports. Do not repeat the claim. Do not mention doses, effect sizes or anything else the \
abstract leaves out, because the limitations field covers that."""

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
        "limitations": TEXT,
        "takeaway": {
            "type": "string",
            "description": "The lesson from the paper, then what to do in training.",
        },
    },
    "required": [
        "claim",
        "population",
        "intervention",
        "outcome",
        "design",
        "sample_size",
        "effect",
        "limitations",
        "takeaway",
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
    def __init__(self, create: Callable[..., Any] | None, model: str) -> None:
        self.create = create
        self.model = model

    def summarize(self, paper: Paper) -> tuple[Summary, Any]:
        if self.create is None:
            raise RuntimeError("No Anthropic API key")
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
