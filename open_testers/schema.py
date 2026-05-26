from pathlib import Path
from typing import Annotated, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field


class ActStep(BaseModel):
    type: Literal["act"]
    title: str


class AssertStep(BaseModel):
    type: Literal["assert"]
    title: str


class LoginStep(BaseModel):
    type: Literal["login"]
    title: str
    credentialId: Optional[str] = None
    temporaryEmail: Optional[bool] = False


class FilesStep(BaseModel):
    type: Literal["files"]
    title: str
    fileIds: list[str]


class ScreenshotStep(BaseModel):
    type: Literal["screenshot"]
    title: str


TestStep = Annotated[
    Union[ActStep, AssertStep, LoginStep, FilesStep, ScreenshotStep],
    Field(discriminator="type"),
]


class TestDefinition(BaseModel):
    id: Optional[str] = None
    title: str
    description: Optional[str] = None
    platform: Literal["web", "mobile"] = "web"
    projectUrl: Optional[str] = None
    steps: list[TestStep]


def load(path: str | Path) -> TestDefinition:
    with open(path) as f:
        data = yaml.safe_load(f)
    return TestDefinition.model_validate(data)
