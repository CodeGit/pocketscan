from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pocketscan_api.models import Status
from pocketscan_api.request_keys import normalise_accessions

# this is where future analyses can be added
SUPPORTED_ANALYSES = {"fpocket"}


class JobCreate(BaseModel):
    analysis: str = "fpocket"
    accessions: list[str]

    @field_validator("analysis")
    @classmethod
    def validate_analysis(cls, analysis: str) -> str:
        v = analysis.strip().lower()
        if v not in SUPPORTED_ANALYSES:
            raise ValueError(
                f"Unsupported analysis: {analysis}. Supported analyses are: {', '.join(sorted(SUPPORTED_ANALYSES))}"
            )
        return v

    @field_validator("accessions")
    @classmethod
    def validate_accessions(cls, accessions: list[str]) -> list[str]:
        return normalise_accessions(accessions)


class JobProteinOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    accession: str
    status: Status
    error: str | None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_key: str
    analysis: str
    created_at: datetime
    status: Status
    proteins: list[JobProteinOut]


class StructureIn(BaseModel):
    source: str  # "alphafold"
    source_version: str  # "v6"
    gcs_uri: str


class RunIn(BaseModel):
    tool: str
    tool_version: str  # includes the git commit
    params: dict[str, Any]  # hashed server-side, never trusted from the client
    status: Status = Status.SUCCEEDED
    output_gcs_uri: str | None = None


class PocketIn(BaseModel):
    rank: int = Field(ge=1)
    score: float
    volume_a3: float = Field(ge=0)
    mean_sasa_a2: float | None = Field(default=None, ge=0)
    mean_plddt: float | None = Field(default=None, ge=0, le=100)
    residues: list[str]


class ResultIn(BaseModel):
    sequence: str = Field(min_length=1)
    structure: StructureIn
    run: RunIn
    pockets: list[PocketIn]

    @model_validator(mode="after")
    def ranks_are_unique(self) -> ResultIn:
        ranks = [p.rank for p in self.pockets]
        if len(ranks) != len(set(ranks)):
            raise ValueError("pocket ranks must be unique")
        return self
