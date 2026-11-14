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

Automated event workflow
------------------------

``run_auto_cmt`` runs acquisition, processing, Green's-function preparation
and inversion from a single event definition. Each call takes an event-specific
``output_dir``. ``waveform_source="fdsn"`` accepts the same provider names,
ObsPy clients and ordered provider lists as ``get_mseed_stationxml``.
For offline runs use ``waveform_source="local"`` and pass the downloaded
station DataFrame or ``metadata/stations_downloaded.csv`` as ``station_df``.
Keep its acquisition geometry, phase arrivals, waveform paths and StationXML
paths. Resolve those fields for the chosen origin before reusing a table at
a relocated source. Relative paths in a CSV are resolved from that CSV.

The inclusive inner radius defaults to 0 km in both acquisition entry points.
Set ``min_radius_km=100`` to reproduce the earlier lower limit. With
``max_radius_km=None``, the outer radius comes from the event magnitude and
``radius_scale_factor=1.66``. The automatic magnitude range is 3.5–8.0.
An explicit ``max_radius_km`` also supports events outside that range.
The automated CMT channel preference defaults to ``HH, BH, LH``. Pass
``channels`` and ``channel_priority`` together to use another preference.

``before_p`` and ``after_s`` define the initial station-specific request.
The automated FDSN route extends it as needed for the processed record,
including the reference-time and residual-correlation margins. The
processing window and band are set separately. Pass the main settings
``motion`` (``DISP``, ``VEL`` or ``ACC``), ``freqmin``, ``freqmax`` and
``dt`` directly. Use ``processing_options`` for options such as
``inversion_duration``, ``corners``, ``window_start_phase``,
``time_before_window_start``, ``window_end_phase``,
``time_after_window_end``, ``max_correlation_shift`` and
``max_reference_time_shift``.

Supply ``depths_km`` to set the trial depths. PyFK and Syngine default to
the supplied event depth, and custom files default to the manifest depths.
With ``reference_time_shifts=None`` the fit uses the supplied origin.
Pass an explicit sequence to search shifts and depths jointly. Shifts are in
seconds relative to that origin and must be multiples of ``dt``.
The requested shift range is reserved automatically during processing.
``correlate=True`` additionally allows per-station residual shifts at each
candidate using the existing bounded correlation.

For a depth search followed by a shift scan at the preferred depth, first run
``run_auto_cmt`` with no scan and reserve the intended shift in
``processing_options["max_reference_time_shift"]``. Then call
``mttime_inversion_oshift`` with the returned ``station_df``, ``gf_manifest``
and one depth. The underlying Green's-function archive can serve both calls.

.. code-block:: python

   from mttime.workflows import run_auto_cmt

   run = run_auto_cmt(
       event_id, event_time, lon_event, lat_event, depth_km, mag_event,
       output_dir=event_output,
       gf_source="pyfk",
       velocity_model=layered_model,
       depths_km=[8, 10, 12, 14],
       client=geonet_nrt,
       min_radius_km=0,
       max_radius_km=None,
       channels=("HH?", "BH?", "LH?"),
       channel_priority=("HH", "BH", "LH"),
       freqmin=0.02, freqmax=0.06, dt=1.0, motion="VEL",
       processing_options={"inversion_duration": 150.0},
       reference_time_shifts=range(-5, 6),
       drop_stations=["EAZ"],
       azimuth_control={
           "azimuth_selection": True,
           "azimuth_min_sectors": 3,
           "azimuth_max_stations_per_sector": 2,
           "minimum_stations": 4,
       },
       station_jackknife={"jackknife_min_stations": 4},
       degree=6,
       plot=True,
       show=False,
   )
   run["results"]["summary"]
   run["results"]["station_jackknife"]

For Syngine use ``gf_source="syngine"`` and pass provider settings such as
``gf_options={"syngine_model": "iasp91_2s", "max_workers": 4}``. See the
two generator docstrings for their full option sets. ``inversion_options``
accepts the additional output settings, such as ``plot_views``,
``figure_format``, ``figure_dpi``, ``write_option`` and ``save_tables``.
In the shift scan it also accepts ``progress``, ``suppress_output`` and
``on_error``. For the single-reference path, ``run["inversion"]`` contains
the completed MTtime object. For a scan, use ``run["results"]["origin_shift_summary"]``
and the full solutions/fits tables. MTtime's search coordinates are fixed at
the supplied epicentre throughout these calls.

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
Use ``gf_source="custom"`` to load an exported MTtime SAC library. For
example, ``sw4_greens.export_mttime_gfs()`` returns the expected manifest
DataFrame and writes its SAC library. Its CSV is also accepted.

