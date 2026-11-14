import os

# Keep CrewAI from sending telemetry or traces while tests run (values per the test-crewai-project skill:
# only "true"/"false" are honoured by every switch).
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
os.environ["CREWAI_TRACING_ENABLED"] = "false"
os.environ["OTEL_SDK_DISABLED"] = "true"
