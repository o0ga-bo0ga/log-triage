"""CrewAI tool wrapping the deterministic parser."""

from pathlib import Path

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from log_triage.parser import parse_log, summarize


class ParseLogFileInput(BaseModel):
    file_name: str = Field(description="Name of a .log file in the log directory, e.g. 'incident-1.log'")


class ParseLogFileTool(BaseTool):
    """Parse a log file and return a compact JSON summary.

    The full event list is deliberately not returned: thousands of lines would overflow the model's context.
    Pipeline code that needs every event calls log_triage.parser.parse_log directly.
    """

    name: str = "parse_log_file"
    description: str = (
        "Parse a multi-service log file. Returns JSON with line counts, the time range, INFO/WARN/ERROR counts "
        "per service, and how many lines could not be parsed and why."
    )
    args_schema: type[BaseModel] = ParseLogFileInput
    log_dir: Path

    def _run(self, file_name: str) -> str:
        # The model chooses file_name and log content is untrusted, so never let it reach outside log_dir.
        root = self.log_dir.resolve()
        path = (root / file_name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return f"Error: no log file named '{file_name}' in the log directory."
        return summarize(parse_log(path.read_text())).model_dump_json()
