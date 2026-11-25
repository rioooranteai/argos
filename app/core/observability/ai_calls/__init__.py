"""AI call records — always on, stored in Argos' own database.

- ``recorder`` — the process-wide recorder; every AI tool wraps its call in ``recorder.track(...)``
- ``model``    — ``LLMCall``, one recorded call
- ``ports``    — ``BaseLLMCallRepository``, where records are written
"""
