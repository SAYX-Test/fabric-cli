# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Module entry point so the CLI can run as ``python -m fabric_cli``.

The ``fab`` console script is the normal entry point. This module matters when
that script is unavailable: when the Scripts directory is off PATH, or when an
endpoint policy blocks the generated launcher executable.
"""

from fabric_cli.main import main

if __name__ == "__main__":
    main()
