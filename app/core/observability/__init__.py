"""AI call recording (DESIGN_GROUP_C.md §7.3) — shared kernel, used by every AI tool.

- ``recorder``: the process-wide recorder; tools wrap each call with ``recorder.track(...)``.
- ``model``: ``LLMCall``, one recorded call.
- ``ports``: ``BaseLLMCallRepository``, where records are written.
"""
