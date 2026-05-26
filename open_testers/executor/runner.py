from pathlib import Path
from typing import Any


class RunResult:
    pass


class Runner:
    def __init__(self, test: Any, llm_provider: Any, output_dir: str | Path) -> None:
        self.test = test
        self.llm_provider = llm_provider
        self.output_dir = output_dir

    async def run(self) -> RunResult:
        raise NotImplementedError
