"""Optional, fully-local AI features backed by Ollama.

Everything here is opt-in and degrades gracefully: if the Ollama server is not
running, the rest of CleanUp works exactly as before. No network calls leave the
machine and no API key is involved.
"""