.. code-block:: python

   run = run_auto_cmt(
       event_id, relocated_origin, relocated_lon, relocated_lat,
       relocated_depth_km, magnitude,
       output_dir=event_output,
       waveform_source="local",
       station_df=raw_station_table,
       gf_source="custom",
       gf_options={"manifest": sw4_manifest},
       motion="VEL", freqmin=0.02, freqmax=0.06, dt=1.0,
       processing_options={"inversion_duration": 150.0},
       degree=6,
   )

Set the motion, filter, sampling and window to those used for the export.
The manifest requires ``station_id``, ``requested_depth_km`` (or
``source_depth_km``), ``basis``, ``motion``, ``units``, ``freqmin`` and
``freqmax``. Declare ``green="tensor"`` for Cartesian tensor files. If
``green`` is absent, the library is interpreted as Herrmann. Include
``npts``, ``dt_s``, ``corners``, and ``reference_moment_nm`` where
available for additional validation. A ``path`` column can identify one
common GF directory. Supply ``gf_options["path_to_green"]`` to specify the
directory explicitly. Paths in a CSV are relative to the CSV when relative.
For a DataFrame, relative paths resolve from the working directory.

SAC names use ``<station_id>.<depth_km:0.4f>.<basis>``, such as
``NZ.MLZ.10.56.0000.Zxy``. A tensor set has all six Cartesian bases
(``xx, yy, zz, xy, xz, yz``) for each of Z, R and T. A vertical-only
inversion can use the six Z bases alone. The source tensor is in
north, east and down coordinates. Receiver components use the same ZRT
orientation as the observations. The samples start at source-reference zero
and match each station's ``dt`` and ``npts``. Amplitudes use cm, cm/s or
cm/s² for a reference moment of ``1e13 N m`` (``1e20 dyne-cm``). For
an existing processed station table, pass the manifest directly to
``run_mttime_inversion`` or ``mttime_inversion_oshift`` to skip acquisition
and processing.

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

Station controls
~~~~~~~~~~~~~~~~

``run_mttime_inversion``, ``mttime_inversion_oshift`` and ``run_auto_cmt``
all accept ``azimuth_control`` and ``station_jackknife``. Omit either, or
pass ``False``, to disable it. ``True`` enables its defaults. A mapping
enables the feature and overrides the supplied keys.

``drop_stations`` accepts exact ``NET.STA.LOC`` IDs and
``(network, station, location)`` tuples. Unambiguous ``STA`` and
``NET.STA`` shorthand are supported. Where a code is ambiguous, specify the
full ID. A selector absent from the input station table is ignored.

Azimuth control applies manual drops and the component mask before assigning
the remaining active stations to eight 45° sectors beginning at geographic
north. The defaults are ``azimuth_min_sectors=3``,
``azimuth_max_stations_per_sector=2``, and ``minimum_stations=4``.
Within each sector, stations are ranked by channel preference, epicentral
distance and exact station ID. The acquisition priority is recorded and
reused, and the staged inversion accepts a ``channel_priority`` override.
Prediction-only stations can still be plotted and do not fill sector slots.
The scan uses one station set for all tested depths and shifts.

The jackknife omits each active station and finds its best fit on the parent
inversion's tested depths and reference-time shifts. The original inversion
supplies station-wise weighted normal equations. Each omission reuses those
terms and the same per-station residual alignment. ``jackknife_min_stations``
sets how many active stations must remain, with a default of four. Set
``jackknife_opposing_station=True`` for a delete-two sensitivity analysis
using all pairs within ``jackknife_opposition_tolerance_deg`` of opposite
azimuths, with a default tolerance of 20°. The existing
``run_mttime_resampling`` remains available for sampled opposing-pair ensembles.

The jackknife table contains source depth/time, Mw, moment and tensor,
VR in percent, Kagan rotation for the DC orientation, retained azimuthal
coverage and the held-out fit. The weighted RMS is the square root of the
weighted sum of squared held-out residuals divided by the active held-out
sample count. It uses the parent's weights at the selected candidate.
Rows with too few stations or no numerically full-rank solution are
marked as skipped.

With table output enabled, ``station_selection.csv`` and
``station_jackknife.csv`` appear in the output manifest when applicable.
The staged single-reference path writes them in its results directory
and exposes ``inversion.station_selection`` and
``inversion.station_jackknife``. A shift scan writes them in the scan root
and exposes their records in ``summary_df.attrs["station_selection"]`` and
``summary_df.attrs["station_jackknife"]``. Convert either list to a DataFrame
with ``pd.DataFrame.from_records``. The automated path writes its
selection audit under ``metadata/`` and returns both tables in the run mapping.

Figures and solution tables
~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
