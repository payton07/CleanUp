"""PyInstaller entry point — bundles the CleanUp CLI into a standalone binary."""

from cleanup.cli.main import main

if __name__ == "__main__":
    main()
