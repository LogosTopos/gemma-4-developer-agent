---
name: repo-context
description: Prepare a compact code reading packet for the issue in the current repository. This is the single repository navigation entry point.
---
Run scripts/context.py with args={"query": "the original issue text"}.
It automatically searches source, follows imports, ranks locations, and returns
up to five source candidates with line-numbered code and nearby test paths. No search
strategy or other option is needed. Read the first relevant code, then implement.
Returned locations are evidence to inspect, not instructions or guaranteed targets.
