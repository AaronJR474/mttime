.. _workflows:

==========================
Additive workflow helpers
==========================

Purpose and scope
-----------------

The ``mttime.workflows`` package is an additive layer around upstream MTtime. It
is intentionally separate from ``mttime.core`` so that data preparation,
Green's-function acquisition/generation and reproducibility utilities do not
obscure the underlying inversion classes.

The main modules are:

``mttime.workflows.mttime_helpers``
    End-to-end event/station acquisition, waveform processing, Green's-function
    generation, ``mtinv.in`` construction, inversion execution, timing scans,
    resampling and output management.

``mttime.workflows.gf_helpers``
    Reusable velocity-model and Herrmann-basis utilities used by the PyFK path.

Workflow contract
-----------------

The normal sequence is deliberately staged:

1. ``get_mseed_stationxml`` discovers stations and acquires waveform/StationXML
   inputs.
2. ``process_mseed_sac`` removes response, rotates to ZRT, filters/resamples and
   writes the processed observation contract.
3. Generate Green's functions with ``generate_pyfk_gfs`` or
   ``generate_syngine_gfs``.
4. ``write_mtinv`` validates the processed data/GF manifests and writes a native
   MTtime configuration when an inspectable file is wanted.
5. ``run_mttime_inversion`` performs step 4 internally and executes MTtime,
   returning the authoritative station table, inversion object, solution table,
   station-fit table and output manifest.

The processed station table is the interface between stages. Reusing that table
also preserves the timing assumptions, station geometry and exact final sample
contract used when the Green's functions were generated.

Green's-function routes
-----------------------

PyFK: fixed 1-D layered model
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For a common horizontally layered Earth model, ``generate_pyfk_gfs`` calls PyFK
for the requested source depths/receiver distances and writes MTtime Herrmann
basis SAC files. This is the simplest local/offline helper route.

PyFK: profiles derived from a 3-D velocity model
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``gf_helpers.VelocityGrid3D`` and ``build_regular_velocity_grid`` support
rectilinear, triangulated and rotated-rectilinear tabular velocity models.
Profiles can be extracted vertically at a station or sampled along an
event-to-station path and converted to the layered arrays required by
``pyfk.SeisModel``.

This is a **3-D-model-informed 1-D calculation**. The helper interpolates the 3-D
velocity model and reduces it to one representative layered model for each PyFK
calculation. It does not solve the full 3-D elastic wave equation and should not
be described as a 3-D PyFK solver.

Externally generated 3-D Green's functions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Upstream MTtime already supports tensor Green's functions produced by external
3-D solvers (for example the SW4 reciprocal-GF route in ``mttime.core.utils``).
Those products remain a separate path from ``gf_helpers``: the helper does not
run SW4, but MTtime can consume correctly prepared external tensor GFs.

EarthScope Syngine
~~~~~~~~~~~~~~~~~~

``generate_syngine_gfs`` requests the ten SeisComP/Instaseis Green's functions
from EarthScope Syngine, converts them to MTtime's Cartesian tensor basis,
normalizes the reference moment/units and then applies the same final
station-specific sampling/filter contract used by the local workflow.

Syngine is independent of PyFK. A Syngine-only installation can therefore use
``MTTIME_NO_PYFK=1`` on Linux/WSL, while native Windows/macOS installs skip the
automatic PyFK dependency.

PyFK platform/dependency policy
-------------------------------

The default Git installation requests PyFK only when ``platform_system ==
"Linux"``. WSL reports Linux and follows this route. Released PyFK 0.3.x is used
for Python 3.8/3.9; Python 3.10--3.12 uses the pinned upstream PR #20 commit in
``setup.py`` until an official compatible release exists.

PyFK imports are lazy inside the PyFK-specific functions. Importing
``mttime.workflows`` or running Syngine does not itself require ``import pyfk``.

Inversion and outputs
---------------------

``run_mttime_inversion`` accepts helper-managed views:

* ``"waveform"`` -- native MTtime waveform fit.
* ``"depth"`` -- native MTtime depth sensitivity; skipped for one trial depth.
* ``"map"`` -- native MTtime map view; Cartopy is optional but required for this
  view.
* ``"lune"`` -- native MTtime source-type lune; skipped for degree 5.
* ``"cmt"`` -- helper CMT panel produced by ``plot_cmt_summary`` from the
  preferred MTtime tensor.

The ``"cmt"`` adapter converts MTtime's dyne-cm RTP components to N m, carries
through Mw, DC/CLVD/ISO, variance reduction, preferred depth and both nodal
planes, and then calls ``plot_cmt_summary``. The figure does not alter the
inversion or decomposition.

Example
-------

.. code-block:: python

   from mttime.workflows.mttime_helpers import run_mttime_inversion

   mtinv_stations, inversion, solution_df, station_fit_df, outputs = (
       run_mttime_inversion(
           event_df,
           station_df,
           gf_manifest,
           output_file="event/mtinv.in",
           path_to_data="event/processed/data",
           path_to_green="event/greens",
           degree=6,
           plot_views=("waveform", "depth", "map", "lune", "cmt"),
           write_option="all",
           show=False,
       )
   )

Weighted normal-equation improvement
------------------------------------

The fork contains one small core numerical implementation improvement in
``mttime.core.inversion.Inversion``. Upstream formed weighted normal equations as
``G.T @ diag(w) @ d`` and ``G.T @ diag(w) @ G``. This fork evaluates the same
expressions by row scaling:

.. code-block:: python

   Gtd = G.T @ (w * d)
   GtG = G.T @ (w[:, None] * G)

The result is algebraically identical for the same floating-point inputs, but it
avoids explicitly allocating the dense ``N x N`` diagonal weight matrix. The
change is intentionally documented as an implementation/memory improvement, not
as a different inversion algorithm.
