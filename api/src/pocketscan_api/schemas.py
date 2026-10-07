from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

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
