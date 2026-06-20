from typing import Any, Literal

from pydantic import BaseModel, Field


class MatchRule(BaseModel):
    remarks_equals: list[str] = Field(default_factory=list)
    remarks_contains: list[str] = Field(default_factory=list)
    flag: str = ""
    network_in: list[str] = Field(default_factory=list)
    protocol: str = ""
    network: str = ""
    address_equals: list[str] = Field(default_factory=list)
    path_equals: list[str] = Field(default_factory=list)
    security: str = ""
    port: int | None = None
    fingerprint_equals: list[str] = Field(default_factory=list)


class TaggingRule(BaseModel):
    match: MatchRule
    tag: str


class OutputConfig(BaseModel):
    format: Literal["single", "grouped", "array", "passthrough"] = "grouped"
    remarks: str = "ExamplePool"
    default_balancer: str = ""


class TaggingConfig(BaseModel):
    rules: list[TaggingRule] = Field(default_factory=list)
    default_template: str = "node-{index}"


class FiltersConfig(BaseModel):
    exclude: list[MatchRule] = Field(default_factory=list)


class BalancerMember(BaseModel):
    tags: list[str] = Field(default_factory=list)
    inbound_ids: list[str] = Field(default_factory=list)
    match: MatchRule | None = None


class BalancerRule(BaseModel):
    tag: str
    remarks: str = ""
    strategy: Literal["roundRobin", "leastLoad", "random"] = "roundRobin"
    members: list[BalancerMember] = Field(default_factory=list)


class TransformRules(BaseModel):
    output: OutputConfig = Field(default_factory=OutputConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    tagging: TaggingConfig = Field(default_factory=TaggingConfig)
    balancers: list[BalancerRule] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TransformRules":
        return cls.model_validate(data)