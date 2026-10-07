from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pocketscan_api.db import Base


class Status(StrEnum):
    """Status of a job or analysis run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def status_column_type() -> Enum:
    """Column type for Status.

    Implemented as a varchar not native enum to allow easier schema migrations.
    This should provide flexibility and maintain data integrity.
    create_constraint is set to False to avoid duplicate automatic creation of the CHECK constraint.
    The CHECK constraint is instead declared separately using status_check().
    """
    return Enum(
        Status,
        name="status",
        native_enum=False,
        length=16,
        create_constraint=False,
        values_callable=lambda members: [member.value for member in members],
    )


def status_check() -> CheckConstraint:
    """One per table: a constraint object cannot be shared between tables."""
    values = ", ".join(f"'{member.value}'" for member in Status)
    return CheckConstraint(f"status IN ({values})", name="status")


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_key: Mapped[str] = mapped_column(String(64), unique=True)
    analysis: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    proteins: Mapped[list[JobProtein]] = relationship(back_populates="job")


class JobProtein(Base):
    __tablename__ = "job_protein"
    __table_args__ = (UniqueConstraint("job_id", "accession"), status_check())

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id"))
    accession: Mapped[str] = mapped_column(String(16))
    status: Mapped[Status] = mapped_column(
        status_column_type(),
        default=Status.PENDING,
        server_default=Status.PENDING.value,
    )
    error: Mapped[str | None] = mapped_column(Text)
    protein_id: Mapped[int | None] = mapped_column(ForeignKey("protein.id"))
    analysis_run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_run.id"))

    job: Mapped[Job] = relationship(back_populates="proteins")
    protein: Mapped[Protein | None] = relationship()
    analysis_run: Mapped[AnalysisRun | None] = relationship()


class Protein(Base):
    """The sequence is used to uniquely identify a protein."""

    __tablename__ = "protein"

    id: Mapped[int] = mapped_column(primary_key=True)
    seq_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    sequence: Mapped[str] = mapped_column(Text)


class Structure(Base):
    __tablename__ = "structure"
    __table_args__ = (UniqueConstraint("protein_id", "source", "source_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    protein_id: Mapped[int] = mapped_column(ForeignKey("protein.id"))
    source: Mapped[str] = mapped_column(String(32))  # e.g. "alphafold"
    source_version: Mapped[str] = mapped_column(String(16))  # e.g. "v6"
    gcs_uri: Mapped[str] = mapped_column(Text)


class AnalysisRun(Base):
    """Represents one tool run against one structure.

    The unique constraint is the cache: a new tool version or parameter hash is
    a different row, so results from two versions are never mixed. Retrying a
    failed run updates the existing row's status rather than inserting another.
    """

    __tablename__ = "analysis_run"
    __table_args__ = (
        UniqueConstraint("structure_id", "tool", "tool_version", "params_hash"),
        status_check(),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    structure_id: Mapped[int] = mapped_column(ForeignKey("structure.id"))
    tool: Mapped[str] = mapped_column(String(32))  # e.g. "fpocket"
    tool_version: Mapped[str] = mapped_column(String(64))  # include the git commit
    params_hash: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[Status] = mapped_column(
        status_column_type(),
        default=Status.PENDING,
        server_default=Status.PENDING.value,
    )
    output_gcs_uri: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Pocket(Base):
    __tablename__ = "pocket"
    __table_args__ = (UniqueConstraint("analysis_run_id", "rank"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("analysis_run.id"))
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    volume_a3: Mapped[float] = mapped_column(Float)  # cubic angstroms
    mean_sasa_a2: Mapped[float | None] = mapped_column(Float)  # square angstroms
    mean_plddt: Mapped[float | None] = mapped_column(Float)
    residues: Mapped[list[str]] = mapped_column(ARRAY(String))
