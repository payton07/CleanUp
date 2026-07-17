"""Core engine: detection, configuration, collection, sorting, undo.

Pure logic with no terminal/UI dependencies. Interfaces (CLI, web) build on
top of this and receive progress through the event callbacks in `engine`.
"""
