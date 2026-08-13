Changelog
=========

Current release is version 1.1.0

Fork workflow update (2026-08-13)
---------------------------------

- Package ``mttime.workflows`` as an installed subpackage by adding its missing
  ``__init__.py``.
- Add a PEP 517 ``pyproject.toml`` build declaration for direct ``pip``/Git
  installations.
- Install the supported PyFK backend automatically on Linux/WSL, with a pinned
  Python-3.10--3.12 upstream PR commit and a fork-specific ``MTTIME_NO_PYFK``
  opt-out for Syngine-only installs.
- Document the workflow helpers, 1-D and 3-D-model-informed PyFK routes, external
  3-D tensor GFs and the independent EarthScope Syngine backend.
- Add the helper-managed ``cmt`` plot view using ``plot_cmt_summary``.
- Retain the weighted-normal-equation row-scaling improvement in the inversion,
  avoiding construction of a dense diagonal weight matrix.
- Replace the conflicted license file with clean LGPL-3.0 text and align package
  metadata with the upstream LGPL license; retain the LLNL NOTICE.


2026-04-14
----------

- Pandas 3.0 will change, modified _update_table_index in inverse configuration.


2021-04-16
----------

- Package name changed to mttime.
- Fixes to saving focal mechanisms in vector file format.
- Correct gil7 model and update examples.


2020-01-20
----------

- fixes to plotting routines.
- data/synthetics in cartesian NED coordinates.
- utility function to read SW4 reciprocal Green's functions.

1.0.0   (2020-09-25)
--------------------

- Modifications to package structure, objects and functions.
- pandas is now required.
- Modules categorized based on functionality.
- Minor changes to input file format.
- Added top-level script "tdmtpy-run" to execute package from shell.
- New function for plotting depth sensitivity.
- Added documentation.

0.1.0 (2020-02-26)
------------------

Initial release.
