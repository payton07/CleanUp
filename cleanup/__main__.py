"""Enable ``python -m cleanup`` and serve as the frozen-binary entry point."""

from cleanup.cli.main import main

if __name__ == "__main__":
    main()
