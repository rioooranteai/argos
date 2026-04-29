"""Conversation domain — multi-thread chat history per user.

Replaces the legacy single-row-per-session ConversationStore with a proper
two-entity model: User (1) → Conversation (N) → Message (N).
"""
