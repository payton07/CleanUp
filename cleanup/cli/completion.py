"""Shell completion script generation (bash / zsh).

Options are read from the argparse parser so the completion never drifts from
the actual flags. Emit with ``cleanup --print-completion bash`` and source it.
"""

from __future__ import annotations

import argparse


def option_strings(parser: argparse.ArgumentParser) -> list[str]:
    opts: set[str] = set()
    for action in parser._actions:
        opts.update(action.option_strings)
    return sorted(opts)


def completion_script(shell: str, parser: argparse.ArgumentParser, prog: str = "cleanup") -> str:
    opts = " ".join(option_strings(parser))
    if shell == "bash":
        return f"""# bash completion for {prog} — source this file or add to ~/.bashrc
_cleanup_complete() {{
  local cur="${{COMP_WORDS[COMP_CWORD]}}"
  if [[ "$cur" == -* ]]; then
    COMPREPLY=( $(compgen -W "{opts}" -- "$cur") )
  else
    COMPREPLY=( $(compgen -d -- "$cur") )
  fi
}}
complete -F _cleanup_complete {prog}
"""
    # zsh
    return f"""#compdef {prog}
# zsh completion for {prog} — put on your $fpath or source it
_arguments '*:path:_files -/'
compadd -- {opts}
"""
