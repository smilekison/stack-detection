from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass
class Evidence:
    category: str
    technology: str
    points: float
    file: str
    reason: str
    source: str = "repository"

@dataclass
class Candidate:
    name: str
    score: float = 0
    evidence: list[Evidence] = field(default_factory=list)

@dataclass
class Finding:
    severity: str
    code: str
    title: str
    message: str
    file: str | None = None
    line: int | None = None
    remediation: str | None = None
    confidence: float = 1.0

@dataclass
class RepairAction:
    code: str
    description: str
    confidence: float
    allowed: bool
    changes: dict[str, Any] = field(default_factory=dict)

@dataclass
class DeploymentSpec:
    schema_version: str = "1.0.0"
    project: dict[str, Any] = field(default_factory=dict)
    languages: list[dict[str, Any]] = field(default_factory=list)
    runtime: dict[str, Any] = field(default_factory=dict)
    frameworks: list[dict[str, Any]] = field(default_factory=list)
    package_managers: list[dict[str, Any]] = field(default_factory=list)
    build: dict[str, Any] = field(default_factory=dict)
    processes: list[dict[str, Any]] = field(default_factory=list)
    network: dict[str, Any] = field(default_factory=dict)
    services: list[dict[str, Any]] = field(default_factory=list)
    dependencies: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    migrations: dict[str, Any] = field(default_factory=dict)
    ci_cd: dict[str, Any] = field(default_factory=dict)
    infrastructure: dict[str, Any] = field(default_factory=dict)
    security: dict[str, Any] = field(default_factory=dict)
    cloud: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)
