# SPDX-License-Identifier: LGPL-3.0-only
"""Streamlined waveform and Green's-function preparation for MTtime inversions.

The module joins five stages that are deliberately kept separate:

1. ``get_mseed_stationxml`` discovers suitable three-component stations within
   a configurable epicentral annulus, selects ground-level sensors by default,
   calculates theoretical P and S arrivals, and downloads only the waveform
   windows required around those arrivals.
2. ``process_mseed_sac`` removes instrument responses, rotates observations to
   ZRT, applies the inversion filter, stores a station-specific phase-bounded
   observation window, and derives the exact sample at event origin.
3. ``generate_pyfk_gfs`` and ``generate_syngine_gfs`` provide independent
   Green's-function backends. The pyFK path retains the existing layered-model
   workflow and writes Herrmann records; the Syngine path requests Instaseis
   SeisComP Green's functions from EarthScope, converts them to MTtime's Cartesian
   tensor basis, and applies the same station-specific final processing contract.
4. ``write_mtinv`` is the low-level configuration writer. It validates the
   processed data and Green's-function manifests and writes ``mtinv.in`` for
   inspection or external MTtime use.
5. ``run_mttime_inversion`` is the normal one-call interface. It invokes
   ``write_mtinv`` internally, runs MTtime, writes numerical solutions, saves
   diagnostic figures, and exports compact solution and station-fit tables.

The processed station table is the contract between the stages. Only stations
that pass ``process_mseed_sac`` should be sent to ``generate_pyfk_gfs`` or
``generate_syngine_gfs`` and then to ``run_mttime_inversion``. ``write_mtinv`` remains available when only a validated
configuration file is required.

Timing convention
-----------------
Observed files may begin before event origin and may be longer than their
matching Green's functions. ``process_mseed_sac`` preserves the catalog-origin
sample as the immutable timing datum and can reserve symmetric margins for a
later global reference-time shift and optional bounded station correlation.
``write_mtinv`` keeps the MTtime ``datetime`` header fixed at the catalog origin
and selects the global source/reference time only through the station ``ts``
indices. Optional correlation is then a residual station-wise adjustment around
that selected reference; it is not allowed to search the complete observation
record.

Units
-----
Raw response-corrected observations are returned by ObsPy in SI units and are
scaled to centimetre-based units before writing. Dynamic ``calculate_gf`` output
is treated explicitly through ``pyfk_native_motion``. Validation against the CPS
Herrmann benchmark showed that native pyFK dynamic traces must be treated as
velocity for this workflow, so the default is ``"VEL"`` and displacement targets
are integrated once before the inversion bandpass.

Depth convention
----------------
``depths_km`` passed to ``generate_pyfk_gfs`` are pyFK/MTtime source depths below
the selected layered-model top. For the initial NZ workflow, use
``surface_depth_km=0`` so catalog depth, pyFK depth, Green's-function filename,
and MTtime trial depth share the same datum.

Station-selection convention
----------------------------
Regional station discovery uses an inclusive ``min_radius_km``--``max_radius_km``
annulus. The minimum remains a configurable regional-workflow choice (100 km by
default), while ``max_radius_km=None`` derives the outer radius from magnitude
through :func:`get_max_radius`; an explicit ``max_radius_km`` remains a direct
user override. By default, only selected three-component families whose
StationXML ``Channel.depth`` is zero are retained, preventing borehole or other
below-surface sensors from being mixed inadvertently with surface records.

Existing-output policy
----------------------
Processed observations and Green's functions carry short deterministic
signatures in their SAC headers. With ``overwrite=False``, matching files are
reused and returned normally. Missing, partial, corrupt or incompatible files
are regenerated automatically. ``overwrite=True`` bypasses the cache and
forces regeneration. This prevents an existing output from producing an empty
station or Green's-function manifest.

Version 0.4.3
-------------
``run_mttime_inversion`` adds ``"cmt"`` to the helper-managed plot views and
routes that view through :func:`plot_cmt_summary` using the preferred MTtime
solution. The generated figure reports the MTtime source decomposition, scalar
moment, magnitude, centroid depth, tensor components, nodal planes and principal
axes. Existing native ``waveform``, ``depth``, ``map`` and ``lune`` views are
unchanged.

Version 0.4.2
-------------
``get_mseed_stationxml`` now uses ``max_radius_km=None`` by default and derives
the outer acquisition radius from event magnitude with :func:`get_max_radius`;
an explicit maximum radius remains an exact user override and
``radius_scale_factor`` exposes the existing magnitude-radius scale. The pyFK
backend now accepts ``grid_mode="station"`` for a ``VelocityGrid3D``, extracting
one vertical layered model at each authoritative processed-station coordinate.
The established 1-D, fixed-profile and event-to-station path modes, pyFK
numerics, cache schemas, waveform processing and MTtime inversion algorithms are
otherwise unchanged. Parallel execution of ``mttime_inversion_oshift`` is not
introduced in this release; shift-level process parallelism is reserved for a
separately validated update.

Version 0.4.1
-------------
``generate_syngine_gfs`` corrects and hardens the Syngine tensor backend after
end-to-end closure testing. Syngine request distances are now computed on the
geocentric sphere from WGS84 geographic latitudes, while the authoritative
station-table azimuth is retained and the validated SeisComP path-frame rotation
``alpha = (180 - azimuth) mod 360`` is used for the Cartesian tensor expansion.
Syngine tensor SAC files are rebuilt with a fresh source-relative epoch so
``b=0`` survives serialization, and cache validation now checks that invariant.
The Syngine cache schema is advanced so tensor files produced with the earlier
geometry/timing convention cannot be reused. Remote station requests at each
trial depth may be issued concurrently through the new ``max_workers`` argument;
``max_workers=1`` retains sequential acquisition. Observation and pyFK cache
compatibility remain pinned to their 0.4.0 schemas, so these Syngine-only changes
do not invalidate otherwise compatible existing observation or pyFK files.

Version 0.4.0
-------------
``generate_syngine_gfs`` adds EarthScope Syngine as an independent Green's-
function provider without changing the existing pyFK path. Syngine's ten
Instaseis/SeisComP Green's functions are requested only over the duration needed
for each processed station, converted analytically to MTtime's 18-component
north-east-down Cartesian tensor basis, normalized to MTtime's 1e20 dyne-cm
reference moment and centimetre-based motion units, then filtered and resampled
locally to the same final station-specific ``npts``/``dt`` contract used by pyFK.
``syngine_dt=None`` leaves the service sampling at its model default; an explicit
``syngine_dt`` is only a server-side resampling request and is independent of the
final MTtime ``dt``. ``write_mtinv`` now infers ``green=tensor`` from a Syngine
manifest while manifests without an explicit format retain the historical
``green=herrmann`` default. Existing pyFK generation, timing, inversion and
component-selection behaviour is otherwise unchanged.

Version 0.3.9
-------------
``generate_pyfk_gfs`` now exposes pyFK's spherical-Earth model-flattening switch
through ``pyfk_flattening``. The default remains ``False`` and therefore preserves
the previous flat-layered-Earth behaviour exactly. When enabled, the flag is passed
only to :class:`pyfk.SeisModel`; it is recorded in Green's-function/model manifests
and included in the deterministic cache signature so flattened and unflattened
Green's functions cannot be mixed or reused accidentally. No other Green's-function,
waveform-processing, timing, inversion or component-selection behaviour is changed.

Version 0.3.8
-------------
``process_mseed_sac`` no longer rejects otherwise safe leading zero padding merely
because ``freqmin`` is lowered. The previous pre-arrival padding gate used the
larger of the reserved timing margin and one longest retained period
(``1/freqmin``). That conflated a filter-period heuristic with actual missing-signal
coverage, so changing from 0.02 to 0.01 Hz could drop stations whose raw records
were unchanged and still began well before P. Leading padding is now permitted
when the common raw start remains earlier than P by the combined global-reference
and residual-correlation margin. Missing coverage that reaches this protected
P-wave interval still fails, and missing end coverage remains strictly disallowed.
No inversion, Green's-function, timing-index, response-removal, filtering or
component-selection behaviour is otherwise changed.

Version 0.3.7
-------------
``write_mtinv`` now accepts ``components="ZR"`` as a helper-level component
selection. Upstream MTtime does not accept ``ZR`` as a global components header,
so the helper writes ``components ZRT`` and masks each station's existing ``used``
flag to ``110`` (Z/R active, T prediction-only). Existing station-specific masks
are intersected with this ZR mask rather than overwritten.
``run_mttime_inversion``, ``mttime_inversion_oshift`` and
``run_mttime_resampling`` continue to forward the same ``components`` argument, so
``ZR`` is supported consistently through all public inversion wrappers.

Version 0.3.6
-------------
The MTtime ``datetime`` header now remains the immutable catalog origin for every
global reference-time trial; ``reference_time_shift`` changes only the observed
``ts``/``reference_ts`` indices that are aligned with Green's-function sample zero.
The timing initializer reconstructs the selected reference from catalog origin plus
that shift. The validated pyFK dynamic-motion default is now ``"VEL"``. Green's
function generation also applies convergence-tested pyFK defaults ``dk=0.15`` and
``kmax=15.0`` automatically, while explicit ``pyfk_config_kwargs`` values retain
precedence.

Version 0.3.5
-------------
``get_mseed_stationxml`` now accepts one FDSN client or an ordered list/tuple of
clients and combines successful stations in the existing raw directories without
provider-specific subfolders. ``process_mseed_sac`` retains its filtered record
section and additionally exports a response-corrected, rotated, unfiltered ZRT
record section for post-processing inspection. ``generate_pyfk_gfs`` now accepts
``pyfk_npt=None`` and selects the smallest even internal record length that covers
the longest requested MTtime trace plus its zero-phase filter guard; explicit even
values remain available when a longer pyFK record is desired. Timing-history
sample columns are restored with an explicit integer dtype to avoid pandas
incompatible-dtype assignment warnings.

Version 0.3.4
-------------
``run_mttime_inversion`` now installs catalog-origin and selected-reference
metadata from the authoritative table returned by ``write_mtinv`` before MTtime
starts. This respects MTtime's lifecycle: observed streams remain unloaded until
``Inversion.invert()`` calls its normal data loader exactly once. The timing
initializer no longer accesses ``inversion.streams`` before that point. The
origin-shift wrapper also tags saved figure filenames with the run index and
signed shift so figures remain self-identifying outside their run directories.
Depth-specific residual-correlation diagnostics are reconstructed from the
recorded per-depth correlation history rather than relying on mutable final-run
configuration state.

Version 0.3.3
-------------
``run_mttime_inversion`` now returns the authoritative station table produced by
``write_mtinv`` as its first result, followed by the MTtime inversion object and
the existing solution, station-fit and output-manifest tables. The origin-shift
and opposing-pair resampling wrappers unpack this five-result interface and use
the written station table as the source of truth for the number of stations in
each run. Numerical inversion, plotting, table-export and timing behaviour are
otherwise unchanged.

Version 0.3.2
-------------
``run_mttime_inversion`` is now the complete public orchestration interface: it
writes a validated ``mtinv.in`` through ``write_mtinv`` and immediately executes
that configuration. The low-level writer remains public for inspection and
external MTtime workflows. The origin-shift and opposing-pair wrappers now call
the same orchestration path, eliminating duplicated write/run logic. Resampling
also accepts one global ``reference_time_shift``. Native MTtime ``plot`` is
forwarded explicitly, while helper-managed saved views remain controlled by
``plot_views``.

Version 0.3.1
-------------
Processed observations may reserve a symmetric global reference-time margin in
addition to the bounded station-correlation margin. ``write_mtinv`` can align
Green's-function sample zero with a user-selected time before or after the catalog
origin without regenerating observations or Green's functions. Correlation remains
a residual station-wise adjustment around that selected global reference. The new
``mttime_inversion_oshift`` wrapper performs and stores a reproducible scan across
multiple global reference-time shifts.

Version 0.3.0
-------------
Common 1-D and fixed-profile models may now batch all receiver distances in one
pyFK calculation per source depth and source type. Station-specific path models
remain unchanged and continue to use one representative 1-D profile per station.
Processed station tables now carry event-centred polar coordinates ``r_epi``
(km) and ``r_azi`` (radians). Geometry-balanced opposing-pair selection and a
silent MTtime resampling wrapper have been added for downstream robustness tests.

Version 0.2.0
-------------
The pyFK native motion order is explicit. The default preserves pyFK's
documented displacement interpretation, while ``pyfk_native_motion="VEL"``
enables the issue-#3 integration hypothesis as a controlled A/B test. Optional
Qs/Qp model columns, raw late-tail diagnostics, and an explicit correlation
objective have been added. Station discovery,
StationXML validation and observation processing are otherwise unchanged.

Version 0.2.2
-------------
A missing raw prefix may be zero-padded only when it lies wholly before the
earliest protected P-wave time. This preserves the exact event-origin MTtime
baseline without discarding otherwise usable records that still contain a long,
quiet pre-arrival interval. Missing end coverage and any start deficit reaching
the protected signal interval remain fatal. Padding is explicit, recorded in the
processed-station table, and can be disabled with
``pad_missing_prearrival=False``.

Version 0.2.1
-------------
Processed-window coverage and final resampling now allow the unavoidable
one-native-sample offset between an arbitrary UTC boundary and a station's sample
grid. Larger true coverage deficits still fail and report the measured offset.
The bounded-correlation ``ts`` assignment also preserves the existing integer
dtype explicitly.

Version 0.1.9
-------------
Station discovery now uses a configurable distance annulus and selects
StationXML ground-level channels by default. Selected sensor coordinates replace
coarser station-site coordinates in source--receiver geometry. The release also
hardens SAC sample-interval comparisons, raw-cache coverage checks, integer and
finite-value validation, MTtime component-use flags, and source placement at
very thin velocity-model interfaces.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence
from contextlib import contextmanager, redirect_stdout, redirect_stderr

import hashlib
import os
import json
import io
import uuid

import numpy as np
from numpy.typing import ArrayLike
import pandas as pd
from pyproj import Geod

__version__ = "0.4.3"

# Cache compatibility is backend-specific. Version 0.4.3 changes plotting
# orchestration only and therefore retains the 0.4.x observation/GF cache
# contracts.
_OBSERVATION_CACHE_COMPAT_VERSION = "0.4.0"
_PYFK_CACHE_COMPAT_VERSION = "0.4.0"
_SYNGINE_CACHE_COMPAT_VERSION = "0.4.1"

__all__ = [
    "__version__",
    "LatLongToPolar",
    "get_max_radius",
    "get_mseed_stationxml",
    "process_mseed_sac",
    "generate_pyfk_gfs",
    "generate_syngine_gfs",
    "write_mtinv",
    "run_mttime_inversion",
    "mttime_inversion_oshift",
    "select_opposing_station_pairs",
    "run_mttime_resampling",
    "plot_cmt_summary",
]

_HERRMANN_BASES = ("ZSS", "ZDS", "ZDD", "ZEX", "RSS", "RDS", "RDD", "REX", "TSS", "TDS")
_SYNGINE_BASES = ("TSS", "ZSS", "RSS", "TDS", "ZDS", "RDS", "ZDD", "RDD", "ZEP", "REP")
_TENSOR_BASES = tuple(
    f"{component}{basis}"
    for component in ("Z", "R", "T")
    for basis in ("xx", "yy", "zz", "xy", "xz", "yz")
)
_SYNGINE_MTTIME_REFERENCE_MOMENT_NM = 1.0e13  # 1e20 dyne-cm
_SYNGINE_SI_TO_CM_SCALE = 100.0
_SYNGINE_MTTIME_AMPLITUDE_SCALE = (
    _SYNGINE_MTTIME_REFERENCE_MOMENT_NM * _SYNGINE_SI_TO_CM_SCALE
)
_COMPONENT_SCHEMES = ("ZNE", "Z12", "123")
_GROUND_LEVEL_DEPTH_ATOL_M = 1e-6
_CHANNEL_COORDINATE_ATOL_DEG = 1e-4
_CHANNEL_ELEVATION_ATOL_M = 1.0
_SAMPLE_INTERVAL_ATOL_S = 1e-8
_SAMPLE_INTERVAL_RTOL = 1e-6
_PYFK_CONFIG_DEFAULTS = {"dk": 0.15, "kmax": 15.0}
_EVENT_ALIASES = {
    "event_id": ("event_id", "eventid", "evid"),
    "origin_time": ("origin_time", "origin", "datetime", "time"),
    "event_lon": ("event_lon", "ev_lon", "longitude", "lon"),
    "event_lat": ("event_lat", "ev_lat", "latitude", "lat"),
    "event_depth_km": ("event_depth_km", "depth_km", "ev_depth_km", "depth"),
}

# Four physically equivalent orientations of a double-couple frame.
_DC_SYMMETRIES = (
    np.diag([1.0, 1.0, 1.0]),
    np.diag([1.0, -1.0, -1.0]),
    np.diag([-1.0, 1.0, -1.0]),
    np.diag([-1.0, -1.0, 1.0]),
)


def dc_matrix_from_sdr(
    strike: float,
    dip: float,
    rake: float,
) -> np.ndarray:
    """
    Construct a normalized double-couple moment tensor in NED coordinates.

    Parameters
    ----------
    strike, dip, rake
        Fault-plane angles in degrees. Strike is clockwise from north,
        dip is measured downward from horizontal, and rake follows the
        standard seismological convention.

    Returns
    -------
    numpy.ndarray
        Symmetric 3 x 3 moment tensor in north-east-down coordinates.
    """
    angles = np.asarray([strike, dip, rake], dtype=float)

    if not np.isfinite(angles).all():
        raise ValueError("strike, dip and rake must be finite.")

    if not 0.0 <= dip <= 90.0:
        raise ValueError("dip must lie within [0, 90] degrees.")

    strike, dip, rake = np.deg2rad(angles)

    sd, cd = np.sin(dip), np.cos(dip)
    s2d, c2d = np.sin(2.0 * dip), np.cos(2.0 * dip)

    ss, cs = np.sin(strike), np.cos(strike)
    s2s, c2s = np.sin(2.0 * strike), np.cos(2.0 * strike)

    sr, cr = np.sin(rake), np.cos(rake)

    mnn = -(sd * cr * s2s + s2d * sr * ss**2)
    mee = sd * cr * s2s - s2d * sr * cs**2
    mdd = s2d * sr

    mne = sd * cr * c2s + 0.5 * s2d * sr * s2s
    mnd = -(cd * cr * cs + c2d * sr * ss)
    med = -(cd * cr * ss - c2d * sr * cs)

    return np.array([
        [mnn, mne, mnd],
        [mne, mee, med],
        [mnd, med, mdd],
    ])


def _dc_orientation_frame(moment_tensor: ArrayLike) -> np.ndarray:
    """
    Return the right-handed P-B-T eigenvector frame of a moment tensor.
    """
    mt = np.asarray(moment_tensor, dtype=float)

    if mt.shape != (3, 3):
        raise ValueError("moment_tensor must have shape (3, 3).")

    if not np.isfinite(mt).all():
        raise ValueError("moment_tensor must contain only finite values.")

    # Enforce symmetry and remove any isotropic component.
    mt = 0.5 * (mt + mt.T)
    mt = mt - np.trace(mt) / 3.0 * np.eye(3)

    scale = np.linalg.norm(mt)

    if scale <= np.finfo(float).eps:
        raise ValueError(
            "The tensor has no stable deviatoric orientation."
        )

    # eigh returns eigenvectors in ascending eigenvalue order:
    # pressure, intermediate/null, tension.
    eigenvalues, frame = np.linalg.eigh(mt)

    # Repeated eigenvalues imply an undefined rotation around one axis.
    minimum_gap = np.min(np.abs(np.diff(eigenvalues)))

    if minimum_gap <= 1e-10 * scale:
        raise ValueError(
            "The tensor has repeated principal values; "
            "the DC orientation is not unique."
        )

    # Eigenvectors have arbitrary signs. Enforce a proper rotation frame.
    if np.linalg.det(frame) < 0.0:
        frame[:, 0] *= -1.0

    return frame


def kagan_angle_mt(
    moment_tensor_a: ArrayLike,
    moment_tensor_b: ArrayLike,
) -> float:
    """
    Compute the Kagan angle between two moment-tensor orientations.

    Both tensors must use the same Cartesian coordinate convention.

    Returns
    -------
    float
        Minimum double-couple rotation angle in degrees, from 0 to 120.
    """
    frame_a = _dc_orientation_frame(moment_tensor_a)
    frame_b = _dc_orientation_frame(moment_tensor_b)

    candidate_angles = []

    for symmetry in _DC_SYMMETRIES:
        rotation = frame_a.T @ frame_b @ symmetry

        cosine = (np.trace(rotation) - 1.0) / 2.0
        cosine = np.clip(cosine, -1.0, 1.0)

        candidate_angles.append(
            np.degrees(np.arccos(cosine))
        )

    return float(min(candidate_angles))


def kagan_angle_sdr(
    sdr_a: ArrayLike,
    sdr_b: ArrayLike,
) -> float:
    """
    Compute the Kagan angle from two strike-dip-rake solutions.

    Parameters
    ----------
    sdr_a, sdr_b
        Sequences containing (strike, dip, rake), in degrees.
        Either nodal plane may be supplied.

    Returns
    -------
    float
        Kagan angle in degrees.
    """
    sdr_a = np.asarray(sdr_a, dtype=float)
    sdr_b = np.asarray(sdr_b, dtype=float)

    if sdr_a.shape != (3,) or sdr_b.shape != (3,):
        raise ValueError(
            "Each SDR input must contain exactly "
            "(strike, dip, rake)."
        )

    mt_a = dc_matrix_from_sdr(*sdr_a)
    mt_b = dc_matrix_from_sdr(*sdr_b)

    return kagan_angle_mt(mt_a, mt_b)

_MAGNITUDES = np.array([
    3.5, 3.6, 3.7, 3.8, 3.9, 4.0, 4.1, 4.2, 4.3, 4.4,
    4.5, 4.6, 4.7, 4.8, 4.9, 5.0, 5.1, 5.2, 5.3, 5.4,
    5.5, 5.6, 5.7, 5.8, 5.9, 6.0, 6.1, 6.2, 6.3, 6.4,
    6.5, 6.6, 6.7, 6.8, 6.9, 7.0, 7.1, 7.2, 7.3, 7.4,
    7.5, 7.6, 7.7, 7.8, 7.9, 8.0,
], dtype=float)

_MAX_RADII = np.array([
    96.001584, 95.9631833664, 98.0, 102.0, 108.026902688,
    114.868566765, 123.445238634, 128.689599653, 134.586833832,
    145.681117253, 157.689926419, 170.688647664, 188.45405921,
    192.223140394, 203.988734372, 216.474476825, 233.196675756,
    248.661128941, 258.190038239, 268.728407146, 280.032818545,
    297.173067302, 315.362436406, 334.665140413, 361.817781899,
    384.425050255, 407.954938731, 439.468601405, 468.049881681,
    497.294793922, 517.385503596, 538.287877942, 560.03470821,
    589.576829967, 615.854723363, 643.04652117, 669.293317953,
    696.332767998, 724.464611825, 753.732982143, 793.492788462,
    845.098386021, 897.18404165, 949.816128972, 994.534662958,
    1055.40814061,
], dtype=float)


def get_max_radius(magnitude, scale_factor=1.66):
    """
    Estimate the maximum radius from earthquake magnitude.

    The unscaled radius is obtained by linear interpolation through the
    tabulated magnitude-radius relationship and is then multiplied by
    ``scale_factor``.

    Parameters
    ----------
    magnitude : float or array-like
        Earthquake magnitude. Values must lie within 3.5 to 8.0.
    scale_factor : float, default=1.66
        Multiplicative factor applied to the interpolated radius.

    Returns
    -------
    float or numpy.ndarray
        Scaled maximum radius. A scalar input returns a float, while an
        array-like input returns a NumPy array.
    """
    magnitude = np.asarray(magnitude, dtype=float)
    scale_factor = float(scale_factor)

    if not np.all(np.isfinite(magnitude)):
        raise ValueError("magnitude must contain only finite values.")

    if not np.isfinite(scale_factor) or scale_factor <= 0.0:
        raise ValueError("scale_factor must be a positive finite value.")

    mag_min = _MAGNITUDES[0]
    mag_max = _MAGNITUDES[-1]

    if np.any((magnitude < mag_min) | (magnitude > mag_max)):
        raise ValueError(
            f"magnitude must lie within [{mag_min:.1f}, {mag_max:.1f}]."
        )

    radius = np.interp(magnitude, _MAGNITUDES, _MAX_RADII)
    scaled_radius = radius * scale_factor

    return float(scaled_radius) if magnitude.ndim == 0 else scaled_radius

def LatLongToPolar(Xst, Xeq):
    """Return event-centred epicentral distance and azimuth.

    Parameters
    ----------
    Xst
        ``(n, 2)`` array of station ``[latitude, longitude]`` coordinates.
    Xeq
        One ``[latitude, longitude]`` coordinate, supplied as shape ``(2,)`` or
        ``(1, 2)``, or one coordinate per station with shape ``(n, 2)``.

    Returns
    -------
    numpy.ndarray
        ``(n, 2)`` array whose columns are epicentral distance in kilometres
        and forward azimuth in radians within ``[0, 2*pi)``.
    """
    stations = np.asarray(Xst, dtype=float)
    reference = np.asarray(Xeq, dtype=float)
    if stations.ndim != 2 or stations.shape[1] != 2:
        raise ValueError("Xst must have shape (n, 2) in [latitude, longitude] order.")
    if reference.ndim == 1:
        reference = reference.reshape(1, -1)
    if reference.ndim != 2 or reference.shape[1] != 2:
        raise ValueError("Xeq must have shape (2,), (1, 2) or (n, 2).")
    if reference.shape[0] == 1:
        reference = np.repeat(reference, stations.shape[0], axis=0)
    elif reference.shape[0] != stations.shape[0]:
        raise ValueError("Xeq must contain one row or one row per station.")
    if not np.isfinite(stations).all() or not np.isfinite(reference).all():
        raise ValueError("Station and reference coordinates must be finite.")

    geod = Geod(ellps="WGS84")
    azimuth_deg, _, distance_m = geod.inv(
        reference[:, 1], reference[:, 0], stations[:, 1], stations[:, 0]
    )
    r_epi = np.asarray(distance_m, dtype=float) / 1000.0
    r_azi = np.mod(np.deg2rad(np.asarray(azimuth_deg, dtype=float)), 2.0 * np.pi)
    return np.column_stack([r_epi, r_azi])

def get_mseed_stationxml(
    event_id: str,
    origin_time,
    event_lon: float,
    event_lat: float,
    event_depth_km: float,
    *,
    magnitude: float | None = None,
    client: str | Sequence[str | Any] | Any = "GEONET",
    min_radius_km: float = 100.0,
    max_radius_km: float | None = None,
    radius_scale_factor: float = 1.66,
    ground_level: bool = True,
    channels: Sequence[str] = ("HH?", "BH?", "HN?", "BN?"),
    channel_priority: Sequence[str] = ("HH", "BH", "HN", "BN"),
    before_p: float = 60.0,
    after_s: float = 300.0,
    taup_model: str = "iasp91",
    output_dir: str | Path,
    overwrite: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Discover stations and download event-specific miniSEED and StationXML.

    Station discovery is restricted to an epicentral annulus and, by default,
    to sensors installed at the local ground surface. The annular selection is a
    configurable workflow policy for regional moment-tensor inversion rather
    than a universal physical requirement. The minimum radius defaults to
    100 km. When ``max_radius_km=None`` (default), the outer radius is derived
    from ``magnitude`` with :func:`get_max_radius`; an explicit maximum radius
    overrides that calculation exactly.

    Parameters
    ----------
    event_id
        Event identifier used in filenames and all metadata tables.
    origin_time
        Event origin time accepted by :class:`obspy.UTCDateTime`.
    event_lon, event_lat
        Event longitude and latitude in decimal degrees.
    event_depth_km
        Non-negative catalog source depth in kilometres. It is used only to
        calculate theoretical P and S arrivals that define each station's
        request window.
    magnitude
        Event magnitude used only when ``max_radius_km=None``. The automatic
        maximum radius is ``get_max_radius(magnitude, scale_factor=radius_scale_factor)``.
        It is not required when an explicit ``max_radius_km`` is supplied.
    client
        One ObsPy FDSN client instance or provider name such as ``"GEONET"``,
        or an ordered list/tuple containing multiple instances and/or provider
        names. Clients are queried independently and their successful stations
        are combined in the same ``raw/waveforms`` and ``raw/stationxml``
        directories. The first successful client is retained when more than one
        client supplies the same network/station/location identifier.
    min_radius_km, max_radius_km
        Inclusive minimum and maximum epicentral distances in kilometres.
        ``min_radius_km`` defaults to 100 km. ``max_radius_km=None`` derives the
        outer radius from ``magnitude``; a finite positive value is a direct
        user override. Resolved values are converted to the angular radii
        required by the FDSN station service and are also enforced against the
        ellipsoidal source--receiver distance calculated by ObsPy. Require
        ``0 <= min_radius_km < resolved max_radius_km``.
    radius_scale_factor
        Positive scale passed to :func:`get_max_radius` when the maximum radius
        is automatic. The default 1.66 matches the existing regional
        magnitude-radius convention. It has no effect on an explicit
        ``max_radius_km``.
    ground_level
        If ``True`` (default), retain only three-component channel families for
        which every selected channel has StationXML ``Channel.depth`` equal to
        zero within floating-point tolerance. In StationXML, channel depth is
        sensor depth below the local ground surface. Set ``False`` only when
        borehole, vault-depth or other non-surface instruments are intentionally
        required.
    channels
        FDSN channel wildcards considered during discovery. Each candidate must
        contain one complete ``ZNE``, ``Z12`` or ``123`` family for one common
        network, station, location code and two-character channel prefix. The
        exact retained triplet is recorded so ``HNZ/HN1/HN2`` and arbitrary
        three-axis installations are rotated unambiguously from StationXML.
    channel_priority
        Preferred two-character channel prefixes, from highest to lowest
        priority. One complete family is retained per network/station. The
        selected location code is preserved and is part of the MTtime station
        identifier.
    before_p
        Non-negative number of seconds requested before the theoretical first P
        arrival.
    after_s
        Non-negative number of seconds requested after the theoretical first S
        arrival.
    taup_model
        TauP Earth model used to calculate the first P and S arrivals.
    output_dir
        Event root directory. Raw waveforms are written under
        ``raw/waveforms``, response metadata under ``raw/stationxml`` and CSV
        tables under ``metadata``.
    overwrite
        If ``True``, force a fresh FDSN request. If ``False``, an existing
        miniSEED/StationXML pair is reused only after checking component
        completeness, continuous common coverage of the requested interval and
        availability of a response for every retained trace. An incomplete or
        incompatible pair is downloaded again automatically.

    Returns
    -------
    event_df : pandas.DataFrame
        One-row event table containing the canonical event fields and acquisition
        settings, including magnitude, the resolved distance annulus,
        ``radius_scale_factor`` and the ground-level policy.
    station_df : pandas.DataFrame
        One row per successful station family. It contains the selected channel
        family and sensor depth, station geometry, theoretical P/S arrivals,
        exact request times and paths to the raw miniSEED and StationXML files.
    download_log : pandas.DataFrame
        One row per considered candidate family with ``downloaded``,
        ``redownloaded``, ``overwritten``, ``existing``, ``distance_excluded``,
        ``arrival_missing``, ``download_failed``, ``client_failed`` or
        ``duplicate_client_station`` status. The ``fdsn_client`` column identifies
        the provider used for each candidate or provider-level failure.

    Notes
    -----
    The request window is station specific:

    ``origin + P_time - before_p`` to ``origin + S_time + after_s``.

    This retains pre-P noise and the S-wave/coda interval without storing the
    unnecessarily long common window that would result from using the most
    distant station for every request.

    FDSN ``minradius`` and ``maxradius`` are angular distances in degrees. The
    service query is padded slightly, then the requested kilometre annulus is
    enforced using the ellipsoidal geodesic distance. This avoids both false
    inclusions and boundary false negatives caused by spherical/ellipsoidal
    conversion differences.
    """
    from obspy import UTCDateTime, read, read_inventory
    from obspy.clients.fdsn import Client
    from obspy.geodetics.base import gps2dist_azimuth, kilometers2degrees
    from obspy.taup import TauPyModel

    event_id = str(event_id).strip()
    taup_model = str(taup_model).strip()
    if not event_id:
        raise ValueError("event_id cannot be empty.")
    if not taup_model:
        raise ValueError("taup_model cannot be empty.")

    event_lon = float(event_lon)
    event_lat = float(event_lat)
    event_depth_km = float(event_depth_km)
    min_radius_km = float(min_radius_km)
    radius_scale_factor = float(radius_scale_factor)
    if not np.isfinite(radius_scale_factor) or radius_scale_factor <= 0:
        raise ValueError("radius_scale_factor must be a positive finite value.")
    if max_radius_km is None:
        if magnitude is None:
            raise ValueError(
                "magnitude is required when max_radius_km=None. Supply magnitude "
                "for the automatic radius or provide an explicit max_radius_km."
            )
        magnitude = float(magnitude)
        max_radius_km = float(
            get_max_radius(magnitude, scale_factor=radius_scale_factor)
        )
    else:
        max_radius_km = float(max_radius_km)
        magnitude = None if magnitude is None else float(magnitude)
        if magnitude is not None and not np.isfinite(magnitude):
            raise ValueError("magnitude must be finite when supplied.")
    before_p = float(before_p)
    after_s = float(after_s)
    if not isinstance(ground_level, (bool, np.bool_)):
        raise TypeError("ground_level must be a boolean.")
    ground_level = bool(ground_level)

    finite_event = np.isfinite([event_lon, event_lat, event_depth_km]).all()
    if not finite_event:
        raise ValueError("Event longitude, latitude and depth must be finite.")
    if not -90.0 <= event_lat <= 90.0:
        raise ValueError("event_lat must lie within [-90, 90] degrees.")
    if not -180.0 <= event_lon <= 180.0:
        raise ValueError("event_lon must lie within [-180, 180] degrees.")
    if event_depth_km < 0:
        raise ValueError("event_depth_km cannot be negative.")
    if not np.isfinite([min_radius_km, max_radius_km]).all():
        raise ValueError("min_radius_km and max_radius_km must be finite.")
    if min_radius_km < 0 or max_radius_km <= 0:
        raise ValueError(
            "Require min_radius_km >= 0 and max_radius_km > 0."
        )
    if min_radius_km >= max_radius_km:
        raise ValueError("Require min_radius_km < max_radius_km.")
    if not np.isfinite([before_p, after_s]).all() or before_p < 0 or after_s < 0:
        raise ValueError("before_p and after_s must be finite and non-negative.")
    if not channels or not channel_priority:
        raise ValueError("channels and channel_priority cannot be empty.")

    channel_patterns = tuple(str(value).strip() for value in channels)
    priority_prefixes = tuple(str(value).strip() for value in channel_priority)
    if any(not value for value in channel_patterns):
        raise ValueError("channels cannot contain empty patterns.")
    if any(len(value) != 2 for value in priority_prefixes):
        raise ValueError("channel_priority entries must be two-character prefixes.")
    if len(set(priority_prefixes)) != len(priority_prefixes):
        raise ValueError("channel_priority cannot contain duplicate prefixes.")

    root = Path(output_dir).expanduser()
    waveform_dir = root / "raw" / "waveforms"
    stationxml_dir = root / "raw" / "stationxml"
    metadata_dir = root / "metadata"
    for directory in (waveform_dir, stationxml_dir, metadata_dir):
        directory.mkdir(parents=True, exist_ok=True)

    if isinstance(client, (list, tuple)):
        client_specs = tuple(client)
    else:
        client_specs = (client,)
    if not client_specs:
        raise ValueError("client cannot be an empty list or tuple.")

    origin = UTCDateTime(origin_time)
    channel_query = ",".join(channel_patterns)
    annulus_query_padding_km = max(1.0, 0.01 * max_radius_km)
    query_min_radius_km = max(0.0, min_radius_km - annulus_query_padding_km)
    query_max_radius_km = max_radius_km + annulus_query_padding_km
    query_min_radius_deg = float(kilometers2degrees(query_min_radius_km))
    query_max_radius_deg = float(kilometers2degrees(query_max_radius_km))
    if query_max_radius_deg > 180.0:
        raise ValueError(
            "max_radius_km is too large for an FDSN radial query after padding."
        )

    successful_rows: list[dict[str, Any]] = []
    log_rows: list[dict[str, Any]] = []
    candidate_tables: list[pd.DataFrame] = []
    fdsn_clients: list[Any] = []
    requested_client_labels: list[str] = []

    for client_index, client_spec in enumerate(client_specs):
        if isinstance(client_spec, str):
            client_label = client_spec.strip()
            if not client_label:
                error = ValueError("FDSN client provider names cannot be empty.")
                if len(client_specs) == 1:
                    raise error
                requested_client_labels.append(f"client_{client_index + 1}")
                log_rows.append({
                    "event_id": str(event_id),
                    "fdsn_client": f"client_{client_index + 1}",
                    "status": "client_failed",
                    "reason": str(error),
                    "cache_reason": "not_checked",
                })
                continue
        else:
            base_url = getattr(client_spec, "base_url", None)
            client_label = (
                str(base_url).strip()
                if base_url is not None and str(base_url).strip()
                else client_spec.__class__.__name__
            )
        requested_client_labels.append(client_label)

        try:
            fdsn = Client(client_spec) if isinstance(client_spec, str) else client_spec
            if not callable(getattr(fdsn, "get_stations", None)) or not callable(
                getattr(fdsn, "get_waveforms", None)
            ):
                raise TypeError(
                    "Each client must be an ObsPy FDSN provider name or an object "
                    "with callable get_stations and get_waveforms methods."
                )
            inventory = fdsn.get_stations(
                latitude=event_lat,
                longitude=event_lon,
                minradius=query_min_radius_deg,
                maxradius=query_max_radius_deg,
                starttime=origin,
                endtime=origin + 1.0,
                channel=channel_query,
                level="channel",
            )
            candidates = _inventory_channel_families(
                inventory,
                priority_prefixes,
                ground_level=ground_level,
            )
        except Exception as exc:
            if len(client_specs) == 1:
                raise
            log_rows.append({
                "event_id": str(event_id),
                "fdsn_client": client_label,
                "status": "client_failed",
                "reason": str(exc),
                "cache_reason": "not_checked",
            })
            continue

        if candidates.empty:
            continue
        fdsn_client_index = len(fdsn_clients)
        fdsn_clients.append(fdsn)
        candidates = candidates.copy()
        candidates.loc[:, "fdsn_client_index"] = int(fdsn_client_index)
        candidates.loc[:, "fdsn_client"] = client_label
        candidate_tables.append(candidates)

    candidate_df = (
        pd.concat(candidate_tables, ignore_index=True, sort=False)
        if candidate_tables else pd.DataFrame()
    )
    taup = TauPyModel(model=taup_model)
    successful_station_ids: set[str] = set()
    distance_tolerance_km = max(1e-6, 1e-9 * max_radius_km)

    for row in candidate_df.itertuples(index=False):
        fdsn = fdsn_clients[int(row.fdsn_client_index)]
        fdsn_client_label = str(row.fdsn_client)
        location = str(row.location)
        location_request = location if location else "--"
        location_label = location if location else "--"
        station_id = f"{row.network}.{row.station}.{location_label}"
        distance_m, azimuth, back_azimuth = gps2dist_azimuth(
            event_lat,
            event_lon,
            float(row.station_lat),
            float(row.station_lon),
        )
        distance_km = float(distance_m) / 1000.0

        base = {
            "event_id": str(event_id),
            "fdsn_client": fdsn_client_label,
            "station_id": station_id,
            "network": row.network,
            "station": row.station,
            "location": location,
            "location_label": location_label,
            "channel_prefix": row.channel_prefix,
            "component_scheme": row.component_scheme,
            "selected_channels": row.selected_channels,
            "channels": row.channels,
            "sample_rate": float(row.sample_rate),
            "channel_depth_m": float(row.channel_depth_m),
            "ground_level": ground_level,
            "station_lat": float(row.station_lat),
            "station_lon": float(row.station_lon),
            "station_elevation_m": float(row.station_elevation_m),
            "site_lat": float(row.site_lat),
            "site_lon": float(row.site_lon),
            "site_elevation_m": float(row.site_elevation_m),
            "distance_km": distance_km,
            "azimuth_deg": float(azimuth) % 360.0,
            "back_azimuth_deg": float(back_azimuth) % 360.0,
            "r_epi": distance_km,
            "r_azi": float(np.deg2rad(float(azimuth) % 360.0)),
        }

        if station_id in successful_station_ids:
            log_rows.append({
                **base,
                "p_arrival_s": np.nan,
                "s_arrival_s": np.nan,
                "status": "duplicate_client_station",
                "reason": (
                    "The same network/station/location was already acquired "
                    "successfully from an earlier client."
                ),
                "cache_reason": "not_checked",
            })
            continue

        outside_annulus = (
            distance_km < min_radius_km - distance_tolerance_km
            or distance_km > max_radius_km + distance_tolerance_km
        )
        if outside_annulus:
            log_rows.append({
                **base,
                "p_arrival_s": np.nan,
                "s_arrival_s": np.nan,
                "status": "distance_excluded",
                "reason": (
                    f"Geodesic distance {distance_km:.6f} km lies outside "
                    f"[{min_radius_km:.6f}, {max_radius_km:.6f}] km."
                ),
                "cache_reason": "not_checked",
            })
            continue

        p_time, s_time = _compute_arrivals(
            taup,
            event_depth_km,
            event_lat,
            event_lon,
            float(row.station_lat),
            float(row.station_lon),
        )
        base.update({"p_arrival_s": p_time, "s_arrival_s": s_time})

        if not np.isfinite(p_time) or not np.isfinite(s_time):
            log_rows.append({
                **base,
                "status": "arrival_missing",
                "reason": "TauP returned no finite P or S arrival.",
                "cache_reason": "not_checked",
            })
            continue

        request_start = origin + p_time - before_p
        request_end = origin + s_time + after_s

        # FDSN request boundaries are arbitrary UTC times, while miniSEED samples lie
        # on a discrete station-specific sample grid. Request two extra samples on
        # each side so the returned common three-component interval fully contains
        # the exact logical processing window.
        sample_interval_s = 1.0 / float(row.sample_rate)
        download_padding_s = 2.0 * sample_interval_s

        waveform_request_start = request_start - download_padding_s
        waveform_request_end = request_end + download_padding_s

        waveform_path = waveform_dir / f"{station_id}.{row.channel_prefix}.mseed"
        stationxml_path = stationxml_dir / f"{station_id}.{row.channel_prefix}.xml"
        existed_before = waveform_path.exists() or stationxml_path.exists()
        cache_reason = "overwrite=True"
        reuse_existing = False

        if not overwrite and waveform_path.exists() and stationxml_path.exists():
            reuse_existing, cache_reason = _raw_inputs_match_request(
                waveform_path,
                stationxml_path,
                network=str(row.network),
                station=str(row.station),
                location=location,
                channel_prefix=str(row.channel_prefix),
                selected_channels=str(row.selected_channels),
                request_start=request_start,
                request_end=request_end,
                response_time=origin,
                expected_ground_level=ground_level,
                expected_channel_depth_m=float(row.channel_depth_m),
                expected_station_lat=float(row.station_lat),
                expected_station_lon=float(row.station_lon),
                expected_station_elevation_m=float(row.station_elevation_m),
                read=read,
                read_inventory=read_inventory,
            )

        if reuse_existing:
            status = "existing"
        else:
            tmp_waveform = waveform_path.with_name(waveform_path.name + ".tmp")
            tmp_stationxml = stationxml_path.with_name(stationxml_path.name + ".tmp")
            try:
                response_inventory = fdsn.get_stations(
                    network=row.network,
                    station=row.station,
                    location=location_request,
                    channel=str(row.selected_channels),
                    starttime=waveform_request_start,
                    endtime=waveform_request_end,
                    level="response",
                )

                stream = fdsn.get_waveforms(
                    network=row.network,
                    station=row.station,
                    location=location_request,
                    channel=str(row.selected_channels),
                    starttime=waveform_request_start,
                    endtime=waveform_request_end,
                    attach_response=False,
                )
                if len(stream) == 0:
                    raise ValueError("Waveform request returned an empty stream.")

                stream.write(str(tmp_waveform), format="MSEED")
                response_inventory.write(str(tmp_stationxml), format="STATIONXML")
                valid, validation_reason = _raw_inputs_match_request(
                    tmp_waveform,
                    tmp_stationxml,
                    network=str(row.network),
                    station=str(row.station),
                    location=location,
                    channel_prefix=str(row.channel_prefix),
                    selected_channels=str(row.selected_channels),
                    request_start=request_start,
                    request_end=request_end,
                    response_time=origin,
                    expected_ground_level=ground_level,
                    expected_channel_depth_m=float(row.channel_depth_m),
                    expected_station_lat=float(row.station_lat),
                    expected_station_lon=float(row.station_lon),
                    expected_station_elevation_m=float(row.station_elevation_m),
                    read=read,
                    read_inventory=read_inventory,
                )
                if not valid:
                    raise ValueError(
                        f"Downloaded files failed validation: {validation_reason}"
                    )

                tmp_waveform.replace(waveform_path)
                tmp_stationxml.replace(stationxml_path)
                if overwrite and existed_before:
                    status = "overwritten"
                elif existed_before:
                    status = "redownloaded"
                else:
                    status = "downloaded"
            except Exception as exc:
                for temporary in (tmp_waveform, tmp_stationxml):
                    if temporary.exists():
                        temporary.unlink()
                log_rows.append({
                    **base,
                    "request_starttime": str(request_start),
                    "request_endtime": str(request_end),
                    "status": "download_failed",
                    "reason": str(exc),
                    "cache_reason": cache_reason,
                })
                continue

        successful_rows.append({
            **base,
            "origin_time": str(origin),
            "event_lon": event_lon,
            "event_lat": event_lat,
            "event_depth_km": event_depth_km,
            "min_radius_km": min_radius_km,
            "max_radius_km": max_radius_km,
            "request_starttime": str(request_start),
            "request_endtime": str(request_end),
            "waveform_path": str(waveform_path),
            "stationxml_path": str(stationxml_path),
            "download_status": status,
        })
        successful_station_ids.add(station_id)
        log_rows.append({
            **base,
            "request_starttime": str(request_start),
            "request_endtime": str(request_end),
            "status": status,
            "reason": "",
            "cache_reason": cache_reason,
        })

    event_df = pd.DataFrame([{
        "event_id": str(event_id),
        "origin_time": str(origin),
        "event_lon": event_lon,
        "event_lat": event_lat,
        "event_depth_km": event_depth_km,
        "magnitude": magnitude,
        "min_radius_km": min_radius_km,
        "max_radius_km": max_radius_km,
        "radius_scale_factor": radius_scale_factor,
        "annulus_query_padding_km": annulus_query_padding_km,
        "ground_level": ground_level,
        "taup_model": str(taup_model),
        "before_p": before_p,
        "after_s": after_s,
        "fdsn_clients": ",".join(requested_client_labels),
    }])
    station_df = (
        pd.DataFrame(successful_rows).sort_values("distance_km", ignore_index=True)
        if successful_rows else pd.DataFrame()
    )
    download_log = pd.DataFrame(log_rows)

    event_df.to_csv(metadata_dir / "event.csv", index=False)
    station_df.to_csv(metadata_dir / "stations_downloaded.csv", index=False)
    download_log.to_csv(metadata_dir / "download_log.csv", index=False)
    return event_df, station_df, download_log


def process_mseed_sac(
    event_df: pd.DataFrame | pd.Series | Mapping[str, Any],
    station_df: pd.DataFrame,
    *,
    output_dir: str | Path,
    motion: str = "DISP",
    water_level: float | None = None,
    freqmin: float = 0.02,
    freqmax: float = 0.05,
    corners: int = 3,
    dt: float = 1.0,
    window_start_phase: str = "P",
    time_before_window_start: float = 60.0,
    window_end_phase: str = "S",
    time_after_window_end: float = 300.0,
    inversion_duration: float | None = 150.0,
    max_correlation_shift: float = 5.0,
    max_reference_time_shift: float = 0.0,
    pad_missing_prearrival: bool = True,
    reduction_velocity_km_s: float = 0.0,
    used: str | int = 1,
    plot: bool = False,
    plot_station_map: bool = False,
    overwrite: bool = False,
) -> tuple[Any, pd.DataFrame, pd.DataFrame]:
    """Prepare response-corrected ZRT observations for an MTtime inversion.

    The observed record is station specific, while the catalog-origin sample is
    retained as the immutable physical timing datum. For the default settings,
    station ``i`` is stored from the earlier of ``P_i - 60`` and the reserved
    reference/correlation margin through ``S_i + 300`` seconds relative to
    origin. The processed table initially sets ``ts`` and ``reference_ts`` equal
    to ``origin_ts``. A later call to :func:`write_mtinv` may move the global
    reference within the reserved range without rewriting the observations.

    Observation storage and inversion duration are deliberately separate. The
    default ``inversion_duration=150`` produces 150 samples at ``dt=1`` from
    the selected reference (last sample at 149 s), matching the MTtime tutorial
    convention. The caller never supplies sample indices directly: this function
    derives the catalog-origin index, the reserved margins and ``npts``.

    Parameters
    ----------
    event_df
        One-row event table, Series or mapping. Recognised aliases include
        ``event_id/evid``, ``origin_time/origin``, ``event_lon/lon``,
        ``event_lat/lat`` and ``event_depth_km/depth``.
    station_df
        Successful station table returned by :func:`get_mseed_stationxml`.
        Each row must contain paths to one raw miniSEED file and its matching
        StationXML response metadata, source-receiver geometry, and finite
        theoretical ``p_arrival_s`` and ``s_arrival_s`` offsets from origin.
    output_dir
        Event root directory. MTtime data files are written under
        ``processed/data``; station and processing tables under ``metadata``;
        optional figures under ``figures``.
    motion
        Physical quantity requested from :meth:`obspy.Trace.remove_response`:
        ``"DISP"``, ``"VEL"`` or ``"ACC"``. Output traces are scaled from SI
        units to cm, cm/s or cm/s². ``"DISP"`` is the recommended default.
        :func:`generate_pyfk_gfs` independently converts native pyFK output to
        the same target motion and centimetre-based unit family.
    water_level
        Optional water level supplied to :meth:`obspy.Trace.remove_response`.
        ``None`` omits the argument so stabilization is controlled by the
        trace-specific pre-filter alone.
    freqmin, freqmax
        Lower and upper frequencies of the zero-phase Butterworth bandpass, in
        hertz, applied after response correction and ZRT rotation.
    corners
        Number of Butterworth filter corners. Must be at least one.
    dt
        Exact final sampling interval, in seconds, shared by observations and
        Green's functions. ``freqmax`` must be below the corresponding Nyquist
        frequency.
    window_start_phase
        Phase anchoring the first stored observation sample: ``"ORIGIN"``,
        ``"P"`` or ``"S"``. Matching is case-insensitive. ``P`` and ``S`` use
        the theoretical arrival offsets in ``station_df``. The inversion itself
        always begins at event origin.
    time_before_window_start
        Non-negative number of seconds retained before ``window_start_phase``.
        This observed-only pre-origin buffer protects against an early P arrival
        and provides the left margin for bounded correlation; it is not part of
        the unshifted inversion segment.
    window_end_phase
        Phase anchoring the final retained sample: ``"ORIGIN"``, ``"P"`` or
        ``"S"``.
    time_after_window_end
        Non-negative number of seconds retained after ``window_end_phase`` in
        the stored observed record.
    inversion_duration
        Duration of the origin-aligned MTtime segment in seconds, interpreted as
        ``npts * dt``. Thus 150 s at ``dt=1`` gives ``npts=150`` and samples at
        0 through 149 s. The default follows the official MTtime tutorial and
        decouples the inversion from the broader stored observation. Set to
        ``None`` to use all samples from origin through the stored endpoint,
        excluding the trailing global-reference and correlation margins.
    max_correlation_shift
        Maximum absolute residual station-wise timing correction, in seconds,
        reserved on both sides of every allowed global reference. It must be a
        non-negative integer multiple of ``dt`` and shorter than half of the
        shortest retained period ``1 / freqmax``. The default 5 seconds is one
        quarter-cycle at 0.05 Hz. Set it to zero when bounded correlation will
        not be used.
    max_reference_time_shift
        Maximum absolute global reference-time shift, in seconds, that later
        calls to :func:`write_mtinv` may apply relative to the catalog origin.
        It must be a non-negative integer multiple of ``dt``. For example, a
        value of 10 reserves all global references from -10 through +10 seconds.
        The stored record reserves this margin in addition to
        ``max_correlation_shift``. The default zero preserves strict catalog-
        origin alignment.
    pad_missing_prearrival
        If ``True`` (default), a missing prefix of the requested stored window is
        filled with zeros after response removal and filtering, provided the first
        common raw sample remains earlier than P by at least the combined
        ``max_reference_time_shift + max_correlation_shift`` margin. This protects
        every allowed source/reference and residual-correlation shift without
        making station acceptance depend on the analysis ``freqmin``. Missing
        coverage that reaches this protected P-wave interval, and all missing end
        coverage, still fail. Set ``False`` for strict complete raw-window coverage.
    reduction_velocity_km_s
        Optional reduction velocity in km/s used only when at least one phase
        anchor is ``"ORIGIN"``. Zero means the unreduced event origin; a positive
        value defines ``origin + distance / velocity``. It is rejected when no
        origin anchor is requested.
    used
        MTtime component-use flag copied to the processed station table. ``1``
        uses all requested components; strings such as ``"110"`` may later be
        used to retain Z and R only.
    plot
        Save the normalized filtered ZRT record section to
        ``figures/waveform_record_section.png`` and a response-corrected,
        ZRT-rotated record section before the inversion bandpass to
        ``figures/waveform_record_section_unfiltered.png``. Both figures use
        plotting copies and do not modify the amplitudes written to SAC.
    plot_station_map
        Save an event/station map to ``figures/station_map.png``.
    overwrite
        If ``True``, force regeneration of every station triplet. If ``False``,
        all three existing SAC files are checked against a deterministic
        processing signature, exact sample grid, start time, component labels
        and finite-data requirements. Complete matching triplets are reused;
        partial, corrupt or incompatible triplets are regenerated automatically.

    Returns
    -------
    processed_stream : obspy.Stream
        All accepted ZRT observations, including matching traces loaded from the
        cache and newly written traces.
    processed_station_df : pandas.DataFrame
        Authoritative station table for :func:`generate_pyfk_gfs`,
        :func:`generate_syngine_gfs` and :func:`write_mtinv`. It includes
        station-specific stored-window geometry,
        immutable ``origin_ts``, initial ``reference_ts`` and ``ts``, derived
        inversion ``npts``, common ``dt``, reserved global-reference and
        correlation margins, processing settings, data paths, cache status and
        processing signature.
    processing_log : pandas.DataFrame
        One row per requested station. Successful statuses are ``existing``,
        ``written``, ``rewritten`` and ``overwritten``. Only genuine waveform,
        metadata, timing, response-removal, rotation or file-write errors are
        marked ``failed``.

    Notes
    -----
    The requested stored interval is

    ``origin + start_phase_i - time_before_window_start``

    through

    ``origin + end_phase_i + time_after_window_end``.

    Boundaries are represented on a common sample grid whose zero is the catalog
    origin. The phase-defined storage interval is expanded automatically to
    contain every allowed global reference, the complete inversion segment and
    the residual correlation margin. When ``pad_missing_prearrival=True``, a
    missing prefix may be zero-padded only while the first available raw sample
    remains before P by the combined reference/correlation timing margin. The
    padding gate is intentionally independent of ``freqmin``; lowering the analysis
    frequency does not by itself remove raw waveform coverage. Missing protected
    signal or end coverage is never padded.

    Let ``r=max_reference_time_shift / dt`` and
    ``c=max_correlation_shift / dt``. ``origin_ts`` is the catalog-origin index.
    The processed baseline has ``reference_ts = ts = origin_ts`` and reserves at
    least ``r + c`` samples before it and after the inversion segment. A later
    configuration with shift ``q`` uses ``reference_ts = origin_ts + q/dt``;
    bounded correlation may then move only within ``+/-c`` samples of that
    reference. Green's functions remain unchanged and start at source-reference
    time zero.

    Origin alignment does not imply that all subsequent arrivals will match.
    Remaining station-dependent lags reflect velocity-model, source-location or
    phase-prediction error.  Correlation should be kept short relative to the
    highest retained frequency to avoid shifting by an adjacent waveform cycle.

    Response-removal pre-filters are created internally by
    :func:`_default_pre_filt`. Their second low corner is forced below the
    inversion ``freqmin`` so response removal cannot taper the analysis band.
    High corners are ``0.9 * Nyquist`` and Nyquist. ObsPy performs its own
    zero-mean and taper operations during deconvolution, so no additional
    pre-deconvolution taper is applied.

    Cache signatures include event/station geometry, raw-file fingerprints,
    both phase anchors, requested offsets, exact station-specific sample
    geometry and processing parameters. Any material change triggers an
    automatic rewrite when ``overwrite=False``.
    """
    import obspy as obspy_module
    from obspy import Stream, UTCDateTime, read, read_inventory
    from obspy.core.util.attribdict import AttribDict

    if station_df.empty:
        raise ValueError("station_df is empty.")

    event = _event_record(event_df)
    origin = UTCDateTime(event["origin_time"])
    motion = str(motion).upper()
    if motion not in {"DISP", "VEL", "ACC"}:
        raise ValueError("motion must be 'DISP', 'VEL' or 'ACC'.")
    if not isinstance(pad_missing_prearrival, (bool, np.bool_)):
        raise TypeError("pad_missing_prearrival must be a boolean.")
    pad_missing_prearrival = bool(pad_missing_prearrival)

    _validate_processing_parameters(freqmin, freqmax, corners, dt)
    phases = {
        "window_start_phase": _normalize_phase(
            window_start_phase, "window_start_phase"
        ),
        "window_end_phase": _normalize_phase(
            window_end_phase, "window_end_phase"
        ),
    }
    _validate_window_parameters(
        time_before_window_start=time_before_window_start,
        time_after_window_end=time_after_window_end,
        inversion_duration=inversion_duration,
        max_correlation_shift=max_correlation_shift,
        max_reference_time_shift=max_reference_time_shift,
        freqmax=freqmax,
        dt=dt,
        reduction_velocity_km_s=reduction_velocity_km_s,
        phases=phases.values(),
    )

    root = Path(output_dir).expanduser()
    data_dir = root / "processed" / "data"
    metadata_dir = root / "metadata"
    figure_dir = root / "figures"
    for directory in (data_dir, metadata_dir, figure_dir):
        directory.mkdir(parents=True, exist_ok=True)

    output_stream = Stream()
    station_rows: list[dict[str, Any]] = []
    log_rows: list[dict[str, Any]] = []

    window_settings = {
        **phases,
        "time_before_window_start": float(time_before_window_start),
        "time_after_window_end": float(time_after_window_end),
        "inversion_duration": (
            None if inversion_duration is None else float(inversion_duration)
        ),
        "max_correlation_shift": float(max_correlation_shift),
        "max_reference_time_shift": float(max_reference_time_shift),
        "pad_missing_prearrival": pad_missing_prearrival,
        "reduction_velocity_km_s": float(reduction_velocity_km_s),
    }

    for row in station_df.itertuples(index=False):
        row_dict = row._asdict()
        station_id = str(
            row_dict["station_id"]
            if "station_id" in row_dict
            else _station_id_from_row(row_dict)
        )
        base_log = {"event_id": event["event_id"], "station_id": station_id}
        cache_reason = "not_checked"

        try:
            component_scheme, selected_channels = _row_component_selection(row_dict)
            row_dict["component_scheme"] = component_scheme
            row_dict["selected_channels"] = ",".join(selected_channels)
            waveform_path = Path(row_dict["waveform_path"])
            stationxml_path = Path(row_dict["stationxml_path"])
            if not waveform_path.exists():
                raise FileNotFoundError(
                    f"Raw waveform file does not exist: {waveform_path}"
                )
            if not stationxml_path.exists():
                raise FileNotFoundError(
                    f"StationXML file does not exist: {stationxml_path}"
                )

            distance_km = float(row_dict["distance_km"])
            geometry = _station_window_geometry(
                row_dict,
                dt=float(dt),
                window_start_phase=phases["window_start_phase"],
                time_before_window_start=float(time_before_window_start),
                window_end_phase=phases["window_end_phase"],
                time_after_window_end=float(time_after_window_end),
                inversion_duration=(
                    None if inversion_duration is None else float(inversion_duration)
                ),
                max_correlation_shift=float(max_correlation_shift),
                max_reference_time_shift=float(max_reference_time_shift),
                reduction_velocity_km_s=float(reduction_velocity_km_s),
            )
            target_start = origin + geometry["window_start_offset_s"]
            target_end = origin + geometry["window_end_offset_s"]
            target_times = (
                target_start.timestamp
                + np.arange(geometry["stored_npts"], dtype=float) * float(dt)
            )
            scale, output_units = _motion_scale_and_units(motion)
            signature = _observation_processing_signature(
                event=event,
                row=row_dict,
                waveform_path=waveform_path,
                stationxml_path=stationxml_path,
                motion=motion,
                water_level=water_level,
                freqmin=freqmin,
                freqmax=freqmax,
                corners=corners,
                dt=dt,
                window_settings=window_settings,
                geometry=geometry,
                obspy_version=str(getattr(obspy_module, "__version__", "unknown")),
            )
            data_paths = {
                component: data_dir / f"{station_id}.{component}.dat"
                for component in "ZRT"
            }
            existing_count = sum(path.exists() for path in data_paths.values())
            cache_reason = "overwrite=True"

            if not overwrite:
                cached, cache_reason = _load_cached_observed_triplet(
                    data_paths=data_paths,
                    signature=signature,
                    station_id=station_id,
                    row=row_dict,
                    expected_start=target_start,
                    expected_npts=geometry["stored_npts"],
                    expected_dt=float(dt),
                    output_units=output_units,
                    read=read,
                    Stream=Stream,
                )
                if cached is not None:
                    output_stream += cached
                    station_rows.append(_processed_station_record(
                        row_dict,
                        station_id=station_id,
                        distance_km=distance_km,
                        window_settings=window_settings,
                        geometry=geometry,
                        dt=dt,
                        used=used,
                        motion=motion,
                        output_units=output_units,
                        freqmin=freqmin,
                        freqmax=freqmax,
                        corners=corners,
                        data_dir=data_dir,
                        status="existing",
                        signature=signature,
                        origin=origin,
                    ))
                    log_rows.append({
                        **base_log,
                        "status": "existing",
                        "reason": "",
                        "cache_reason": cache_reason,
                        "window_starttime": str(target_start),
                        "window_endtime": str(target_end),
                        "ts": int(geometry["ts"]),
                        "npts": int(geometry["npts"]),
                        "stored_npts": int(geometry["stored_npts"]),
                    })
                    continue

            inventory = read_inventory(str(stationxml_path), format="STATIONXML")
            available = read(str(waveform_path), format="MSEED")
            available = available.select(
                network=str(row_dict["network"]),
                station=str(row_dict["station"]),
                location=str(row_dict.get("location", "")),
                channel=f"{row_dict['channel_prefix']}?",
            )
            if len(available) == 0:
                raise ValueError(
                    "No traces match the selected station/location/channel family."
                )

            stream = Stream()
            for channel in selected_channels:
                matching = available.select(channel=channel)
                if len(matching) == 0:
                    raise ValueError(
                        f"Selected input channel {channel} is absent from the raw waveform."
                    )
                stream += matching

            true_gaps = [gap for gap in stream.get_gaps() if gap[-1] > 0]
            if true_gaps:
                raise ValueError(f"Internal waveform gaps: {true_gaps}")
            stream.merge(method=0)
            if len(stream) != 3:
                raise ValueError(
                    "The explicit input channel selection must reduce to exactly "
                    f"three traces; found {[trace.id for trace in stream]}."
                )
            expected_ground_level = _optional_boolean(
                row_dict.get("ground_level"), "ground_level"
            )
            orientation = _inventory_orientation_summary(
                inventory,
                stream,
                origin,
                expected_ground_level=expected_ground_level,
            )
            expected_depth = row_dict.get("channel_depth_m")
            if expected_depth is not None and pd.notna(expected_depth):
                expected_depth = float(expected_depth)
                if not np.isclose(
                    orientation["input_channel_depth_m"],
                    expected_depth,
                    atol=_GROUND_LEVEL_DEPTH_ATOL_M,
                    rtol=0.0,
                ):
                    raise ValueError(
                        "Station table channel_depth_m does not match StationXML: "
                        f"{expected_depth} versus "
                        f"{orientation['input_channel_depth_m']} m."
                    )
            geometry_checks = {
                "station_lat": ("input_sensor_lat", _CHANNEL_COORDINATE_ATOL_DEG),
                "station_lon": ("input_sensor_lon", _CHANNEL_COORDINATE_ATOL_DEG),
                "station_elevation_m": (
                    "input_sensor_elevation_m", _CHANNEL_ELEVATION_ATOL_M
                ),
            }
            for row_name, (metadata_name, atol) in geometry_checks.items():
                expected_value = row_dict.get(row_name)
                if expected_value is None or pd.isna(expected_value):
                    continue
                if not np.isclose(
                    float(expected_value),
                    float(orientation[metadata_name]),
                    atol=atol,
                    rtol=0.0,
                ):
                    raise ValueError(
                        f"Station table {row_name} does not match StationXML: "
                        f"{expected_value} versus {orientation[metadata_name]}."
                    )
            row_dict.update(orientation)
            common_start = max(trace.stats.starttime for trace in stream)
            common_end = min(trace.stats.endtime for trace in stream)
            if common_end <= common_start:
                raise ValueError("The components have no common recorded interval.")
            max_raw_delta = max(float(trace.stats.delta) for trace in stream)
            coverage_tolerance = max_raw_delta + 1e-6
            start_offset_s = float(common_start - target_start)
            end_offset_s = float(target_end - common_end)
            raw_common_start_offset_s = float(common_start - origin)
            p_arrival_s = float(row_dict["p_arrival_s"])
            available_pre_p_s = p_arrival_s - raw_common_start_offset_s
            # Leading padding protects timing flexibility, not a filter-period
            # heuristic. Response removal and filtering are performed on the
            # available raw trace before any zero padding is added, so using
            # 1/freqmin here made station acceptance change solely when the
            # analysis band was lowered (for example 0.02 -> 0.01 Hz).
            prearrival_guard_s = (
                float(max_reference_time_shift) + float(max_correlation_shift)
            )
            protected_p_offset_s = p_arrival_s - prearrival_guard_s
            protected_p_time = origin + protected_p_offset_s
            prearrival_padding_applied = start_offset_s > coverage_tolerance

            if prearrival_padding_applied:
                if not pad_missing_prearrival:
                    raise ValueError(
                        "Raw waveform begins after the required processed-window start: "
                        f"common_start={common_start}, required_start={target_start}, "
                        f"late_by={start_offset_s:.6f} s, "
                        f"allowed_one_sample={coverage_tolerance:.6f} s, and "
                        "pad_missing_prearrival=False."
                    )
                if common_start >= protected_p_time - coverage_tolerance:
                    raise ValueError(
                        "Raw waveform begins too late for safe pre-arrival padding: "
                        f"common_start={common_start}, protected_P_start={protected_p_time}, "
                        f"available_pre_P={available_pre_p_s:.6f} s, "
                        f"required_prearrival_guard={prearrival_guard_s:.6f} s."
                    )

            if end_offset_s > coverage_tolerance:
                raise ValueError(
                    "Raw waveform ends before the required processed-window end: "
                    f"common_end={common_end}, required_end={target_end}, "
                    f"short_by={end_offset_s:.6f} s, "
                    f"allowed_one_sample={coverage_tolerance:.6f} s."
                )

            row_dict.update({
                "raw_common_start_offset_s": raw_common_start_offset_s,
                "raw_common_end_offset_s": float(common_end - origin),
                "available_pre_p_s": float(available_pre_p_s),
                "prearrival_guard_s": float(prearrival_guard_s),
                "prearrival_padding_applied": bool(prearrival_padding_applied),
                "prearrival_padding_s": float(max(0.0, start_offset_s)),
                "prearrival_padding_samples": int(
                    np.count_nonzero(target_times < common_start.timestamp)
                ),
            })
            stream.trim(common_start, common_end, pad=False)

            corrected = Stream()
            for source_trace in stream:
                trace = source_trace.copy()
                trace.detrend("linear")
                trace.detrend("demean")
                kwargs = {
                    "inventory": inventory,
                    "output": motion,
                    "pre_filt": _default_pre_filt(trace, float(freqmin)),
                    "zero_mean": True,
                    "taper": True,
                }
                if water_level is not None:
                    kwargs["water_level"] = float(water_level)
                trace.remove_response(**kwargs)
                trace.detrend("linear")
                trace.detrend("demean")
                corrected += trace

            corrected.rotate(
                method="->ZNE",
                inventory=inventory,
                components=(component_scheme,),
            )
            zne = Stream()
            for component in "ZNE":
                selected = corrected.select(component=component)
                if len(selected) != 1:
                    raise ValueError(
                        f"Expected one {component} component after ZNE rotation; "
                        f"found {len(selected)}."
                    )
                zne += selected[0].copy()

            back_azimuth = float(row_dict["back_azimuth_deg"])
            zne.rotate(method="NE->RT", back_azimuth=back_azimuth)
            zne.filter(
                "bandpass",
                freqmin=float(freqmin),
                freqmax=float(freqmax),
                corners=int(corners),
                zerophase=True,
            )
            zne.taper(max_percentage=0.05, type="hann", side="both")

            candidate = Stream()
            for component in "ZRT":
                selected = zne.select(component=component)
                if len(selected) != 1:
                    raise ValueError(
                        f"Expected one {component} component after ZRT rotation; "
                        f"found {len(selected)}."
                    )
                trace = _sample_trace_at_times(
                    selected[0],
                    target_times,
                    dt,
                    pad_left=bool(prearrival_padding_applied),
                )
                trace.data = np.asarray(trace.data * scale, dtype=np.float32)
                trace.stats.network = str(row_dict["network"])
                trace.stats.station = str(row_dict["station"])
                trace.stats.location = str(row_dict.get("location", ""))
                trace.stats.channel = f"MT{component}"
                trace.stats.units = output_units
                trace.stats.back_azimuth = back_azimuth
                trace.stats.coordinates = {
                    "latitude": float(row_dict["station_lat"]),
                    "longitude": float(row_dict["station_lon"]),
                    "elevation": float(row_dict.get("station_elevation_m", 0.0)),
                }
                if component == "Z":
                    component_azimuth, component_incidence = 0.0, 0.0
                elif component == "R":
                    component_azimuth = float(row_dict["azimuth_deg"]) % 360.0
                    component_incidence = 90.0
                else:
                    component_azimuth = (
                        float(row_dict["azimuth_deg"]) + 90.0
                    ) % 360.0
                    component_incidence = 90.0
                p_arrival = float(row_dict.get("p_arrival_s", np.nan))
                s_arrival = float(row_dict.get("s_arrival_s", np.nan))
                trace.stats.sac = AttribDict({
                    "stla": float(row_dict["station_lat"]),
                    "stlo": float(row_dict["station_lon"]),
                    "stel": float(row_dict.get("station_elevation_m", 0.0)),
                    "evla": float(event["event_lat"]),
                    "evlo": float(event["event_lon"]),
                    "evdp": float(event["event_depth_km"]),
                    "az": float(row_dict["azimuth_deg"]),
                    "baz": back_azimuth,
                    "dist": distance_km,
                    "cmpaz": component_azimuth,
                    "cmpinc": component_incidence,
                    "o": 0.0,
                    "b": float(geometry["window_start_offset_s"]),
                    "a": p_arrival,
                    "ka": "P",
                    "t0": p_arrival,
                    "kt0": "P",
                    "t1": s_arrival,
                    "kt1": "S",
                    "t2": 0.0,
                    "kt2": "ORIGIN",
                    "t3": float(geometry["inversion_end_offset_s"]),
                    "kt3": "INVEND",
                    "user0": p_arrival,
                    "user1": s_arrival,
                    "user2": float(freqmin),
                    "user3": float(freqmax),
                    "user4": float(corners),
                    "user5": float(dt),
                    "user6": float(time_before_window_start),
                    "user7": float(time_after_window_end),
                    "user8": float(geometry["stored_npts"]),
                    "user9": float(geometry["correlation_max_shift_s"]),
                    "kstnm": str(row_dict["station"])[:8],
                    "knetwk": str(row_dict["network"])[:8],
                    "khole": str(row_dict.get("location", ""))[:8],
                    "kcmpnm": component,
                    "kevnm": str(event["event_id"])[:16],
                })
                _set_sac_signature(trace, "MTHOBS", signature)
                candidate += trace

            persisted = _write_observed_triplet(
                candidate,
                data_paths=data_paths,
                signature=signature,
                expected_start=target_start,
                expected_npts=geometry["stored_npts"],
                expected_dt=float(dt),
                station_id=station_id,
                row=row_dict,
                output_units=output_units,
                read=read,
                Stream=Stream,
            )
            output_stream += persisted

            if overwrite and existing_count:
                status = "overwritten"
            elif existing_count:
                status = "rewritten"
            else:
                status = "written"
            station_rows.append(_processed_station_record(
                row_dict,
                station_id=station_id,
                distance_km=distance_km,
                window_settings=window_settings,
                geometry=geometry,
                dt=dt,
                used=used,
                motion=motion,
                output_units=output_units,
                freqmin=freqmin,
                freqmax=freqmax,
                corners=corners,
                data_dir=data_dir,
                status=status,
                signature=signature,
                origin=origin,
            ))
            log_rows.append({
                **base_log,
                "status": status,
                "reason": "",
                "cache_reason": cache_reason,
                "window_starttime": str(target_start),
                "window_endtime": str(target_end),
                "origin_ts": int(geometry["origin_ts"]),
                "reference_ts": int(geometry["reference_ts"]),
                "ts": int(geometry["ts"]),
                "npts": int(geometry["npts"]),
                "stored_npts": int(geometry["stored_npts"]),
                "max_reference_time_shift": float(
                    geometry["max_reference_time_shift"]
                ),
                "max_reference_time_shift_samples": int(
                    geometry["max_reference_time_shift_samples"]
                ),
                "raw_common_start_offset_s": row_dict.get(
                    "raw_common_start_offset_s", np.nan
                ),
                "available_pre_p_s": row_dict.get("available_pre_p_s", np.nan),
                "prearrival_guard_s": row_dict.get("prearrival_guard_s", np.nan),
                "prearrival_padding_applied": row_dict.get(
                    "prearrival_padding_applied", False
                ),
                "prearrival_padding_s": row_dict.get("prearrival_padding_s", 0.0),
                "prearrival_padding_samples": row_dict.get(
                    "prearrival_padding_samples", 0
                ),
            })
        except Exception as exc:
            log_rows.append({
                **base_log,
                "status": "failed",
                "reason": str(exc),
                "cache_reason": cache_reason,
            })

    processed_station_df = pd.DataFrame(station_rows)
    if not processed_station_df.empty:
        processed_station_df.sort_values(
            "distance", inplace=True, ignore_index=True
        )
    processing_log = pd.DataFrame(log_rows)
    processed_station_df.to_csv(
        metadata_dir / "stations_processed.csv", index=False
    )
    processing_log.to_csv(metadata_dir / "processing_log.csv", index=False)

    record_section_path = figure_dir / "waveform_record_section.png"
    unfiltered_record_section_path = (
        figure_dir / "waveform_record_section_unfiltered.png"
    )
    station_map_path = figure_dir / "station_map.png"
    if plot:
        if len(output_stream):
            _plot_observed_record_section(
                output_stream, origin, processed_station_df, record_section_path
            )
            unfiltered_stream = _build_unfiltered_observed_stream_for_plot(
                processed_station_df,
                origin,
                motion=motion,
                water_level=water_level,
                freqmin=float(freqmin),
                dt=float(dt),
                read=read,
                read_inventory=read_inventory,
                Stream=Stream,
            )
            if len(unfiltered_stream):
                _plot_observed_record_section(
                    unfiltered_stream,
                    origin,
                    processed_station_df,
                    unfiltered_record_section_path,
                    amplitude_scale=1.25,
                    figure_title=(
                        "Response-corrected ZRT waveforms before bandpass filtering"
                    ),
                )
            elif unfiltered_record_section_path.exists():
                unfiltered_record_section_path.unlink()
        else:
            for path in (record_section_path, unfiltered_record_section_path):
                if path.exists():
                    path.unlink()
    if plot_station_map:
        if not processed_station_df.empty:
            _plot_station_map(event, processed_station_df, station_map_path)
        elif station_map_path.exists():
            station_map_path.unlink()

    return output_stream, processed_station_df, processing_log


def generate_pyfk_gfs(
    event_df: pd.DataFrame | pd.Series | Mapping[str, Any],
    station_df: pd.DataFrame,
    velocity_model: pd.DataFrame | Any,
    *,
    depths_km: Sequence[float],
    output_dir: str | Path,
    depth_col: str = "depth",
    vp_col: str = "Vp",
    vs_col: str = "Vs",
    density_col: str | None = None,
    qs_col: str | None = None,
    qp_col: str | None = None,
    grid_mode: str = "path",
    profile_location: tuple[float, float] | None = None,
    profile_crs: str = "EPSG:4326",
    path_spacing_km: float = 2.0,
    path_profile: str = "median",
    surface_depth_km: float = 0.0,
    max_depth_km: float | None = None,
    compress: bool = True,
    motion: str | None = None,
    freqmin: float | None = None,
    freqmax: float | None = None,
    corners: int | None = None,
    dt: float | None = None,
    pyfk_dt: float = 0.1,
    pyfk_npt: int | None = None,
    samples_before_first_arrival: int = 100,
    pyfk_native_motion: str = "VEL",
    pyfk_flattening: bool = False,
    pyfk_config_kwargs: Mapping[str, Any] | None = None,
    batch_common_model: bool = True,
    plot: bool = False,
    progress: bool = True,
    overwrite: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate MTtime Herrmann Green's functions with pyFK.

    Parameters
    ----------
    event_df, station_df
        Event metadata and the authoritative processed station table returned by
        :func:`process_mseed_sac`.
    velocity_model
        Either a depth-sampled 1-D :class:`pandas.DataFrame` or a prepared
        :class:`gf_helpers.VelocityGrid3D` object. A DataFrame is converted once
        and reused for every station. A grid may provide one fixed profile, one
        vertical profile per station, or a station-specific event-to-station
        path profile.
    depths_km
        Positive trial source depths below the selected layered-model top. The
        requested values are used in filenames and MTtime metadata. If a value
        lies exactly on a real interface, pyFK is evaluated 0.001 km deeper and
        the actual calculation depth is recorded separately.
    output_dir
        Event root directory. Herrmann basis files are written directly under
        ``greens``; manifests under ``metadata``; optional diagnostic figures
        under ``figures``.
    depth_col, vp_col, vs_col, density_col, qs_col, qp_col
        Input model column names. Velocities are km/s, density is g/cm3 and Q is
        dimensionless. Optional density and attenuation values are passed only
        when supplied; omitted properties are left to :class:`pyfk.SeisModel`
        rather than synthesized by this helper. ``qp_col`` requires ``qs_col``
        and an explicitly supplied Qp also requires density because of pyFK's
        positional model format. ``depth_col`` applies to a 1-D DataFrame.
    grid_mode
        For a :class:`gf_helpers.VelocityGrid3D`, ``"path"`` derives one
        representative model per event-station path, ``"station"`` extracts one
        vertical profile at each authoritative processed-station coordinate, and
        ``"profile"`` extracts one fixed profile that is reused for every
        station. The default remains ``"path"`` for backward compatibility.
    profile_location, profile_crs
        Fixed profile coordinates and CRS for ``grid_mode="profile"``. If
        omitted, the event longitude/latitude in EPSG:4326 are used.
    path_spacing_km, path_profile
        Path-sampling interval and depth-wise statistic passed internally to
        :func:`gf_helpers.get_profile_from_path` for ``grid_mode="path"``.
    surface_depth_km, max_depth_km, compress
        Vertical clipping, maximum retained depth and adjacent-layer compression
        settings forwarded to ``gf_helpers``.
    motion, freqmin, freqmax, corners, dt
        Final Green's-function processing settings. Missing values are inferred
        from ``station_df`` and must be common across stations. The inversion
        length is not a function argument: each station supplies its own ``npts``.
        Every Green's-function basis starts at event-origin time zero, while the
        observed ``ts`` selects the corresponding origin-aligned data segment.
    pyfk_dt, pyfk_npt
        Internal pyFK sample interval and FFT length. ``pyfk_npt=None``
        (default) selects the smallest even number of samples that guarantees
        coverage of the longest station-specific MTtime trace plus one period at
        ``freqmin`` for the zero-phase filter guard. Supply a larger positive
        even integer to retain a longer internal pyFK record. Explicit values
        shorter than the calculated requirement are rejected with the required
        minimum reported in the error message.
    samples_before_first_arrival
        Number of internal pyFK samples retained before pyFK's predicted first
        P arrival. When event origin precedes pyFK's retained record start, the
        missing pre-arrival interval is extended explicitly with causal zeros
        before filtering. This does not replace missing late waveform energy;
        ``pyfk_npt`` must cover the complete origin-aligned GF interval.
    pyfk_native_motion
        Temporal order assigned to native dynamic :func:`pyfk.calculate_gf`
        traces. The default ``"VEL"`` follows the CPS benchmark validation;
        displacement targets are integrated once before the inversion bandpass.
        This setting is included in the cache signature.
    pyfk_flattening
        Boolean passed to :class:`pyfk.SeisModel` as its ``flattening`` argument.
        ``False`` (default) preserves the existing flat layered-Earth calculation.
        ``True`` activates pyFK's native Earth-flattening transformation of layer
        thicknesses and velocities; pyFK then applies the corresponding source-
        and receiver-depth transformation when constructing :class:`pyfk.Config`.
        Receiver distances remain the existing epicentral distances in kilometres.
        This option is independent of ``pyfk_config_kwargs``, is recorded in both
        output manifests, and is part of the Green's-function cache signature.
    pyfk_config_kwargs
        Optional overrides for :class:`pyfk.Config`. The helper starts from the
        convergence-tested defaults ``dk=0.15`` and ``kmax=15.0``; values supplied
        here replace those defaults. ``model``, ``source``, ``receiver_distance``,
        ``dt``, ``npt``, ``samples_before_first_arrival`` and ``flattening`` are
        controlled by this function and cannot be overridden; use
        ``pyfk_flattening`` for the latter.
    batch_common_model
        If ``True`` (default), a common 1-D DataFrame model or one fixed grid
        profile is evaluated for all receiver distances in a single pyFK call
        per source depth and source type. Station-dependent ``grid_mode="path"``
        and ``grid_mode="station"`` models are never receiver-batched. Set
        ``False`` for a direct comparison with the legacy one-station-per-call
        calculation.
    plot
        Save one ten-panel basis-function record section for each trial depth.
    progress
        Display one overall tqdm progress bar covering every station-depth
        combination. Cached and newly generated Green's-function sets each
        advance the bar once. Set to ``False`` to disable the progress display.
    overwrite
        If ``True``, force every station/depth calculation. If ``False``, the
        ten-file Herrmann set is reused only when every file has the expected
        deterministic signature, ``npts``, ``dt`` and finite values. Missing,
        partial, corrupt or incompatible sets are recalculated and rewritten
        automatically.

    Returns
    -------
    gf_manifest : pandas.DataFrame
        One row per station, requested depth and Herrmann basis file. It records
        requested/actual pyFK depths, processing settings, cache status and the
        deterministic signature used to validate reuse.
    model_manifest : pandas.DataFrame
        One row per station/depth describing whether the model came from a 1-D
        DataFrame, fixed grid profile or path statistic, together with path
        length, layer count and cache status.

    Notes
    -----
    MTtime permits station-specific ``npts`` values. For station ``i``, this
    function samples every Herrmann basis from origin-relative time zero for
    exactly ``station_df.loc[i, "npts"]`` samples at the common final ``dt``.
    The matching observed segment begins at ``station_df.loc[i, "ts"]``.  Thus
    the unshifted baseline always compares the same physical origin time, while
    optional correlation changes only the observed start index within the
    bounded margins prepared by :func:`process_mseed_sac`.

    The function delegates all layer conversion, path extraction and Herrmann
    basis naming to ``gf_helpers``; those algorithms are not duplicated here.
    When a common model is batched, the complete ordered receiver-distance array
    is included in every cache signature because pyFK's wavenumber spacing uses
    the maximum receiver distance. If one station set at a depth is missing or
    incompatible, the complete common-model batch for that depth is recomputed
    so all stations retain one deterministic numerical discretization.

    Matching cached files avoid rerunning pyFK, which is particularly important
    for station-specific path models and dense source-depth grids.
    """
    from obspy import Stream, UTCDateTime, read
    from tqdm.auto import tqdm
    import pyfk as pyfk_module
    from pyfk import Config, SeisModel, SourceModel, calculate_gf
    import gf_helpers as gf_helpers_module
    from gf_helpers import (
        VelocityGrid3D, get_profile_from_path, layers_to_pyfk_array,
        profile_to_pyfk_layers, write_mttime_herrmann_sac,
    )

    if station_df.empty:
        raise ValueError("station_df is empty.")
    if not isinstance(batch_common_model, (bool, np.bool_)):
        raise TypeError("batch_common_model must be a boolean.")
    if not isinstance(pyfk_flattening, (bool, np.bool_)):
        raise TypeError("pyfk_flattening must be a boolean.")
    batch_common_model = bool(batch_common_model)
    pyfk_flattening = bool(pyfk_flattening)
    _validate_station_depth_policy(station_df)
    event = _event_record(event_df)
    depths = sorted({float(value) for value in depths_km})
    if not depths or any(
        not np.isfinite(value) or value <= 0 for value in depths
    ):
        raise ValueError("depths_km must contain finite positive source depths.")

    pyfk_dt = float(pyfk_dt)
    samples_before_float = float(samples_before_first_arrival)
    if not np.isfinite(pyfk_dt) or pyfk_dt <= 0:
        raise ValueError("pyfk_dt must be finite and positive.")
    if (
        not np.isfinite(samples_before_float)
        or samples_before_float < 0
        or not np.isclose(samples_before_float, round(samples_before_float))
    ):
        raise ValueError("samples_before_first_arrival must be a non-negative integer.")
    samples_before_first_arrival = int(round(samples_before_float))

    settings = _gf_processing_settings(
        station_df,
        motion=motion,
        freqmin=freqmin,
        freqmax=freqmax,
        corners=corners,
        dt=dt,
    )

    pyfk_native_motion = _normalize_motion_name(
        pyfk_native_motion, "pyfk_native_motion"
    )
    settings["pyfk_native_motion"] = pyfk_native_motion
    settings["motion_conversion"] = _motion_conversion_label(
        pyfk_native_motion, settings["motion"]
    )

    filter_guard_s = _gf_filter_guard_seconds(settings)

    # Preflight pyFK record duration before extracting station-specific models.
    if "npts" not in station_df.columns:
        raise KeyError(
            "station_df is missing npts. Run process_mseed_sac before "
            "generate_pyfk_gfs."
        )

    station_npts_float = pd.to_numeric(
        station_df["npts"],
        errors="raise",
    ).to_numpy(dtype=float)
    station_npts_rounded = np.rint(station_npts_float)
    if (
        not np.isfinite(station_npts_float).all()
        or (station_npts_rounded < 1).any()
        or not np.allclose(
            station_npts_float,
            station_npts_rounded,
            atol=1e-8,
            rtol=0.0,
        )
    ):
        raise ValueError(
            "station_df['npts'] must contain finite positive integers."
        )
    station_npts = station_npts_rounded.astype(int)

    # Green's functions begin at origin. The latest required retained sample is
    # determined by the longest station-specific MTtime segment.
    max_target_end_s = float(
        np.max((station_npts - 1) * float(settings["dt"]))
    )
    required_pyfk_end_s = max_target_end_s + filter_guard_s

    # A pyFK trace starts samples_before_first_arrival samples before its first
    # arrival. Since travel time cannot be negative, this is the conservative
    # minimum record length that guarantees the required late-time coverage.
    minimum_pyfk_npt = (
        int(np.ceil(required_pyfk_end_s / pyfk_dt))
        + samples_before_first_arrival
        + 1
    )
    if minimum_pyfk_npt % 2:
        minimum_pyfk_npt += 1

    pyfk_npt_was_automatic = pyfk_npt is None
    if pyfk_npt_was_automatic:
        pyfk_npt = int(minimum_pyfk_npt)
    else:
        pyfk_npt_float = float(pyfk_npt)
        if (
            not np.isfinite(pyfk_npt_float)
            or pyfk_npt_float < 1
            or not np.isclose(pyfk_npt_float, round(pyfk_npt_float))
        ):
            raise ValueError("pyfk_npt must be None or a positive even integer.")
        pyfk_npt = int(round(pyfk_npt_float))
        if pyfk_npt % 2:
            raise ValueError("pyfk_npt must be even when supplied explicitly.")

    guaranteed_pyfk_end_s = float(
        (pyfk_npt - 1 - samples_before_first_arrival) * pyfk_dt
    )
    coverage_tolerance = max(1e-8, 0.01 * pyfk_dt)
    if guaranteed_pyfk_end_s < required_pyfk_end_s - coverage_tolerance:
        raise ValueError(
            "pyfk_npt is too small for the requested MTtime duration and "
            "zero-phase filter guard. The longest station requires coverage "
            f"through {required_pyfk_end_s:.3f} s, but pyfk_npt={pyfk_npt}, "
            f"pyfk_dt={pyfk_dt:g} and "
            f"samples_before_first_arrival={samples_before_first_arrival} "
            f"guarantee coverage only through {guaranteed_pyfk_end_s:.3f} s. "
            f"Use an even pyfk_npt >= {minimum_pyfk_npt}, increase pyfk_dt "
            "while preserving the required bandwidth, or shorten "
            "inversion_duration."
        )

    root = Path(output_dir).expanduser()

    green_dir = root / "greens"
    metadata_dir = root / "metadata"
    figure_dir = root / "figures"
    for directory in (green_dir, metadata_dir, figure_dir):
        directory.mkdir(parents=True, exist_ok=True)

    is_grid = isinstance(velocity_model, VelocityGrid3D)
    if not is_grid and not isinstance(velocity_model, pd.DataFrame):
        raise TypeError(
            "velocity_model must be a pandas DataFrame or "
            "gf_helpers.VelocityGrid3D."
        )
    grid_mode = str(grid_mode).lower()
    if is_grid and grid_mode not in {"path", "station", "profile"}:
        raise ValueError("grid_mode must be 'path', 'station' or 'profile'.")

    common_array = None
    common_description = None
    if isinstance(velocity_model, pd.DataFrame):
        layers = profile_to_pyfk_layers(
            velocity_model, depth_col=depth_col, vp_col=vp_col, vs_col=vs_col,
            density_col=density_col, qs_col=qs_col, qp_col=qp_col,
            surface_depth_km=surface_depth_km,
            max_depth_km=max_depth_km, compress=compress,
        )
        common_array = layers_to_pyfk_array(layers)
        common_description = "1d_dataframe"
    elif grid_mode == "profile":
        if profile_location is None:
            profile_location = (
                float(event["event_lon"]), float(event["event_lat"])
            )
            profile_crs = "EPSG:4326"
        profile = velocity_model.extract_profile(
            float(profile_location[0]), float(profile_location[1]),
            crs=profile_crs,
            value_names=[
                name for name in (vp_col, vs_col, density_col, qs_col, qp_col)
                if name is not None
            ],
        )
        layers = profile_to_pyfk_layers(
            profile, depth_col="Depth_km", vp_col=vp_col, vs_col=vs_col,
            density_col=density_col, qs_col=qs_col, qp_col=qp_col,
            surface_depth_km=surface_depth_km,
            max_depth_km=max_depth_km, compress=compress,
        )
        common_array = layers_to_pyfk_array(layers)
        common_description = (
            f"grid_profile:{profile_location[0]},{profile_location[1]}:"
            f"{profile_crs}"
        )

    gf_rows: list[dict[str, Any]] = []
    model_rows: list[dict[str, Any]] = []
    config_kwargs = dict(_PYFK_CONFIG_DEFAULTS)
    config_kwargs.update(dict(pyfk_config_kwargs or {}))
    forbidden = {
        "model", "source", "receiver_distance", "dt", "npt",
        "samples_before_first_arrival", "flattening",
    }
    overlap = forbidden.intersection(config_kwargs)
    if overlap:
        raise ValueError(
            f"pyfk_config_kwargs cannot override: {sorted(overlap)}"
        )

    pyfk_version = str(getattr(pyfk_module, "__version__", "unknown"))
    gf_helpers_version = str(
        getattr(gf_helpers_module, "__version__", "unknown")
    )

    progress_bar = tqdm(
        total=len(station_df) * len(depths),
        desc="pyFK Green's functions",
        unit="set",
        disable=not progress,
    )

    def _station_context(station) -> dict[str, Any]:
        row = station._asdict()
        station_id = str(
            row["station_id"]
            if "station_id" in row
            else _station_id_from_row(row)
        )
        distance_value = row.get("distance", row.get("distance_km"))
        if distance_value is None:
            raise KeyError(f"Station {station_id} has no distance column.")
        distance_km = float(distance_value)
        if not np.isfinite(distance_km) or distance_km < 0:
            raise ValueError(
                f"Station {station_id} has invalid distance {distance_km}."
            )

        required_timing = {
            "window_start_offset_s", "origin_ts", "ts", "npts",
            "stored_npts", "correlation_max_shift_samples",
        }
        missing_timing = required_timing.difference(row)
        if missing_timing:
            raise KeyError(
                f"Station {station_id} is missing processed timing fields "
                f"{sorted(missing_timing)}. Run process_mseed_sac before "
                "generating Green's functions."
            )
        station_npts = int(row["npts"])
        station_ts = int(row["ts"])
        origin_ts = int(row["origin_ts"])
        stored_npts = int(row["stored_npts"])
        max_shift_samples = int(row["correlation_max_shift_samples"])
        if station_npts < 1:
            raise ValueError(f"Station {station_id} has npts < 1.")
        if station_ts != origin_ts:
            raise ValueError(
                f"Station {station_id} has ts={station_ts} but "
                f"origin_ts={origin_ts}; origin alignment is required as the "
                "unshifted baseline."
            )
        if station_ts < max_shift_samples:
            raise ValueError(
                f"Station {station_id} has insufficient pre-origin samples for "
                f"the requested correlation margin ({max_shift_samples})."
            )
        post_samples = stored_npts - (station_ts + station_npts)
        if post_samples < max_shift_samples:
            raise ValueError(
                f"Station {station_id} has only {post_samples} post-inversion "
                f"samples but requires {max_shift_samples}."
            )
        window_start_offset_s = float(row["window_start_offset_s"])
        if not np.isfinite(window_start_offset_s):
            raise ValueError(
                f"Station {station_id} has a non-finite "
                "window_start_offset_s."
            )
        return {
            "row": row,
            "station_id": station_id,
            "distance_km": distance_km,
            "npts": station_npts,
            "origin_ts": origin_ts,
            "max_shift_samples": max_shift_samples,
            "gf_start_offset_s": 0.0,
            "station_settings": {**settings, "npts": station_npts},
        }

    station_contexts = [
        _station_context(station)
        for station in station_df.itertuples(index=False)
    ]

    def _gf_paths(station_id: str, requested_depth: float) -> dict[str, Path]:
        return {
            basis: green_dir / f"{station_id}.{requested_depth:.4f}.{basis}"
            for basis in _HERRMANN_BASES
        }

    def _append_cached_rows(
        context: Mapping[str, Any],
        *,
        requested_depth: float,
        actual_depth: float,
        signature: str,
        cached_records,
        model_description: str,
        path_length_km: float,
        model_array: np.ndarray,
        model_metadata: Mapping[str, Any],
        cache_reason: str,
        batch_mode: str,
        batch_size: int,
    ) -> None:
        for record in cached_records:
            gf_rows.append({
                **record,
                "station_id": context["station_id"],
                "requested_depth_km": requested_depth,
                "pyfk_source_depth_km": actual_depth,
                "distance_km": context["distance_km"],
                "motion": settings["motion"],
                "units": settings["units"],
                "pyfk_native_motion": settings["pyfk_native_motion"],
                "motion_conversion": settings["motion_conversion"],
                "freqmin": settings["freqmin"],
                "freqmax": settings["freqmax"],
                "corners": settings["corners"],
                "gf_start_offset_s": context["gf_start_offset_s"],
                "filter_guard_s": filter_guard_s,
                "origin_ts": context["origin_ts"],
                "correlation_max_shift_samples": context["max_shift_samples"],
                "npts": context["npts"],
                "pyfk_npt": int(pyfk_npt),
                "minimum_pyfk_npt": int(minimum_pyfk_npt),
                "pyfk_npt_mode": (
                    "automatic" if pyfk_npt_was_automatic else "user"
                ),
                "pyfk_flattening": pyfk_flattening,
                "processing_signature": signature,
                "cache_status": "existing",
                "cache_reason": cache_reason,
                "batch_mode": batch_mode,
                "batch_size": int(batch_size),
            })
        model_rows.append({
            "station_id": context["station_id"],
            "requested_depth_km": requested_depth,
            "pyfk_source_depth_km": actual_depth,
            "model_source": model_description,
            "path_length_km": path_length_km,
            "n_layers": int(model_array.shape[0]),
            **model_metadata,
            "raw_record_end_s": np.nan,
            "raw_tail_start_s": np.nan,
            "raw_tail_available": False,
            "raw_tail_peak_ratio": np.nan,
            "raw_tail_rms_ratio": np.nan,
            "surface_depth_km": float(surface_depth_km),
            "gf_start_offset_s": context["gf_start_offset_s"],
            "filter_guard_s": filter_guard_s,
            "origin_ts": context["origin_ts"],
            "correlation_max_shift_samples": context["max_shift_samples"],
            "npts": context["npts"],
            "pyfk_npt": int(pyfk_npt),
            "minimum_pyfk_npt": int(minimum_pyfk_npt),
            "pyfk_npt_mode": (
                "automatic" if pyfk_npt_was_automatic else "user"
            ),
            "pyfk_flattening": pyfk_flattening,
            "dt": settings["dt"],
            "processing_signature": signature,
            "cache_status": "existing",
            "cache_reason": cache_reason,
            "batch_mode": batch_mode,
            "batch_size": int(batch_size),
        })

    def _write_generated_rows(
        context: Mapping[str, Any],
        *,
        requested_depth: float,
        actual_depth: float,
        signature: str,
        dc_stream,
        ep_stream,
        output_paths: Mapping[str, Path],
        existing_count: int,
        cache_reason: str,
        model_description: str,
        path_length_km: float,
        model_array: np.ndarray,
        model_metadata: Mapping[str, Any],
        batch_mode: str,
        batch_size: int,
        batch_recalculated: bool = False,
    ) -> None:
        tail_metrics = _pyfk_tail_metrics(
            [*dc_stream, *ep_stream],
            retained_end_s=(context["npts"] - 1) * float(settings["dt"]),
            guard_s=filter_guard_s,
        )
        dc_processed = _process_pyfk_stream(
            dc_stream,
            context["station_settings"],
            context["gf_start_offset_s"],
            UTCDateTime,
            Stream,
        )
        ep_processed = _process_pyfk_stream(
            ep_stream,
            context["station_settings"],
            context["gf_start_offset_s"],
            UTCDateTime,
            Stream,
        )
        _tag_stream_signature(dc_processed, "MTHGF", signature)
        _tag_stream_signature(ep_processed, "MTHGF", signature)

        manifest = write_mttime_herrmann_sac(
            [dc_processed], [ep_processed],
            stations=[context["station_id"]],
            source_depth_km=requested_depth,
            output_dir=green_dir,
            overwrite=True,
        )
        _validate_written_gf_set(
            output_paths=output_paths,
            signature=signature,
            expected_npts=context["npts"],
            expected_dt=settings["dt"],
            read=read,
        )

        if overwrite and existing_count:
            cache_status = "overwritten"
        elif existing_count and batch_recalculated:
            cache_status = "rewritten_batch"
        elif existing_count:
            cache_status = "rewritten"
        else:
            cache_status = "written"

        for record in manifest.to_dict("records"):
            gf_rows.append({
                **record,
                "station_id": context["station_id"],
                "requested_depth_km": requested_depth,
                "pyfk_source_depth_km": actual_depth,
                "distance_km": context["distance_km"],
                "motion": settings["motion"],
                "units": settings["units"],
                "pyfk_native_motion": settings["pyfk_native_motion"],
                "motion_conversion": settings["motion_conversion"],
                "freqmin": settings["freqmin"],
                "freqmax": settings["freqmax"],
                "corners": settings["corners"],
                "gf_start_offset_s": context["gf_start_offset_s"],
                "filter_guard_s": filter_guard_s,
                "origin_ts": context["origin_ts"],
                "correlation_max_shift_samples": context["max_shift_samples"],
                "npts": context["npts"],
                "pyfk_npt": int(pyfk_npt),
                "minimum_pyfk_npt": int(minimum_pyfk_npt),
                "pyfk_npt_mode": (
                    "automatic" if pyfk_npt_was_automatic else "user"
                ),
                "pyfk_flattening": pyfk_flattening,
                "processing_signature": signature,
                "cache_status": cache_status,
                "cache_reason": cache_reason,
                "batch_mode": batch_mode,
                "batch_size": int(batch_size),
            })
        model_rows.append({
            "station_id": context["station_id"],
            "requested_depth_km": requested_depth,
            "pyfk_source_depth_km": actual_depth,
            "model_source": model_description,
            "path_length_km": path_length_km,
            "n_layers": int(model_array.shape[0]),
            **model_metadata,
            **tail_metrics,
            "surface_depth_km": float(surface_depth_km),
            "gf_start_offset_s": context["gf_start_offset_s"],
            "filter_guard_s": filter_guard_s,
            "origin_ts": context["origin_ts"],
            "correlation_max_shift_samples": context["max_shift_samples"],
            "npts": context["npts"],
            "pyfk_npt": int(pyfk_npt),
            "minimum_pyfk_npt": int(minimum_pyfk_npt),
            "pyfk_npt_mode": (
                "automatic" if pyfk_npt_was_automatic else "user"
            ),
            "pyfk_flattening": pyfk_flattening,
            "dt": settings["dt"],
            "processing_signature": signature,
            "cache_status": cache_status,
            "cache_reason": cache_reason,
            "batch_mode": batch_mode,
            "batch_size": int(batch_size),
        })

    if common_array is not None and batch_common_model:
        model_array = np.asarray(common_array, dtype=float)
        model_description = str(common_description)
        model_metadata = _pyfk_model_metadata(model_array)
        seis_model = SeisModel(model=model_array, flattening=pyfk_flattening)
        receiver_distances = np.asarray(
            [context["distance_km"] for context in station_contexts],
            dtype=float,
        )
        batch_size = len(station_contexts)

        for requested_depth in depths:
            actual_depth = _source_depth_off_interface(
                model_array, requested_depth
            )
            entries = []
            all_cached = not overwrite
            for context in station_contexts:
                signature = _gf_processing_signature(
                    station_id=context["station_id"],
                    distance_km=context["distance_km"],
                    gf_start_offset_s=context["gf_start_offset_s"],
                    requested_depth=requested_depth,
                    actual_depth=actual_depth,
                    model_array=model_array,
                    settings=context["station_settings"],
                    pyfk_dt=pyfk_dt,
                    pyfk_npt=pyfk_npt,
                    samples_before_first_arrival=samples_before_first_arrival,
                    config_kwargs=config_kwargs,
                    pyfk_flattening=pyfk_flattening,
                    pyfk_version=pyfk_version,
                    gf_helpers_version=gf_helpers_version,
                    batch_mode="common_receiver_batch",
                    receiver_distance_batch=receiver_distances,
                )
                output_paths = _gf_paths(
                    context["station_id"], requested_depth
                )
                existing_count = sum(
                    path.exists() for path in output_paths.values()
                )
                cache_reason = "overwrite=True"
                cached_records = None
                if not overwrite:
                    cached_records, cache_reason = _load_cached_gf_records(
                        output_paths=output_paths,
                        signature=signature,
                        station_id=context["station_id"],
                        requested_depth=requested_depth,
                        expected_npts=context["npts"],
                        expected_dt=settings["dt"],
                        read=read,
                    )
                    if cached_records is None:
                        all_cached = False
                entries.append({
                    "context": context,
                    "signature": signature,
                    "output_paths": output_paths,
                    "existing_count": existing_count,
                    "cache_reason": cache_reason,
                    "cached_records": cached_records,
                })

            if all_cached:
                for entry in entries:
                    _append_cached_rows(
                        entry["context"],
                        requested_depth=requested_depth,
                        actual_depth=actual_depth,
                        signature=entry["signature"],
                        cached_records=entry["cached_records"],
                        model_description=model_description,
                        path_length_km=np.nan,
                        model_array=model_array,
                        model_metadata=model_metadata,
                        cache_reason=entry["cache_reason"],
                        batch_mode="common_receiver_batch",
                        batch_size=batch_size,
                    )
                    progress_bar.update(1)
                continue

            dc_source = SourceModel(sdep=actual_depth, srcType="dc")
            ep_source = SourceModel(sdep=actual_depth, srcType="ep")
            base_config = {
                "model": seis_model,
                "receiver_distance": receiver_distances,
                "npt": int(pyfk_npt),
                "dt": float(pyfk_dt),
                "samples_before_first_arrival": int(
                    samples_before_first_arrival
                ),
                **config_kwargs,
            }
            dc_streams = calculate_gf(Config(source=dc_source, **base_config))
            ep_streams = calculate_gf(Config(source=ep_source, **base_config))
            if len(dc_streams) != batch_size or len(ep_streams) != batch_size:
                raise RuntimeError(
                    "pyFK returned a receiver count inconsistent with the common "
                    f"batch: expected {batch_size}, got DC={len(dc_streams)} and "
                    f"EP={len(ep_streams)}."
                )

            for index, entry in enumerate(entries):
                cache_reason = entry["cache_reason"]
                if (
                    not overwrite
                    and entry["cached_records"] is not None
                    and not all_cached
                ):
                    cache_reason = (
                        "valid station cache rewritten because another station "
                        "in the common receiver batch was not reusable"
                    )
                _write_generated_rows(
                    entry["context"],
                    requested_depth=requested_depth,
                    actual_depth=actual_depth,
                    signature=entry["signature"],
                    dc_stream=dc_streams[index],
                    ep_stream=ep_streams[index],
                    output_paths=entry["output_paths"],
                    existing_count=entry["existing_count"],
                    cache_reason=cache_reason,
                    model_description=model_description,
                    path_length_km=np.nan,
                    model_array=model_array,
                    model_metadata=model_metadata,
                    batch_mode="common_receiver_batch",
                    batch_size=batch_size,
                    batch_recalculated=not overwrite,
                )
                progress_bar.update(1)
    else:
        # Legacy common-model mode and station-dependent grid models deliberately
        # retain one pyFK receiver per call. ``path`` derives one representative
        # event-to-station model, while ``station`` extracts one vertical model at
        # the authoritative receiver coordinate.
        for context in station_contexts:
            row = context["row"]
            if common_array is not None:
                model_array = np.asarray(common_array, dtype=float).copy()
                model_description = str(common_description)
                path_length_km = np.nan
                batch_mode = "station_common_legacy"
            else:
                station_lon = float(
                    row.get("longitude", row.get("station_lon"))
                )
                station_lat = float(
                    row.get("latitude", row.get("station_lat"))
                )
                if grid_mode == "station":
                    profile = velocity_model.extract_profile(
                        station_lon,
                        station_lat,
                        crs="EPSG:4326",
                        value_names=[
                            name for name in (
                                vp_col, vs_col, density_col, qs_col, qp_col
                            )
                            if name is not None
                        ],
                    )
                    layers = profile_to_pyfk_layers(
                        profile,
                        depth_col="Depth_km",
                        vp_col=vp_col,
                        vs_col=vs_col,
                        density_col=density_col,
                        qs_col=qs_col,
                        qp_col=qp_col,
                        surface_depth_km=surface_depth_km,
                        max_depth_km=max_depth_km,
                        compress=compress,
                    )
                    model_array = layers_to_pyfk_array(layers)
                    model_description = "grid_station"
                    path_length_km = np.nan
                    batch_mode = "station_specific_vertical_profile"
                else:
                    _, summary, model_array = get_profile_from_path(
                        velocity_model,
                        float(event["event_lon"]), float(event["event_lat"]),
                        station_lon, station_lat,
                        crs="EPSG:4326",
                        spacing_km=float(path_spacing_km),
                        profile=path_profile,
                        vp_name=vp_col,
                        vs_name=vs_col,
                        density_name=density_col,
                        qs_name=qs_col,
                        qp_name=qp_col,
                        surface_depth_km=surface_depth_km,
                        max_depth_km=max_depth_km,
                        compress=compress,
                    )
                    model_description = f"grid_path:{path_profile}"
                    path_length_km = float(
                        summary.attrs.get(
                            "path_length_km", context["distance_km"]
                        )
                    )
                    batch_mode = "station_specific_path"

            model_array = np.asarray(model_array, dtype=float)
            model_metadata = _pyfk_model_metadata(model_array)
            seis_model = SeisModel(model=model_array, flattening=pyfk_flattening)

            for requested_depth in depths:
                actual_depth = _source_depth_off_interface(
                    model_array, requested_depth
                )
                signature = _gf_processing_signature(
                    station_id=context["station_id"],
                    distance_km=context["distance_km"],
                    gf_start_offset_s=context["gf_start_offset_s"],
                    requested_depth=requested_depth,
                    actual_depth=actual_depth,
                    model_array=model_array,
                    settings=context["station_settings"],
                    pyfk_dt=pyfk_dt,
                    pyfk_npt=pyfk_npt,
                    samples_before_first_arrival=samples_before_first_arrival,
                    config_kwargs=config_kwargs,
                    pyfk_flattening=pyfk_flattening,
                    pyfk_version=pyfk_version,
                    gf_helpers_version=gf_helpers_version,
                    batch_mode=batch_mode,
                    receiver_distance_batch=None,
                )
                output_paths = _gf_paths(
                    context["station_id"], requested_depth
                )
                existing_count = sum(
                    path.exists() for path in output_paths.values()
                )
                cache_reason = "overwrite=True"

                if not overwrite:
                    cached_records, cache_reason = _load_cached_gf_records(
                        output_paths=output_paths,
                        signature=signature,
                        station_id=context["station_id"],
                        requested_depth=requested_depth,
                        expected_npts=context["npts"],
                        expected_dt=settings["dt"],
                        read=read,
                    )
                    if cached_records is not None:
                        _append_cached_rows(
                            context,
                            requested_depth=requested_depth,
                            actual_depth=actual_depth,
                            signature=signature,
                            cached_records=cached_records,
                            model_description=model_description,
                            path_length_km=path_length_km,
                            model_array=model_array,
                            model_metadata=model_metadata,
                            cache_reason=cache_reason,
                            batch_mode=batch_mode,
                            batch_size=1,
                        )
                        progress_bar.update(1)
                        continue

                dc_source = SourceModel(sdep=actual_depth, srcType="dc")
                ep_source = SourceModel(sdep=actual_depth, srcType="ep")
                base_config = {
                    "model": seis_model,
                    "receiver_distance": np.array(
                        [context["distance_km"]], dtype=float
                    ),
                    "npt": int(pyfk_npt),
                    "dt": float(pyfk_dt),
                    "samples_before_first_arrival": int(
                        samples_before_first_arrival
                    ),
                    **config_kwargs,
                }
                dc_stream = calculate_gf(
                    Config(source=dc_source, **base_config)
                )[0]
                ep_stream = calculate_gf(
                    Config(source=ep_source, **base_config)
                )[0]
                _write_generated_rows(
                    context,
                    requested_depth=requested_depth,
                    actual_depth=actual_depth,
                    signature=signature,
                    dc_stream=dc_stream,
                    ep_stream=ep_stream,
                    output_paths=output_paths,
                    existing_count=existing_count,
                    cache_reason=cache_reason,
                    model_description=model_description,
                    path_length_km=path_length_km,
                    model_array=model_array,
                    model_metadata=model_metadata,
                    batch_mode=batch_mode,
                    batch_size=1,
                )
                progress_bar.update(1)

    progress_bar.close()

    gf_manifest = pd.DataFrame(gf_rows)
    model_manifest = pd.DataFrame(model_rows)
    gf_manifest.to_csv(metadata_dir / "gf_manifest.csv", index=False)
    model_manifest.to_csv(metadata_dir / "path_model_manifest.csv", index=False)

    if plot and not gf_manifest.empty:
        for depth in depths:
            _plot_gf_record_sections(
                gf_manifest.loc[
                    np.isclose(gf_manifest["requested_depth_km"], depth)
                ],
                station_df, depth,
                figure_dir / f"greens_{depth:.4f}km.png", read,
            )
    return gf_manifest, model_manifest


def generate_syngine_gfs(
    event_df: pd.DataFrame | pd.Series | Mapping[str, Any],
    station_df: pd.DataFrame,
    *,
    depths_km: Sequence[float],
    output_dir: str | Path,
    syngine_model: str = "iasp91_2s",
    syngine_url: str = "https://service.earthscope.org/irisws/syngine/1/query",
    syngine_dt: float | None = None,
    kernelwidth: int = 12,
    motion: str | None = None,
    freqmin: float | None = None,
    freqmax: float | None = None,
    corners: int | None = None,
    dt: float | None = None,
    timeout: float = 120.0,
    request_padding_s: float = 10.0,
    max_workers: int = 4,
    plot: bool = False,
    progress: bool = True,
    overwrite: bool = False,
) -> pd.DataFrame:
    """Generate MTtime tensor Green's functions from EarthScope Syngine.

    This is the remote-provider analogue of :func:`generate_pyfk_gfs`. It uses
    the same processed-station timing and final-processing contract, but no local
    velocity-model construction or pyFK configuration is required. Each
    station/depth pair is requested from Syngine's Green's-function endpoint,
    which returns the ten Instaseis/SeisComP bases ``TSS, ZSS, RSS, TDS, ZDS,
    RDS, ZDD, RDD, ZEP, REP``. These are converted analytically to MTtime's
    18-file Cartesian tensor format in north-east-down coordinates before local
    filtering and final resampling.

    Parameters
    ----------
    event_df, station_df
        Event metadata and the authoritative processed station table returned by
        :func:`process_mseed_sac`. WGS84 station/event latitudes are converted to
        geocentric latitudes before calculating the spherical angular distance
        required by Syngine. The existing station-table azimuth is retained for
        the validated SeisComP path-frame to Cartesian tensor transformation.
    depths_km
        Positive trial source depths in kilometres. Syngine receives depths in
        integer metres; the requested kilometre values remain the MTtime filename
        and inversion depths, while the rounded service depth is recorded in the
        manifest.
    output_dir
        Event root directory. Tensor Green's functions are written under
        ``greens`` and ``metadata/gf_manifest.csv`` records the complete provider,
        request, processing and cache metadata. No velocity-model manifest is
        produced.
    syngine_model
        EarthScope Syngine model name, for example ``"iasp91_2s"``,
        ``"prem_i_2s"``, ``"prem_a_2s"`` or ``"prem_e_2s"``.
    syngine_url
        Syngine query endpoint. The default is the current EarthScope service.
    syngine_dt
        Optional sampling interval passed to Syngine. ``None`` omits ``dt`` and
        leaves the service at the model's default output sampling. This setting
        is independent of the final MTtime ``dt`` below; all accepted service
        output is filtered and resampled locally onto the processed-station grid.
    kernelwidth
        Syngine/Instaseis sinc-kernel width used only when ``syngine_dt`` is
        explicitly supplied.
    motion, freqmin, freqmax, corners, dt
        Final Green's-function processing settings. Missing values are inferred
        from ``station_df`` exactly as in :func:`generate_pyfk_gfs`. Syngine is
        asked directly for the corresponding physical motion, and local output
        is converted from SI metres to the centimetre-based unit family used by
        the processed observations. In the standard workflow the processed
        station ``dt`` is 1 s.
    timeout
        Positive HTTP request timeout in seconds for each station/depth query.
    request_padding_s
        Additional non-negative late-time service coverage beyond the final
        station sample plus the existing one-period zero-phase filter guard. The
        default 10 s also provides room for any server-side interpolation boundary
        trimming when ``syngine_dt`` is requested. The downloaded SACZIP remains
        in memory and is not retained on disk.
    max_workers
        Maximum number of simultaneous Syngine HTTP requests at one trial depth.
        The default is 4; set to 1 for sequential acquisition or increase it when
        the service and local network sustain higher concurrency. Local tensor
        conversion, filtering, SAC writing and manifest mutation remain serialized
        in the caller thread.
    plot
        Save one 18-panel tensor-basis record section for each trial depth.
    progress
        Display one tqdm progress bar over station/depth Green's-function sets.
    overwrite
        If ``True``, force every Syngine request. If ``False``, a complete
        18-file tensor set is reused only when every file has the current
        deterministic signature, station-specific ``npts``/``dt``, source-relative
        zero start and finite data. Partial or incompatible sets are requested and
        rewritten.

    Returns
    -------
    gf_manifest : pandas.DataFrame
        One row per station, requested depth and MTtime tensor basis file. The
        manifest includes ``green='tensor'`` so :func:`write_mtinv` selects
        MTtime's native tensor Green's-function reader automatically.

    Notes
    -----
    Instaseis defines the Syngine Green's-function sources with unit moment-
    tensor components in N m. MTtime interprets its Green's functions as the
    response to ``1e20 dyne-cm = 1e13 N m`` and the processed observations use
    centimetre-based motion units. The fixed conversion from raw Syngine SI
    output to MTtime input is therefore ``1e13 * 100 = 1e15`` after the
    SeisComP-to-NED tensor expansion.

    The validated SeisComP path frame is referenced to the southward positive
    theta direction. For a station-table forward azimuth ``A`` measured clockwise
    from north, the tensor expansion therefore uses ``alpha=(180-A) mod 360``.

    The remote request begins at source-origin time zero and ends only after the
    station-specific final sample plus the same one-period ``1/freqmin`` guard
    used by the pyFK path. A causal zero prefix is added locally before the
    zero-phase filter; late-time data are never invented.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from queue import Queue

    import requests
    import zipfile
    from obspy import Stream, UTCDateTime, read
    from tqdm.auto import tqdm

    if station_df.empty:
        raise ValueError("station_df is empty.")
    _validate_station_depth_policy(station_df)
    event = _event_record(event_df)

    depths = sorted({float(value) for value in depths_km})
    if not depths or any(
        not np.isfinite(value) or value <= 0 for value in depths
    ):
        raise ValueError("depths_km must contain finite positive source depths.")

    syngine_model = str(syngine_model).strip()
    syngine_url = str(syngine_url).strip()
    if not syngine_model:
        raise ValueError("syngine_model cannot be empty.")
    if not syngine_url:
        raise ValueError("syngine_url cannot be empty.")

    if syngine_dt is not None:
        syngine_dt = float(syngine_dt)
        if not np.isfinite(syngine_dt) or syngine_dt <= 0:
            raise ValueError("syngine_dt must be None or a positive finite value.")

    kernelwidth_float = float(kernelwidth)
    if (
        not np.isfinite(kernelwidth_float)
        or kernelwidth_float < 1
        or not np.isclose(kernelwidth_float, round(kernelwidth_float))
    ):
        raise ValueError("kernelwidth must be a positive integer.")
    kernelwidth = int(round(kernelwidth_float))

    max_workers_float = float(max_workers)
    if (
        not np.isfinite(max_workers_float)
        or max_workers_float < 1
        or not np.isclose(max_workers_float, round(max_workers_float))
    ):
        raise ValueError("max_workers must be a positive integer.")
    max_workers = int(round(max_workers_float))

    timeout = float(timeout)
    request_padding_s = float(request_padding_s)
    if not np.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive.")
    if not np.isfinite(request_padding_s) or request_padding_s < 0:
        raise ValueError("request_padding_s must be finite and non-negative.")

    settings = _gf_processing_settings(
        station_df,
        motion=motion,
        freqmin=freqmin,
        freqmax=freqmax,
        corners=corners,
        dt=dt,
    )
    syngine_units = {
        "DISP": "displacement",
        "VEL": "velocity",
        "ACC": "acceleration",
    }[settings["motion"]]
    filter_guard_s = _gf_filter_guard_seconds(settings)

    required_columns = {
        "station_lat", "station_lon", "npts", "origin_ts", "ts",
        "stored_npts", "correlation_max_shift_samples",
    }
    missing = required_columns.difference(station_df.columns)
    if missing:
        raise KeyError(
            "station_df is missing processed/Syngine fields: "
            f"{sorted(missing)}. Run process_mseed_sac before generate_syngine_gfs."
        )

    root = Path(output_dir).expanduser()
    green_dir = root / "greens"
    metadata_dir = root / "metadata"
    figure_dir = root / "figures"
    for directory in (green_dir, metadata_dir, figure_dir):
        directory.mkdir(parents=True, exist_ok=True)

    origin = UTCDateTime(event["origin_time"])
    event_lat = float(event["event_lat"])
    event_lon = float(event["event_lon"])

    station_contexts: list[dict[str, Any]] = []
    for station_index, station in enumerate(station_df.itertuples(index=False)):
        row = station._asdict()
        station_id = str(
            row["station_id"]
            if "station_id" in row
            else _station_id_from_row(row)
        )

        distance_value = row.get("distance", row.get("distance_km"))
        if distance_value is None:
            raise KeyError(f"Station {station_id} has no distance column.")
        distance_km = float(distance_value)
        station_lat = float(row["station_lat"])
        station_lon = float(row["station_lon"])
        azimuth_deg = float(row.get("azimuth", row.get("azimuth_deg", np.nan)))
        if not np.isfinite([distance_km, station_lat, station_lon, azimuth_deg]).all():
            raise ValueError(
                f"Station {station_id} has non-finite geometry required by Syngine."
            )
        if distance_km < 0:
            raise ValueError(f"Station {station_id} has negative distance.")
        if not -90.0 <= station_lat <= 90.0 or not -180.0 <= station_lon <= 180.0:
            raise ValueError(f"Station {station_id} has invalid latitude/longitude.")
        azimuth_deg %= 360.0

        station_npts = int(row["npts"])
        station_ts = int(row["ts"])
        origin_ts = int(row["origin_ts"])
        stored_npts = int(row["stored_npts"])
        max_shift_samples = int(row["correlation_max_shift_samples"])
        if station_npts < 1:
            raise ValueError(f"Station {station_id} has npts < 1.")
        if station_ts != origin_ts:
            raise ValueError(
                f"Station {station_id} has ts={station_ts} but origin_ts={origin_ts}; "
                "origin alignment is required as the unshifted GF baseline."
            )
        if station_ts < max_shift_samples:
            raise ValueError(
                f"Station {station_id} has insufficient pre-origin samples for "
                f"the requested correlation margin ({max_shift_samples})."
            )
        post_samples = stored_npts - (station_ts + station_npts)
        if post_samples < max_shift_samples:
            raise ValueError(
                f"Station {station_id} has only {post_samples} post-inversion "
                f"samples but requires {max_shift_samples}."
            )

        distance_deg = _syngine_geocentric_distance_degrees(
            event_lat, event_lon, station_lat, station_lon
        )
        if not np.isfinite(distance_deg) or not 0.0 <= distance_deg <= 180.0:
            raise ValueError(
                f"Station {station_id} has invalid Syngine distance {distance_deg}."
            )

        station_settings = {**settings, "npts": station_npts}
        target_end_s = float((station_npts - 1) * settings["dt"])
        request_end_s = float(target_end_s + filter_guard_s + request_padding_s)

        station_contexts.append({
            "station_index": station_index,
            "row": row,
            "station_id": station_id,
            "distance_km": distance_km,
            "distance_deg": distance_deg,
            "station_lat": station_lat,
            "station_lon": station_lon,
            "azimuth_deg": azimuth_deg,
            "station_npts": station_npts,
            "origin_ts": origin_ts,
            "max_shift_samples": max_shift_samples,
            "station_settings": station_settings,
            "request_end_s": request_end_s,
        })

    gf_rows: list[dict[str, Any]] = []
    progress_bar = tqdm(
        total=len(station_contexts) * len(depths),
        desc="Syngine Green's functions",
        unit="set",
        disable=not progress,
    )

    session_count = min(max_workers, len(station_contexts))
    session_pool = Queue()
    sessions = [requests.Session() for _ in range(session_count)]
    for session in sessions:
        session_pool.put(session)

    def _fetch_syngine_job(job):
        session = session_pool.get()
        try:
            raw_stream, request_info = _request_syngine_gf_stream(
                session=session,
                syngine_url=syngine_url,
                syngine_model=syngine_model,
                source_depth_m=job["source_depth_m"],
                distance_deg=job["distance_deg"],
                syngine_units=syngine_units,
                syngine_dt=syngine_dt,
                kernelwidth=kernelwidth,
                origin=origin,
                request_end_s=job["request_end_s"],
                timeout=timeout,
                read=read,
                Stream=Stream,
                zipfile=zipfile,
            )
            return raw_stream, request_info
        finally:
            session_pool.put(session)

    try:
        for requested_depth in depths:
            source_depth_m = int(round(requested_depth * 1000.0))
            service_depth_km = source_depth_m / 1000.0
            request_jobs: list[dict[str, Any]] = []

            for context in station_contexts:
                station_id = context["station_id"]
                distance_km = context["distance_km"]
                distance_deg = context["distance_deg"]
                azimuth_deg = context["azimuth_deg"]
                station_npts = context["station_npts"]
                origin_ts = context["origin_ts"]
                max_shift_samples = context["max_shift_samples"]
                station_settings = context["station_settings"]
                request_end_s = context["request_end_s"]

                signature = _syngine_gf_processing_signature(
                    station_id=station_id,
                    distance_km=distance_km,
                    distance_deg=distance_deg,
                    azimuth_deg=azimuth_deg,
                    requested_depth=requested_depth,
                    source_depth_m=source_depth_m,
                    syngine_model=syngine_model,
                    syngine_url=syngine_url,
                    syngine_units=syngine_units,
                    syngine_dt=syngine_dt,
                    kernelwidth=kernelwidth,
                    request_end_s=request_end_s,
                    request_padding_s=request_padding_s,
                    settings=station_settings,
                )
                output_paths = {
                    basis: green_dir / f"{station_id}.{requested_depth:.4f}.{basis}"
                    for basis in _TENSOR_BASES
                }
                existing_count = sum(path.exists() for path in output_paths.values())

                cached_records = None
                cache_reason = "overwrite=True"
                if not overwrite:
                    cached_records, cache_reason = _load_cached_gf_records(
                        output_paths=output_paths,
                        signature=signature,
                        station_id=station_id,
                        requested_depth=requested_depth,
                        expected_npts=station_npts,
                        expected_dt=settings["dt"],
                        read=read,
                        bases=_TENSOR_BASES,
                        expected_start_offset_s=0.0,
                    )

                if cached_records is not None:
                    first_trace = read(
                        str(output_paths[_TENSOR_BASES[0]]), format="SAC"
                    )[0]
                    raw_dt = float(_sac_header_value(
                        getattr(first_trace.stats, "sac", None), "user7", np.nan
                    ))
                    for record in cached_records:
                        gf_rows.append({
                            **record,
                            "station_id": station_id,
                            "requested_depth_km": requested_depth,
                            "syngine_source_depth_m": source_depth_m,
                            "syngine_source_depth_km": service_depth_km,
                            "distance_km": distance_km,
                            "syngine_distance_deg": distance_deg,
                            "azimuth_deg": azimuth_deg,
                            "green": "tensor",
                            "provider": "syngine",
                            "syngine_model": syngine_model,
                            "syngine_url": syngine_url,
                            "motion": settings["motion"],
                            "units": settings["units"],
                            "syngine_units": syngine_units,
                            "syngine_dt_requested_s": syngine_dt,
                            "syngine_dt_returned_s": raw_dt,
                            "kernelwidth": kernelwidth,
                            "freqmin": settings["freqmin"],
                            "freqmax": settings["freqmax"],
                            "corners": settings["corners"],
                            "filter_guard_s": filter_guard_s,
                            "request_end_s": request_end_s,
                            "request_padding_s": request_padding_s,
                            "reference_moment_Nm": _SYNGINE_MTTIME_REFERENCE_MOMENT_NM,
                            "amplitude_scale": _SYNGINE_MTTIME_AMPLITUDE_SCALE,
                            "origin_ts": origin_ts,
                            "correlation_max_shift_samples": max_shift_samples,
                            "processing_signature": signature,
                            "cache_status": "existing",
                            "cache_reason": cache_reason,
                        })
                    progress_bar.update(1)
                    continue

                request_jobs.append({
                    **context,
                    "requested_depth": requested_depth,
                    "source_depth_m": source_depth_m,
                    "service_depth_km": service_depth_km,
                    "signature": signature,
                    "output_paths": output_paths,
                    "existing_count": existing_count,
                    "cache_reason": cache_reason,
                })

            if not request_jobs:
                continue

            worker_count = min(max_workers, len(request_jobs))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(_fetch_syngine_job, job): job
                    for job in request_jobs
                }

                for future in as_completed(futures):
                    job = futures[future]
                    raw_stream, request_info = future.result()

                    tensor_stream = _syngine_seiscomp_to_tensor_stream(
                        raw_stream,
                        azimuth_deg=job["azimuth_deg"],
                        Stream=Stream,
                    )
                    for trace in tensor_stream:
                        trace.data = np.asarray(trace.data, dtype=np.float64) * (
                            _SYNGINE_MTTIME_AMPLITUDE_SCALE
                        )

                    processed = _process_syngine_stream(
                        tensor_stream,
                        job["station_settings"],
                        origin=origin,
                        UTCDateTime=UTCDateTime,
                        Stream=Stream,
                    )
                    _tag_stream_signature(processed, "MTHGF", job["signature"])
                    _write_mttime_tensor_sac(
                        processed,
                        station_id=job["station_id"],
                        requested_depth=requested_depth,
                        output_paths=job["output_paths"],
                        event=event,
                        station_row=job["row"],
                        distance_km=job["distance_km"],
                        azimuth_deg=job["azimuth_deg"],
                        raw_dt=float(request_info["returned_dt_s"]),
                    )
                    _validate_written_gf_set(
                        output_paths=job["output_paths"],
                        signature=job["signature"],
                        expected_npts=job["station_npts"],
                        expected_dt=settings["dt"],
                        read=read,
                        bases=_TENSOR_BASES,
                        expected_start_offset_s=0.0,
                    )

                    if overwrite and job["existing_count"]:
                        cache_status = "overwritten"
                    elif job["existing_count"]:
                        cache_status = "rewritten"
                    else:
                        cache_status = "written"

                    for basis in _TENSOR_BASES:
                        path = job["output_paths"][basis]
                        trace = read(str(path), format="SAC")[0]
                        gf_rows.append({
                            "station": job["station_id"],
                            "station_id": job["station_id"],
                            "source_depth_km": requested_depth,
                            "requested_depth_km": requested_depth,
                            "syngine_source_depth_m": source_depth_m,
                            "syngine_source_depth_km": service_depth_km,
                            "basis": basis,
                            "path": str(path),
                            "npts": int(trace.stats.npts),
                            "dt_s": float(trace.stats.delta),
                            "distance_km": job["distance_km"],
                            "syngine_distance_deg": job["distance_deg"],
                            "azimuth_deg": job["azimuth_deg"],
                            "green": "tensor",
                            "provider": "syngine",
                            "syngine_model": syngine_model,
                            "syngine_url": syngine_url,
                            "motion": settings["motion"],
                            "units": settings["units"],
                            "syngine_units": syngine_units,
                            "syngine_dt_requested_s": syngine_dt,
                            "syngine_dt_returned_s": float(request_info["returned_dt_s"]),
                            "syngine_raw_npts": int(request_info["returned_npts"]),
                            "syngine_raw_start_offset_s": float(request_info["start_offset_s"]),
                            "syngine_raw_end_offset_s": float(request_info["end_offset_s"]),
                            "kernelwidth": kernelwidth,
                            "freqmin": settings["freqmin"],
                            "freqmax": settings["freqmax"],
                            "corners": settings["corners"],
                            "filter_guard_s": filter_guard_s,
                            "request_end_s": job["request_end_s"],
                            "request_padding_s": request_padding_s,
                            "reference_moment_Nm": _SYNGINE_MTTIME_REFERENCE_MOMENT_NM,
                            "amplitude_scale": _SYNGINE_MTTIME_AMPLITUDE_SCALE,
                            "origin_ts": job["origin_ts"],
                            "correlation_max_shift_samples": job["max_shift_samples"],
                            "processing_signature": job["signature"],
                            "cache_status": cache_status,
                            "cache_reason": job["cache_reason"],
                        })
                    progress_bar.update(1)
    finally:
        for session in sessions:
            session.close()
        progress_bar.close()

    gf_manifest = pd.DataFrame(gf_rows)
    if not gf_manifest.empty:
        station_order = {
            context["station_id"]: context["station_index"]
            for context in station_contexts
        }
        basis_order = {basis: index for index, basis in enumerate(_TENSOR_BASES)}
        gf_manifest["_station_order"] = gf_manifest["station_id"].map(station_order)
        gf_manifest["_basis_order"] = gf_manifest["basis"].map(basis_order)
        gf_manifest = (
            gf_manifest.sort_values(
                ["_station_order", "requested_depth_km", "_basis_order"],
                kind="mergesort",
            )
            .drop(columns=["_station_order", "_basis_order"])
            .reset_index(drop=True)
        )
    gf_manifest.to_csv(metadata_dir / "gf_manifest.csv", index=False)

    if plot and not gf_manifest.empty:
        for depth in depths:
            _plot_tensor_gf_record_sections(
                gf_manifest.loc[
                    np.isclose(gf_manifest["requested_depth_km"], depth)
                ],
                station_df,
                depth,
                figure_dir / f"greens_syngine_{depth:.4f}km.png",
                read,
            )

    return gf_manifest

def write_mtinv(
    event_df: pd.DataFrame | pd.Series | Mapping[str, Any],
    station_df: pd.DataFrame,
    gf_manifest: pd.DataFrame,
    *,
    output_file: str | Path,
    path_to_data: str | Path,
    path_to_green: str | Path,
    depths_km: Sequence[float] | None = None,
    components: str = "ZRT",
    degree: int = 5,
    weight: str = "none",
    plot: bool = False,
    correlate: bool = False,
    reference_time_shift: float = 0.0,
    drop_stations: Sequence[str | tuple[str, str, str]] | None = None,
) -> pd.DataFrame:
    """Validate inputs and write an MTtime configuration at one global reference.

    Parameters
    ----------
    event_df, station_df, gf_manifest
        Outputs from the preceding helper stages. ``gf_manifest`` may come from
        :func:`generate_pyfk_gfs` (Herrmann format) or
        :func:`generate_syngine_gfs` (tensor format). ``station_df`` must be the
        authoritative table returned by :func:`process_mseed_sac`; its ``ts``
        must still equal the immutable catalog-origin index ``origin_ts``.
    output_file
        Destination ``mtinv.in`` path. MTtime interprets data and Green's-
        function paths relative to this file's parent directory.
    path_to_data, path_to_green
        Data and Green's-function directories. Absolute or relative paths are
        accepted for validation; normalized relative paths are written because
        MTtime joins them to the configuration directory.
    depths_km
        Trial source depths. When omitted, unique requested depths are read from
        ``gf_manifest``.
    components
        ``"ZRT"`` (all three components), ``"ZR"`` (Z/R inversion with T
        retained as prediction-only through the MTtime ``used`` mask), or ``"Z"``.
    degree
        Moment-tensor degrees of freedom: 5 for deviatoric or 6 for full.
    weight
        MTtime weighting mode: ``"none"``, ``"distance"`` or ``"variance"``.
    plot
        MTtime configuration flag for its native automatic plotting. The normal
        :func:`run_mttime_inversion` interface forwards this value, although
        helper-managed saved products are selected independently through
        ``plot_views`` and normally make ``plot=False`` preferable.
    correlate
        Enable bounded residual station-wise timing correction around the global
        reference selected by ``reference_time_shift``. Each station may move
        only within the symmetric margin prepared by ``max_correlation_shift``
        in :func:`process_mseed_sac`.
    reference_time_shift
        Global shift in seconds relative to the catalog origin. Positive values
        select a later source reference; negative values select an earlier one.
        The value must be finite, an integer multiple of each station's ``dt``
        and no larger in absolute value than the processed
        ``max_reference_time_shift``. For example, ``+5`` aligns Green's-function
        sample zero with the observed sample five seconds after catalog origin.
    drop_stations
        Stations excluded only from this configuration. Entries may be complete
        ``station_id`` strings or ``(network, station, location)`` tuples.

    Returns
    -------
    pandas.DataFrame
        The MTtime station table. In addition to the standard columns written to
        ``mtinv.in``, the returned table includes ``origin_ts``, ``reference_ts``,
        ``reference_time_shift`` and ``reference_time_shift_samples`` for audit.

    Notes
    -----
    The physical invariants are

    ``observed_start + origin_ts * dt == catalog_origin``

    and

    ``observed_start + reference_ts * dt == reference_time == GF time zero``.

    The MTtime ``datetime`` header remains ``catalog_origin`` for every global
    shift. A global shift changes only the observed sample aligned with the
    existing causal Green's functions; observations and Green's functions are
    not regenerated. If correlation is enabled, its station-specific shift is a
    residual correction around ``reference_ts``, not around ``origin_ts``.
    """
    from obspy import UTCDateTime, read

    event = _event_record(event_df)
    components = str(components).strip().upper()
    mt_components, component_mask = _resolve_mtinv_components(components)
    weight = str(weight).lower()
    reference_time_shift = float(reference_time_shift)

    if degree not in {5, 6}:
        raise ValueError("degree must be 5 or 6.")
    if weight not in {"none", "distance", "variance"}:
        raise ValueError("weight must be 'none', 'distance' or 'variance'.")
    if not np.isfinite(reference_time_shift):
        raise ValueError("reference_time_shift must be finite.")
    if station_df.empty:
        raise ValueError("station_df is empty.")
    if gf_manifest.empty:
        raise ValueError("gf_manifest is empty.")
    _validate_station_depth_policy(station_df)

    table = station_df.copy()
    if "station_id" not in table:
        table["station_id"] = table.apply(
            lambda row: _station_id_from_row(row), axis=1
        )
    table["station_id"] = table["station_id"].astype(str)

    dropped = {
        _normalize_station_selector(value) for value in (drop_stations or [])
    }
    table = table.loc[~table["station_id"].isin(dropped)].copy()
    if table.empty:
        raise ValueError("No stations remain after applying drop_stations.")

    required_timing = {"ts", "origin_ts", "npts", "stored_npts", "dt"}
    missing_timing = required_timing.difference(table.columns)
    if missing_timing:
        raise KeyError(
            "Station table is missing MTtime timing columns: "
            f"{sorted(missing_timing)}. Re-run process_mseed_sac."
        )

    numeric = table.loc[:, sorted(required_timing)].apply(
        pd.to_numeric, errors="raise"
    )
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("Station timing columns must contain only finite values.")

    for column in ("ts", "origin_ts", "npts", "stored_npts"):
        values = numeric[column].to_numpy(dtype=float)
        rounded = np.rint(values)
        if not np.allclose(values, rounded, atol=1e-8, rtol=0.0):
            raise ValueError(f"{column} must be an integer for every station.")
        numeric[column] = rounded.astype(int)

    if (numeric["origin_ts"] < 0).any():
        raise ValueError("Require origin_ts >= 0 for every station.")
    if (numeric["npts"] < 1).any() or (numeric["dt"] <= 0).any():
        raise ValueError("Require npts >= 1 and dt > 0 for every station.")
    if (numeric["stored_npts"] < 1).any():
        raise ValueError("Require stored_npts >= 1 for every station.")

    processed_mismatch = (
        numeric["ts"].astype(int) != numeric["origin_ts"].astype(int)
    )
    if processed_mismatch.any():
        bad = table.loc[processed_mismatch, "station_id"].tolist()
        raise ValueError(
            "station_df must remain catalog-origin aligned before writing a "
            f"configuration; ts differs from origin_ts for: {bad}."
        )

    shift_float = reference_time_shift / numeric["dt"].astype(float)
    shift_samples = np.rint(shift_float).astype(int)
    exact_shift = np.isclose(
        shift_float.to_numpy(dtype=float),
        shift_samples.to_numpy(dtype=float),
        atol=1e-8,
        rtol=0.0,
    )
    if not exact_shift.all():
        bad = table.loc[~exact_shift, "station_id"].tolist()
        raise ValueError(
            "reference_time_shift must be an integer multiple of dt for every "
            f"station. Invalid stations: {bad}."
        )

    if "max_reference_time_shift" in table:
        maximum = pd.to_numeric(
            table["max_reference_time_shift"], errors="raise"
        ).astype(float)
    elif np.isclose(reference_time_shift, 0.0, atol=1e-12, rtol=0.0):
        maximum = pd.Series(0.0, index=table.index)
    else:
        raise KeyError(
            "A nonzero reference_time_shift requires max_reference_time_shift "
            "from process_mseed_sac."
        )
    if not np.isfinite(maximum.to_numpy(dtype=float)).all() or (maximum < 0).any():
        raise ValueError(
            "max_reference_time_shift must be finite and non-negative for every "
            "station."
        )
    exceeds = abs(reference_time_shift) > maximum + 1e-8
    if exceeds.any():
        bad = table.loc[exceeds, "station_id"].tolist()
        raise ValueError(
            f"abs(reference_time_shift)={abs(reference_time_shift):.6f} seconds "
            "exceeds the processed max_reference_time_shift for: "
            f"{bad}. Re-run process_mseed_sac with a larger reserved margin."
        )

    origin_ts = numeric["origin_ts"].astype(int)
    reference_ts = origin_ts + shift_samples
    npts = numeric["npts"].astype(int)
    stored_npts = numeric["stored_npts"].astype(int)

    outside = (reference_ts < 0) | (reference_ts + npts > stored_npts)
    if outside.any():
        bad = table.loc[outside, "station_id"].tolist()
        raise ValueError(
            "The selected global reference does not leave a complete inversion "
            f"segment in the stored observations for: {bad}."
        )

    if correlate:
        if "correlation_max_shift_samples" not in table:
            raise KeyError(
                "correlate=True requires correlation_max_shift_samples from "
                "process_mseed_sac."
            )
        margin_float = pd.to_numeric(
            table["correlation_max_shift_samples"], errors="raise"
        ).to_numpy(dtype=float)
        margin = np.rint(margin_float).astype(int)
        if (
            not np.isfinite(margin_float).all()
            or not np.allclose(margin_float, margin, atol=1e-8, rtol=0.0)
        ):
            raise ValueError(
                "correlation_max_shift_samples must be a finite integer for "
                "every station."
            )
        margin = pd.Series(margin, index=table.index)
        if (margin <= 0).any():
            bad = table.loc[margin <= 0, "station_id"].tolist()
            raise ValueError(
                "correlate=True requires a positive correlation margin for every "
                f"station. Invalid stations: {bad}."
            )
        before = reference_ts
        after = stored_npts - (reference_ts + npts)
        insufficient = (before < margin) | (after < margin)
        if insufficient.any():
            bad = table.loc[insufficient, "station_id"].tolist()
            raise ValueError(
                "Observed records lack the symmetric correlation margin around "
                f"the selected global reference for: {bad}."
            )

    # Replace timing columns rather than assigning through ``.loc``. This makes
    # the intended integer/float dtypes explicit and avoids pandas' incompatible-
    # dtype assignment warning when an existing MTtime table uses int32 columns.
    table["origin_ts"] = origin_ts.to_numpy(dtype=np.int64)
    table["reference_ts"] = reference_ts.to_numpy(dtype=np.int64)
    table["reference_time_shift"] = np.full(
        len(table), reference_time_shift, dtype=float
    )
    table["reference_time_shift_samples"] = shift_samples.to_numpy(
        dtype=np.int64
    )
    table["ts"] = reference_ts.to_numpy(dtype=np.int64)
    table["npts"] = npts.to_numpy(dtype=np.int64)
    table["stored_npts"] = stored_npts.to_numpy(dtype=np.int64)
    table["dt"] = numeric["dt"].to_numpy(dtype=float)

    if depths_km is None:
        depth_column = (
            "requested_depth_km"
            if "requested_depth_km" in gf_manifest
            else "source_depth_km"
        )
        depths = sorted(gf_manifest[depth_column].astype(float).unique())
    else:
        depths = sorted({float(value) for value in depths_km})
    if not depths or any(
        not np.isfinite(value) or value <= 0 for value in depths
    ):
        raise ValueError("Trial depths must contain finite positive values.")

    output_path = Path(output_file).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    config_root = output_path.parent
    data_root = _resolve_from_config(
        config_root, path_to_data
    ).expanduser().resolve()
    green_root = _resolve_from_config(
        config_root, path_to_green
    ).expanduser().resolve()

    catalog_origin = UTCDateTime(event["origin_time"])
    reference_time = catalog_origin + reference_time_shift
    green_format = _green_format_from_manifest(gf_manifest)
    _validate_mtinv_files(
        table,
        gf_manifest,
        depths,
        mt_components,
        data_root,
        green_root,
        catalog_origin=catalog_origin,
        reference_time=reference_time,
        correlate=bool(correlate),
        green=green_format,
        read=read,
    )

    required_columns = {
        "distance": ("distance", "distance_km"),
        "azimuth": ("azimuth", "azimuth_deg"),
        "ts": ("ts",),
        "npts": ("npts",),
        "dt": ("dt",),
        "used": ("used",),
        "longitude": ("longitude", "station_lon"),
        "latitude": ("latitude", "station_lat"),
    }
    standard = pd.DataFrame({"station": table["station_id"].astype(str)})
    for target, aliases in required_columns.items():
        standard[target] = _column_from_aliases(table, aliases)

    numeric_columns = [
        "distance", "azimuth", "ts", "npts", "dt", "longitude", "latitude"
    ]
    standard.loc[:, numeric_columns] = standard.loc[:, numeric_columns].apply(
        pd.to_numeric, errors="raise"
    )
    if not np.isfinite(
        standard.loc[:, numeric_columns].to_numpy(dtype=float)
    ).all():
        raise ValueError("MTtime station columns must contain only finite values.")
    if (standard["distance"] < 0).any():
        raise ValueError("Station distance cannot be negative.")
    if ((standard["azimuth"] < 0) | (standard["azimuth"] >= 360)).any():
        raise ValueError("Station azimuth must lie within [0, 360) degrees.")
    if ((standard["latitude"] < -90) | (standard["latitude"] > 90)).any():
        raise ValueError("Station latitude must lie within [-90, 90] degrees.")
    if ((standard["longitude"] < -180) | (standard["longitude"] > 180)).any():
        raise ValueError("Station longitude must lie within [-180, 180] degrees.")

    standard["ts"] = standard["ts"].astype(int)
    standard["npts"] = standard["npts"].astype(int)
    standard["used"] = standard["used"].map(_normalize_used_flag)
    if component_mask is not None:
        standard["used"] = standard["used"].map(
            lambda value: _intersect_used_mask(value, component_mask)
        )

    audit = pd.DataFrame({
        "station": table["station_id"].astype(str),
        "origin_ts": table["origin_ts"].astype(int),
        "reference_ts": table["reference_ts"].astype(int),
        "reference_time_shift_samples": table[
            "reference_time_shift_samples"
        ].astype(int),
        "reference_time_shift": table["reference_time_shift"].astype(float),
        "max_reference_time_shift": maximum.astype(float),
    })
    output = standard.merge(audit, on="station", how="left", validate="one_to_one")
    output.sort_values("distance", inplace=True, ignore_index=True)
    standard = output.loc[:, ["station", *required_columns]].copy()

    try:
        data_relative = Path(
            os.path.relpath(data_root, start=config_root)
        ).as_posix()
        green_relative = Path(
            os.path.relpath(green_root, start=config_root)
        ).as_posix()
    except ValueError as exc:
        raise ValueError(
            "MTtime requires data and Green's-function directories that can be "
            "written relative to the mtinv.in project directory."
        ) from exc

    headers = {
        "datetime": str(catalog_origin),
        "longitude": f"{float(event['event_lon']):.6f}",
        "latitude": f"{float(event['event_lat']):.6f}",
        "depth": ",".join(f"{value:.4f}" for value in depths),
        "path_to_data": data_relative,
        "path_to_green": green_relative,
        "green": green_format,
        "components": mt_components,
        "degree": int(degree),
        "weight": weight,
        "plot": int(bool(plot)),
        "correlate": int(bool(correlate)),
    }
    with output_path.open("w", encoding="utf-8") as file:
        for key, value in headers.items():
            file.write(f"{key:<15}{value}\n")
        file.write(
            standard.to_string(
                index=False,
                float_format=lambda value: f"{value:.4f}",
            )
        )
        file.write("\n")

    return output


def run_mttime_inversion(
    event_df: pd.DataFrame | pd.Series | Mapping[str, Any],
    station_df: pd.DataFrame,
    gf_manifest: pd.DataFrame,
    *,
    output_file: str | Path,
    path_to_data: str | Path,
    path_to_green: str | Path,
    depths_km: Sequence[float] | None = None,
    components: str = "ZRT",
    degree: int = 5,
    weight: str = "none",
    plot: bool = False,
    correlate: bool = False,
    reference_time_shift: float = 0.0,
    drop_stations: Sequence[str | tuple[str, str, str]] | None = None,
    results_dir: str | Path | None = None,
    figures_dir: str | Path | None = None,
    plot_views: Sequence[str] = ("waveform", "depth", "map", "lune", "cmt"),
    waveform_option: str | None = "preferred",
    figure_format: str = "png",
    figure_dpi: int = 300,
    show: bool = False,
    write_option: str | None = "all",
    save_tables: bool = True,
    strict_plots: bool = False,
    correlation_abs_max: bool = True,
) -> tuple[pd.DataFrame, Any, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Write and run one complete MTtime inversion.

    This is the normal public interface. It first calls :func:`write_mtinv` with
    the supplied event, station, Green's-function and timing options, then runs
    the resulting configuration through the common MTtime execution layer. A
    separate call to :func:`write_mtinv` is therefore unnecessary unless the
    caller only wants to inspect or externally execute ``mtinv.in``.

    Parameters
    ----------
    event_df, station_df, gf_manifest
        Inputs from :func:`process_mseed_sac` and either
        :func:`generate_pyfk_gfs` or :func:`generate_syngine_gfs`, with event
        metadata accepted by :func:`write_mtinv`.
    output_file
        Destination for the generated ``mtinv.in``. Its parent directory is the
        MTtime project root used to resolve relative observation and
        Green's-function paths.
    path_to_data, path_to_green
        Observation and Green's-function directories. Absolute or
        project-relative paths are accepted and normalized by
        :func:`write_mtinv`.
    depths_km
        Trial source depths. ``None`` uses the depths available in
        ``gf_manifest``.
    components
        ``"ZRT"`` (all three components), ``"ZR"`` (Z/R inversion with T
        retained as prediction-only through the MTtime ``used`` mask), or ``"Z"``.
    degree
        Five for a deviatoric inversion or six for a full moment tensor. The
        same value is written into the configuration and supplied to MTtime, so
        there is no separate post-write degree override.
    weight
        MTtime weighting mode: ``"none"``, ``"distance"`` or ``"variance"``.
    plot
        Native MTtime configuration plotting flag. It normally remains
        ``False`` because saved and optionally displayed products are selected
        explicitly through ``plot_views`` and ``show``. Setting it to ``True``
        also permits MTtime's own inversion-time plotting behaviour.
    correlate
        Enable the bounded station-specific residual timing search around the
        selected global reference.
    reference_time_shift
        Global source/reference-time shift in seconds relative to catalog
        origin. Positive values select a later reference and negative values an
        earlier reference. The value must lie on every station's sample grid and
        within the margin reserved by ``max_reference_time_shift`` during
        :func:`process_mseed_sac`.
    drop_stations
        Station identifiers excluded only from this inversion. Observations and
        Green's functions are reused without regeneration.
    results_dir
        Directory for MTtime text solutions and exported tables. The default is
        ``<output_file parent>/results``.
    figures_dir
        Directory for requested figures. The default is
        ``<output_file parent>/figures``.
    plot_views
        Sequence containing any of ``"waveform"``, ``"depth"``, ``"map"``,
        ``"lune"`` and ``"cmt"``. ``"cmt"`` uses :func:`plot_cmt_summary` for
        the preferred MTtime solution. A depth view is skipped for one trial
        depth and a lune view is skipped for degree five.
    waveform_option
        ``"preferred"`` saves only the preferred waveform fit; ``None`` saves
        waveform fits for all trial depths.
    figure_format
        Figure extension understood by Matplotlib and MTtime.
    figure_dpi
        Positive raster resolution for saved figures.
    show
        Display requested figures after first saving them.
    write_option
        ``"all"`` writes every detailed MTtime solution, ``"preferred"`` writes
        only the preferred solution and ``None`` disables detailed text output.
    save_tables
        Write ``solutions.csv``, ``station_fits.csv`` and
        ``inversion_outputs.csv`` when ``True``.
    strict_plots
        Raise plotting failures when ``True``; otherwise record them in the
        output manifest without discarding the completed inversion.
    correlation_abs_max
        Use the absolute normalized basis correlation when selecting residual
        station shifts. ``False`` requires positive correlation. This affects
        lag selection only.

    Returns
    -------
    mtinv_stations : pandas.DataFrame
        Authoritative station table returned by :func:`write_mtinv` after
        applying ``drop_stations`` and the selected global reference-time shift.
        Its rows correspond one-to-one with the station rows written to
        ``mtinv.in``. In addition to the standard MTtime fields, the returned
        table retains audit columns such as ``origin_ts``, ``reference_ts`` and
        ``reference_time_shift`` that are not written into MTtime's text table.
        Its row count is the exact number of stations supplied to this inversion.
    inversion : mttime.Inversion
        Completed inversion. For compatibility with version 0.3.2, a copy of
        ``mtinv_stations`` is also attached as
        ``inversion.mtinv_station_table`` when the MTtime object permits dynamic
        attributes, and the resolved configuration path is attached as
        ``inversion.mtinv_path``.
    solution_df : pandas.DataFrame
        One row per trial depth with preferred-solution, scalar-moment,
        magnitude, source-type, tensor and nodal-plane information. Its attrs
        record the resolved configuration path and number of written stations.
    station_fit_df : pandas.DataFrame
        Station-level fits at every trial depth, including immutable catalog
        origin, selected global reference, optional residual correlation and
        total timing shifts.
    output_manifest : pandas.DataFrame
        Inventory of the generated configuration, detailed solutions, figures
        and exported tables.

    Notes
    -----
    The timing decomposition is

    ``final station shift = reference_time_shift + correlation_time_shift``.

    The global shift changes only which observed sample aligns with existing GF
    sample zero. It does not regenerate observations or Green's functions. The
    authoritative table returned by :func:`write_mtinv` is passed directly to the
    private execution layer before ``Inversion.invert()`` begins; this installs
    timing metadata without reading the SAC streams early or invoking MTtime's
    private data loader outside its normal lifecycle.
    """
    mtinv_stations = write_mtinv(
        event_df,
        station_df,
        gf_manifest,
        output_file=output_file,
        path_to_data=path_to_data,
        path_to_green=path_to_green,
        depths_km=depths_km,
        components=components,
        degree=degree,
        weight=weight,
        plot=plot,
        correlate=correlate,
        reference_time_shift=reference_time_shift,
        drop_stations=drop_stations,
    )

    mtinv_path = Path(output_file).expanduser().resolve()
    inversion, solution_df, station_fit_df, output_manifest = _run_mttime_file(
        mtinv_path,
        timing_table=mtinv_stations,
        degree=degree,
        results_dir=results_dir,
        figures_dir=figures_dir,
        plot_views=plot_views,
        waveform_option=waveform_option,
        figure_format=figure_format,
        figure_dpi=figure_dpi,
        show=show,
        write_option=write_option,
        save_tables=save_tables,
        strict_plots=strict_plots,
        correlation_abs_max=correlation_abs_max,
    )

    try:
        inversion.mtinv_station_table = mtinv_stations.copy()
        inversion.mtinv_path = str(mtinv_path)
    except (AttributeError, TypeError):
        # MTtime currently permits dynamic attributes, but inversion completion
        # should not depend on that implementation detail.
        pass

    solution_df.attrs["mtinv_path"] = str(mtinv_path)
    solution_df.attrs["n_mtinv_stations"] = int(len(mtinv_stations))
    station_fit_df.attrs["mtinv_path"] = str(mtinv_path)
    station_fit_df.attrs["n_mtinv_stations"] = int(len(mtinv_stations))

    configuration_row = pd.DataFrame([{
        "kind": "configuration",
        "view": "mtinv",
        "path": str(mtinv_path),
        "status": "written" if mtinv_path.is_file() else "missing",
        "reason": "" if mtinv_path.is_file() else "write_mtinv did not create the expected configuration.",
    }])
    output_manifest = pd.concat(
        [configuration_row, output_manifest],
        ignore_index=True,
        sort=False,
    )

    if save_tables:
        project_dir = mtinv_path.parent
        result_root = _resolve_output_directory(project_dir, results_dir, "results")
        result_root.mkdir(parents=True, exist_ok=True)
        output_manifest.to_csv(
            result_root / "inversion_outputs.csv",
            index=False,
        )

    return mtinv_stations, inversion, solution_df, station_fit_df, output_manifest


def _run_mttime_file(
    mtinv_file: str | Path,
    *,
    timing_table: pd.DataFrame,
    degree: int | None = None,
    results_dir: str | Path | None = None,
    figures_dir: str | Path | None = None,
    plot_views: Sequence[str] = ("waveform", "depth", "map", "lune", "cmt"),
    waveform_option: str | None = "preferred",
    figure_format: str = "png",
    figure_dpi: int = 300,
    show: bool = False,
    write_option: str | None = "all",
    save_tables: bool = True,
    strict_plots: bool = False,
    correlation_abs_max: bool = True,
) -> tuple[Any, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Execute one already-written MTtime configuration.

    This private execution layer contains the numerical inversion, bounded
    residual-correlation patch, output writing and plotting logic. ``timing_table``
    is the authoritative table returned by :func:`write_mtinv`; it is used to
    install catalog-origin and selected-reference metadata before MTtime begins.
    MTtime itself still loads the observed SAC streams exactly once inside
    :meth:`mttime.Inversion.invert`. Public code should normally call
    :func:`run_mttime_inversion`, which creates both the configuration and timing
    table. Keeping this layer private avoids duplicating execution logic in the
    origin-shift and resampling wrappers.
    """
    mtinv_path = Path(mtinv_file).expanduser().resolve()
    if not mtinv_path.is_file():
        raise FileNotFoundError(f"MTtime configuration file does not exist: {mtinv_path}")
    if degree is not None and int(degree) not in {5, 6}:
        raise ValueError("degree must be 5, 6 or None.")
    if not isinstance(save_tables, (bool, np.bool_)):
        raise TypeError("save_tables must be a boolean.")
    save_tables = bool(save_tables)

    write_key = None if write_option is None else str(write_option).strip().lower()
    if write_key not in {None, "all", "preferred"}:
        raise ValueError("write_option must be 'all', 'preferred' or None.")
    waveform_key = None if waveform_option is None else str(waveform_option).strip().lower()
    if waveform_key not in {None, "preferred"}:
        raise ValueError("waveform_option must be 'preferred' or None.")

    allowed_views = {"waveform", "depth", "map", "lune", "cmt"}
    views = []
    for value in plot_views:
        view = str(value).strip().lower()
        if view not in allowed_views:
            raise ValueError(f"Unsupported plot view {value!r}; choose from {sorted(allowed_views)}.")
        if view not in views:
            views.append(view)

    fmt = str(figure_format).strip().lower().lstrip(".")
    if not fmt:
        raise ValueError("figure_format cannot be empty.")

    figure_dpi = int(figure_dpi)
    if figure_dpi < 1:
        raise ValueError("figure_dpi must be a positive integer.")

    project_dir = mtinv_path.parent
    result_root = _resolve_output_directory(project_dir, results_dir, "results")
    figure_root = _resolve_output_directory(project_dir, figures_dir, "figures")
    if write_key is not None or save_tables:
        result_root.mkdir(parents=True, exist_ok=True)
    if views:
        figure_root.mkdir(parents=True, exist_ok=True)

    _ensure_mttime_numpy_compatibility()
    import mttime

    configure_kwargs = {}
    if degree is not None:
        configure_kwargs["degree"] = int(degree)

    config = mttime.Configure(path_to_file=str(mtinv_path), **configure_kwargs)
    if degree is not None and int(config.degree) != int(degree):
        raise RuntimeError(
            f"MTtime Configure resolved degree={config.degree}, expected {int(degree)}."
        )
    inversion = mttime.Inversion(config=config)
    _initialize_reference_timing(inversion, timing_table)
    if bool(config.correlate):
        _install_bounded_origin_correlation(
            inversion, abs_max=bool(correlation_abs_max)
        )
    inversion.invert()

    if not inversion.moment_tensors:
        raise RuntimeError("MTtime completed without producing any moment-tensor solutions.")
    if inversion.get_preferred_tensor() is None:
        raise RuntimeError("MTtime did not identify a preferred solution.")

    solution_df, station_fit_df = _mttime_result_tables(inversion)
    manifest_rows: list[dict[str, Any]] = []

    if write_key is not None:
        try:
            with _working_directory(result_root):
                if write_key == "preferred":
                    inversion.write(option="preferred")
                    tensors_written = [inversion.get_preferred_tensor()]
                else:
                    inversion.write()
                    tensors_written = list(inversion.moment_tensors)

            for tensor in tensors_written:
                path = result_root / f"d{float(tensor.depth):.4f}.mtinv.out"
                manifest_rows.append({
                    "kind": "solution_text",
                    "view": write_key,
                    "path": str(path),
                    "status": "written" if path.exists() else "missing",
                    "reason": "" if path.exists() else "MTtime did not create the expected output file.",
                })
        except Exception as exc:
            manifest_rows.append({
                "kind": "solution_text", "view": write_key, "path": str(result_root),
                "status": "failed", "reason": str(exc),
            })
            raise

    for view in views:
        skip_reason = None
        if view == "depth" and len(inversion.moment_tensors) < 2:
            skip_reason = "A depth plot requires more than one trial depth."
        elif view == "lune" and int(inversion.config.degree) != 6:
            skip_reason = "A lune plot requires degree=6."

        if skip_reason is not None:
            manifest_rows.append({
                "kind": "figure", "view": view, "path": str(figure_root),
                "status": "skipped", "reason": skip_reason,
            })
            continue

        before = _directory_state(figure_root)
        plot_kwargs = {"view": view, "show": False, "format": fmt}
        if view == "waveform":
            plot_kwargs["option"] = waveform_key

        try:
            import matplotlib as mpl
            if view == "cmt":
                summary, centroid, tensor_mode = _mttime_cmt_inputs(inversion)
                cmt_path = figure_root / f"cmt.{fmt}"
                with mpl.rc_context({"figure.facecolor": "white", "savefig.facecolor": "white",
                                     "savefig.transparent": False, "savefig.dpi": figure_dpi}):
                    fig = plot_cmt_summary(
                        summary, centroid, tensor_mode=tensor_mode, dpi=figure_dpi,
                        output_file=cmt_path, show=show,
                    )
                import matplotlib.pyplot as plt
                plt.close(fig)
            else:
                with mpl.rc_context({"figure.facecolor": "white", "savefig.facecolor": "white", "savefig.transparent": False,
                                     "savefig.dpi": figure_dpi}):
                    with _opaque_white_savefig(figure_dpi), _working_directory(figure_root):
                        inversion.plot(**plot_kwargs)

            changed = _changed_files(figure_root, before)
            matching = [path for path in changed if path.suffix.lower() == f".{fmt}"]

            if matching:
                for path in matching:
                    manifest_rows.append({
                        "kind": "figure", "view": view, "path": str(path),
                        "status": "written", "reason": "",
                    })
            else:
                manifest_rows.append({
                    "kind": "figure", "view": view, "path": str(figure_root),
                    "status": "missing",
                    "reason": "Plotting returned without creating or updating a figure file.",
                })

            if show and view != "cmt":
                display_kwargs = dict(plot_kwargs)
                display_kwargs["show"] = True
                with mpl.rc_context({"figure.facecolor": "white", "savefig.facecolor": "white", "savefig.transparent": False,
                                     "savefig.dpi": figure_dpi}):
                    with _opaque_white_savefig(figure_dpi), _working_directory(figure_root):
                        inversion.plot(**display_kwargs)
        except Exception as exc:
            manifest_rows.append({
                "kind": "figure", "view": view, "path": str(figure_root),
                "status": "failed", "reason": str(exc),
            })
            if strict_plots:
                raise

    if save_tables:
        solution_path = result_root / "solutions.csv"
        station_fit_path = result_root / "station_fits.csv"
        manifest_path = result_root / "inversion_outputs.csv"
        solution_df.to_csv(solution_path, index=False)
        station_fit_df.to_csv(station_fit_path, index=False)
        manifest_rows.extend([
            {"kind": "table", "view": "solutions", "path": str(solution_path), "status": "written", "reason": ""},
            {"kind": "table", "view": "station_fits", "path": str(station_fit_path), "status": "written", "reason": ""},
            {"kind": "table", "view": "manifest", "path": str(manifest_path), "status": "written", "reason": ""},
        ])
        output_manifest = pd.DataFrame(manifest_rows)
        output_manifest.to_csv(manifest_path, index=False)
    else:
        output_manifest = pd.DataFrame(manifest_rows)
    return inversion, solution_df, station_fit_df, output_manifest


def mttime_inversion_oshift(
    event_df: pd.DataFrame | pd.Series | Mapping[str, Any],
    station_df: pd.DataFrame,
    gf_manifest: pd.DataFrame,
    *,
    output_dir: str | Path,
    reference_time_shifts: Sequence[float],
    path_to_data: str | Path = "processed/data",
    path_to_green: str | Path = "greens",
    depths_km: Sequence[float] | None = None,
    components: str = "ZRT",
    degree: int = 5,
    weight: str = "none",
    plot: bool = False,
    correlate: bool = False,
    drop_stations: Sequence[str | tuple[str, str, str]] | None = None,
    plot_views: Sequence[str] = (),
    waveform_option: str | None = "preferred",
    figure_format: str = "png",
    figure_dpi: int = 300,
    show: bool = False,
    write_option: str | None = "all",
    save_tables: bool = True,
    strict_plots: bool = False,
    correlation_abs_max: bool = True,
    suppress_output: bool = True,
    progress: bool = True,
    on_error: str = "raise",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Scan MTtime solutions across global origin/reference-time shifts.

    Each requested shift is written as an independent MTtime project under
    ``output_dir``. Existing observations and Green's functions are reused; only
    the observed ``ts`` values change. The MTtime ``datetime`` header remains the
    immutable catalog origin in every run. Every run performs the complete depth
    search requested through ``depths_km``.

    Parameters
    ----------
    event_df, station_df, gf_manifest
        Inputs accepted by :func:`write_mtinv`.
    output_dir
        Root directory for the shift scan. Run ``i`` is stored under
        ``shift_<index>_<signed-value>`` with its own ``mtinv.in``, ``results``
        and ``figures`` directories. Saved figure filenames are tagged with the
        run index and signed shift, for example
        ``depth.bbmw_oshift_000_m0005p0000.png``. Combined CSV tables are written
        directly under this root when ``save_tables=True``.
    reference_time_shifts
        Finite global shifts in seconds relative to catalog origin. Positive is
        later and negative is earlier. Values must be unique, lie on every
        station's sample grid and remain within the margin reserved by
        ``max_reference_time_shift`` in :func:`process_mseed_sac`.
    path_to_data, path_to_green, depths_km, components, degree, weight, plot,
    correlate, drop_stations
        Configuration arguments forwarded to :func:`run_mttime_inversion`;
        ``components`` accepts ``"ZRT"``, ``"ZR"`` or ``"Z"``. It invokes
        :func:`write_mtinv` internally. Paths are resolved relative
        to the scan root before being written into each run-specific project.
    plot_views, waveform_option, figure_format, figure_dpi, show, write_option,
    save_tables, strict_plots, correlation_abs_max
        Forwarded to :func:`run_mttime_inversion`. ``show`` controls interactive
        display after figures are saved.
    suppress_output
        If ``True``, capture MTtime stdout and stderr for each run. If ``False``,
        preserve normal MTtime console output.
    progress
        Display a tqdm progress bar over the requested shifts.
    on_error
        ``"raise"`` stops on the first failed shift. ``"record"`` stores the
        failure in ``summary_df`` and continues.

    Returns
    -------
    summary_df
        One row per requested shift. Successful rows contain the complete
        preferred-depth solution, run paths, the exact station count from the
        table written to that run's ``mtinv.in``, and ranking fields.
        ``best_vr_across_shifts`` marks the largest in-sample preferred variance
        reduction; it is a fit diagnostic rather than automatic evidence that
        the corresponding source time is physically correct.
    solution_df
        All trial-depth solution rows from all successful shifts, augmented with
        run and shift metadata.
    station_fit_df
        All station-fit rows from all successful shifts, including catalog,
        global-reference, residual-correlation and total timing shifts.
    output_manifest
        Combined run-specific output manifests with shift and run metadata.
        Paths for successfully written figures point to filenames tagged with
        both the run index and signed reference-time shift.

    Notes
    -----
    The algorithm is

    1. validate each requested global shift through :func:`write_mtinv`;
    2. align GF time zero with ``origin_ts + shift/dt``;
    3. optionally correlate each station only around that selected reference;
    4. invert all requested depths and retain MTtime's preferred solution for the
       per-shift summary; and
    5. rank successful shifts by preferred variance reduction without discarding
       the complete depth and station-fit tables.

    Global and residual shifts are deliberately separated. When correlation is
    enabled, the final station shift relative to catalog origin is

    ``reference_time_shift + correlation_time_shift``.
    """
    from tqdm.auto import tqdm

    if not isinstance(suppress_output, (bool, np.bool_)):
        raise TypeError("suppress_output must be a boolean.")
    if not isinstance(progress, (bool, np.bool_)):
        raise TypeError("progress must be a boolean.")
    if not isinstance(save_tables, (bool, np.bool_)):
        raise TypeError("save_tables must be a boolean.")

    suppress_output = bool(suppress_output)
    progress = bool(progress)
    save_tables = bool(save_tables)
    error_mode = str(on_error).strip().lower()
    if error_mode not in {"raise", "record"}:
        raise ValueError("on_error must be 'raise' or 'record'.")

    shifts = np.asarray(list(reference_time_shifts), dtype=float)
    if shifts.ndim != 1 or shifts.size == 0:
        raise ValueError("reference_time_shifts must contain at least one value.")
    if not np.isfinite(shifts).all():
        raise ValueError("reference_time_shifts must contain only finite values.")
    if np.unique(shifts).size != shifts.size:
        raise ValueError("reference_time_shifts cannot contain duplicate values.")

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    data_root = _resolve_from_config(root, path_to_data).expanduser().resolve()
    green_root = _resolve_from_config(root, path_to_green).expanduser().resolve()

    summary_rows: list[dict[str, Any]] = []
    solution_tables: list[pd.DataFrame] = []
    fit_tables: list[pd.DataFrame] = []
    manifest_tables: list[pd.DataFrame] = []

    iterator = tqdm(
        enumerate(shifts),
        total=len(shifts),
        desc="MTtime global reference-time scan",
        unit="shift",
        disable=not progress,
    )

    for run_index, shift in iterator:
        shift = float(shift)
        shift_token = f"{shift:+010.4f}".replace("+", "p").replace("-", "m").replace(".", "p")
        run_dir = root / f"shift_{run_index:03d}_{shift_token}"
        results_dir = run_dir / "results"
        figures_dir = run_dir / "figures"
        mtinv_path = run_dir / "mtinv.in"
        run_dir.mkdir(parents=True, exist_ok=True)

        try:
            with _suppressed_console_output(suppress_output):
                (
                    mtinv_stations,
                    inversion,
                    run_solutions,
                    run_fits,
                    run_manifest,
                ) = run_mttime_inversion(
                    event_df,
                    station_df,
                    gf_manifest,
                    output_file=mtinv_path,
                    path_to_data=data_root,
                    path_to_green=green_root,
                    depths_km=depths_km,
                    components=components,
                    degree=degree,
                    weight=weight,
                    plot=plot,
                    correlate=correlate,
                    reference_time_shift=shift,
                    drop_stations=drop_stations,
                    results_dir=results_dir,
                    figures_dir=figures_dir,
                    plot_views=plot_views,
                    waveform_option=waveform_option,
                    figure_format=figure_format,
                    figure_dpi=figure_dpi,
                    show=show,
                    write_option=write_option,
                    save_tables=save_tables,
                    strict_plots=strict_plots,
                    correlation_abs_max=correlation_abs_max,
                )

            figure_tag = f"oshift_{run_index:03d}_{shift_token}"
            run_manifest = _tag_written_figure_files(
                run_manifest,
                figure_tag,
            )
            if save_tables:
                run_manifest.to_csv(
                    results_dir / "inversion_outputs.csv",
                    index=False,
                )

            n_stations_used = int(len(mtinv_stations))
            if n_stations_used < 1:
                raise RuntimeError(
                    f"Shift {shift:+.6f} wrote an empty MTtime station table."
                )

            preferred = run_solutions.loc[run_solutions["preferred"]]
            if len(preferred) != 1:
                raise RuntimeError(
                    f"Shift {shift:+.6f} produced {len(preferred)} preferred "
                    "solutions."
                )

            base = {
                "run_index": int(run_index),
                "status": "ok",
                "reference_time_shift": shift,
                "components": str(components).upper(),
                "degree_requested": int(degree),
                "weight": str(weight).lower(),
                "correlate": bool(correlate),
                "n_stations": n_stations_used,
                "n_trial_depths": int(len(run_solutions)),
                "mtinv_path": str(mtinv_path),
                "results_dir": str(results_dir),
                "figures_dir": str(figures_dir),
            }
            summary_rows.append({**base, **preferred.iloc[0].to_dict()})

            run_solutions = run_solutions.copy()
            run_solutions.insert(0, "run_index", int(run_index))
            if "reference_time_shift" not in run_solutions:
                run_solutions.insert(1, "reference_time_shift", shift)
            solution_tables.append(run_solutions)

            run_fits = run_fits.copy()
            run_fits.insert(0, "run_index", int(run_index))
            if "reference_time_shift" not in run_fits:
                run_fits.insert(1, "reference_time_shift", shift)
            fit_tables.append(run_fits)

            run_manifest = run_manifest.copy()
            if not run_manifest.empty:
                run_manifest.insert(0, "run_index", int(run_index))
                run_manifest.insert(1, "reference_time_shift", shift)
                manifest_tables.append(run_manifest)

            del inversion

        except Exception as exc:
            if error_mode == "raise":
                raise
            summary_rows.append({
                "run_index": int(run_index),
                "status": "failed",
                "reference_time_shift": shift,
                "components": str(components).upper(),
                "degree_requested": int(degree),
                "weight": str(weight).lower(),
                "correlate": bool(correlate),
                "n_stations": np.nan,
                "n_trial_depths": np.nan,
                "mtinv_path": str(mtinv_path),
                "results_dir": str(results_dir),
                "figures_dir": str(figures_dir),
                "reason": str(exc),
            })

    summary_df = pd.DataFrame(summary_rows).sort_values(
        "run_index", ignore_index=True
    )
    solution_df = (
        pd.concat(solution_tables, ignore_index=True)
        if solution_tables else pd.DataFrame()
    )
    station_fit_df = (
        pd.concat(fit_tables, ignore_index=True)
        if fit_tables else pd.DataFrame()
    )
    output_manifest = (
        pd.concat(manifest_tables, ignore_index=True)
        if manifest_tables else pd.DataFrame()
    )

    successful = summary_df["status"].eq("ok") if not summary_df.empty else pd.Series(dtype=bool)
    summary_df["best_vr_across_shifts"] = False
    summary_df["vr_rank_across_shifts"] = np.nan
    summary_df["delta_vr_from_best"] = np.nan
    if successful.any():
        successful_index = summary_df.index[successful]
        vr = pd.to_numeric(
            summary_df.loc[successful_index, "total_vr_percent"], errors="raise"
        )
        best_index = int(vr.idxmax())
        best_vr = float(vr.loc[best_index])
        summary_df.loc[best_index, "best_vr_across_shifts"] = True
        summary_df.loc[successful_index, "vr_rank_across_shifts"] = (
            vr.rank(method="min", ascending=False).astype(int)
        )
        summary_df.loc[successful_index, "delta_vr_from_best"] = best_vr - vr
    elif error_mode == "record":
        if save_tables:
            summary_df.to_csv(root / "origin_shift_summary.csv", index=False)
        reasons = summary_df.get("reason", pd.Series(dtype=str)).dropna().astype(str)
        reason_text = "; ".join(sorted(set(reasons))) or "unknown failures"
        raise RuntimeError(
            "All global reference-time shifts failed. Failure reasons: "
            f"{reason_text}"
        )

    if save_tables:
        summary_df.to_csv(root / "origin_shift_summary.csv", index=False)
        solution_df.to_csv(root / "origin_shift_solutions.csv", index=False)
        station_fit_df.to_csv(root / "origin_shift_station_fits.csv", index=False)
        output_manifest.to_csv(root / "origin_shift_outputs.csv", index=False)

    return summary_df, solution_df, station_fit_df, output_manifest



def _maximum_azimuth_gap_deg(azimuth_rad: Sequence[float]) -> float:
    """Return the largest circular gap between sorted azimuths in degrees."""
    azimuth = np.mod(np.asarray(azimuth_rad, dtype=float), 2.0 * np.pi)
    if azimuth.size < 2:
        return 360.0
    azimuth.sort()
    gaps = np.diff(np.r_[azimuth, azimuth[0] + 2.0 * np.pi])
    return float(np.rad2deg(np.max(gaps)))


def _station_polar_table(station_df: pd.DataFrame) -> pd.DataFrame:
    """Return unique station IDs with event-centred radius and azimuth."""
    if station_df.empty:
        raise ValueError("station_df is empty.")
    table = station_df.copy()
    if "station_id" not in table.columns:
        table["station_id"] = table.apply(
            lambda row: _station_id_from_row(row), axis=1
        )
    if table["station_id"].astype(str).duplicated().any():
        duplicate = table.loc[
            table["station_id"].astype(str).duplicated(keep=False), "station_id"
        ].astype(str).tolist()
        raise ValueError(f"station_df contains duplicate station IDs: {duplicate}")

    if "r_epi" in table.columns:
        radius = pd.to_numeric(table["r_epi"], errors="raise").to_numpy(float)
    else:
        radius = pd.to_numeric(
            _column_from_aliases(table, ("distance", "distance_km")),
            errors="raise",
        ).to_numpy(float)

    if "r_azi" in table.columns:
        azimuth = pd.to_numeric(table["r_azi"], errors="raise").to_numpy(float)
    else:
        azimuth_deg = pd.to_numeric(
            _column_from_aliases(table, ("azimuth", "azimuth_deg")),
            errors="raise",
        ).to_numpy(float)
        azimuth = np.deg2rad(azimuth_deg)

    if not np.isfinite(radius).all() or not np.isfinite(azimuth).all():
        raise ValueError("Station polar coordinates must be finite.")
    if (radius < 0).any():
        raise ValueError("Station epicentral radii cannot be negative.")

    return pd.DataFrame({
        "station_id": table["station_id"].astype(str).to_numpy(),
        "r_epi": radius,
        "r_azi": np.mod(azimuth, 2.0 * np.pi),
    })


def select_opposing_station_pairs(
    station_df: pd.DataFrame,
    *,
    loo_pairs: int = 1,
    opposition_tolerance_deg: float = 20.0,
    max_relative_radial_difference: float | None = None,
    min_remaining_stations: int = 6,
    max_azimuth_gap_increase_deg: float | None = None,
    random_state: int | np.random.Generator | None = None,
    max_attempts: int = 2000,
) -> tuple[list[str], pd.DataFrame]:
    """Select disjoint, approximately opposing station pairs for deletion.

    The function constructs one geometry-balanced delete-d station design for
    moment-tensor robustness analysis. Each selected pair contains two stations
    lying on approximately opposite source-to-station azimuths. When multiple
    pairs are requested, their undirected pair axes are additionally required to
    be approximately evenly distributed across the 180-degree axial domain.

    The station network may already have strongly uneven azimuth coverage.
    Consequently, the retained network is constrained by the *increase* in its
    largest azimuth gap rather than by an absolute maximum gap:

    ``gap_increase = remaining_max_gap - baseline_max_gap``.

    This allows a biased original network to be analysed while preventing a
    deletion from substantially worsening its existing azimuth coverage.

    Parameters
    ----------
    station_df
        Station table containing unique station identifiers and event-centred
        polar coordinates. The table must contain ``r_epi`` and ``r_azi`` or
        provide coordinate aliases accepted by :func:`_station_polar_table`.

        ``r_epi`` is epicentral distance in kilometres. ``r_azi`` is the
        event-to-station azimuth in radians within ``[0, 2*pi)``.

    loo_pairs
        Number of disjoint opposing station pairs to delete. The total number
        of deleted stations is ``2 * loo_pairs``.

        Examples:

        - ``loo_pairs=1`` deletes two approximately opposing stations.
        - ``loo_pairs=2`` deletes four stations defining two approximately
          perpendicular pair axes.
        - ``loo_pairs=3`` deletes six stations with pair axes ideally separated
          by 60 degrees.

    opposition_tolerance_deg
        Maximum departure from exact opposition for each individual pair:

        ``abs(180 - azimuth_separation_deg) <= opposition_tolerance_deg``.

        The same tolerance is used for the spacing among multiple pair axes.
        For example, with ``loo_pairs=2`` and a tolerance of 15 degrees, the two
        axes must be separated by approximately ``90 +/- 15`` degrees.

    max_relative_radial_difference
        Optional maximum symmetric relative difference between the epicentral
        distances of the two stations in a pair:

        ``abs(r_i - r_j) / ((r_i + r_j) / 2)``.

        Values are fractions:

        - ``0.25`` allows a difference up to 25% of the mean pair radius.
        - ``0.50`` allows a difference up to 50%.
        - ``None`` disables radial-distance filtering.

        The measure is symmetric and scales naturally with source-to-station
        distance. Its mathematical range is ``[0, 2]`` for non-negative radii.

    min_remaining_stations
        Minimum number of stations that must remain after deleting all selected
        pairs.

    max_azimuth_gap_increase_deg
        Optional maximum permitted increase in the largest circular station
        azimuth gap, in degrees.

        For example, ``15.0`` accepts the original network geometry but rejects
        deletions that enlarge its largest gap by more than 15 degrees. ``None``
        disables this constraint.

        This is preferable to an absolute retained-gap threshold for naturally
        biased networks.

    random_state
        Integer seed or existing :class:`numpy.random.Generator` controlling the
        randomized ordering of candidate-pair combinations.

    max_attempts
        Maximum number of complete disjoint candidate sets evaluated while
        searching for a feasible multi-pair design. For ``loo_pairs=1``, valid
        candidate pairs are enumerated directly and a random one is selected.

    Returns
    -------
    dropped
        Station identifiers selected for deletion. The list contains two
        identifiers per selected pair.

    pair_table
        One row per selected pair with station identifiers, radii, azimuths,
        pair-axis orientation, opposition error, absolute and relative radial
        differences, pair-axis spacing diagnostics, the baseline azimuth gap,
        the retained-network gap and its increase.

    Raises
    ------
    ValueError
        Raised for invalid parameters, insufficient remaining stations or when
        too few individual candidate pairs satisfy the opposition, radial and
        necessary single-pair gap constraints.

    RuntimeError
        Raised when candidate pairs exist but no disjoint combination satisfies
        the pair-axis spacing and retained-network gap-increase constraints
        within ``max_attempts`` evaluated combinations.

    Notes
    -----
    This is a geometry-balanced delete-d robustness design, not a classical
    bootstrap with replacement.

    An opposing pair defines an undirected axis, so pair-axis orientations lie
    in ``[0, 180)`` degrees. For ``loo_pairs=k``, the ideal circular spacing is

    ``180 / k`` degrees.

    Removing stations cannot decrease the largest circular azimuth gap. An
    individual candidate pair that already violates the allowed gap increase is
    therefore removed before the multi-pair search.

    Selection depends only on station geometry. It does not use waveform fit,
    variance reduction or the resulting moment-tensor solution.
    """
    loo_pairs = int(loo_pairs)
    min_remaining_stations = int(min_remaining_stations)
    max_attempts = int(max_attempts)

    if loo_pairs < 0:
        raise ValueError("loo_pairs must be non-negative.")
    if min_remaining_stations < 1:
        raise ValueError("min_remaining_stations must be positive.")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive.")

    tolerance = float(opposition_tolerance_deg)
    if not np.isfinite(tolerance) or not 0.0 <= tolerance <= 180.0:
        raise ValueError(
            "opposition_tolerance_deg must lie within [0, 180]."
        )

    if max_relative_radial_difference is not None:
        max_relative_radial_difference = float(
            max_relative_radial_difference
        )
        if (
            not np.isfinite(max_relative_radial_difference)
            or not 0.0 <= max_relative_radial_difference <= 2.0
        ):
            raise ValueError(
                "max_relative_radial_difference must lie within [0, 2] "
                "or be None. Use fractions such as 0.25 or 0.50."
            )

    if max_azimuth_gap_increase_deg is not None:
        max_azimuth_gap_increase_deg = float(
            max_azimuth_gap_increase_deg
        )
        if (
            not np.isfinite(max_azimuth_gap_increase_deg)
            or not 0.0 <= max_azimuth_gap_increase_deg <= 360.0
        ):
            raise ValueError(
                "max_azimuth_gap_increase_deg must lie within [0, 360] "
                "or be None."
            )

    polar = _station_polar_table(station_df).reset_index(drop=True)
    n_stations = len(polar)
    n_drop = 2 * loo_pairs

    if n_stations - n_drop < min_remaining_stations:
        raise ValueError(
            f"Removing {loo_pairs} opposing pairs would leave "
            f"{n_stations - n_drop} stations, fewer than "
            f"min_remaining_stations={min_remaining_stations}."
        )

    output_columns = [
        "pair_index",
        "station_i",
        "station_j",
        "r_epi_i_km",
        "r_epi_j_km",
        "radial_mean_km",
        "radial_difference_km",
        "relative_radial_difference",
        "relative_radial_difference_percent",
        "r_azi_i_deg",
        "r_azi_j_deg",
        "pair_axis_deg",
        "azimuth_separation_deg",
        "opposition_error_deg",
        "ideal_axis_spacing_deg",
        "axis_spacing_max_error_deg",
        "baseline_max_azimuth_gap_deg",
        "remaining_max_azimuth_gap_deg",
        "azimuth_gap_increase_deg",
    ]

    baseline_gap_deg = _maximum_azimuth_gap_deg(
        polar["r_azi"].to_numpy(dtype=float)
    )

    if loo_pairs == 0:
        return [], pd.DataFrame(columns=output_columns)

    station_ids = polar["station_id"].astype(str).to_numpy()
    radii = polar["r_epi"].to_numpy(dtype=float)
    azimuths = np.mod(
        polar["r_azi"].to_numpy(dtype=float),
        2.0 * np.pi,
    )

    candidates: list[dict[str, Any]] = []

    for i in range(n_stations - 1):
        for j in range(i + 1, n_stations):
            theta_i = float(azimuths[i])
            theta_j = float(azimuths[j])

            angular_difference = abs(theta_i - theta_j)
            angular_difference = min(
                angular_difference,
                2.0 * np.pi - angular_difference,
            )

            separation_deg = float(
                np.rad2deg(angular_difference)
            )
            opposition_error_deg = abs(
                180.0 - separation_deg
            )

            if opposition_error_deg > tolerance + 1e-12:
                continue

            # An opposing pair defines an undirected axis. The doubled-angle
            # circular mean correctly handles its 180-degree periodicity.
            pair_axis_rad = 0.5 * np.arctan2(
                np.sin(2.0 * theta_i) + np.sin(2.0 * theta_j),
                np.cos(2.0 * theta_i) + np.cos(2.0 * theta_j),
            )
            pair_axis_deg = float(
                np.rad2deg(np.mod(pair_axis_rad, np.pi))
            )

            r_i = float(radii[i])
            r_j = float(radii[j])
            radial_mean_km = 0.5 * (r_i + r_j)
            radial_difference_km = abs(r_i - r_j)

            if radial_mean_km > 0.0:
                relative_radial_difference = (
                    radial_difference_km / radial_mean_km
                )
            else:
                # Non-negative radii imply both stations are at zero radius.
                relative_radial_difference = 0.0

            if (
                max_relative_radial_difference is not None
                and relative_radial_difference
                > max_relative_radial_difference + 1e-12
            ):
                continue

            # Removing additional stations cannot reduce the largest circular
            # gap. If this pair alone violates the allowed increase, no larger
            # deletion set containing it can be feasible.
            remaining_mask = np.ones(n_stations, dtype=bool)
            remaining_mask[[i, j]] = False

            individual_remaining_gap_deg = (
                _maximum_azimuth_gap_deg(
                    azimuths[remaining_mask]
                )
            )
            individual_gap_increase_deg = max(
                0.0,
                individual_remaining_gap_deg - baseline_gap_deg,
            )

            if (
                max_azimuth_gap_increase_deg is not None
                and individual_gap_increase_deg
                > max_azimuth_gap_increase_deg + 1e-12
            ):
                continue

            candidates.append({
                "i": i,
                "j": j,
                "station_i": station_ids[i],
                "station_j": station_ids[j],
                "r_epi_i_km": r_i,
                "r_epi_j_km": r_j,
                "radial_mean_km": radial_mean_km,
                "radial_difference_km": radial_difference_km,
                "relative_radial_difference": (
                    relative_radial_difference
                ),
                "relative_radial_difference_percent": (
                    100.0 * relative_radial_difference
                ),
                "r_azi_i_deg": float(np.rad2deg(theta_i)),
                "r_azi_j_deg": float(np.rad2deg(theta_j)),
                "pair_axis_deg": pair_axis_deg,
                "azimuth_separation_deg": separation_deg,
                "opposition_error_deg": opposition_error_deg,
            })

    if len(candidates) < loo_pairs:
        radial_description = (
            "no relative radial-distance limit"
            if max_relative_radial_difference is None
            else (
                "max_relative_radial_difference="
                f"{max_relative_radial_difference:.3f}"
            )
        )
        gap_description = (
            "no azimuth-gap increase limit"
            if max_azimuth_gap_increase_deg is None
            else (
                "max_azimuth_gap_increase_deg="
                f"{max_azimuth_gap_increase_deg:.3f}"
            )
        )

        raise ValueError(
            f"Only {len(candidates)} opposing candidate pairs satisfy "
            f"opposition_tolerance_deg={tolerance:.3f}, "
            f"{radial_description}, and {gap_description}; fewer than "
            f"loo_pairs={loo_pairs}. The baseline maximum azimuth gap is "
            f"{baseline_gap_deg:.3f} degrees."
        )

    rng = (
        random_state
        if isinstance(random_state, np.random.Generator)
        else np.random.default_rng(random_state)
    )

    # Random order provides different valid designs across repeated calls while
    # bounded backtracking avoids the false failures possible with greedy pairing.
    candidate_order = np.asarray(
        rng.permutation(len(candidates)),
        dtype=int,
    )

    evaluated_sets = 0
    selected_result = None
    best_result = None

    def evaluate_candidate_set(
        chosen: list[dict[str, Any]],
    ) -> tuple[
        bool,
        float,
        float,
        float,
        float,
    ]:
        """Evaluate pair-axis spacing and retained-network azimuth coverage."""
        nonlocal evaluated_sets, best_result

        evaluated_sets += 1

        if loo_pairs > 1:
            pair_axes_deg = np.sort(np.asarray(
                [pair["pair_axis_deg"] for pair in chosen],
                dtype=float,
            ))
            axis_gaps_deg = np.diff(np.concatenate([
                pair_axes_deg,
                [pair_axes_deg[0] + 180.0],
            ]))
            ideal_axis_spacing_deg = (
                180.0 / float(loo_pairs)
            )
            axis_spacing_max_error_deg = float(np.max(np.abs(
                axis_gaps_deg - ideal_axis_spacing_deg
            )))
        else:
            ideal_axis_spacing_deg = 180.0
            axis_spacing_max_error_deg = 0.0

        used_indices = np.fromiter(
            (
                index
                for pair in chosen
                for index in (pair["i"], pair["j"])
            ),
            dtype=int,
        )

        remaining_mask = np.ones(n_stations, dtype=bool)
        remaining_mask[used_indices] = False

        remaining_gap_deg = _maximum_azimuth_gap_deg(
            azimuths[remaining_mask]
        )
        gap_increase_deg = max(
            0.0,
            remaining_gap_deg - baseline_gap_deg,
        )

        axis_excess = max(
            0.0,
            axis_spacing_max_error_deg - tolerance,
        )
        gap_excess = (
            0.0
            if max_azimuth_gap_increase_deg is None
            else max(
                0.0,
                gap_increase_deg
                - max_azimuth_gap_increase_deg,
            )
        )

        score = (
            axis_excess + gap_excess,
            axis_spacing_max_error_deg,
            gap_increase_deg,
        )

        if best_result is None or score < best_result["score"]:
            best_result = {
                "score": score,
                "axis_spacing_max_error_deg": (
                    axis_spacing_max_error_deg
                ),
                "remaining_gap_deg": remaining_gap_deg,
                "gap_increase_deg": gap_increase_deg,
            }

        valid_axis_spacing = (
            axis_spacing_max_error_deg <= tolerance + 1e-12
        )
        valid_gap_increase = (
            max_azimuth_gap_increase_deg is None
            or gap_increase_deg
            <= max_azimuth_gap_increase_deg + 1e-12
        )

        valid = valid_axis_spacing and valid_gap_increase

        return (
            valid,
            axis_spacing_max_error_deg,
            ideal_axis_spacing_deg,
            remaining_gap_deg,
            gap_increase_deg,
        )

    def search_candidate_sets(
        start_position: int,
        chosen: list[dict[str, Any]],
        used_station_indices: set[int],
    ) -> None:
        """Search disjoint candidate combinations in randomized order."""
        nonlocal selected_result

        if (
            selected_result is not None
            or evaluated_sets >= max_attempts
        ):
            return

        if len(chosen) == loo_pairs:
            (
                valid,
                axis_error,
                ideal_spacing,
                remaining_gap,
                gap_increase,
            ) = evaluate_candidate_set(chosen)

            if valid:
                selected_result = (
                    list(chosen),
                    axis_error,
                    ideal_spacing,
                    remaining_gap,
                    gap_increase,
                )
            return

        pairs_still_needed = loo_pairs - len(chosen)

        if (
            len(candidate_order) - start_position
            < pairs_still_needed
        ):
            return

        for position in range(
            start_position,
            len(candidate_order),
        ):
            if (
                selected_result is not None
                or evaluated_sets >= max_attempts
            ):
                return

            candidate = candidates[
                int(candidate_order[position])
            ]

            if (
                candidate["i"] in used_station_indices
                or candidate["j"] in used_station_indices
            ):
                continue

            search_candidate_sets(
                position + 1,
                [*chosen, candidate],
                used_station_indices.union({
                    candidate["i"],
                    candidate["j"],
                }),
            )

    search_candidate_sets(
        start_position=0,
        chosen=[],
        used_station_indices=set(),
    )

    if selected_result is None:
        diagnostic = ""

        if best_result is not None:
            diagnostic = (
                " Best evaluated combination had "
                "axis_spacing_max_error_deg="
                f"{best_result['axis_spacing_max_error_deg']:.3f}, "
                "remaining_max_azimuth_gap_deg="
                f"{best_result['remaining_gap_deg']:.3f}, and "
                "azimuth_gap_increase_deg="
                f"{best_result['gap_increase_deg']:.3f}."
            )

        raise RuntimeError(
            "Could not select a disjoint opposing-pair deletion "
            f"after evaluating {evaluated_sets} candidate sets from "
            f"{len(candidates)} individual candidate pairs. The baseline "
            f"maximum azimuth gap is {baseline_gap_deg:.3f} degrees."
            f"{diagnostic} Relax loo_pairs, "
            "opposition_tolerance_deg, max_relative_radial_difference "
            "or max_azimuth_gap_increase_deg as physically appropriate."
        )

    (
        chosen,
        axis_spacing_max_error_deg,
        ideal_axis_spacing_deg,
        remaining_gap_deg,
        gap_increase_deg,
    ) = selected_result

    pair_table = (
        pd.DataFrame(chosen)
        .drop(columns=["i", "j"])
        .sort_values("pair_axis_deg", ignore_index=True)
    )

    pair_table.insert(
        0,
        "pair_index",
        np.arange(1, loo_pairs + 1, dtype=int),
    )
    pair_table["ideal_axis_spacing_deg"] = (
        ideal_axis_spacing_deg
    )
    pair_table["axis_spacing_max_error_deg"] = (
        axis_spacing_max_error_deg
    )
    pair_table["baseline_max_azimuth_gap_deg"] = (
        baseline_gap_deg
    )
    pair_table["remaining_max_azimuth_gap_deg"] = (
        remaining_gap_deg
    )
    pair_table["azimuth_gap_increase_deg"] = (
        gap_increase_deg
    )

    pair_table = pair_table.loc[:, output_columns]

    dropped = [
        station
        for row in pair_table.itertuples(index=False)
        for station in (row.station_i, row.station_j)
    ]

    return dropped, pair_table


@contextmanager
def _suppressed_console_output(enabled: bool = True):
    """Suppress stdout and stderr within ensemble inversions when requested."""
    if not enabled:
        yield
        return
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        yield

_RESAMPLING_TENSOR_COLUMNS = (
    "mxx_dyne_cm",
    "myy_dyne_cm",
    "mzz_dyne_cm",
    "mxy_dyne_cm",
    "mxz_dyne_cm",
    "myz_dyne_cm",
)


def _tensor6_to_matrix(values: Sequence[float]) -> np.ndarray:
    """Convert six independent XYZ tensor elements to a symmetric matrix."""
    mxx, myy, mzz, mxy, mxz, myz = np.asarray(values, dtype=float)

    return np.array([
        [mxx, mxy, mxz],
        [mxy, myy, myz],
        [mxz, myz, mzz],
    ], dtype=float)


def _matrix_to_tensor6(matrix: np.ndarray) -> np.ndarray:
    """Convert a symmetric XYZ tensor matrix to six independent elements."""
    matrix = np.asarray(matrix, dtype=float)

    return np.array([
        matrix[0, 0],
        matrix[1, 1],
        matrix[2, 2],
        matrix[0, 1],
        matrix[0, 2],
        matrix[1, 2],
    ], dtype=float)


def _normalized_tensor_matrices(table: pd.DataFrame) -> np.ndarray:
    """Return unit-Frobenius XYZ tensor matrices for preferred solutions."""
    values = table.loc[:, _RESAMPLING_TENSOR_COLUMNS].to_numpy(dtype=float)
    matrices = np.stack([
        _tensor6_to_matrix(row)
        for row in values
    ])

    norms = np.linalg.norm(matrices, axis=(1, 2))

    if not np.isfinite(matrices).all():
        raise ValueError("Preferred moment tensors contain non-finite values.")

    if np.any(norms <= 0.0):
        raise ValueError("Preferred moment tensors must be nonzero.")

    return matrices / norms[:, None, None]


def _tensor_medoid_position(normalized: np.ndarray) -> int:
    """Return the tensor minimizing total normalized Frobenius distance."""
    normalized = np.asarray(normalized, dtype=float)

    if len(normalized) == 1:
        return 0

    differences = normalized[:, None, :, :] - normalized[None, :, :, :]
    distances = np.linalg.norm(differences, axis=(2, 3))

    return int(np.argmin(distances.sum(axis=1)))


def _circular_difference_deg(
    values: Sequence[float] | np.ndarray,
    reference: float,
) -> np.ndarray:
    """Return signed circular differences within [-180, 180) degrees."""
    values = np.asarray(values, dtype=float)
    return (values - float(reference) + 180.0) % 360.0 - 180.0


def _half_central_68(values: Sequence[float] | pd.Series) -> float:
    """Return half the central 16th-to-84th percentile interval."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]

    if len(values) == 0:
        return np.nan

    q16, q84 = np.quantile(values, [0.16, 0.84])
    return float(0.5 * (q84 - q16))


def _decompose_xyz_tensor(
    tensor6: Sequence[float],
    *,
    depth_km: float,
    inversion_type: str,
    target_mo_dyne_cm: float | None = None,
) -> dict[str, Any]:
    """Decompose an XYZ tensor using MTtime's own Tensor implementation.

    Parameters
    ----------
    tensor6
        Six independent XYZ tensor elements ordered as
        ``MXX, MYY, MZZ, MXY, MXZ, MYZ``.
    depth_km
        Representative source depth assigned to the tensor.
    inversion_type
        MTtime inversion type, normally ``"Deviatoric"`` or ``"Full"``.
    target_mo_dyne_cm
        Optional scalar moment to which the tensor is rescaled before its final
        decomposition.

    Returns
    -------
    dict
        Decomposition quantities, nodal planes, lune coordinates and rescaled
        XYZ tensor components.
    """
    from mttime.core.tensor import Tensor

    values = np.asarray(tensor6, dtype=float)

    # Tensor inserts the VR column at index 7 + len(components). Seven empty
    # columns therefore provide the minimum valid zero-station table.
    dummy_station_table = pd.DataFrame(
        columns=[f"_dummy_{index}" for index in range(7)]
    )

    def make_tensor(moment_tensor: np.ndarray):
        tensor = Tensor(
            np.asarray(moment_tensor, dtype=float),
            basis="XYZ",
            depth=float(depth_km),
            inversion_type=str(inversion_type),
            components=[],
            station_table=dummy_station_table,
            station_VR=np.empty(0, dtype=float),
            total_VR=np.nan,
            dd=np.empty(0, dtype=float),
            ss=np.empty(0, dtype=float),
        )
        tensor.decompose()
        return tensor

    tensor = make_tensor(values)

    if target_mo_dyne_cm is not None:
        target_mo_dyne_cm = float(target_mo_dyne_cm)

        if (
            not np.isfinite(target_mo_dyne_cm)
            or target_mo_dyne_cm <= 0.0
        ):
            raise ValueError(
                "target_mo_dyne_cm must be finite and positive."
            )

        if not np.isfinite(tensor.mo) or tensor.mo <= 0.0:
            raise ValueError(
                "The unscaled tensor has an invalid scalar moment."
            )

        scale = target_mo_dyne_cm / float(tensor.mo)
        tensor = make_tensor(values * scale)

    fps = list(tensor.fps or [])
    fp1 = fps[0] if len(fps) > 0 else (np.nan, np.nan, np.nan)
    fp2 = fps[1] if len(fps) > 1 else (np.nan, np.nan, np.nan)

    lune = tensor.lune
    if lune is None or len(lune) < 2:
        lune = (np.nan, np.nan)

    xyz = tensor.get_tensor_elements(basis="XYZ")

    return {
        "tensor_mw": float(tensor.mw),
        "tensor_mo_dyne_cm": float(tensor.mo),
        "dc_percent": float(tensor.pdc),
        "clvd_percent": float(tensor.pclvd),
        "iso_percent": float(tensor.piso),
        "lune_gamma_deg": float(lune[0]),
        "lune_delta_deg": float(lune[1]),
        "fp1_strike_deg": float(fp1[0]),
        "fp1_dip_deg": float(fp1[1]),
        "fp1_rake_deg": float(fp1[2]),
        "fp2_strike_deg": float(fp2[0]),
        "fp2_dip_deg": float(fp2[1]),
        "fp2_rake_deg": float(fp2[2]),
        "mxx_dyne_cm": float(xyz["MXX"]),
        "myy_dyne_cm": float(xyz["MYY"]),
        "mzz_dyne_cm": float(xyz["MZZ"]),
        "mxy_dyne_cm": float(xyz["MXY"]),
        "mxz_dyne_cm": float(xyz["MXZ"]),
        "myz_dyne_cm": float(xyz["MYZ"]),
    }


def _matched_nodal_plane_uncertainty(
    preferred_df: pd.DataFrame,
    representative: Mapping[str, Any],
) -> dict[str, float]:
    """Calculate matched-plane angular uncertainty around a representative.

    NP1 and NP2 are first matched to the representative plane ordering. Strike
    and rake differences are evaluated circularly, while dip differences are
    evaluated linearly. Reported uncertainties are half-widths of the central
    68% difference distributions.
    """
    plane_columns = [
        "fp1_strike_deg",
        "fp1_dip_deg",
        "fp1_rake_deg",
        "fp2_strike_deg",
        "fp2_dip_deg",
        "fp2_rake_deg",
    ]

    values = preferred_df.loc[:, plane_columns].to_numpy(dtype=float)
    reference = np.array(
        [float(representative[name]) for name in plane_columns],
        dtype=float,
    )

    empty = {
        "fp1_strike_unc_deg": np.nan,
        "fp1_dip_unc_deg": np.nan,
        "fp1_rake_unc_deg": np.nan,
        "fp2_strike_unc_deg": np.nan,
        "fp2_dip_unc_deg": np.nan,
        "fp2_rake_unc_deg": np.nan,
        "strike_unc_deg": np.nan,
        "dip_unc_deg": np.nan,
        "rake_unc_deg": np.nan,
    }

    if not np.isfinite(values).all() or not np.isfinite(reference).all():
        return empty

    ref1 = reference[:3]
    ref2 = reference[3:]
    matched_rows = []

    def plane_score(
        plane: np.ndarray,
        reference_plane: np.ndarray,
    ) -> float:
        strike_difference = abs(float(
            _circular_difference_deg(
                [plane[0]],
                reference_plane[0],
            )[0]
        ))
        dip_difference = abs(float(plane[1] - reference_plane[1]))
        rake_difference = abs(float(
            _circular_difference_deg(
                [plane[2]],
                reference_plane[2],
            )[0]
        ))

        return (
            strike_difference / 180.0
            + dip_difference / 90.0
            + rake_difference / 180.0
        )

    for row in values:
        plane1 = row[:3]
        plane2 = row[3:]

        direct_score = (
            plane_score(plane1, ref1)
            + plane_score(plane2, ref2)
        )
        swapped_score = (
            plane_score(plane2, ref1)
            + plane_score(plane1, ref2)
        )

        if direct_score <= swapped_score:
            matched_rows.append(row)
        else:
            matched_rows.append(np.r_[plane2, plane1])

    matched = np.asarray(matched_rows, dtype=float)

    fp1_strike_unc = _half_central_68(
        _circular_difference_deg(matched[:, 0], ref1[0])
    )
    fp1_dip_unc = _half_central_68(matched[:, 1] - ref1[1])
    fp1_rake_unc = _half_central_68(
        _circular_difference_deg(matched[:, 2], ref1[2])
    )

    fp2_strike_unc = _half_central_68(
        _circular_difference_deg(matched[:, 3], ref2[0])
    )
    fp2_dip_unc = _half_central_68(matched[:, 4] - ref2[1])
    fp2_rake_unc = _half_central_68(
        _circular_difference_deg(matched[:, 5], ref2[2])
    )

    return {
        "fp1_strike_unc_deg": fp1_strike_unc,
        "fp1_dip_unc_deg": fp1_dip_unc,
        "fp1_rake_unc_deg": fp1_rake_unc,
        "fp2_strike_unc_deg": fp2_strike_unc,
        "fp2_dip_unc_deg": fp2_dip_unc,
        "fp2_rake_unc_deg": fp2_rake_unc,
        "strike_unc_deg": float(np.nanmax([
            fp1_strike_unc,
            fp2_strike_unc,
        ])),
        "dip_unc_deg": float(np.nanmax([
            fp1_dip_unc,
            fp2_dip_unc,
        ])),
        "rake_unc_deg": float(np.nanmax([
            fp1_rake_unc,
            fp2_rake_unc,
        ])),
    }


def _build_mttime_resampling_summary(
    depth_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build four representative solutions from preferred realizations.

    Only successful preferred-depth solutions are used. The output contains the
    mean normalized tensor, tensor medoid, modal-depth tensor medoid and
    highest-VR diagnostic realization.
    """
    successful = depth_df.loc[
        depth_df["status"].eq("ok")
    ].reset_index(drop=True)

    if successful.empty:
        raise ValueError(
            "No successful preferred-depth realizations are available."
        )

    normalized = _normalized_tensor_matrices(successful)

    scalar_uncertainty = {
        "mw_unc": _half_central_68(successful["mw"]),
        "mo_unc_dyne_cm": _half_central_68(
            successful["mo_dyne_cm"]
        ),
        "depth_unc_km": _half_central_68(successful["depth_km"]),
        "vr_unc_percent": _half_central_68(
            successful["total_vr_percent"]
        ),
    }

    def actual_row(
        position: int,
        representative_type: str,
        interpretation: str,
    ) -> dict[str, Any]:
        row = successful.iloc[int(position)].to_dict()

        row.update({
            "representative_type": representative_type,
            "source_realization": int(row["realization"]),
            "vr_definition": (
                "Preferred VR of the source realization."
            ),
            "interpretation": interpretation,
        })

        return row

    representatives: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # 1. Mean normalized tensor
    # ------------------------------------------------------------------
    mean_matrix = normalized.mean(axis=0)
    resultant_length = float(np.linalg.norm(mean_matrix))

    if (
        not np.isfinite(resultant_length)
        or resultant_length <= 1e-12
    ):
        raise RuntimeError(
            "The normalized preferred tensors cancel; "
            "no stable mean mechanism exists."
        )

    mean_shape = _matrix_to_tensor6(
        mean_matrix / resultant_length
    )

    mean_mo = float(
        pd.to_numeric(
            successful["mo_dyne_cm"],
            errors="raise",
        ).mean()
    )
    mean_depth = float(
        pd.to_numeric(
            successful["depth_km"],
            errors="raise",
        ).mean()
    )
    inversion_type = str(
        successful["inversion_type"].mode().iloc[0]
    )

    mean_decomposition = _decompose_xyz_tensor(
        mean_shape,
        depth_km=mean_depth,
        inversion_type=inversion_type,
        target_mo_dyne_cm=mean_mo,
    )

    mean_row = {
        "representative_type": "mean_normalized_tensor",
        "source_realization": np.nan,
        "degree": int(
            pd.to_numeric(
                successful["degree"],
                errors="raise",
            ).mode().iloc[0]
        ),
        "inversion_type": inversion_type,
        "mw": float(
            pd.to_numeric(
                successful["mw"],
                errors="raise",
            ).mean()
        ),
        "mo_dyne_cm": mean_mo,
        "depth_km": mean_depth,
        "total_vr_percent": float(
            pd.to_numeric(
                successful["total_vr_percent"],
                errors="raise",
            ).mean()
        ),
        "vr_definition": (
            "Mean of preferred-realization VR values; this is not a "
            "direct forward-fit VR for the synthetic mean tensor."
        ),
        "tensor_resultant_length": resultant_length,
        "interpretation": (
            "Mean of unit-Frobenius moment tensors, decomposed after "
            "rescaling to the arithmetic mean scalar moment."
        ),
        **mean_decomposition,
    }

    representatives.append(mean_row)

    # ------------------------------------------------------------------
    # 2. Tensor medoid
    # ------------------------------------------------------------------
    medoid_position = _tensor_medoid_position(normalized)

    representatives.append(actual_row(
        medoid_position,
        "tensor_medoid",
        (
            "Actual realization minimizing total normalized tensor "
            "distance to the ensemble."
        ),
    ))

    # ------------------------------------------------------------------
    # 3. Modal preferred depth and tensor medoid within that depth
    # ------------------------------------------------------------------
    preferred_depths = pd.to_numeric(
        successful["depth_km"],
        errors="raise",
    )

    depth_counts = preferred_depths.value_counts().sort_index()
    maximum_count = int(depth_counts.max())

    modal_candidates = depth_counts.loc[
        depth_counts.eq(maximum_count)
    ].index.to_numpy(dtype=float)

    if len(modal_candidates) == 1:
        modal_depth = float(modal_candidates[0])
    else:
        # Deterministic tie-breaking:
        # 1. highest median preferred VR at the tied depth;
        # 2. closest to the ensemble median depth;
        # 3. shallower numeric depth.
        median_vr = {
            candidate: float(pd.to_numeric(
                successful.loc[
                    np.isclose(preferred_depths, candidate),
                    "total_vr_percent",
                ],
                errors="raise",
            ).median())
            for candidate in modal_candidates
        }

        ensemble_median_depth = float(preferred_depths.median())

        modal_depth = float(sorted(
            modal_candidates,
            key=lambda candidate: (
                -median_vr[candidate],
                abs(candidate - ensemble_median_depth),
                candidate,
            ),
        )[0])

    modal_mask = np.isclose(
        preferred_depths.to_numpy(dtype=float),
        modal_depth,
    )

    modal_subset = successful.loc[
        modal_mask
    ].reset_index(drop=True)

    modal_normalized = _normalized_tensor_matrices(modal_subset)
    modal_position = _tensor_medoid_position(modal_normalized)

    modal_source_realization = int(
        modal_subset.iloc[modal_position]["realization"]
    )

    modal_global_position = int(
        successful.index[
            successful["realization"].eq(
                modal_source_realization
            )
        ][0]
    )

    modal_row = actual_row(
        modal_global_position,
        "modal_depth_tensor_medoid",
        (
            "Central actual realization among solutions sharing the "
            "most frequent preferred depth."
        ),
    )

    modal_row.update({
        "modal_depth_km": modal_depth,
        "modal_depth_count": maximum_count,
        "modal_depth_fraction": (
            maximum_count / len(successful)
        ),
    })

    representatives.append(modal_row)

    # ------------------------------------------------------------------
    # 4. Highest preferred VR diagnostic
    # ------------------------------------------------------------------
    preferred_vr = pd.to_numeric(
        successful["total_vr_percent"],
        errors="raise",
    )

    highest_position = int(preferred_vr.idxmax())

    representatives.append(actual_row(
        highest_position,
        "highest_vr_diagnostic",
        (
            "Actual realization with the highest subset-specific VR; "
            "this is a fit diagnostic rather than an ensemble optimum."
        ),
    ))

    summary_df = pd.DataFrame(representatives)

    for name, value in scalar_uncertainty.items():
        summary_df[name] = value

    # Representative-specific mechanism dispersion.
    for index, row in summary_df.iterrows():
        representative_matrix = _tensor6_to_matrix([
            row[name]
            for name in _RESAMPLING_TENSOR_COLUMNS
        ])
        representative_matrix /= np.linalg.norm(
            representative_matrix
        )

        dot_products = np.einsum(
            "nij,ij->n",
            normalized,
            representative_matrix,
        )

        tensor_angles = np.rad2deg(np.arccos(
            np.clip(dot_products, -1.0, 1.0)
        ))

        summary_df.loc[
            index,
            "tensor_angle_median_deg",
        ] = float(np.median(tensor_angles))

        summary_df.loc[
            index,
            "tensor_angle_q84_deg",
        ] = float(np.quantile(tensor_angles, 0.84))

        summary_df.loc[
            index,
            "tensor_angle_max_deg",
        ] = float(np.max(tensor_angles))

        plane_uncertainty = _matched_nodal_plane_uncertainty(
            successful,
            row,
        )

        for name, value in plane_uncertainty.items():
            summary_df.loc[index, name] = value

    leading_columns = [
        "representative_type",
        "source_realization",
        "mw",
        "mo_dyne_cm",
        "depth_km",
        "total_vr_percent",
        "dc_percent",
        "clvd_percent",
        "iso_percent",
        "fp1_strike_deg",
        "fp1_dip_deg",
        "fp1_rake_deg",
        "fp2_strike_deg",
        "fp2_dip_deg",
        "fp2_rake_deg",
        "mw_unc",
        "mo_unc_dyne_cm",
        "depth_unc_km",
        "vr_unc_percent",
        "strike_unc_deg",
        "dip_unc_deg",
        "rake_unc_deg",
        "tensor_angle_median_deg",
        "tensor_angle_q84_deg",
        "tensor_angle_max_deg",
        "tensor_resultant_length",
        "vr_definition",
        "interpretation",
    ]

    return summary_df.reindex(columns=[
        *leading_columns,
        *[
            name
            for name in summary_df.columns
            if name not in leading_columns
        ],
    ])

def run_mttime_resampling(
    event_df: pd.DataFrame | pd.Series | Mapping[str, Any],
    station_df: pd.DataFrame,
    gf_manifest: pd.DataFrame,
    *,
    output_dir: str | Path,
    path_to_data: str | Path = "processed/data",
    path_to_green: str | Path = "greens",
    depths_km: Sequence[float] | None = None,
    components: str = "ZRT",
    degree: int = 5,
    weight: str = "variance",
    correlate: bool = False,
    reference_time_shift: float = 0.0,
    correlation_abs_max: bool = True,
    n_realizations: int = 500,
    loo_pairs: int = 1,
    opposition_tolerance_deg: float = 20.0,
    max_relative_radial_difference: float | None = None,
    min_remaining_stations: int = 6,
    max_azimuth_gap_increase_deg: float | None = None,
    base_drop_stations: Sequence[
        str | tuple[str, str, str]
    ] | None = None,
    unique_designs: bool = True,
    seed: int | None = 91,
    progress: bool = True,
    suppress_output: bool = True,
    on_error: str = "raise",
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """Run a geometry-balanced MTtime delete-d robustness ensemble.

    Each realization removes ``loo_pairs`` disjoint, approximately opposing
    station pairs and performs the complete MTtime source-depth search using
    existing observations and Green's functions.

    Only the single preferred depth from each successful realization is retained
    for ensemble inference. Nonpreferred trial-depth solutions are discarded and
    do not contribute to reported means, modal depths or uncertainties.

    The procedure is a Monte Carlo geometry-balanced delete-d analysis rather
    than a classical bootstrap with replacement.

    Parameters
    ----------
    event_df
        Event metadata accepted by :func:`write_mtinv`.

    station_df
        Complete processed-station table returned by
        :func:`process_mseed_sac`. All usable stations should remain available
        here because deletion occurs only while writing each temporary MTtime
        configuration.

    gf_manifest
        Complete Green's-function manifest returned by either
        :func:`generate_pyfk_gfs` or :func:`generate_syngine_gfs`.

    output_dir
        Event root directory. One temporary ``mtinv`` file is created for each
        realization and removed in a ``finally`` block. No per-realization
        figures, text solutions or CSV files are retained.

    path_to_data, path_to_green
        Observation and Green's-function paths supplied to
        :func:`write_mtinv`.

    depths_km
        Trial source depths. ``None`` allows :func:`write_mtinv` to infer the
        available depths from ``gf_manifest``.

    components
        Component selection accepted by :func:`write_mtinv`: ``"ZRT"``, ``"ZR"``
        or ``"Z"``; normally ``"ZRT"``.

    degree
        MTtime inversion degree. Use 5 for a deviatoric tensor or 6 for a full
        moment tensor.

    weight
        MTtime weighting option passed to :func:`write_mtinv`.

    correlate
        Whether bounded waveform timing correlation is applied around the
        selected global reference.

    reference_time_shift
        One global source/reference-time shift in seconds relative to catalog
        origin, forwarded to :func:`run_mttime_inversion` for every realization.
        Positive values select a later reference and negative values an earlier
        reference. Use :func:`mttime_inversion_oshift` when the shift itself is
        being scanned.

    correlation_abs_max
        When ``correlate=True``, select timing shifts using the absolute
        normalized correlation coefficient. It has no effect when correlation
        is disabled.

    n_realizations
        Number of station-deletion realizations.

    loo_pairs
        Number of disjoint opposing pairs deleted per realization. The number
        of deleted stations is ``2 * loo_pairs``.

    opposition_tolerance_deg
        Maximum departure from exact opposition for each pair and from ideal
        spacing among the selected pair axes.

    max_relative_radial_difference
        Optional symmetric relative epicentral-distance difference within each
        pair:

        ``abs(r_i-r_j) / ((r_i+r_j)/2)``.

        Values are fractions. For example, ``0.25`` permits 25%, ``0.50``
        permits 50%, and ``None`` disables the radial constraint.

    min_remaining_stations
        Minimum number of stations retained after fixed and
        realization-specific deletions.

    max_azimuth_gap_increase_deg
        Optional maximum permitted increase, in degrees, in the largest circular
        station-azimuth gap relative to the undeleted pairing network.

    base_drop_stations
        Stations excluded from every realization using independent waveform or
        metadata quality-control criteria.

    unique_designs
        Require each realization to omit a unique set of stations.

    seed
        Seed for deletion-design generation.

    progress
        Display a tqdm realization progress bar.

    suppress_output
        Capture MTtime console output during every inversion.

    on_error
        ``"raise"`` stops on the first failed realization. ``"record"`` stores
        the failure reason in ``depth_df`` and continues.

    Returns
    -------
    summary_df
        Exactly four representative ensemble solutions:

        ``mean_normalized_tensor``
            Mean of unit-Frobenius preferred tensors, decomposed after scaling to
            the arithmetic mean scalar moment. Its reported VR is the mean of
            realization-specific preferred VR values and is not a direct fit of
            the synthetic mean tensor.

        ``tensor_medoid``
            Actual realization minimizing total normalized tensor distance to
            all successful realizations.

        ``modal_depth_tensor_medoid``
            Actual tensor medoid among realizations sharing the most frequent
            preferred trial depth.

        ``highest_vr_diagnostic``
            Actual realization having the highest subset-specific preferred VR.
            This is retained as a fit diagnostic, not as an ensemble optimum.

        Each row includes scalar and mechanism uncertainties derived only from
        the preferred solution of every successful realization.

    depth_df
        One row per requested realization. Successful rows contain only the
        preferred depth solution, tensor components, deletion metadata and the
        exact number of stations written to that realization's ``mtinv.in``.
        Failed rows contain the failure reason.

        Nonpreferred trial-depth solutions are not retained.

    station_fit_df
        Preferred-depth station-fit table for every successful realization,
        augmented with event-centred station polar coordinates.

    pair_df
        Exact opposing-pair deletion design for each successful realization.

    Notes
    -----
    Scalar ``*_unc`` values are half-widths of the central 68% interval:

    ``0.5 * (q84 - q16)``.

    Nodal-plane uncertainties are calculated after matching NP1/NP2 to each
    representative solution. Strike and rake are treated circularly. These
    quantities can become unstable for mechanisms having a weak DC component,
    so ``tensor_angle_q84_deg`` should generally be treated as the principal
    mechanism-dispersion metric.
    """
    import uuid
    from tqdm.auto import tqdm

    n_realizations = int(n_realizations)

    if n_realizations < 1:
        raise ValueError("n_realizations must be positive.")

    if not isinstance(unique_designs, (bool, np.bool_)):
        raise TypeError("unique_designs must be a boolean.")

    if not isinstance(progress, (bool, np.bool_)):
        raise TypeError("progress must be a boolean.")

    if not isinstance(suppress_output, (bool, np.bool_)):
        raise TypeError("suppress_output must be a boolean.")

    unique_designs = bool(unique_designs)
    progress = bool(progress)
    suppress_output = bool(suppress_output)

    error_mode = str(on_error).strip().lower()

    if error_mode not in {"raise", "record"}:
        raise ValueError("on_error must be 'raise' or 'record'.")

    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    table = station_df.copy()

    if "station_id" not in table.columns:
        table["station_id"] = table.apply(
            lambda row: _station_id_from_row(row),
            axis=1,
        )

    table["station_id"] = table["station_id"].astype(str)

    base_drop = {
        _normalize_station_selector(value)
        for value in (base_drop_stations or [])
    }

    unknown_base_drop = sorted(
        base_drop.difference(table["station_id"])
    )

    if unknown_base_drop:
        raise ValueError(
            "base_drop_stations contains identifiers absent from "
            f"station_df: {unknown_base_drop}."
        )

    pairing_table = table.loc[
        ~table["station_id"].isin(base_drop)
    ].copy()

    if pairing_table.empty:
        raise ValueError(
            "No stations remain after base_drop_stations."
        )

    if loo_pairs == 0 and n_realizations > 1 and unique_designs:
        raise ValueError(
            "loo_pairs=0 has only one deletion design. Set "
            "n_realizations=1 or unique_designs=False."
        )

    rng = np.random.default_rng(seed)
    used_designs: set[tuple[str, ...]] = set()

    preferred_rows: list[dict[str, Any]] = []
    fit_tables: list[pd.DataFrame] = []
    pair_tables: list[pd.DataFrame] = []

    iterator = tqdm(
        range(n_realizations),
        desc="MTtime opposing-pair resampling",
        unit="run",
        disable=not progress,
    )

    for realization in iterator:
        mtinv_path = (
            root
            / f".mtinv_resampling_{uuid.uuid4().hex}.in"
        )

        try:
            selected_drop: list[str] | None = None
            selected_pairs: pd.DataFrame | None = None

            for _ in range(2000):
                dropped, pairs = select_opposing_station_pairs(
                    pairing_table,
                    loo_pairs=loo_pairs,
                    opposition_tolerance_deg=(
                        opposition_tolerance_deg
                    ),
                    max_relative_radial_difference=(
                        max_relative_radial_difference
                    ),
                    min_remaining_stations=(
                        min_remaining_stations
                    ),
                    max_azimuth_gap_increase_deg=(
                        max_azimuth_gap_increase_deg
                    ),
                    random_state=rng,
                )

                design_key = tuple(sorted(dropped))

                if (
                    not unique_designs
                    or design_key not in used_designs
                ):
                    selected_drop = dropped
                    selected_pairs = pairs
                    used_designs.add(design_key)
                    break

            if selected_drop is None or selected_pairs is None:
                raise RuntimeError(
                    "Could not generate another unique opposing-pair "
                    "design. Reduce n_realizations, set "
                    "unique_designs=False, or relax the pair-selection "
                    "constraints."
                )

            complete_drop = sorted(
                base_drop.union(selected_drop)
            )

            with _suppressed_console_output(suppress_output):
                (
                    mtinv_stations,
                    inversion,
                    solution_df,
                    station_fit_table,
                    _,
                ) = run_mttime_inversion(
                    event_df,
                    table,
                    gf_manifest,
                    output_file=mtinv_path,
                    path_to_data=path_to_data,
                    path_to_green=path_to_green,
                    depths_km=depths_km,
                    components=components,
                    degree=degree,
                    weight=weight,
                    plot=False,
                    correlate=correlate,
                    reference_time_shift=reference_time_shift,
                    drop_stations=complete_drop,
                    plot_views=(),
                    waveform_option="preferred",
                    show=False,
                    write_option=None,
                    save_tables=False,
                    correlation_abs_max=(
                        correlation_abs_max
                    ),
                )

            expected_station_count = int(
                len(table) - len(complete_drop)
            )
            if len(mtinv_stations) != expected_station_count:
                raise RuntimeError(
                    f"Realization {realization} wrote {len(mtinv_stations)} "
                    "stations to mtinv.in, but the deletion design expected "
                    f"{expected_station_count}."
                )

            preferred = solution_df.loc[
                solution_df["preferred"]
            ]

            if len(preferred) != 1:
                raise RuntimeError(
                    f"Realization {realization} produced "
                    f"{len(preferred)} preferred solutions."
                )

            preferred_tensor = inversion.get_preferred_tensor()

            if preferred_tensor is None:
                raise RuntimeError(
                    f"Realization {realization} has no preferred "
                    "tensor."
                )

            tensor_xyz = preferred_tensor.get_tensor_elements(
                basis="XYZ"
            )

            if len(selected_pairs):
                remaining_gap = float(
                    selected_pairs[
                        "remaining_max_azimuth_gap_deg"
                    ].iloc[0]
                )
            else:
                remaining_gap = _maximum_azimuth_gap_deg(
                    _station_polar_table(pairing_table)[
                        "r_azi"
                    ].to_numpy(dtype=float)
                )

            preferred_rows.append({
                "realization": int(realization),
                "status": "ok",
                "seed": seed,
                "loo_pairs": int(loo_pairs),
                "n_stations_total": int(len(table)),
                "n_stations_pairing_pool": int(
                    len(pairing_table)
                ),
                "n_stations_used": int(len(mtinv_stations)),
                "base_dropped_stations": "|".join(
                    sorted(base_drop)
                ),
                "resampled_dropped_stations": "|".join(
                    sorted(selected_drop)
                ),
                "dropped_stations": "|".join(
                    complete_drop
                ),
                "design_key": "|".join(
                    sorted(selected_drop)
                ),
                "remaining_max_azimuth_gap_deg": (
                    remaining_gap
                ),
                **preferred.iloc[0].to_dict(),
                "mxx_dyne_cm": float(tensor_xyz["MXX"]),
                "myy_dyne_cm": float(tensor_xyz["MYY"]),
                "mzz_dyne_cm": float(tensor_xyz["MZZ"]),
                "mxy_dyne_cm": float(tensor_xyz["MXY"]),
                "mxz_dyne_cm": float(tensor_xyz["MXZ"]),
                "myz_dyne_cm": float(tensor_xyz["MYZ"]),
            })

            preferred_fits = station_fit_table.loc[
                station_fit_table["preferred"]
            ].copy()

            polar_metadata = _station_polar_table(
                table
            ).rename(
                columns={"station_id": "station"}
            )

            preferred_fits["station"] = (
                preferred_fits["station"].astype(str)
            )

            preferred_fits = preferred_fits.merge(
                polar_metadata,
                on="station",
                how="left",
                validate="one_to_one",
            )

            preferred_fits.insert(
                0,
                "realization",
                int(realization),
            )

            fit_tables.append(preferred_fits)

            pair_table = selected_pairs.copy()

            pair_table.insert(
                0,
                "realization",
                int(realization),
            )

            pair_tables.append(pair_table)

            del inversion

        except Exception as exc:
            if error_mode == "raise":
                raise

            preferred_rows.append({
                "realization": int(realization),
                "status": "failed",
                "seed": seed,
                "loo_pairs": int(loo_pairs),
                "reason": str(exc),
            })

        finally:
            if mtinv_path.exists():
                mtinv_path.unlink()

    depth_df = pd.DataFrame(preferred_rows)

    station_fit_df = (
        pd.concat(fit_tables, ignore_index=True)
        if fit_tables
        else pd.DataFrame()
    )

    pair_df = (
        pd.concat(pair_tables, ignore_index=True)
        if pair_tables
        else pd.DataFrame()
    )

    has_successful_solution = (
        not depth_df.empty
        and "status" in depth_df.columns
        and depth_df["status"].eq("ok").any()
    )

    summary_df = (
        _build_mttime_resampling_summary(depth_df)
        if has_successful_solution
        else pd.DataFrame()
    )

    return summary_df, depth_df, station_fit_df, pair_df


def _initialize_reference_timing(
    inversion,
    timing_table: pd.DataFrame,
) -> None:
    """Install catalog-origin and global-reference timing before data loading.

    MTtime constructs :class:`mttime.Inversion` with ``streams=None`` and reads
    the observed SAC files only when :meth:`mttime.Inversion.invert` calls its
    internal data loader. Timing metadata therefore cannot be reconstructed from
    ``inversion.streams`` immediately after construction. Instead, this helper
    uses the authoritative station table returned by :func:`write_mtinv`, which
    has already validated every observed file, its SAC ``b`` value, the catalog
    origin, the selected reference time and the available inversion margins.

    The function verifies that the parsed MTtime configuration contains exactly
    the same stations, ``ts``, ``npts`` and ``dt`` values as ``timing_table``.
    It then appends explicit catalog-origin, global-reference and zero residual-
    correlation fields to ``inversion.config.station_table``. No waveform is
    read here; MTtime's normal loader remains responsible for reading each SAC
    trace once at the start of ``invert()``.

    Parameters
    ----------
    inversion
        Newly constructed :class:`mttime.Inversion` whose configuration was read
        from the ``mtinv.in`` written by :func:`write_mtinv`.
    timing_table
        DataFrame returned by :func:`write_mtinv` for the same configuration.
        Required columns are ``station``, ``origin_ts``, ``reference_ts``,
        ``reference_time_shift_samples``, ``reference_time_shift``, ``ts``,
        ``npts`` and ``dt``.
    """
    from obspy import UTCDateTime

    if not isinstance(timing_table, pd.DataFrame):
        raise TypeError("timing_table must be the DataFrame returned by write_mtinv.")
    if timing_table.empty:
        raise ValueError("timing_table is empty.")

    config_table = inversion.config.station_table
    required_timing = {
        "station",
        "origin_ts",
        "reference_ts",
        "reference_time_shift_samples",
        "reference_time_shift",
        "ts",
        "npts",
        "dt",
    }
    missing = required_timing.difference(timing_table.columns)
    if missing:
        raise KeyError(
            "timing_table is missing required reference-timing columns: "
            f"{sorted(missing)}. Use the table returned by write_mtinv."
        )
    required_config = {"station", "ts", "npts", "dt"}
    missing_config = required_config.difference(config_table.columns)
    if missing_config:
        raise KeyError(
            "MTtime's parsed station table is missing required columns: "
            f"{sorted(missing_config)}."
        )

    timing = timing_table.copy()
    timing.loc[:, "station"] = timing["station"].astype(str)
    config_stations = config_table["station"].astype(str).tolist()
    if pd.Series(config_stations).duplicated().any():
        duplicates = pd.Series(config_stations)[
            pd.Series(config_stations).duplicated(keep=False)
        ].tolist()
        raise ValueError(
            f"MTtime's parsed station table contains duplicate stations: {duplicates}."
        )
    if timing["station"].duplicated().any():
        duplicates = timing.loc[
            timing["station"].duplicated(keep=False), "station"
        ].tolist()
        raise ValueError(
            f"timing_table contains duplicate stations: {duplicates}."
        )

    timing_stations = set(timing["station"])
    config_station_set = set(config_stations)
    missing_from_timing = sorted(config_station_set.difference(timing_stations))
    extra_in_timing = sorted(timing_stations.difference(config_station_set))
    if missing_from_timing or extra_in_timing:
        raise ValueError(
            "timing_table and MTtime's parsed configuration contain different "
            f"stations; missing_from_timing={missing_from_timing}, "
            f"extra_in_timing={extra_in_timing}."
        )
    if len(timing) != len(config_stations) or int(inversion.config.nsta) != len(
        config_stations
    ):
        raise ValueError(
            "timing_table, MTtime station_table and config.nsta do not contain "
            "the same number of stations."
        )

    timing = timing.set_index("station").loc[config_stations].reset_index()
    integer_columns = (
        "origin_ts",
        "reference_ts",
        "reference_time_shift_samples",
        "ts",
        "npts",
    )
    numeric_columns = [*integer_columns, "reference_time_shift", "dt"]
    numeric = timing.loc[:, numeric_columns].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("timing_table contains non-finite timing values.")

    for column in integer_columns:
        values = numeric[column].to_numpy(dtype=float)
        rounded = np.rint(values)
        if not np.allclose(values, rounded, atol=1e-8, rtol=0.0):
            raise ValueError(f"timing_table column {column} must contain integers.")
        numeric[column] = rounded.astype(np.int64)

    origin_ts = numeric["origin_ts"].to_numpy(dtype=int)
    reference_ts = numeric["reference_ts"].to_numpy(dtype=int)
    shift_samples = numeric["reference_time_shift_samples"].to_numpy(dtype=int)
    configured_ts = numeric["ts"].to_numpy(dtype=int)
    station_npts = numeric["npts"].to_numpy(dtype=int)
    station_dt = numeric["dt"].to_numpy(dtype=float)
    reference_shift = numeric["reference_time_shift"].to_numpy(dtype=float)

    if (origin_ts < 0).any() or (reference_ts < 0).any():
        raise ValueError("origin_ts and reference_ts must be non-negative.")
    if (station_npts < 1).any() or (station_dt <= 0).any():
        raise ValueError("timing_table requires npts >= 1 and dt > 0.")
    if not np.array_equal(configured_ts, reference_ts):
        raise ValueError(
            "timing_table ts must equal reference_ts before residual correlation."
        )
    if not np.array_equal(reference_ts - origin_ts, shift_samples):
        raise ValueError(
            "reference_time_shift_samples must equal reference_ts - origin_ts."
        )

    time_tolerance = max(1e-8, 1e-8 * float(np.max(station_dt)))
    expected_shift = shift_samples * station_dt
    if not np.allclose(
        reference_shift,
        expected_shift,
        atol=time_tolerance,
        rtol=0.0,
    ):
        raise ValueError(
            "reference_time_shift is inconsistent with "
            "reference_time_shift_samples * dt."
        )
    shift_tolerance = max(
        1e-6,
        1e-8 * max(float(np.max(np.abs(reference_shift))), 1.0),
    )
    if np.ptp(reference_shift) > shift_tolerance:
        raise ValueError(
            "timing_table applies different global reference-time shifts across "
            "stations."
        )

    config_numeric = config_table.loc[:, ["ts", "npts", "dt"]].apply(
        pd.to_numeric, errors="raise"
    )
    config_ts_float = config_numeric["ts"].to_numpy(dtype=float)
    config_npts_float = config_numeric["npts"].to_numpy(dtype=float)
    config_dt = config_numeric["dt"].to_numpy(dtype=float)
    if not np.isfinite(config_numeric.to_numpy(dtype=float)).all():
        raise ValueError("MTtime's parsed station timing contains non-finite values.")
    if not np.allclose(config_ts_float, np.rint(config_ts_float), atol=1e-8, rtol=0.0):
        raise ValueError("MTtime's parsed ts values are not integers.")
    if not np.allclose(
        config_npts_float,
        np.rint(config_npts_float),
        atol=1e-8,
        rtol=0.0,
    ):
        raise ValueError("MTtime's parsed npts values are not integers.")
    config_ts = np.rint(config_ts_float).astype(int)
    config_npts = np.rint(config_npts_float).astype(int)
    if not np.array_equal(config_ts, reference_ts):
        raise ValueError(
            "MTtime's parsed ts values differ from the reference_ts values "
            "validated and written by write_mtinv."
        )
    if not np.array_equal(config_npts, station_npts):
        raise ValueError(
            "MTtime's parsed npts values differ from the values written by "
            "write_mtinv."
        )
    serialized_dt = np.asarray(
        [float(f"{value:.4f}") for value in station_dt],
        dtype=float,
    )
    if not np.allclose(config_dt, serialized_dt, atol=1e-10, rtol=0.0):
        raise ValueError(
            "MTtime's parsed dt values differ from the four-decimal values "
            "written by write_mtinv."
        )

    event = getattr(inversion.config, "event", None)
    if not isinstance(event, Mapping) or not str(event.get("datetime", "")).strip():
        raise ValueError(
            "MTtime configuration has no catalog-origin datetime; re-run write_mtinv."
        )
    catalog_origin_time = UTCDateTime(str(event["datetime"]))
    global_shift = float(np.mean(reference_shift))
    reference_time = catalog_origin_time + global_shift

    table = inversion.config.station_table
    table["origin_ts"] = np.asarray(origin_ts, dtype=np.int64)
    table["reference_ts"] = np.asarray(reference_ts, dtype=np.int64)
    table["reference_time_shift_samples"] = np.asarray(
        shift_samples, dtype=np.int64
    )
    table["reference_time_shift"] = np.asarray(reference_shift, dtype=float)
    table["correlation_time_shift_samples"] = np.zeros(
        len(table), dtype=np.int64
    )
    table["correlation_time_shift"] = np.zeros(len(table), dtype=float)
    table["total_time_shift_samples"] = np.asarray(
        shift_samples, dtype=np.int64
    )
    table["total_time_shift"] = np.asarray(reference_shift, dtype=float)
    table["time_shift_samples"] = np.zeros(len(table), dtype=np.int64)
    table["time_shift_s"] = np.zeros(len(table), dtype=float)

    inversion._origin_baseline_ts = origin_ts.copy()
    inversion._reference_baseline_ts = reference_ts.copy()
    inversion._catalog_origin_time = catalog_origin_time
    inversion._reference_time = reference_time
    inversion._reference_time_shift = global_shift
    inversion._reference_timing_table = timing.copy()


def _install_bounded_origin_correlation(inversion, *, abs_max: bool = True) -> None:
    """Install bounded residual correlation around the selected global reference.

    The function name is retained for backward compatibility with the helper's
    internal API. The actual immutable correlation baseline is now
    ``reference_ts``. ``origin_ts`` remains the catalog-origin datum used to
    report the total shift.
    """
    from types import MethodType

    if not hasattr(inversion, "_reference_baseline_ts"):
        raise RuntimeError(
            "Reference timing has not been initialized. Construct the inversion "
            "through run_mttime_inversion so the write_mtinv timing table is "
            "installed before bounded correlation."
        )

    inversion._correlation_abs_max = bool(abs_max)
    inversion._bounded_correlation_history = []
    inversion._bounded_correlation_call_count = 0
    inversion.config.station_table["correlation_score"] = np.nan
    inversion.config.station_table["correlation_basis_column"] = -1
    inversion.config.station_table["correlation_max_shift_samples"] = -1
    inversion.config.station_table["correlation_objective"] = (
        "absolute" if inversion._correlation_abs_max else "signed"
    )
    inversion._correlate = MethodType(_bounded_origin_correlate, inversion)


def _stored_correlation_margin_samples(stream, dt: float, station: str) -> int:
    """Read and validate one station's correlation margin from SAC user9."""
    margins = []
    for trace in stream:
        sac = getattr(trace.stats, "sac", None)
        value = _sac_header_value(sac, "user9", np.nan) if sac is not None else np.nan
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            seconds = np.nan
        if not np.isfinite(seconds) or seconds < 0:
            raise ValueError(
                f"Station {station} has no valid non-negative correlation margin "
                "in observation SAC header user9. Re-run process_mseed_sac."
            )
        samples_float = seconds / float(dt)
        samples = int(round(samples_float))
        if not np.isclose(samples_float, samples, atol=1e-8, rtol=0.0):
            raise ValueError(
                f"Station {station} has user9={seconds} seconds, which is not an "
                f"integer multiple of dt={dt} seconds."
            )
        margins.append(samples)

    if not margins or len(set(margins)) != 1:
        raise ValueError(
            f"Station {station} has inconsistent observation correlation margins: "
            f"{margins}."
        )
    return int(margins[0])


def _bounded_origin_correlate(self, abs_max: bool | None = None) -> None:
    """Correlate each station around its selected global reference sample."""
    if abs_max is None:
        abs_max = bool(self._correlation_abs_max)

    origin = np.asarray(self._origin_baseline_ts, dtype=int)
    reference = np.asarray(self._reference_baseline_ts, dtype=int)
    station_npts = self.config.station_table.npts.to_numpy(dtype=int)
    station_dt = self.config.station_table.dt.to_numpy(dtype=float)
    final_ts = reference.copy()
    history = []
    depth_index = int(self._bounded_correlation_call_count)
    depth = (
        float(self.config.depth[depth_index])
        if depth_index < len(self.config.depth)
        else np.nan
    )

    for index in range(self.config.nsta):
        station = str(self.config.station_table.station.iloc[index])
        npts = int(station_npts[index])
        lengths = [
            int(self.streams[index].select(component=component)[0].stats.npts)
            for component in self.config.components
        ]
        if len(set(lengths)) != 1:
            raise ValueError(
                f"Station {station} has different observed component lengths."
            )
        observed_npts = lengths[0]
        left_margin = int(reference[index])
        right_margin = observed_npts - (int(reference[index]) + npts)
        configured_margin = _stored_correlation_margin_samples(
            self.streams[index], station_dt[index], station
        )
        if configured_margin <= 0:
            raise ValueError(
                f"Station {station} has a zero correlation margin although "
                "correlate=True was requested."
            )
        if left_margin < configured_margin or right_margin < configured_margin:
            raise ValueError(
                f"Station {station} does not contain the configured +/-"
                f"{configured_margin}-sample correlation margin around the "
                f"selected reference: before={left_margin}, after={right_margin}."
            )
        positions = np.arange(
            int(reference[index]) - configured_margin,
            int(reference[index]) + configured_margin + 1,
            dtype=int,
        )

        b = self.config.index1[index]
        e = self.config.index2[index]
        best_value = -np.inf
        best_position = int(reference[index])
        best_basis = -1

        for column in range(self.config.degree):
            combined = np.zeros(positions.size, dtype=float)
            active_count = 0
            for component_index, component in enumerate(self.config.components):
                flag = int(self.config.station_table.iloc[index][component])
                if flag == 0:
                    continue
                data = np.asarray(
                    self.streams[index].select(component=component)[0].data,
                    dtype=float,
                )
                template = np.asarray(
                    self.G[b[component_index]:e[component_index], column],
                    dtype=float,
                )
                template_energy = float(np.dot(template, template))
                if template_energy <= 0 or not np.isfinite(template_energy):
                    continue
                values = np.empty(positions.size, dtype=float)
                for candidate_index, position in enumerate(positions):
                    segment = data[position:position + npts]
                    if segment.size != npts:
                        raise RuntimeError(
                            f"Station {station}: correlation candidate {position} "
                            "does not contain npts samples."
                        )
                    segment_energy = float(np.dot(segment, segment))
                    denominator = np.sqrt(segment_energy * template_energy)
                    values[candidate_index] = (
                        float(np.dot(segment, template)) / denominator
                        if denominator > 0 and np.isfinite(denominator)
                        else 0.0
                    )
                combined += values
                active_count += 1

            if active_count == 0:
                continue
            combined /= active_count
            objective = np.abs(combined) if abs_max else combined
            candidate_index = int(np.nanargmax(objective))
            candidate_value = float(objective[candidate_index])
            if candidate_value > best_value:
                best_value = candidate_value
                best_position = int(positions[candidate_index])
                best_basis = int(column)

        if not np.isfinite(best_value):
            best_value = np.nan
            best_position = int(reference[index])

        final_ts[index] = best_position
        residual_samples = best_position - int(reference[index])
        total_samples = best_position - int(origin[index])
        history.append({
            "depth_km": depth,
            "station": station,
            "origin_ts": int(origin[index]),
            "reference_ts": int(reference[index]),
            "ts": int(best_position),
            "reference_time_shift_samples": int(reference[index] - origin[index]),
            "reference_time_shift": float(
                (reference[index] - origin[index]) * station_dt[index]
            ),
            "correlation_time_shift_samples": int(residual_samples),
            "correlation_time_shift": float(residual_samples * station_dt[index]),
            "total_time_shift_samples": int(total_samples),
            "total_time_shift": float(total_samples * station_dt[index]),
            "time_shift_samples": int(residual_samples),
            "time_shift_s": float(residual_samples * station_dt[index]),
            "correlation_score": float(best_value),
            "basis_column": int(best_basis),
            "max_shift_samples": int(configured_margin),
            "correlation_objective": "absolute" if abs_max else "signed",
        })

    self.config.station_table["ts"] = np.asarray(
        final_ts, dtype=self.config.station_table["ts"].dtype
    )
    table = self.config.station_table
    table["origin_ts"] = np.asarray(origin, dtype=np.int64)
    table["reference_ts"] = np.asarray(reference, dtype=np.int64)
    table["reference_time_shift_samples"] = np.asarray(
        reference - origin, dtype=np.int64
    )
    table["reference_time_shift"] = np.asarray(
        (reference - origin) * station_dt, dtype=float
    )
    table["correlation_time_shift_samples"] = np.asarray(
        final_ts - reference, dtype=np.int64
    )
    table["correlation_time_shift"] = np.asarray(
        (final_ts - reference) * station_dt, dtype=float
    )
    table["total_time_shift_samples"] = np.asarray(
        final_ts - origin, dtype=np.int64
    )
    table["total_time_shift"] = np.asarray(
        (final_ts - origin) * station_dt, dtype=float
    )
    table["time_shift_samples"] = np.asarray(
        final_ts - reference, dtype=np.int64
    )
    table["time_shift_s"] = np.asarray(
        (final_ts - reference) * station_dt, dtype=float
    )

    score_lookup = {row["station"]: row["correlation_score"] for row in history}
    basis_lookup = {row["station"]: row["basis_column"] for row in history}
    margin_lookup = {row["station"]: row["max_shift_samples"] for row in history}
    table["correlation_score"] = table.station.map(score_lookup).to_numpy(
        dtype=float
    )
    table["correlation_basis_column"] = table.station.map(
        basis_lookup
    ).to_numpy(dtype=np.int64)
    table["correlation_max_shift_samples"] = table.station.map(
        margin_lookup
    ).to_numpy(dtype=np.int64)

    self._bounded_correlation_history.extend(history)
    self._bounded_correlation_call_count += 1

    print("Reference-centred bounded data/Green's-function correlation:")
    print(
        table[[
            "station", "origin_ts", "reference_ts", "ts",
            "reference_time_shift", "correlation_time_shift", "total_time_shift",
        ]]
    )


def _ensure_mttime_numpy_compatibility() -> None:
    """Restore NumPy scalar aliases required by the original MTtime release."""
    if not hasattr(np, "float"):
        setattr(np, "float", float)
    if not hasattr(np, "int"):
        setattr(np, "int", int)


@contextmanager
def _opaque_white_savefig(dpi: int = 300):
    """Temporarily override explicit transparent MTtime saves.

    MTtime's waveform and depth plotting functions call ``Figure.savefig`` with
    ``transparent=True`` explicitly.  Matplotlib rcParams cannot override an
    explicit keyword, so this narrow context replaces that keyword with an
    opaque white face colour and restores the original method immediately after
    plotting.
    """

    from matplotlib.figure import Figure

    original_savefig = Figure.savefig
    dpi = int(dpi)

    def savefig_opaque(self, *args, **kwargs):
        kwargs["transparent"] = False
        kwargs.setdefault("facecolor", "white")
        kwargs.setdefault("dpi", dpi)
        return original_savefig(self, *args, **kwargs)

    Figure.savefig = savefig_opaque
    try:
        yield
    finally:
        Figure.savefig = original_savefig

@contextmanager
def _working_directory(path: Path):
    """Temporarily change the process working directory and always restore it."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _resolve_output_directory(project_dir: Path, value: str | Path | None, default_name: str) -> Path:
    """Resolve an optional output directory relative to the MTtime project root."""
    if value is None:
        return project_dir / default_name
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (project_dir / path).resolve()


def _directory_state(directory: Path) -> dict[str, tuple[int, int]]:
    """Return file modification-time and size metadata for change detection."""
    return {
        path.name: (path.stat().st_mtime_ns, path.stat().st_size)
        for path in directory.iterdir()
        if path.is_file()
    }


def _changed_files(directory: Path, before: Mapping[str, tuple[int, int]]) -> list[Path]:
    """Return files created or modified since a prior directory snapshot."""
    changed = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        state = (path.stat().st_mtime_ns, path.stat().st_size)
        if path.name not in before or before[path.name] != state:
            changed.append(path)
    return sorted(changed)


def _tag_written_figure_files(
    output_manifest: pd.DataFrame,
    tag: str,
) -> pd.DataFrame:
    """Rename written figures with one wrapper-specific identifier.

    MTtime chooses fixed base filenames such as ``depth.bbmw.png``. Repeated-run
    wrappers already isolate runs in separate directories, but the filenames are
    ambiguous after files are copied or collected. This helper renames only
    successfully written figure rows and updates the returned manifest. Numerical
    outputs, configuration files and CSV tables are unchanged.
    """
    manifest = output_manifest.copy()
    tag = str(tag).strip()
    if not tag or Path(tag).name != tag or any(value in tag for value in ("/", "\\")):
        raise ValueError("Figure tag must be a non-empty filename-safe token.")
    if manifest.empty:
        return manifest
    required = {"kind", "status", "path"}
    missing = required.difference(manifest.columns)
    if missing:
        raise KeyError(
            "output_manifest is missing columns required for figure tagging: "
            f"{sorted(missing)}."
        )

    selected = manifest["kind"].astype(str).eq("figure") & manifest[
        "status"
    ].astype(str).eq("written")
    for index in manifest.index[selected]:
        source = Path(str(manifest.at[index, "path"])).expanduser()
        if not source.is_file():
            raise FileNotFoundError(
                f"Cannot tag figure because the manifest path does not exist: {source}"
            )
        destination = source.with_name(
            f"{source.stem}_{tag}{source.suffix}"
        )
        if source.resolve() != destination.resolve():
            if destination.exists():
                destination.unlink()
            source.replace(destination)
        manifest.at[index, "path"] = str(destination)
    return manifest


def _mttime_result_tables(inversion) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Convert completed MTtime tensors into depth and station-level tables.

    MTtime's configuration station table is mutable: bounded correlation updates
    ``ts`` once per trial depth, leaving the configuration in the state of the
    final depth after inversion. The helper records one immutable correlation row
    per station and trial depth while the inversion runs. When that history is
    present, this function validates it and restores the corresponding origin,
    reference, residual and total timing fields for each tensor's station table.
    This prevents all exported depths from incorrectly inheriting the timing
    solution of the last depth. Non-correlated inversions continue to use the
    timing metadata installed from the authoritative ``write_mtinv`` table.
    """
    preferred_index = int(inversion.preferred_tensor_id)
    solution_rows: list[dict[str, Any]] = []
    station_tables: list[pd.DataFrame] = []

    config_timing = inversion.config.station_table.copy()
    timing_columns = [
        "origin_ts",
        "reference_ts",
        "reference_time_shift_samples",
        "reference_time_shift",
        "correlation_time_shift_samples",
        "correlation_time_shift",
        "total_time_shift_samples",
        "total_time_shift",
        "time_shift_samples",
        "time_shift_s",
        "correlation_score",
        "correlation_basis_column",
        "correlation_max_shift_samples",
        "correlation_objective",
    ]
    timing_lookup = config_timing.set_index("station")

    correlation_history = pd.DataFrame(
        getattr(inversion, "_bounded_correlation_history", [])
    )
    if not correlation_history.empty:
        required_history = {"depth_km", "station"}
        missing_history = required_history.difference(correlation_history.columns)
        if missing_history:
            raise RuntimeError(
                "Bounded-correlation history is missing required columns: "
                f"{sorted(missing_history)}."
            )
        correlation_history = correlation_history.copy()
        correlation_history.loc[:, "station"] = correlation_history[
            "station"
        ].astype(str)

    catalog_origin_time = str(
        getattr(inversion, "_catalog_origin_time", "")
    )
    reference_time = str(getattr(inversion, "_reference_time", ""))
    reference_time_shift = float(
        getattr(inversion, "_reference_time_shift", np.nan)
    )

    for index, tensor in enumerate(inversion.moment_tensors):
        fps = list(getattr(tensor, "fps", []) or [])
        fp1 = fps[0] if len(fps) > 0 else (np.nan, np.nan, np.nan)
        fp2 = fps[1] if len(fps) > 1 else (np.nan, np.nan, np.nan)
        lune = getattr(tensor, "lune", (np.nan, np.nan))
        if lune is None or len(lune) < 2:
            lune = (np.nan, np.nan)

        try:
            tensor_xyz = tensor.get_tensor_elements(basis="XYZ")
        except Exception:
            tensor_xyz = {}

        solution_rows.append({
            "solution_index": index,
            "preferred": index == preferred_index,
            "degree": int(inversion.config.degree),
            "inversion_type": str(
                getattr(tensor, "inversion_type", inversion.config.inversion_type)
            ),
            "catalog_origin_time": catalog_origin_time,
            "reference_time": reference_time,
            "reference_time_shift": reference_time_shift,
            "depth_km": float(tensor.depth),
            "total_vr_percent": float(tensor.total_VR),
            "mw": float(getattr(tensor, "mw", np.nan)),
            "mo_dyne_cm": float(getattr(tensor, "mo", np.nan)),
            "mxx_dyne_cm": float(tensor_xyz.get("MXX", np.nan)),
            "myy_dyne_cm": float(tensor_xyz.get("MYY", np.nan)),
            "mzz_dyne_cm": float(tensor_xyz.get("MZZ", np.nan)),
            "mxy_dyne_cm": float(tensor_xyz.get("MXY", np.nan)),
            "mxz_dyne_cm": float(tensor_xyz.get("MXZ", np.nan)),
            "myz_dyne_cm": float(tensor_xyz.get("MYZ", np.nan)),
            "dc_percent": float(getattr(tensor, "pdc", np.nan)),
            "clvd_percent": float(getattr(tensor, "pclvd", np.nan)),
            "iso_percent": float(getattr(tensor, "piso", np.nan)),
            "lune_gamma_deg": float(lune[0]),
            "lune_delta_deg": float(lune[1]),
            "fp1_strike_deg": float(fp1[0]),
            "fp1_dip_deg": float(fp1[1]),
            "fp1_rake_deg": float(fp1[2]),
            "fp2_strike_deg": float(fp2[0]),
            "fp2_dip_deg": float(fp2[1]),
            "fp2_rake_deg": float(fp2[2]),
        })

        table = tensor.station_table.copy()
        if "VR" not in table.columns and hasattr(tensor, "station_VR"):
            table["VR"] = np.asarray(tensor.station_VR, dtype=float)

        table["station"] = table["station"].astype(str)
        for column in timing_columns:
            if column in table.columns:
                continue
            if column in timing_lookup.columns:
                table[column] = table["station"].map(timing_lookup[column])

        if not correlation_history.empty:
            depth_history = correlation_history.loc[
                np.isclose(
                    pd.to_numeric(
                        correlation_history["depth_km"], errors="raise"
                    ).to_numpy(dtype=float),
                    float(tensor.depth),
                    atol=1e-8,
                    rtol=0.0,
                )
            ].copy()
            if len(depth_history) != len(table):
                raise RuntimeError(
                    f"Depth {float(tensor.depth):.6f} km has "
                    f"{len(depth_history)} bounded-correlation records for "
                    f"{len(table)} stations."
                )
            if depth_history["station"].duplicated().any():
                duplicate = depth_history.loc[
                    depth_history["station"].duplicated(keep=False), "station"
                ].tolist()
                raise RuntimeError(
                    f"Depth {float(tensor.depth):.6f} km has duplicate "
                    f"bounded-correlation station records: {duplicate}."
                )
            history_lookup = depth_history.set_index("station")
            missing_stations = sorted(
                set(table["station"]).difference(history_lookup.index)
            )
            if missing_stations:
                raise RuntimeError(
                    f"Depth {float(tensor.depth):.6f} km correlation history "
                    f"is missing stations: {missing_stations}."
                )
            history_columns = {
                "origin_ts": "origin_ts",
                "reference_ts": "reference_ts",
                "ts": "ts",
                "reference_time_shift_samples": (
                    "reference_time_shift_samples"
                ),
                "reference_time_shift": "reference_time_shift",
                "correlation_time_shift_samples": (
                    "correlation_time_shift_samples"
                ),
                "correlation_time_shift": "correlation_time_shift",
                "total_time_shift_samples": "total_time_shift_samples",
                "total_time_shift": "total_time_shift",
                "time_shift_samples": "time_shift_samples",
                "time_shift_s": "time_shift_s",
                "correlation_score": "correlation_score",
                "correlation_basis_column": "basis_column",
                "correlation_max_shift_samples": "max_shift_samples",
                "correlation_objective": "correlation_objective",
            }
            integer_history_targets = {
                "origin_ts",
                "reference_ts",
                "ts",
                "reference_time_shift_samples",
                "correlation_time_shift_samples",
                "total_time_shift_samples",
                "time_shift_samples",
                "correlation_max_shift_samples",
            }
            for target, source in history_columns.items():
                if source not in history_lookup.columns:
                    raise RuntimeError(
                        "Bounded-correlation history is missing column "
                        f"{source!r} required for {target!r}."
                    )
                mapped = table["station"].map(history_lookup[source])
                if target in integer_history_targets:
                    mapped = pd.to_numeric(mapped, errors="raise").astype(np.int64)
                table[target] = mapped.to_numpy()

        # Backward-compatible residual-shift aliases.
        if "origin_ts" not in table:
            table["origin_ts"] = pd.to_numeric(table["ts"], errors="raise").astype(int)
        if "reference_ts" not in table:
            table["reference_ts"] = pd.to_numeric(table["ts"], errors="raise").astype(int)
        if "reference_time_shift_samples" not in table:
            table["reference_time_shift_samples"] = (
                pd.to_numeric(table["reference_ts"], errors="raise").astype(int)
                - pd.to_numeric(table["origin_ts"], errors="raise").astype(int)
            )
        if "reference_time_shift" not in table:
            table["reference_time_shift"] = (
                pd.to_numeric(
                    table["reference_time_shift_samples"], errors="raise"
                ).astype(float)
                * pd.to_numeric(table["dt"], errors="raise").astype(float)
            )
        if "correlation_time_shift_samples" not in table:
            table["correlation_time_shift_samples"] = (
                pd.to_numeric(table["ts"], errors="raise").astype(int)
                - pd.to_numeric(table["reference_ts"], errors="raise").astype(int)
            )
        if "correlation_time_shift" not in table:
            table["correlation_time_shift"] = (
                pd.to_numeric(
                    table["correlation_time_shift_samples"], errors="raise"
                ).astype(float)
                * pd.to_numeric(table["dt"], errors="raise").astype(float)
            )
        if "total_time_shift_samples" not in table:
            table["total_time_shift_samples"] = (
                pd.to_numeric(table["ts"], errors="raise").astype(int)
                - pd.to_numeric(table["origin_ts"], errors="raise").astype(int)
            )
        if "total_time_shift" not in table:
            table["total_time_shift"] = (
                pd.to_numeric(table["total_time_shift_samples"], errors="raise").astype(float)
                * pd.to_numeric(table["dt"], errors="raise").astype(float)
            )
        if "time_shift_samples" not in table:
            table["time_shift_samples"] = table[
                "correlation_time_shift_samples"
            ]
        if "time_shift_s" not in table:
            table["time_shift_s"] = table["correlation_time_shift"]
        if "correlation_score" not in table:
            table["correlation_score"] = np.nan
        if "correlation_basis_column" not in table:
            table["correlation_basis_column"] = -1
        if "correlation_max_shift_samples" not in table:
            table["correlation_max_shift_samples"] = 0
        if "correlation_objective" not in table:
            table["correlation_objective"] = "disabled"

        table.insert(0, "reference_time", reference_time)
        table.insert(0, "catalog_origin_time", catalog_origin_time)
        table.insert(0, "preferred", index == preferred_index)
        table.insert(0, "depth_km", float(tensor.depth))
        station_tables.append(table)

    solution_df = pd.DataFrame(solution_rows).sort_values(
        "depth_km", ignore_index=True
    )
    station_fit_df = (
        pd.concat(station_tables, ignore_index=True)
        if station_tables else pd.DataFrame()
    )
    return solution_df, station_fit_df


def _default_pre_filt(
    trace, analysis_freqmin: float
) -> tuple[float, float, float, float]:
    """Construct a response-removal pre-filter below the analysis passband.

    The second low corner must lie below ``analysis_freqmin``; otherwise ObsPy's
    cosine pre-filter attenuates frequencies that the subsequent inversion
    bandpass intends to retain. Version 0.1.7 used 0.05 Hz as the second low
    corner for ordinary seismometers, which overlapped a 0.02--0.05 Hz inversion
    band. Version 0.1.8 constrained that corner to at most half the analysis lower
    frequency. The same conservative low-frequency pre-filter is used for all
    supported channel families; the analysis bandpass remains the controlling
    filter for the inversion.
    """
    nyquist = 0.5 / float(trace.stats.delta)
    analysis_freqmin = float(analysis_freqmin)
    if not np.isfinite(analysis_freqmin) or analysis_freqmin <= 0:
        raise ValueError("analysis_freqmin must be finite and positive.")

    nominal_low_1, nominal_low_2 = 0.004,0.007
    low_2 = min(nominal_low_2, 0.5 * analysis_freqmin)
    low_1 = min(nominal_low_1, 0.5 * low_2)
    high_1 = 0.90 * nyquist
    high_2 = nyquist

    if low_2 >= high_1:
        low_2 = 0.10 * high_1
        low_1 = 0.20 * low_2
    if not (0 < low_1 < low_2 < high_1 < high_2):
        raise ValueError(
            "Could not construct a valid response-removal pre-filter for "
            f"channel {trace.stats.channel}: "
            f"{(low_1, low_2, high_1, high_2)}."
        )
    return float(low_1), float(low_2), float(high_1), float(high_2)


def _raw_inputs_match_request(
    waveform_path: Path,
    stationxml_path: Path,
    *,
    network: str,
    station: str,
    location: str,
    channel_prefix: str,
    selected_channels: Sequence[str] | str | None,
    request_start,
    request_end,
    response_time,
    expected_ground_level: bool,
    expected_channel_depth_m: float,
    expected_station_lat: float,
    expected_station_lon: float,
    expected_station_elevation_m: float,
    read,
    read_inventory,
) -> tuple[bool, str]:
    """Check whether an existing raw miniSEED/StationXML pair is reusable.

    Validation is performed on one explicit three-component set rather than on
    every channel sharing the two-character prefix. This prevents a station that
    exposes both ``ZNE`` and ``Z12`` (or multiple orientation epochs) from
    producing duplicate components during rotation.
    """
    try:
        stream = read(str(waveform_path), format="MSEED")
        stream = stream.select(
            network=network, station=station, location=location,
            channel=f"{channel_prefix}?",
        )
        if len(stream) == 0:
            return False, "no matching traces in existing miniSEED"

        requested = _parse_channel_codes(selected_channels)
        if not requested:
            _, requested = _component_selection_from_codes(
                [trace.stats.channel for trace in stream]
            )
        selected = stream.__class__()
        for channel in requested:
            traces = stream.select(channel=channel)
            if len(traces) == 0:
                return False, f"missing selected channel {channel}"
            selected += traces

        gaps = [gap for gap in selected.get_gaps() if gap[-1] > 0]
        if gaps:
            return False, f"internal gaps in existing miniSEED: {gaps}"
        selected.merge(method=0)
        if len(selected) != 3:
            return False, (
                "selected channel set does not reduce to exactly three traces: "
                f"{[trace.id for trace in selected]}"
            )
        common_start = max(trace.stats.starttime for trace in selected)
        common_end = min(trace.stats.endtime for trace in selected)
        max_delta = max(float(trace.stats.delta) for trace in selected)
        tolerance = max_delta + 1e-6

        if common_start > request_start + tolerance:
            return False, "existing miniSEED begins after requested start"
        if common_end < request_end - tolerance:
            return False, "existing miniSEED ends before requested end"

        inventory = read_inventory(str(stationxml_path), format="STATIONXML")
        depths = []
        latitudes = []
        longitudes = []
        elevations = []
        for trace in selected:
            inventory.get_response(trace.id, response_time)
            metadata = inventory.get_channel_metadata(trace.id, response_time)
            if not np.isfinite(float(metadata["azimuth"])) or not np.isfinite(
                float(metadata["dip"])
            ):
                return False, f"non-finite orientation metadata for {trace.id}"
            depth = float(metadata.get("local_depth", np.nan))
            latitude = float(metadata.get("latitude", np.nan))
            longitude = float(metadata.get("longitude", np.nan))
            elevation = float(metadata.get("elevation", np.nan))
            if not np.isfinite(depth):
                return False, f"non-finite StationXML channel depth for {trace.id}"
            if not np.isfinite([latitude, longitude, elevation]).all():
                return False, f"non-finite StationXML sensor geometry for {trace.id}"
            depths.append(depth)
            latitudes.append(latitude)
            longitudes.append(longitude)
            elevations.append(elevation)

        if not np.allclose(
            depths, depths[0], atol=_GROUND_LEVEL_DEPTH_ATOL_M, rtol=0.0
        ):
            return False, f"selected channels have inconsistent sensor depths: {depths}"
        if expected_ground_level and not np.allclose(
            depths, 0.0, atol=_GROUND_LEVEL_DEPTH_ATOL_M, rtol=0.0
        ):
            return False, f"selected channels are not at ground level: depths={depths} m"
        if not np.isclose(
            float(np.mean(depths)),
            float(expected_channel_depth_m),
            atol=_GROUND_LEVEL_DEPTH_ATOL_M,
            rtol=0.0,
        ):
            return False, "StationXML sensor depth differs from discovery metadata"

        geometry = (
            (
                latitudes, expected_station_lat,
                _CHANNEL_COORDINATE_ATOL_DEG, "latitude",
            ),
            (
                longitudes, expected_station_lon,
                _CHANNEL_COORDINATE_ATOL_DEG, "longitude",
            ),
            (
                elevations, expected_station_elevation_m,
                _CHANNEL_ELEVATION_ATOL_M, "elevation",
            ),
        )
        for values, expected, atol, name in geometry:
            if not np.allclose(values, values[0], atol=atol, rtol=0.0):
                return False, (
                    f"selected channels have inconsistent sensor {name}: {values}"
                )
            if not np.isclose(
                float(np.mean(values)), float(expected), atol=atol, rtol=0.0
            ):
                return False, (
                    f"StationXML sensor {name} differs from discovery metadata"
                )

        return True, (
            "existing raw inputs cover the request, contain responses and match "
            "the sensor-depth policy"
        )
    except Exception as exc:
        return False, f"existing raw-input validation failed: {exc}"


def _normalize_phase(value: str, name: str) -> str:
    """Normalize and validate an origin/P/S phase-anchor name."""
    phase = str(value).strip().upper()
    if phase not in {"ORIGIN", "P", "S"}:
        raise ValueError(f"{name} must be 'origin', 'P' or 'S'.")
    return phase


def _validate_window_parameters(
    *,
    time_before_window_start: float,
    time_after_window_end: float,
    inversion_duration: float | None,
    max_correlation_shift: float,
    max_reference_time_shift: float,
    freqmax: float,
    dt: float,
    reduction_velocity_km_s: float,
    phases,
) -> None:
    """Validate observation-storage, inversion and correlation settings.

    Public durations are expressed in seconds. Correlation shift and a finite
    inversion duration must map exactly to the final sample interval ``dt``.
    ``inversion_duration`` is interpreted as ``npts * dt`` so that 150 s at
    ``dt=1`` gives 150 samples with the last sample at 149 s, matching the
    official MTtime tutorial convention.
    """
    values = {
        "time_before_window_start": float(time_before_window_start),
        "time_after_window_end": float(time_after_window_end),
        "max_correlation_shift": float(max_correlation_shift),
        "max_reference_time_shift": float(max_reference_time_shift),
    }
    if inversion_duration is not None:
        values["inversion_duration"] = float(inversion_duration)

    non_finite = [name for name, value in values.items() if not np.isfinite(value)]
    if non_finite:
        raise ValueError(f"Time-window settings must be finite: {non_finite}.")
    negative = [
        name for name, value in values.items()
        if value < 0 or (name == "inversion_duration" and value == 0)
    ]
    if negative:
        raise ValueError(
            "Time-window settings must be non-negative and "
            f"inversion_duration must be positive: {negative}."
        )

    dt = float(dt)
    freqmax = float(freqmax)
    shift_samples = float(max_correlation_shift) / dt
    nearest_shift = round(shift_samples)
    if not np.isclose(shift_samples, nearest_shift, atol=1e-8, rtol=1e-12):
        raise ValueError(
            "max_correlation_shift must be an integer multiple of dt so the "
            "reference-centred search bounds are exact sample indices."
        )

    reference_samples = float(max_reference_time_shift) / dt
    nearest_reference = round(reference_samples)
    if not np.isclose(
        reference_samples, nearest_reference, atol=1e-8, rtol=1e-12
    ):
        raise ValueError(
            "max_reference_time_shift must be an integer multiple of dt so all "
            "allowed global references lie on the processed sample grid."
        )
    if float(max_correlation_shift) > 0:
        half_shortest_period = 0.5 / freqmax
        if float(max_correlation_shift) >= half_shortest_period - 1e-10:
            raise ValueError(
                "max_correlation_shift must be shorter than half the shortest "
                "retained period (0.5 / freqmax) to limit cycle ambiguity."
            )

    if inversion_duration is not None:
        duration_samples = float(inversion_duration) / dt
        nearest_duration = round(duration_samples)
        if not np.isclose(duration_samples, nearest_duration, atol=1e-8, rtol=1e-12):
            raise ValueError(
                "inversion_duration must be an integer multiple of dt because "
                "MTtime uses an integer number of samples."
            )
        if nearest_duration < 1:
            raise ValueError("inversion_duration must contain at least one sample.")

    if float(reduction_velocity_km_s) < 0:
        raise ValueError("reduction_velocity_km_s cannot be negative.")
    phases = tuple(phases)
    if float(reduction_velocity_km_s) != 0.0 and "ORIGIN" not in phases:
        raise ValueError(
            "reduction_velocity_km_s is only meaningful when at least one "
            "stored-window phase anchor is 'origin'."
        )


def _phase_offset(
    row: Mapping[str, Any],
    phase: str,
    reduction_velocity_km_s: float,
) -> float:
    """Return one station-specific phase-anchor offset from event origin.

    P and S offsets are read from ``p_arrival_s`` and ``s_arrival_s``. An
    ``ORIGIN`` anchor is zero unless a positive reduction velocity is supplied,
    in which case the offset is ``distance / velocity``.
    """
    if phase == "P":
        value = float(row["p_arrival_s"])
    elif phase == "S":
        value = float(row["s_arrival_s"])
    else:
        distance = row.get("distance_km", row.get("distance"))
        if distance is None:
            raise KeyError("An ORIGIN anchor requires distance_km or distance.")
        value = (
            0.0
            if float(reduction_velocity_km_s) == 0.0
            else float(distance) / float(reduction_velocity_km_s)
        )
    if not np.isfinite(value):
        raise ValueError(f"The {phase} phase-anchor offset is not finite.")
    return float(value)



def _floor_sample_count(value: float) -> int:
    """Floor a sample count while preserving values numerically equal to integers."""
    value = float(value)
    nearest = round(value)
    if np.isclose(value, nearest, atol=1e-8, rtol=1e-12):
        return int(nearest)
    return int(np.floor(value))


def _ceil_sample_count(value: float) -> int:
    """Ceil a sample index while preserving values numerically equal to integers."""
    value = float(value)
    nearest = round(value)
    if np.isclose(value, nearest, atol=1e-8, rtol=1e-12):
        return int(nearest)
    return int(np.ceil(value))


def _station_window_geometry(
    row: Mapping[str, Any],
    *,
    dt: float,
    window_start_phase: str,
    time_before_window_start: float,
    window_end_phase: str,
    time_after_window_end: float,
    inversion_duration: float | None,
    max_correlation_shift: float,
    max_reference_time_shift: float,
    reduction_velocity_km_s: float,
) -> dict[str, Any]:
    """Derive stored-record geometry around the immutable catalog origin.

    The stored record is expanded to support every global reference within
    ``+/-max_reference_time_shift`` and, around each such reference, every
    residual station shift within ``+/-max_correlation_shift``. The processed
    baseline remains catalog-origin aligned; selecting a nonzero reference later
    changes only the MTtime ``ts`` value.

    ``inversion_duration`` is interpreted as ``npts * dt``. For example, 150
    seconds at ``dt=1`` gives 150 samples from 0 through 149 seconds relative to
    whichever global reference is selected by :func:`write_mtinv`.
    """
    dt = float(dt)
    start_anchor = _phase_offset(
        row, window_start_phase, reduction_velocity_km_s
    )
    end_anchor = _phase_offset(
        row, window_end_phase, reduction_velocity_km_s
    )
    requested_start = start_anchor - float(time_before_window_start)
    requested_end = end_anchor + float(time_after_window_end)
    tolerance = max(
        1e-9,
        1e-9 * max(abs(requested_start), abs(requested_end), 1.0),
    )
    if requested_end <= requested_start + tolerance:
        raise ValueError("The requested window end must be later than its start.")

    requested_start_index = _ceil_sample_count(requested_start / dt)
    requested_end_index = _floor_sample_count(requested_end / dt)
    correlation_shift_samples = int(
        round(float(max_correlation_shift) / dt)
    )
    reference_shift_samples = int(
        round(float(max_reference_time_shift) / dt)
    )
    reserved_margin_samples = (
        reference_shift_samples + correlation_shift_samples
    )

    if inversion_duration is None:
        start_index = min(requested_start_index, -reserved_margin_samples)
        end_index = requested_end_index
        if end_index < reserved_margin_samples:
            end_index = reserved_margin_samples
        inversion_end_index = end_index - reserved_margin_samples
        npts = inversion_end_index + 1
    else:
        npts = int(round(float(inversion_duration) / dt))
        inversion_end_index = npts - 1
        required_end_index = inversion_end_index + reserved_margin_samples
        start_index = min(requested_start_index, -reserved_margin_samples)
        end_index = max(requested_end_index, required_end_index)

    if end_index < start_index:
        raise ValueError("The effective waveform window contains no samples.")
    if npts < 1:
        raise ValueError("The origin-aligned inversion has fewer than one sample.")

    window_start = start_index * dt
    window_end = end_index * dt
    origin_ts = -start_index
    stored_npts = end_index - start_index + 1
    post_inversion_samples = stored_npts - (origin_ts + npts)
    if post_inversion_samples < reserved_margin_samples:
        raise RuntimeError(
            "Internal timing error: trailing reference/correlation margin is "
            "inconsistent."
        )
    if origin_ts < reserved_margin_samples:
        raise RuntimeError(
            "Internal timing error: leading reference/correlation margin is "
            "inconsistent."
        )

    return {
        "requested_window_start_offset_s": float(requested_start),
        "requested_window_end_offset_s": float(requested_end),
        "window_start_offset_s": float(window_start),
        "window_end_offset_s": float(window_end),
        "window_start_rounding_s": float(window_start - requested_start),
        "window_end_rounding_s": float(requested_end - window_end),
        "window_start_auto_extension_s": float(max(0.0, requested_start - window_start)),
        "window_end_auto_extension_s": float(max(0.0, window_end - requested_end)),
        "window_span_s": float(window_end - window_start),
        "origin_offset_s": 0.0,
        "origin_ts": int(origin_ts),
        "inversion_start_offset_s": 0.0,
        "inversion_end_offset_s": float(inversion_end_index * dt),
        "inversion_duration_s": float(npts * dt),
        "inversion_span_s": float((npts - 1) * dt),
        "correlation_max_shift_s": float(correlation_shift_samples * dt),
        "correlation_max_shift_samples": int(correlation_shift_samples),
        "max_reference_time_shift": float(reference_shift_samples * dt),
        "max_reference_time_shift_samples": int(reference_shift_samples),
        "reserved_timing_margin": float(reserved_margin_samples * dt),
        "reserved_timing_margin_samples": int(reserved_margin_samples),
        "reference_time_shift": 0.0,
        "reference_time_shift_samples": 0,
        "reference_ts": int(origin_ts),
        "pre_origin_samples": int(origin_ts),
        "post_inversion_samples": int(post_inversion_samples),
        "ts": int(origin_ts),
        "stored_npts": int(stored_npts),
        "npts": int(npts),
    }


def _file_fingerprint(path: Path) -> dict[str, Any]:
    """Return a lightweight fingerprint that changes when a source file changes."""
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _jsonable(value):
    """Convert common NumPy/path values into deterministic JSON-compatible data."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float):
        if np.isnan(value):
            return "NaN"
        if np.isposinf(value):
            return "Infinity"
        if np.isneginf(value):
            return "-Infinity"
    return value


def _short_signature(payload: Mapping[str, Any], length: int = 16) -> str:
    """Return an uppercase deterministic hexadecimal signature."""
    canonical = json.dumps(
        _jsonable(payload), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:length].upper()


def _observation_processing_signature(
    *,
    event: Mapping[str, Any],
    row: Mapping[str, Any],
    waveform_path: Path,
    stationxml_path: Path,
    motion: str,
    water_level,
    freqmin,
    freqmax,
    corners,
    dt,
    window_settings: Mapping[str, Any],
    geometry: Mapping[str, Any],
    obspy_version: str,
) -> str:
    """Build the signature stored in each processed observation SAC file."""
    payload = {
        "schema": "mttime-observation-v5",
        "mttime_helpers_version": _OBSERVATION_CACHE_COMPAT_VERSION,
        "obspy_version": obspy_version,
        "event": {
            key: event[key]
            for key in (
                "event_id", "origin_time", "event_lon", "event_lat",
                "event_depth_km",
            )
        },
        "station": {
            key: row.get(key)
            for key in (
                "station_id", "network", "station", "location",
                "channel_prefix", "component_scheme", "selected_channels",
                "station_lat", "station_lon",
                "station_elevation_m", "channel_depth_m", "ground_level",
                "distance_km", "azimuth_deg", "back_azimuth_deg",
                "p_arrival_s", "s_arrival_s",
            )
        },
        "source_files": {
            "waveform": _file_fingerprint(waveform_path),
            "stationxml": _file_fingerprint(stationxml_path),
        },
        "processing": {
            "motion": motion,
            "water_level": water_level,
            "prefilter": "analysis-passband-v2",
            "freqmin": float(freqmin),
            "freqmax": float(freqmax),
            "corners": int(corners),
            "dt": float(dt),
            "window_settings": dict(window_settings),
            "geometry": dict(geometry),
            "rotation": "explicit-triplet:StationXML->ZNE;ObsPy-baz->RT",
            "output_scale": "SI_to_centimetre",
        },
    }
    return _short_signature(payload)

def _set_sac_signature(trace, tag: str, signature: str) -> None:
    """Store a 16-hex-character signature across SAC string headers."""
    if not hasattr(trace.stats, "sac") or trace.stats.sac is None:
        trace.stats.sac = {}
    values = {
        "kuser0": str(tag)[:8],
        "kuser1": str(signature)[:8],
        "kuser2": str(signature)[8:16],
    }
    sac = trace.stats.sac
    for key, value in values.items():
        try:
            setattr(sac, key, value)
        except (AttributeError, TypeError):
            sac[key] = value


def _sac_header_value(sac, key: str, default=""):
    """Read a SAC header from either an AttribDict-like object or a mapping."""
    if isinstance(sac, Mapping):
        return sac.get(key, default)
    return getattr(sac, key, default)


def _sac_text(value) -> str:
    """Normalize a SAC string header returned as bytes, str or None."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="ignore")
    return str(value).strip().replace("\x00", "")


def _get_sac_signature(trace, expected_tag: str) -> str | None:
    """Read a signature previously written by :func:`_set_sac_signature`."""
    sac = getattr(trace.stats, "sac", None)
    if sac is None:
        return None
    tag = _sac_text(_sac_header_value(sac, "kuser0", ""))
    if tag != str(expected_tag)[:8]:
        return None
    first = _sac_text(_sac_header_value(sac, "kuser1", ""))
    second = _sac_text(_sac_header_value(sac, "kuser2", ""))
    value = (first + second).upper()
    return value if len(value) == 16 else None


def _load_cached_observed_triplet(
    *,
    data_paths: Mapping[str, Path],
    signature: str,
    station_id: str,
    row: Mapping[str, Any],
    expected_start,
    expected_npts: int,
    expected_dt: float,
    output_units: str,
    read,
    Stream,
):
    """Load an existing ZRT triplet when every cache check succeeds."""
    missing = [component for component, path in data_paths.items() if not path.exists()]
    if missing:
        return None, f"missing processed components: {missing}"

    cached = Stream()
    for component in "ZRT":
        path = data_paths[component]
        try:
            stream = read(str(path), format="SAC")
            if len(stream) != 1:
                return None, f"{path.name} contains {len(stream)} traces"
            trace = stream[0]
            if _get_sac_signature(trace, "MTHOBS") != signature:
                return None, f"processing signature differs for {path.name}"
            if trace.stats.npts != int(expected_npts):
                return None, f"npts differs for {path.name}"
            if not _sample_interval_matches(trace.stats.delta, expected_dt):
                return None, f"dt differs for {path.name}"
            if abs(trace.stats.starttime - expected_start) > max(1e-3, 0.01 * expected_dt):
                return None, f"start time differs for {path.name}"
            if not np.isfinite(trace.data).all():
                return None, f"non-finite data in {path.name}"

            trace.stats.network = str(row["network"])
            trace.stats.station = str(row["station"])
            trace.stats.location = str(row.get("location", ""))
            trace.stats.channel = f"MT{component}"
            trace.stats.units = output_units
            cached += trace
        except Exception as exc:
            return None, f"cannot validate {path.name}: {exc}"
    return cached, "all ZRT files match the current processing signature"


def _write_observed_triplet(
    candidate,
    *,
    data_paths: Mapping[str, Path],
    signature: str,
    expected_start,
    expected_npts: int,
    expected_dt: float,
    station_id: str,
    row: Mapping[str, Any],
    output_units: str,
    read,
    Stream,
):
    """Write and verify a complete ZRT triplet before replacing final files."""
    temporary_paths: dict[str, Path] = {}
    try:
        for component in "ZRT":
            selected = candidate.select(component=component)
            if len(selected) != 1:
                raise ValueError(
                    f"Expected one candidate {component} trace for {station_id}; "
                    f"found {len(selected)}."
                )
            final_path = data_paths[component]
            temporary = final_path.with_name(final_path.name + ".tmp")
            if temporary.exists():
                temporary.unlink()
            selected[0].write(str(temporary), format="SAC")
            temporary_paths[component] = temporary

        temp_stream, reason = _load_cached_observed_triplet(
            data_paths=temporary_paths,
            signature=signature,
            station_id=station_id,
            row=row,
            expected_start=expected_start,
            expected_npts=expected_npts,
            expected_dt=expected_dt,
            output_units=output_units,
            read=read,
            Stream=Stream,
        )
        if temp_stream is None:
            raise ValueError(f"Temporary SAC validation failed: {reason}")

        for component in "ZRT":
            temporary_paths[component].replace(data_paths[component])

        final_stream, reason = _load_cached_observed_triplet(
            data_paths=data_paths,
            signature=signature,
            station_id=station_id,
            row=row,
            expected_start=expected_start,
            expected_npts=expected_npts,
            expected_dt=expected_dt,
            output_units=output_units,
            read=read,
            Stream=Stream,
        )
        if final_stream is None:
            raise ValueError(f"Final SAC validation failed: {reason}")
        return final_stream
    finally:
        for temporary in temporary_paths.values():
            if temporary.exists():
                temporary.unlink()


def _processed_station_record(
    row: Mapping[str, Any],
    *,
    station_id: str,
    distance_km: float,
    window_settings: Mapping[str, Any],
    geometry: Mapping[str, Any],
    dt: float,
    used,
    motion: str,
    output_units: str,
    freqmin: float,
    freqmax: float,
    corners: int,
    data_dir: Path,
    status: str,
    signature: str,
    origin,
) -> dict[str, Any]:
    """Build the authoritative station record shared by all downstream stages."""
    window_starttime = origin + float(geometry["window_start_offset_s"])
    window_endtime = origin + float(geometry["window_end_offset_s"])
    return {
        **row,
        "station_id": station_id,
        "distance": float(distance_km),
        "azimuth": float(row["azimuth_deg"]) % 360.0,
        "longitude": float(row["station_lon"]),
        "latitude": float(row["station_lat"]),
        "r_epi": float(row.get("r_epi", distance_km)),
        "r_azi": float(
            row.get("r_azi", np.deg2rad(float(row["azimuth_deg"]) % 360.0))
        ) % (2.0 * np.pi),
        **dict(window_settings),
        **dict(geometry),
        "window_starttime": str(window_starttime),
        "window_endtime": str(window_endtime),
        "ts": int(geometry["origin_ts"]),
        "reference_ts": int(geometry["origin_ts"]),
        "reference_time_shift": 0.0,
        "reference_time_shift_samples": 0,
        "npts": int(geometry["npts"]),
        "dt": float(dt),
        "used": str(used),
        "motion": motion,
        "units": output_units,
        "freqmin": float(freqmin),
        "freqmax": float(freqmax),
        "corners": int(corners),
        "data_Z": str(data_dir / f"{station_id}.Z.dat"),
        "data_R": str(data_dir / f"{station_id}.R.dat"),
        "data_T": str(data_dir / f"{station_id}.T.dat"),
        "processing_status": status,
        "processing_signature": signature,
    }


def _model_array_hash(model_array: np.ndarray) -> str:
    """Hash a layered model using a stable little-endian float64 representation."""
    array = np.ascontiguousarray(np.asarray(model_array, dtype="<f8"))
    return hashlib.sha256(array.tobytes()).hexdigest()


def _gf_processing_signature(
    *,
    station_id: str,
    distance_km: float,
    gf_start_offset_s: float,
    requested_depth: float,
    actual_depth: float,
    model_array: np.ndarray,
    settings: Mapping[str, Any],
    pyfk_dt: float,
    pyfk_npt: int,
    samples_before_first_arrival: int,
    config_kwargs: Mapping[str, Any],
    pyfk_flattening: bool,
    pyfk_version: str,
    gf_helpers_version: str,
    batch_mode: str = "station",
    receiver_distance_batch: Sequence[float] | None = None,
) -> str:
    """Build the signature stored in every Herrmann Green's-function file."""
    payload = {
        "schema": "mttime-pyfk-gf-v9-seismodel-flattening",
        "mttime_helpers_version": _PYFK_CACHE_COMPAT_VERSION,
        "station_id": station_id,
        "distance_km": float(distance_km),
        "batch_mode": str(batch_mode),
        "receiver_distance_batch_km": (
            None
            if receiver_distance_batch is None
            else np.asarray(receiver_distance_batch, dtype=float).tolist()
        ),
        "gf_start_offset_s": float(gf_start_offset_s),
        "requested_depth_km": float(requested_depth),
        "actual_depth_km": float(actual_depth),
        "model_sha256": _model_array_hash(model_array),
        "settings": settings,
        "pyfk": {
            "version": pyfk_version,
            "dt": float(pyfk_dt),
            "npt": int(pyfk_npt),
            "samples_before_first_arrival": int(samples_before_first_arrival),
            "flattening": bool(pyfk_flattening),
            "config_kwargs": config_kwargs,
        },
        "gf_helpers_version": gf_helpers_version,
    }
    return _short_signature(payload)



def _tag_stream_signature(stream, tag: str, signature: str) -> None:
    """Attach one SAC cache signature to every trace in a stream."""
    for trace in stream:
        _set_sac_signature(trace, tag, signature)


def _load_cached_gf_records(
    *,
    output_paths: Mapping[str, Path],
    signature: str,
    station_id: str,
    requested_depth: float,
    expected_npts: int,
    expected_dt: float,
    read,
    bases: Sequence[str] = _HERRMANN_BASES,
    expected_start_offset_s: float | None = None,
):
    """Validate one complete Green's-function set and return manifest records."""
    bases = tuple(str(basis) for basis in bases)
    missing = [basis for basis, path in output_paths.items() if not path.exists()]
    if missing:
        return None, f"missing Green's-function bases: {missing}"

    records = []
    for basis in bases:
        path = output_paths[basis]
        try:
            stream = read(str(path), format="SAC")
            if len(stream) != 1:
                return None, f"{path.name} contains {len(stream)} traces"
            trace = stream[0]
            if _get_sac_signature(trace, "MTHGF") != signature:
                return None, f"processing signature differs for {path.name}"
            if trace.stats.npts != int(expected_npts):
                return None, f"npts differs for {path.name}"
            if not _sample_interval_matches(trace.stats.delta, expected_dt):
                return None, f"dt differs for {path.name}"
            if expected_start_offset_s is not None:
                expected_start = float(expected_start_offset_s)
                tolerance = max(1e-3, 0.01 * float(expected_dt))
                sac = getattr(trace.stats, "sac", None)
                b = float(_sac_header_value(sac, "b", np.nan))
                start_offset = float(trace.stats.starttime.timestamp)
                if (
                    not np.isfinite([b, start_offset]).all()
                    or not np.isclose(b, expected_start, atol=tolerance, rtol=0.0)
                    or not np.isclose(
                        start_offset, expected_start, atol=tolerance, rtol=0.0
                    )
                ):
                    return None, f"source-reference start differs for {path.name}"
            if not np.isfinite(trace.data).all():
                return None, f"non-finite data in {path.name}"
            records.append({
                "station": station_id,
                "source_depth_km": float(requested_depth),
                "basis": basis,
                "path": str(path),
                "npts": int(trace.stats.npts),
                "dt_s": float(trace.stats.delta),
            })
        except Exception as exc:
            return None, f"cannot validate {path.name}: {exc}"
    return records, f"all {len(bases)} Green's-function files match the current GF signature"


def _validate_written_gf_set(
    *,
    output_paths: Mapping[str, Path],
    signature: str,
    expected_npts: int,
    expected_dt: float,
    read,
    bases: Sequence[str] = _HERRMANN_BASES,
    expected_start_offset_s: float | None = None,
) -> None:
    """Read back a newly written GF set and fail on any inconsistency."""
    records, reason = _load_cached_gf_records(
        output_paths=output_paths,
        signature=signature,
        station_id="validation",
        requested_depth=0.0,
        expected_npts=expected_npts,
        expected_dt=expected_dt,
        read=read,
        bases=bases,
        expected_start_offset_s=expected_start_offset_s,
    )
    if records is None:
        raise ValueError(f"Written Green's functions failed validation: {reason}")


def _parse_channel_codes(value: Sequence[str] | str | None) -> tuple[str, ...]:
    """Normalize a channel-code sequence or comma-separated string."""
    if value is None:
        return ()
    if isinstance(value, str):
        values = value.split(",")
    else:
        values = value
    return tuple(sorted({str(item).strip() for item in values if str(item).strip()}))


def _component_selection_from_codes(
    channel_codes: Sequence[str],
) -> tuple[str, tuple[str, str, str]]:
    """Choose one complete orientation family from channel codes.

    Preference is ``ZNE`` followed by ``Z12`` and then fully arbitrary ``123``.
    The latter two are rotated from StationXML azimuth/dip metadata. Channel
    names such as ``HNZ/HN1/HN2`` are therefore handled as the ``Z12`` scheme.
    """
    codes = _parse_channel_codes(channel_codes)
    by_suffix: dict[str, list[str]] = {}
    for code in codes:
        if not code:
            continue
        by_suffix.setdefault(code[-1].upper(), []).append(code)
    for scheme in _COMPONENT_SCHEMES:
        if all(suffix in by_suffix for suffix in scheme):
            selected = tuple(sorted(by_suffix[suffix])[0] for suffix in scheme)
            return scheme, selected
    raise ValueError(
        "No complete three-component family was found. Expected one of ZNE, "
        f"Z12 or 123; available channels are {list(codes)}."
    )


def _row_component_selection(row: Mapping[str, Any]) -> tuple[str, tuple[str, str, str]]:
    """Resolve the explicit three-channel set recorded for a station."""
    selected = _parse_channel_codes(row.get("selected_channels"))
    scheme = str(row.get("component_scheme", "")).upper().strip()
    if selected:
        inferred_scheme, inferred = _component_selection_from_codes(selected)
        if scheme and scheme != inferred_scheme:
            raise ValueError(
                f"component_scheme={scheme!r} conflicts with selected_channels={selected}."
            )
        return inferred_scheme, inferred
    channels = _parse_channel_codes(row.get("channels"))
    return _component_selection_from_codes(channels)


def _optional_boolean(value, name: str) -> bool | None:
    """Parse an optional boolean from an in-memory or CSV-derived station row."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and int(value) in {0, 1}:
        return bool(int(value))
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    raise ValueError(f"{name} must be boolean-like, not {value!r}.")


def _validate_station_depth_policy(station_df: pd.DataFrame) -> None:
    """Validate any ground-level policy carried by a station table."""
    if "ground_level" not in station_df.columns:
        return
    for row in station_df.itertuples(index=False):
        row_dict = row._asdict()
        policy = _optional_boolean(row_dict.get("ground_level"), "ground_level")
        if policy is None:
            continue
        depth = row_dict.get(
            "input_channel_depth_m", row_dict.get("channel_depth_m")
        )
        if depth is None or pd.isna(depth):
            if policy:
                station_id = row_dict.get("station_id", "<unknown>")
                raise ValueError(
                    f"Station {station_id} is marked ground_level=True but has no "
                    "channel-depth metadata."
                )
            continue
        depth = float(depth)
        if not np.isfinite(depth):
            raise ValueError("Station channel depth must be finite.")
        if policy and not np.isclose(
            depth, 0.0, atol=_GROUND_LEVEL_DEPTH_ATOL_M, rtol=0.0
        ):
            station_id = row_dict.get("station_id", "<unknown>")
            raise ValueError(
                f"Station {station_id} is marked ground_level=True but has "
                f"channel depth {depth} m."
            )


def _inventory_orientation_summary(
    inventory,
    stream,
    time,
    *,
    expected_ground_level: bool | None = None,
) -> dict[str, Any]:
    """Validate and summarize the three input-axis orientations.

    StationXML azimuth is clockwise from north and dip is positive downward from
    horizontal. The determinant check mirrors the linear-independence condition
    required by ObsPy's ``rotate2zne`` transformation.
    """
    records = []
    basis_vectors = []
    depths = []
    latitudes = []
    longitudes = []
    elevations = []
    for trace in sorted(stream, key=lambda item: item.stats.channel):
        metadata = inventory.get_channel_metadata(trace.id, time)
        azimuth = float(metadata["azimuth"])
        dip = float(metadata["dip"])
        depth = float(metadata.get("local_depth", np.nan))
        latitude = float(metadata.get("latitude", np.nan))
        longitude = float(metadata.get("longitude", np.nan))
        elevation = float(metadata.get("elevation", np.nan))
        if not np.isfinite(azimuth) or not np.isfinite(dip):
            raise ValueError(f"Non-finite orientation metadata for {trace.id}.")
        if not np.isfinite(depth):
            raise ValueError(f"Non-finite StationXML channel depth for {trace.id}.")
        if not np.isfinite([latitude, longitude, elevation]).all():
            raise ValueError(f"Non-finite StationXML sensor coordinates for {trace.id}.")
        depths.append(depth)
        latitudes.append(latitude)
        longitudes.append(longitude)
        elevations.append(elevation)
        azimuth_rad = np.deg2rad(azimuth)
        dip_rad = np.deg2rad(dip)
        basis_vectors.append([
            -np.sin(dip_rad),
            np.cos(azimuth_rad) * np.cos(dip_rad),
            np.sin(azimuth_rad) * np.cos(dip_rad),
        ])
        records.append({
            "channel": str(trace.stats.channel),
            "azimuth_deg": azimuth,
            "dip_deg": dip,
            "depth_m": depth,
            "latitude": latitude,
            "longitude": longitude,
            "elevation_m": elevation,
        })

    if not np.allclose(
        depths, depths[0], atol=_GROUND_LEVEL_DEPTH_ATOL_M, rtol=0.0
    ):
        raise ValueError(
            f"Selected components have inconsistent sensor depths: {depths} m."
        )
    if expected_ground_level and not np.allclose(
        depths, 0.0, atol=_GROUND_LEVEL_DEPTH_ATOL_M, rtol=0.0
    ):
        raise ValueError(
            f"Ground-level records were requested but sensor depths are {depths} m."
        )
    if not np.allclose(
        latitudes, latitudes[0], atol=_CHANNEL_COORDINATE_ATOL_DEG, rtol=0.0
    ) or not np.allclose(
        longitudes, longitudes[0], atol=_CHANNEL_COORDINATE_ATOL_DEG, rtol=0.0
    ):
        raise ValueError(
            "Selected components do not share one sensor location: "
            f"latitudes={latitudes}, longitudes={longitudes}."
        )
    if not np.allclose(
        elevations, elevations[0], atol=_CHANNEL_ELEVATION_ATOL_M, rtol=0.0
    ):
        raise ValueError(
            f"Selected components have inconsistent sensor elevations: {elevations} m."
        )

    determinant = float(np.linalg.det(np.asarray(basis_vectors, dtype=float)))
    if not np.isfinite(determinant) or abs(determinant) <= 1e-6:
        raise ValueError(
            "Selected component orientations are not linearly independent; "
            f"orientation determinant={determinant}."
        )
    return {
        "input_orientation_json": json.dumps(records, separators=(",", ":")),
        "input_orientation_determinant": determinant,
        "input_channel_depth_m": float(np.mean(depths)),
        "input_sensor_lat": float(np.mean(latitudes)),
        "input_sensor_lon": float(np.mean(longitudes)),
        "input_sensor_elevation_m": float(np.mean(elevations)),
    }


def _inventory_channel_families(
    inventory,
    channel_priority: Sequence[str],
    *,
    ground_level: bool,
) -> pd.DataFrame:
    """Select one explicit three-component channel family per station.

    Families are grouped by network, station, location and two-character channel
    prefix. Within each group the orientation suffix preference is ``ZNE``,
    ``Z12``, then ``123``. Only three channels with a common positive sample rate
    and a common finite StationXML sensor depth are retained. When
    ``ground_level=True``, the selected depth must be zero within
    ``_GROUND_LEVEL_DEPTH_ATOL_M``.

    Depth and geometry checks are performed on the three selected channel
    objects. FDSN StationXML defines ``Channel.depth`` as sensor depth below the
    local ground surface and channel elevation as sensor elevation. The retained
    ``station_lat``, ``station_lon`` and ``station_elevation_m`` therefore refer
    to the actual selected sensor triplet; site-level station coordinates are
    preserved separately as ``site_lat``, ``site_lon`` and ``site_elevation_m``.
    """
    rows: list[dict[str, Any]] = []
    priority = {
        str(prefix): index for index, prefix in enumerate(channel_priority)
    }
    for network in inventory:
        for station in network:
            grouped: dict[tuple[str, str], list[Any]] = {}
            for channel in station.channels:
                prefix = str(channel.code)[:2]
                if prefix not in priority:
                    continue
                grouped.setdefault(
                    (channel.location_code or "", prefix), []
                ).append(channel)

            candidates = []
            for (location, prefix), channels in grouped.items():
                try:
                    scheme, selected_codes = _component_selection_from_codes(
                        [channel.code for channel in channels]
                    )
                except ValueError:
                    continue

                selected_objects = []
                valid_selection = True
                for code in selected_codes:
                    matches = [
                        channel for channel in channels if channel.code == code
                    ]
                    finite_rate_matches = []
                    for channel in matches:
                        try:
                            rate = float(channel.sample_rate)
                        except (TypeError, ValueError):
                            continue
                        if np.isfinite(rate) and rate > 0:
                            finite_rate_matches.append(channel)
                    if not finite_rate_matches:
                        valid_selection = False
                        break
                    selected_objects.append(
                        max(
                            finite_rate_matches,
                            key=lambda channel: float(channel.sample_rate),
                        )
                    )
                if not valid_selection:
                    continue

                sample_rates = np.asarray(
                    [float(channel.sample_rate) for channel in selected_objects],
                    dtype=float,
                )
                if not np.allclose(
                    sample_rates, sample_rates[0], atol=1e-9, rtol=0.0
                ):
                    continue

                try:
                    channel_depths = np.asarray(
                        [float(channel.depth) for channel in selected_objects],
                        dtype=float,
                    )
                except (TypeError, ValueError):
                    continue
                if not np.isfinite(channel_depths).all():
                    continue
                if not np.allclose(
                    channel_depths,
                    channel_depths[0],
                    atol=_GROUND_LEVEL_DEPTH_ATOL_M,
                    rtol=0.0,
                ):
                    continue
                if ground_level and not np.allclose(
                    channel_depths,
                    0.0,
                    atol=_GROUND_LEVEL_DEPTH_ATOL_M,
                    rtol=0.0,
                ):
                    continue

                try:
                    channel_latitudes = np.asarray(
                        [float(channel.latitude) for channel in selected_objects],
                        dtype=float,
                    )
                    channel_longitudes = np.asarray(
                        [float(channel.longitude) for channel in selected_objects],
                        dtype=float,
                    )
                    channel_elevations = np.asarray(
                        [float(channel.elevation) for channel in selected_objects],
                        dtype=float,
                    )
                except (TypeError, ValueError):
                    continue
                if not (
                    np.isfinite(channel_latitudes).all()
                    and np.isfinite(channel_longitudes).all()
                    and np.isfinite(channel_elevations).all()
                ):
                    continue
                if not np.allclose(
                    channel_latitudes,
                    channel_latitudes[0],
                    atol=_CHANNEL_COORDINATE_ATOL_DEG,
                    rtol=0.0,
                ):
                    continue
                if not np.allclose(
                    channel_longitudes,
                    channel_longitudes[0],
                    atol=_CHANNEL_COORDINATE_ATOL_DEG,
                    rtol=0.0,
                ):
                    continue
                if not np.allclose(
                    channel_elevations,
                    channel_elevations[0],
                    atol=_CHANNEL_ELEVATION_ATOL_M,
                    rtol=0.0,
                ):
                    continue

                candidates.append({
                    "network": network.code,
                    "station": station.code,
                    "location": location,
                    "channel_prefix": prefix,
                    "component_scheme": scheme,
                    "selected_channels": ",".join(selected_codes),
                    "channels": ",".join(
                        sorted({channel.code for channel in channels})
                    ),
                    "sample_rate": float(sample_rates[0]),
                    "channel_depth_m": float(channel_depths.mean()),
                    "station_lat": float(channel_latitudes.mean()),
                    "station_lon": float(channel_longitudes.mean()),
                    "station_elevation_m": float(channel_elevations.mean()),
                    "site_lat": float(station.latitude),
                    "site_lon": float(station.longitude),
                    "site_elevation_m": float(station.elevation),
                    "priority": priority[prefix],
                })
            if candidates:
                candidates.sort(
                    key=lambda item: (
                        item["priority"],
                        _COMPONENT_SCHEMES.index(item["component_scheme"]),
                        -item["sample_rate"],
                        item["location"],
                    )
                )
                rows.append(candidates[0])

    columns = [
        "network",
        "station",
        "location",
        "channel_prefix",
        "component_scheme",
        "selected_channels",
        "channels",
        "sample_rate",
        "channel_depth_m",
        "station_lat",
        "station_lon",
        "station_elevation_m",
        "site_lat",
        "site_lon",
        "site_elevation_m",
        "priority",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["network", "station"], ignore_index=True
    )

def _compute_arrivals(taup, depth_km, event_lat, event_lon, station_lat, station_lon) -> tuple[float, float]:
    p = taup.get_travel_times_geo(
        source_depth_in_km=depth_km, source_latitude_in_deg=event_lat,
        source_longitude_in_deg=event_lon, receiver_latitude_in_deg=station_lat,
        receiver_longitude_in_deg=station_lon, phase_list=["P", "p", "Pn", "Pg"],
    )
    s = taup.get_travel_times_geo(
        source_depth_in_km=depth_km, source_latitude_in_deg=event_lat,
        source_longitude_in_deg=event_lon, receiver_latitude_in_deg=station_lat,
        receiver_longitude_in_deg=station_lon, phase_list=["S", "s", "Sn", "Sg"],
    )
    return (float(p[0].time) if p else np.nan, float(s[0].time) if s else np.nan)


def _event_record(event_df) -> dict[str, Any]:
    if isinstance(event_df, pd.DataFrame):
        if len(event_df) != 1:
            raise ValueError("event_df must contain exactly one row.")
        source = event_df.iloc[0].to_dict()
    elif isinstance(event_df, pd.Series):
        source = event_df.to_dict()
    elif isinstance(event_df, Mapping):
        source = dict(event_df)
    else:
        raise TypeError("event_df must be a one-row DataFrame, Series or mapping.")
    output = {}
    for canonical, aliases in _EVENT_ALIASES.items():
        for alias in aliases:
            if alias in source and pd.notna(source[alias]):
                output[canonical] = source[alias]
                break
        else:
            raise KeyError(f"Event metadata is missing {canonical}; accepted aliases are {aliases}.")
    return output


def _sample_interval_matches(actual: float, expected: float) -> bool:
    """Return whether a persisted sample interval matches the requested value.

    SAC stores ``delta`` as a 32-bit floating-point header. Exact decimal sample
    intervals such as 0.1 s therefore do not necessarily round-trip to within
    1e-9 s. This comparison allows the expected single-precision serialization
    error while remaining strict enough to reject a genuinely different sample
    grid.
    """
    actual = float(actual)
    expected = float(expected)
    if not np.isfinite(actual) or not np.isfinite(expected):
        return False
    return bool(np.isclose(
        actual,
        expected,
        atol=_SAMPLE_INTERVAL_ATOL_S,
        rtol=_SAMPLE_INTERVAL_RTOL,
    ))


def _validate_processing_parameters(freqmin, freqmax, corners, dt) -> None:
    """Validate the common observed/GF filter and final sample interval."""
    if not (0 < float(freqmin) < float(freqmax)):
        raise ValueError("Require 0 < freqmin < freqmax.")
    if int(corners) < 1:
        raise ValueError("corners must be at least 1.")
    if float(dt) <= 0:
        raise ValueError("dt must be positive.")
    if float(freqmax) >= 0.5 / float(dt):
        raise ValueError(
            "freqmax must be below the final Nyquist frequency 0.5/dt."
        )

def _motion_scale_and_units(motion: str) -> tuple[float, str]:
    return {"DISP": (100.0, "cm"), "VEL": (100.0, "cm/s"), "ACC": (100.0, "cm/s^2")}[motion]


def _sample_trace_at_times(
    trace,
    target_times: np.ndarray,
    dt: float,
    *,
    pad_left: bool = False,
):
    """Sample one processed trace on the target grid.

    A missing left prefix is filled with zeros only when ``pad_left=True``. The
    caller performs the physical safety check that the missing interval is wholly
    pre-arrival. Missing right-edge coverage is never padded because it may remove
    modeled signal or coda.
    """
    from obspy import UTCDateTime

    old_times = (
        trace.stats.starttime.timestamp
        + np.arange(len(trace.data), dtype=float) * float(trace.stats.delta)
    )
    target_times = np.asarray(target_times, dtype=float)
    tolerance = float(trace.stats.delta) + 1e-6
    start_gap_s = float(old_times[0] - target_times[0])
    end_gap_s = float(target_times[-1] - old_times[-1])
    if start_gap_s > tolerance and not pad_left:
        raise ValueError(
            "Requested observed grid begins before the available response-corrected "
            f"trace by {start_gap_s:.6f} s; the one-sample allowance is "
            f"{tolerance:.6f} s. Re-download a longer pre-event waveform or enable "
            "safe pre-arrival padding."
        )
    if end_gap_s > tolerance:
        raise ValueError(
            "Requested observed grid ends after the available response-corrected "
            f"trace by {end_gap_s:.6f} s; the one-sample allowance is "
            f"{tolerance:.6f} s. Re-download a longer post-event waveform."
        )

    values = np.asarray(trace.data, dtype=float)
    if pad_left:
        sampled = np.zeros(target_times.size, dtype=float)
        available = target_times >= old_times[0]
        safe_times = np.clip(target_times[available], old_times[0], old_times[-1])
        sampled[available] = np.interp(safe_times, old_times, values)
    else:
        safe_times = np.clip(target_times, old_times[0], old_times[-1])
        sampled = np.interp(safe_times, old_times, values)

    output = trace.copy()
    output.data = sampled
    output.stats.starttime = UTCDateTime(float(target_times[0]))
    output.stats.delta = float(dt)
    return output


def _station_id_from_row(row: Mapping[str, Any] | pd.Series) -> str:
    location = str(row.get("location", ""))
    location_label = location if location else "--"
    return f"{row['network']}.{row['station']}.{location_label}"


def _build_unfiltered_observed_stream_for_plot(
    station_df: pd.DataFrame,
    origin,
    *,
    motion: str,
    water_level: float | None,
    freqmin: float,
    dt: float,
    read,
    read_inventory,
    Stream,
):
    """Rebuild response-corrected ZRT traces before the inversion bandpass.

    This helper is used only when ``process_mseed_sac(plot=True)`` requests the
    supplementary unfiltered record section. It repeats response removal and
    rotation from the validated raw miniSEED/StationXML inputs so cached and newly
    processed stations are treated identically. ObsPy's response-removal pre-filter
    and taper remain necessary for stable deconvolution; "unfiltered" here means
    before the explicit ``freqmin``--``freqmax`` inversion bandpass and its final
    Hann taper. No additional waveform files are written.
    """
    output = Stream()
    scale, output_units = _motion_scale_and_units(str(motion).upper())

    for row in station_df.itertuples(index=False):
        row_dict = row._asdict()
        component_scheme, selected_channels = _row_component_selection(row_dict)
        waveform_path = Path(row_dict["waveform_path"])
        stationxml_path = Path(row_dict["stationxml_path"])
        inventory = read_inventory(str(stationxml_path), format="STATIONXML")
        available = read(str(waveform_path), format="MSEED")
        available = available.select(
            network=str(row_dict["network"]),
            station=str(row_dict["station"]),
            location=str(row_dict.get("location", "")),
            channel=f"{row_dict['channel_prefix']}?",
        )

        stream = Stream()
        for channel in selected_channels:
            matching = available.select(channel=channel)
            if len(matching) == 0:
                raise ValueError(
                    f"Selected input channel {channel} is absent from "
                    f"{waveform_path}."
                )
            stream += matching
        true_gaps = [gap for gap in stream.get_gaps() if gap[-1] > 0]
        if true_gaps:
            raise ValueError(
                f"Internal waveform gaps while building the unfiltered record "
                f"section for {row_dict['station_id']}: {true_gaps}"
            )
        stream.merge(method=0)
        if len(stream) != 3:
            raise ValueError(
                "The explicit input channel selection must reduce to exactly "
                f"three traces for {row_dict['station_id']}."
            )
        common_start = max(trace.stats.starttime for trace in stream)
        common_end = min(trace.stats.endtime for trace in stream)
        if common_end <= common_start:
            raise ValueError(
                f"The components for {row_dict['station_id']} have no common "
                "recorded interval."
            )
        stream.trim(common_start, common_end, pad=False)

        corrected = Stream()
        for source_trace in stream:
            trace = source_trace.copy()
            trace.detrend("linear")
            trace.detrend("demean")
            kwargs = {
                "inventory": inventory,
                "output": str(motion).upper(),
                "pre_filt": _default_pre_filt(trace, float(freqmin)),
                "zero_mean": True,
                "taper": True,
            }
            if water_level is not None:
                kwargs["water_level"] = float(water_level)
            trace.remove_response(**kwargs)
            trace.detrend("linear")
            trace.detrend("demean")
            corrected += trace

        corrected.rotate(
            method="->ZNE",
            inventory=inventory,
            components=(component_scheme,),
        )
        zne = Stream()
        for component in "ZNE":
            selected = corrected.select(component=component)
            if len(selected) != 1:
                raise ValueError(
                    f"Expected one {component} component after ZNE rotation for "
                    f"{row_dict['station_id']}; found {len(selected)}."
                )
            zne += selected[0].copy()
        zne.rotate(
            method="NE->RT",
            back_azimuth=float(row_dict["back_azimuth_deg"]),
        )

        stored_npts = int(row_dict["stored_npts"])
        target_start = origin + float(row_dict["window_start_offset_s"])
        target_times = (
            target_start.timestamp
            + np.arange(stored_npts, dtype=float) * float(dt)
        )
        pad_left = _optional_boolean(
            row_dict.get("prearrival_padding_applied"),
            "prearrival_padding_applied",
        )
        pad_left = False if pad_left is None else bool(pad_left)

        for component in "ZRT":
            selected = zne.select(component=component)
            if len(selected) != 1:
                raise ValueError(
                    f"Expected one {component} component after ZRT rotation for "
                    f"{row_dict['station_id']}; found {len(selected)}."
                )
            trace = _sample_trace_at_times(
                selected[0],
                target_times,
                float(dt),
                pad_left=pad_left,
            )
            trace.data = np.asarray(trace.data * scale, dtype=np.float32)
            trace.stats.network = str(row_dict["network"])
            trace.stats.station = str(row_dict["station"])
            trace.stats.location = str(row_dict.get("location", ""))
            trace.stats.channel = f"MT{component}"
            trace.stats.units = output_units
            trace.stats.sac = {"dist": float(row_dict["distance"])}
            output += trace

    return output


def _plot_observed_record_section(
    stream,
    origin,
    station_df,
    output_path: Path,
    *,
    amplitude_scale: float = 1.0,
    figure_title: str | None = None,
) -> None:
    """Plot stored ZRT observations on an event-origin-relative time axis.

    Negative values are intentionally retained: they are samples recorded before
    the event origin, not negative travel times. The event origin and theoretical
    P/S positions are drawn explicitly so storage, arrivals and the inversion
    reference cannot be confused.
    """
    import matplotlib.pyplot as plt

    amplitude_scale = float(amplitude_scale)
    if not np.isfinite(amplitude_scale) or amplitude_scale <= 0.0:
        raise ValueError("amplitude_scale must be finite and positive.")

    fig, axes = plt.subplots(
        1, 3, figsize=(15, 9), dpi=200, sharey=True, constrained_layout=True
    )
    station_table = station_df.set_index("station_id")
    for component, axis in zip("ZRT", axes):
        for trace in stream.select(component=component):
            station_id = (
                f"{trace.stats.network}.{trace.stats.station}."
                f"{trace.stats.location or '--'}"
            )
            if station_id in station_table.index:
                row = station_table.loc[station_id]
                distance = float(row["distance"])
                p_time = float(row.get("p_arrival_s", np.nan))
                s_time = float(row.get("s_arrival_s", np.nan))
            else:
                distance = float(trace.stats.sac.dist)
                p_time = np.nan
                s_time = np.nan
            amplitude = np.nanmax(np.abs(trace.data))
            values = (
                amplitude_scale * trace.data / amplitude
                if amplitude > 0 else trace.data
            )
            time = trace.times() + float(trace.stats.starttime - origin)
            axis.plot(time, values + distance, linewidth=0.7)
            if np.isfinite(p_time):
                axis.plot(p_time, distance, marker="|", markersize=5, linestyle="none")
            if np.isfinite(s_time):
                axis.plot(s_time, distance, marker="|", markersize=5, linestyle="none")
        axis.axvline(0.0, linestyle="--", linewidth=0.8)
        axis.set_title(component)
        axis.set_xlabel("Time relative to event origin (s)")
        axis.set_ylabel("Distance (km)")
        axis.grid(axis="x", alpha=0.15)
    if figure_title:
        fig.suptitle(str(figure_title))
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def _plot_station_map(event: Mapping[str, Any], station_df: pd.DataFrame, output_path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, axis = plt.subplots(figsize=(8, 8), dpi=180, constrained_layout=True)
    axis.scatter(station_df["longitude"], station_df["latitude"], marker="^", s=35, label="Stations")
    axis.scatter(float(event["event_lon"]), float(event["event_lat"]), marker="*", s=140, label="Event")
    for row in station_df.itertuples(index=False):
        axis.annotate(
            row.station_id, (row.longitude, row.latitude), xytext=(3, 3),
            textcoords="offset points", fontsize=7,
        )
    axis.set_xlabel("Longitude")
    axis.set_ylabel("Latitude")
    axis.set_title(str(event["event_id"]))
    axis.legend()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def _gf_processing_settings(
    station_df: pd.DataFrame, **overrides
) -> dict[str, Any]:
    """Resolve processing settings that must remain common across stations.

    The inversion length is intentionally excluded. Each station supplies its
    own ``npts`` from :func:`process_mseed_sac`.
    """
    aliases = {
        "motion": "motion",
        "freqmin": "freqmin",
        "freqmax": "freqmax",
        "corners": "corners",
        "dt": "dt",
    }
    settings = {}
    for name, column in aliases.items():
        override = overrides.get(name)
        if override is not None:
            settings[name] = override
        elif column in station_df:
            unique = pd.unique(station_df[column].dropna())
            if len(unique) != 1:
                raise ValueError(
                    f"station_df must have one common {column}; "
                    f"found {unique.tolist()}."
                )
            settings[name] = unique[0]
        else:
            raise ValueError(
                f"{name} was not supplied and is absent from station_df."
            )
    settings["motion"] = str(settings["motion"]).upper()
    settings["freqmin"] = float(settings["freqmin"])
    settings["freqmax"] = float(settings["freqmax"])
    settings["corners"] = int(settings["corners"])
    settings["dt"] = float(settings["dt"])
    _, settings["units"] = _motion_scale_and_units(settings["motion"])
    _validate_processing_parameters(
        settings["freqmin"],
        settings["freqmax"],
        settings["corners"],
        settings["dt"],
    )
    return settings




def _wgs84_geocentric_latitude(latitude_deg: float) -> float:
    """Convert WGS84 geographic latitude to geocentric latitude in degrees."""
    latitude_deg = float(latitude_deg)
    if not np.isfinite(latitude_deg) or not -90.0 <= latitude_deg <= 90.0:
        raise ValueError("latitude_deg must be finite and lie within [-90, 90].")

    # WGS84 semi-major and semi-minor axes in metres.  atan2 keeps the poles
    # well behaved while remaining algebraically equivalent to
    # atan((b**2/a**2) * tan(latitude)).
    a = 6378137.0
    b = 6356752.314245
    latitude = np.deg2rad(latitude_deg)
    geocentric = np.arctan2(
        (b * b) * np.sin(latitude),
        (a * a) * np.cos(latitude),
    )
    return float(np.rad2deg(geocentric))


def _syngine_geocentric_distance_degrees(
    event_lat: float,
    event_lon: float,
    station_lat: float,
    station_lon: float,
) -> float:
    """Return Syngine's spherical angle after WGS84 geocentric conversion."""
    from obspy.geodetics import locations2degrees

    event_lon = float(event_lon)
    station_lon = float(station_lon)
    if not np.isfinite([event_lon, station_lon]).all():
        raise ValueError("Event/station longitudes must be finite.")
    if not -180.0 <= event_lon <= 180.0 or not -180.0 <= station_lon <= 180.0:
        raise ValueError("Event/station longitudes must lie within [-180, 180].")

    event_lat_gc = _wgs84_geocentric_latitude(event_lat)
    station_lat_gc = _wgs84_geocentric_latitude(station_lat)
    return float(locations2degrees(
        event_lat_gc,
        event_lon,
        station_lat_gc,
        station_lon,
    ))

def _syngine_gf_processing_signature(
    *,
    station_id: str,
    distance_km: float,
    distance_deg: float,
    azimuth_deg: float,
    requested_depth: float,
    source_depth_m: int,
    syngine_model: str,
    syngine_url: str,
    syngine_units: str,
    syngine_dt: float | None,
    kernelwidth: int,
    request_end_s: float,
    request_padding_s: float,
    settings: Mapping[str, Any],
) -> str:
    """Build the deterministic cache signature for one Syngine tensor GF set."""
    payload = {
        "schema": "mttime-syngine-gf-v2-geocentric-southward-seiscomp-tensor",
        "mttime_helpers_version": _SYNGINE_CACHE_COMPAT_VERSION,
        "station_id": str(station_id),
        "distance_km": float(distance_km),
        "syngine_distance_deg": float(distance_deg),
        "azimuth_deg": float(azimuth_deg),
        "requested_depth_km": float(requested_depth),
        "syngine_source_depth_m": int(source_depth_m),
        "syngine": {
            "model": str(syngine_model),
            "url": str(syngine_url),
            "units": str(syngine_units),
            "dt": None if syngine_dt is None else float(syngine_dt),
            "kernelwidth": int(kernelwidth),
            "request_start_s": 0.0,
            "request_end_s": float(request_end_s),
            "request_padding_s": float(request_padding_s),
            "definition": "seiscomp",
        },
        "syngine_distance_geometry": "WGS84_geographic_to_geocentric_sphere",
        "tensor_coordinates": "NED_x_north_y_east_z_down",
        "tensor_rotation": "alpha_deg=(180-azimuth_deg)%360",
        "tensor_bases": list(_TENSOR_BASES),
        "reference_moment_Nm": _SYNGINE_MTTIME_REFERENCE_MOMENT_NM,
        "si_to_cm_scale": _SYNGINE_SI_TO_CM_SCALE,
        "amplitude_scale": _SYNGINE_MTTIME_AMPLITUDE_SCALE,
        "settings": dict(settings),
    }
    return _short_signature(payload)


def _request_syngine_gf_stream(
    *,
    session,
    syngine_url: str,
    syngine_model: str,
    source_depth_m: int,
    distance_deg: float,
    syngine_units: str,
    syngine_dt: float | None,
    kernelwidth: int,
    origin,
    request_end_s: float,
    timeout: float,
    read,
    Stream,
    zipfile,
):
    """Request one trimmed Syngine SeisComP GF set and return it in memory."""
    params = {
        "model": str(syngine_model),
        "greensfunction": 1,
        "sourcedistanceindegrees": float(distance_deg),
        "sourcedepthinmeters": int(source_depth_m),
        "format": "saczip",
        "units": str(syngine_units),
        "origintime": str(origin),
        "starttime": 0.0,
        "endtime": float(request_end_s),
        "nodata": 404,
    }
    if syngine_dt is not None:
        params["dt"] = float(syngine_dt)
        params["kernelwidth"] = int(kernelwidth)

    response = session.get(syngine_url, params=params, timeout=float(timeout))
    if response.status_code != 200:
        detail = response.text.strip()
        if len(detail) > 2000:
            detail = detail[:2000] + "..."
        raise RuntimeError(
            f"Syngine returned HTTP {response.status_code} for model "
            f"{syngine_model}, depth={source_depth_m} m, "
            f"distance={distance_deg:.6f} deg. {detail}"
        )

    try:
        archive = zipfile.ZipFile(io.BytesIO(response.content))
    except Exception as exc:
        raise ValueError("Syngine response is not a readable SACZIP archive.") from exc

    stream = Stream()
    try:
        names = archive.namelist()
        for name in names:
            if not name.lower().endswith(".sac"):
                continue
            with archive.open(name) as file:
                loaded = read(io.BytesIO(file.read()), format="SAC")
            if len(loaded) != 1:
                raise ValueError(
                    f"Syngine archive member {name!r} contains {len(loaded)} traces."
                )
            stream += loaded
    finally:
        archive.close()

    channels = [str(trace.stats.channel).upper() for trace in stream]
    expected = set(_SYNGINE_BASES)
    if len(stream) != len(_SYNGINE_BASES) or set(channels) != expected:
        missing = sorted(expected.difference(channels))
        extra = sorted(set(channels).difference(expected))
        raise ValueError(
            "Syngine GF archive does not contain the expected ten SeisComP "
            f"bases. Missing={missing}, extra={extra}, channels={channels}."
        )
    if len(set(channels)) != len(channels):
        raise ValueError(f"Syngine GF archive contains duplicate channels: {channels}.")

    by_channel = {str(trace.stats.channel).upper(): trace for trace in stream}
    ordered = Stream([by_channel[basis].copy() for basis in _SYNGINE_BASES])

    dt_values = np.asarray([float(trace.stats.delta) for trace in ordered], dtype=float)
    npts_values = np.asarray([int(trace.stats.npts) for trace in ordered], dtype=int)
    start_offsets = np.asarray(
        [float(trace.stats.starttime - origin) for trace in ordered], dtype=float
    )
    if not np.isfinite(dt_values).all() or (dt_values <= 0).any():
        raise ValueError("Syngine returned an invalid sample interval.")
    if not np.allclose(dt_values, dt_values[0], atol=1e-8, rtol=1e-6):
        raise ValueError(f"Syngine bases have inconsistent dt values: {dt_values.tolist()}.")
    if len(set(npts_values.tolist())) != 1:
        raise ValueError(f"Syngine bases have inconsistent npts: {npts_values.tolist()}.")
    tolerance = max(1e-6, 0.01 * float(dt_values[0]))
    if not np.allclose(start_offsets, start_offsets[0], atol=tolerance, rtol=0.0):
        raise ValueError(
            f"Syngine bases have inconsistent start offsets: {start_offsets.tolist()}."
        )
    for trace in ordered:
        if not np.isfinite(trace.data).all():
            raise ValueError(
                f"Syngine basis {trace.stats.channel} contains non-finite samples."
            )

    returned_dt = float(dt_values[0])
    returned_npts = int(npts_values[0])
    start_offset = float(start_offsets[0])
    end_offset = start_offset + (returned_npts - 1) * returned_dt
    return ordered, {
        "returned_dt_s": returned_dt,
        "returned_npts": returned_npts,
        "start_offset_s": start_offset,
        "end_offset_s": float(end_offset),
    }


def _syngine_seiscomp_to_tensor_stream(stream, *, azimuth_deg: float, Stream):
    """Expand Syngine's ten SeisComP bases to 18 MTtime NED tensor bases.

    The output coordinates are MTtime/Aki-Richards Cartesian ``x=north``,
    ``y=east``, ``z=down``. Instaseis documents the spherical-to-Cartesian
    source mapping as ``Mtt=Mxx, Mpp=Myy, Mrr=Mzz, Mrp=-Myz, Mrt=Mxz,
    Mtp=-Mxy``. The SeisComP path frame is referenced to the southward positive
    theta direction, so a geographic forward azimuth ``A`` is converted through
    ``alpha=(180-A) mod 360`` before substitution into the Minson-Dreger
    representation below.
    """
    by_channel = {
        str(trace.stats.channel).upper(): trace.copy()
        for trace in stream
    }
    missing = set(_SYNGINE_BASES).difference(by_channel)
    if missing:
        raise ValueError(f"Missing Syngine SeisComP bases: {sorted(missing)}.")

    reference = by_channel[_SYNGINE_BASES[0]]
    ref_dt = float(reference.stats.delta)
    ref_npts = int(reference.stats.npts)
    ref_start = reference.stats.starttime
    tolerance = max(1e-8, 0.01 * ref_dt)
    for basis in _SYNGINE_BASES:
        trace = by_channel[basis]
        if int(trace.stats.npts) != ref_npts:
            raise ValueError(f"Syngine basis {basis} has inconsistent npts.")
        if not _sample_interval_matches(trace.stats.delta, ref_dt):
            raise ValueError(f"Syngine basis {basis} has inconsistent dt.")
        if abs(trace.stats.starttime - ref_start) > tolerance:
            raise ValueError(f"Syngine basis {basis} has inconsistent start time.")

    data = {
        basis: np.asarray(by_channel[basis].data, dtype=np.float64)
        for basis in _SYNGINE_BASES
    }
    azimuth = np.deg2rad((180.0 - float(azimuth_deg)) % 360.0)
    c1, s1 = np.cos(azimuth), np.sin(azimuth)
    c2, s2 = np.cos(2.0 * azimuth), np.sin(2.0 * azimuth)

    tensor = {
        "Zxx": 0.5 * data["ZSS"] * c2 - data["ZDD"] / 6.0 + data["ZEP"] / 3.0,
        "Zyy": -0.5 * data["ZSS"] * c2 - data["ZDD"] / 6.0 + data["ZEP"] / 3.0,
        "Zzz": data["ZDD"] / 3.0 + data["ZEP"] / 3.0,
        "Zxy": -data["ZSS"] * s2,
        "Zxz": data["ZDS"] * c1,
        "Zyz": -data["ZDS"] * s1,
        "Rxx": 0.5 * data["RSS"] * c2 - data["RDD"] / 6.0 + data["REP"] / 3.0,
        "Ryy": -0.5 * data["RSS"] * c2 - data["RDD"] / 6.0 + data["REP"] / 3.0,
        "Rzz": data["RDD"] / 3.0 + data["REP"] / 3.0,
        "Rxy": -data["RSS"] * s2,
        "Rxz": data["RDS"] * c1,
        "Ryz": -data["RDS"] * s1,
        "Txx": 0.5 * data["TSS"] * s2,
        "Tyy": -0.5 * data["TSS"] * s2,
        "Tzz": np.zeros_like(data["TSS"]),
        "Txy": data["TSS"] * c2,
        "Txz": data["TDS"] * s1,
        "Tyz": data["TDS"] * c1,
    }

    templates = {
        "Z": by_channel["ZSS"],
        "R": by_channel["RSS"],
        "T": by_channel["TSS"],
    }
    output = Stream()
    for basis in _TENSOR_BASES:
        trace = templates[basis[0]].copy()
        trace.data = np.asarray(tensor[basis], dtype=np.float64)
        trace.stats.channel = basis
        output += trace
    return output


def _process_syngine_stream(stream, settings, *, origin, UTCDateTime, Stream):
    """Filter and sample Syngine tensor bases on the MTtime origin grid."""
    processed = Stream()
    target_times = np.arange(int(settings["npts"]), dtype=float) * float(settings["dt"])
    guard_seconds = _gf_filter_guard_seconds(settings)
    guarded_start = min(float(target_times[0]), -guard_seconds)
    required_raw_end = float(target_times[-1]) + guard_seconds

    for source_trace in stream:
        trace = source_trace.copy()
        raw_dt = float(trace.stats.delta)
        raw_start = float(trace.stats.starttime - origin)
        raw_end = raw_start + (int(trace.stats.npts) - 1) * raw_dt
        tolerance = max(1e-8, 0.01 * raw_dt)
        if settings["freqmax"] >= 0.5 / raw_dt:
            raise ValueError(
                "Syngine returned dt="
                f"{raw_dt:.8g} s, whose Nyquist frequency is not above "
                f"freqmax={settings['freqmax']:.8g} Hz."
            )

        if raw_end < required_raw_end - tolerance:
            raise ValueError(
                "The Syngine request does not provide the required late-time "
                "filter guard. The final MTtime sample is at "
                f"{target_times[-1]:.3f} s and requires coverage through "
                f"{required_raw_end:.3f} s, but the returned trace ends at "
                f"{raw_end:.3f} s."
            )

        if guarded_start < raw_start - tolerance:
            n_pre = int(np.ceil((raw_start - guarded_start) / raw_dt))
            trace.data = np.concatenate([
                np.zeros(n_pre, dtype=np.asarray(trace.data).dtype),
                np.asarray(trace.data),
            ])
            trace.stats.starttime -= n_pre * raw_dt

        trace.filter(
            "bandpass",
            freqmin=settings["freqmin"],
            freqmax=settings["freqmax"],
            corners=settings["corners"],
            zerophase=True,
        )
        trace.taper(max_percentage=0.05, type="hann", side="both")

        old_times = (
            float(trace.stats.starttime - origin)
            + np.arange(len(trace.data), dtype=float) * float(trace.stats.delta)
        )
        if target_times[0] < old_times[0] - tolerance:
            raise RuntimeError(
                "Internal Syngine timing error: causal pre-padding did not cover "
                "source-origin time zero."
            )
        if target_times[-1] > old_times[-1] + tolerance:
            raise RuntimeError(
                "Internal Syngine timing error: the guarded trace no longer "
                "covers the requested final MTtime sample."
            )

        trace.data = np.asarray(
            np.interp(target_times, old_times, np.asarray(trace.data, dtype=float)),
            dtype=np.float64,
        )
        trace.stats.starttime = UTCDateTime(0)
        trace.stats.delta = float(settings["dt"])
        trace.stats.units = settings["units"]
        if not hasattr(trace.stats, "sac") or trace.stats.sac is None:
            trace.stats.sac = {}
        trace.stats.sac.b = 0.0
        trace.stats.sac.o = 0.0
        trace.stats.sac.user8 = float(guard_seconds)
        processed += trace
    return processed


def _write_mttime_tensor_sac(
    stream,
    *,
    station_id: str,
    requested_depth: float,
    output_paths: Mapping[str, Path],
    event: Mapping[str, Any],
    station_row: Mapping[str, Any],
    distance_km: float,
    azimuth_deg: float,
    raw_dt: float,
) -> None:
    """Write one processed 18-file MTtime Cartesian tensor Green's-function set.

    A fresh SAC header is constructed for every tensor basis.  Syngine's native
    SAC reference epoch is therefore never inherited into the source-relative
    MTtime files; sample zero, ``stats.starttime`` and SAC ``b`` all remain at
    source-reference time zero after serialization.
    """
    from obspy import Trace, UTCDateTime
    from obspy.core.util.attribdict import AttribDict

    by_basis = {str(trace.stats.channel): trace for trace in stream}
    missing = set(_TENSOR_BASES).difference(by_basis)
    if missing or len(by_basis) != len(_TENSOR_BASES):
        raise ValueError(
            f"Processed tensor stream is incomplete; missing={sorted(missing)}."
        )

    station_lat = float(station_row["station_lat"])
    station_lon = float(station_row["station_lon"])
    back_azimuth = float(station_row.get("back_azimuth_deg", np.nan))
    if not np.isfinite(back_azimuth):
        back_azimuth = (float(azimuth_deg) + 180.0) % 360.0

    for basis in _TENSOR_BASES:
        source = by_basis[basis]
        trace = Trace(
            data=np.asarray(source.data, dtype=np.float64).copy(),
            header={
                "network": str(getattr(source.stats, "network", "")),
                "station": str(station_id),
                "location": str(getattr(source.stats, "location", "")),
                "channel": basis,
                "starttime": UTCDateTime(0),
                "delta": float(source.stats.delta),
            },
        )
        if hasattr(source.stats, "units"):
            trace.stats.units = source.stats.units

        trace.stats.sac = AttribDict()
        sac = trace.stats.sac
        source_sac = getattr(source.stats, "sac", None)

        # Preserve only helper-owned processing metadata; do not copy any of
        # Syngine's original nz* absolute reference-time fields.
        for key in ("user8", "kuser0", "kuser1", "kuser2"):
            value = _sac_header_value(source_sac, key, None)
            if value is not None:
                setattr(sac, key, value)

        sac.kstnm = str(station_id)[:8]
        sac.kcmpnm = basis[:8]
        sac.evdp = float(requested_depth)
        sac.evla = float(event["event_lat"])
        sac.evlo = float(event["event_lon"])
        sac.stla = station_lat
        sac.stlo = station_lon
        sac.dist = float(distance_km)
        sac.az = float(azimuth_deg) % 360.0
        sac.baz = back_azimuth % 360.0
        component = basis[0]
        sac.cmpaz = {
            "Z": 0.0,
            "R": float(azimuth_deg) % 360.0,
            "T": (float(azimuth_deg) + 90.0) % 360.0,
        }[component]
        sac.cmpinc = 0.0 if component == "Z" else 90.0
        sac.b = 0.0
        sac.o = 0.0
        sac.user7 = float(raw_dt)

        path = output_paths[basis]
        trace.write(str(path), format="SAC", keep_sac_header=True)

def _green_format_from_manifest(gf_manifest: pd.DataFrame) -> str:
    """Infer MTtime Green's-function format while preserving legacy Herrmann use."""
    if "green" not in gf_manifest.columns:
        return "herrmann"
    values = {
        str(value).strip().lower()
        for value in gf_manifest["green"].dropna().tolist()
        if str(value).strip()
    }
    if not values:
        return "herrmann"
    if len(values) != 1:
        raise ValueError(
            f"gf_manifest contains multiple Green's-function formats: {sorted(values)}."
        )
    green = next(iter(values))
    if green not in {"herrmann", "tensor"}:
        raise ValueError(
            f"Unsupported Green's-function format {green!r}; expected 'herrmann' or 'tensor'."
        )
    return green

def _source_depth_off_interface(
    model_array: np.ndarray,
    requested_depth: float,
    offset_km: float = 0.001,
) -> float:
    """Move a source lying on an interface a small distance into the deeper layer.

    The displacement is capped at one quarter of the deeper finite-layer
    thickness so a very thin layer cannot be crossed inadvertently. The final
    half-space has no lower interface and therefore uses ``offset_km`` directly.
    """
    array = np.asarray(model_array, dtype=float)
    requested_depth = float(requested_depth)
    offset_km = float(offset_km)
    if array.ndim != 2 or array.shape[0] < 1 or array.shape[1] < 1:
        raise ValueError("model_array must be a non-empty two-dimensional array.")
    if not np.isfinite(requested_depth) or requested_depth <= 0:
        raise ValueError("requested_depth must be finite and positive.")
    if not np.isfinite(offset_km) or offset_km <= 0:
        raise ValueError("offset_km must be finite and positive.")

    thickness = np.asarray(array[:, 0], dtype=float)
    if not np.isfinite(thickness).all() or (thickness[:-1] <= 0).any():
        raise ValueError("All finite-layer thicknesses must be positive and finite.")
    interfaces = np.r_[0.0, np.cumsum(thickness[:-1])]
    matches = np.flatnonzero(
        np.isclose(interfaces[1:], requested_depth, atol=1e-8, rtol=0.0)
    )
    if matches.size == 0:
        return requested_depth

    deeper_layer_index = int(matches[0] + 1)
    deeper_thickness = float(thickness[deeper_layer_index])
    actual_offset = offset_km
    if deeper_layer_index < len(thickness) - 1 or deeper_thickness > 0:
        if deeper_thickness > 0:
            actual_offset = min(offset_km, 0.25 * deeper_thickness)
    if actual_offset <= 0:
        raise ValueError("Could not move source off the velocity-model interface.")
    return float(requested_depth + actual_offset)


def _gf_filter_guard_seconds(settings: Mapping[str, Any]) -> float:
    """Return the minimum edge guard used before zero-phase GF filtering.

    One period at the lowest retained frequency is kept between the final MTtime
    segment and either edge of the internal Green's-function record. This is a
    conservative, transparent guard against forward-backward filter transients
    and the tapered end of the finite record.
    """
    return float(1.0 / float(settings["freqmin"]))



def _normalize_motion_name(value: str, name: str = "motion") -> str:
    """Normalize one supported waveform-motion label."""
    motion = str(value).strip().upper()
    if motion not in {"DISP", "VEL", "ACC"}:
        raise ValueError(f"{name} must be 'DISP', 'VEL' or 'ACC'.")
    return motion


def _motion_conversion_label(native_motion: str, target_motion: str) -> str:
    """Describe the temporal operation from native to target motion."""
    order = {"DISP": 0, "VEL": 1, "ACC": 2}
    difference = order[target_motion] - order[native_motion]
    if difference == 0:
        return "none"
    operation = "differentiate" if difference > 0 else "integrate"
    count = abs(difference)
    return operation if count == 1 else f"{operation}_{count}"


def _convert_pyfk_motion_before_filter(trace, native_motion: str, target_motion: str):
    """Apply required integrations and return the number of later derivatives.

    Integrations precede the bandpass so its unknown constant and finite-record
    drift are removed by filtering. Derivatives follow filtering and tapering so
    high-frequency numerical noise is not amplified first.
    """
    order = {"DISP": 0, "VEL": 1, "ACC": 2}
    difference = order[target_motion] - order[native_motion]
    if difference < 0:
        for _ in range(-difference):
            trace.integrate(method="cumtrapz")
        return trace, 0
    return trace, difference


def _pyfk_model_metadata(model_array: np.ndarray) -> dict[str, Any]:
    """Report which density and attenuation values are supplied versus pyFK defaults."""
    model = np.asarray(model_array, dtype=float)
    if model.ndim != 2:
        raise ValueError("pyFK model array must be two-dimensional.")
    ncol = int(model.shape[1])

    base = {
        "model_columns": ncol,
        "density_policy": "pyfk_default",
        "qs_policy": "pyfk_default",
        "qp_policy": "pyfk_default",
        "qs_min": np.nan,
        "qs_max": np.nan,
        "qp_min": np.nan,
        "qp_max": np.nan,
    }

    if ncol == 3:
        return base

    if ncol == 4:
        fourth = model[:, 3]
        if np.any(fourth > 20.0):
            base.update({
                "qs_policy": "supplied",
                "qs_min": float(np.min(fourth)),
                "qs_max": float(np.max(fourth)),
            })
        else:
            base["density_policy"] = "supplied"
        return base

    if ncol == 5:
        qs = model[:, 4]
        base.update({
            "density_policy": "supplied",
            "qs_policy": "supplied",
            "qs_min": float(np.min(qs)),
            "qs_max": float(np.max(qs)),
        })
        return base

    if ncol == 6:
        qs, qp = model[:, 4], model[:, 5]
        base.update({
            "density_policy": "supplied",
            "qs_policy": "supplied",
            "qp_policy": "supplied",
            "qs_min": float(np.min(qs)),
            "qs_max": float(np.max(qs)),
            "qp_min": float(np.min(qp)),
            "qp_max": float(np.max(qp)),
        })
        return base

    raise ValueError(f"Unsupported pyFK model column count {ncol}.")

def _pyfk_tail_metrics(
    traces,
    *,
    retained_end_s: float,
    guard_s: float,
) -> dict[str, Any]:
    """Quantify, but never modify, raw pyFK energy after the retained interval."""
    retained_peaks, retained_squares = [], []
    tail_peaks, tail_squares = [], []
    retained_count = tail_count = 0
    raw_ends = []
    tail_start = float(retained_end_s) + float(guard_s)

    for trace in traces:
        data = np.asarray(trace.data, dtype=float)
        times = (
            float(trace.stats.starttime.timestamp)
            + np.arange(data.size, dtype=float) * float(trace.stats.delta)
        )
        raw_ends.append(float(times[-1]))
        retained = (times >= 0.0) & (times <= float(retained_end_s))
        tail = times >= tail_start
        if np.any(retained):
            values = data[retained]
            retained_peaks.append(float(np.max(np.abs(values))))
            retained_squares.append(float(np.dot(values, values)))
            retained_count += int(values.size)
        if np.any(tail):
            values = data[tail]
            tail_peaks.append(float(np.max(np.abs(values))))
            tail_squares.append(float(np.dot(values, values)))
            tail_count += int(values.size)

    retained_peak = max(retained_peaks, default=np.nan)
    tail_peak = max(tail_peaks, default=np.nan)
    retained_rms = (
        np.sqrt(sum(retained_squares) / retained_count)
        if retained_count else np.nan
    )
    tail_rms = np.sqrt(sum(tail_squares) / tail_count) if tail_count else np.nan
    return {
        "raw_record_end_s": max(raw_ends, default=np.nan),
        "raw_tail_start_s": tail_start,
        "raw_tail_available": bool(tail_count),
        "raw_tail_peak_ratio": (
            float(tail_peak / retained_peak)
            if np.isfinite(tail_peak) and np.isfinite(retained_peak)
            and retained_peak > 0 else np.nan
        ),
        "raw_tail_rms_ratio": (
            float(tail_rms / retained_rms)
            if np.isfinite(tail_rms) and np.isfinite(retained_rms)
            and retained_rms > 0 else np.nan
        ),
    }


def _process_pyfk_stream(
    stream, settings, target_start_offset_s, UTCDateTime, Stream
):
    """Convert, filter and sample pyFK bases on an origin-relative grid.

    Native temporal order is set by ``settings['pyfk_native_motion']``.
    Integrations are performed before the bandpass; derivatives are performed
    after filtering and tapering. Missing causal pre-origin samples may be
    zero-extended, but late samples are never invented.
    """
    processed = Stream()
    target_times = (
        float(target_start_offset_s)
        + np.arange(int(settings["npts"]), dtype=float) * float(settings["dt"])
    )
    guard_seconds = _gf_filter_guard_seconds(settings)
    guarded_start = min(float(target_times[0]), -guard_seconds)
    required_raw_end = float(target_times[-1]) + guard_seconds
    native_motion = _normalize_motion_name(
        settings.get("pyfk_native_motion", "DISP"), "pyfk_native_motion"
    )
    target_motion = _normalize_motion_name(settings["motion"], "motion")

    for source_trace in stream:
        trace = source_trace.copy()
        raw_dt = float(trace.stats.delta)
        raw_start = float(trace.stats.starttime.timestamp)
        raw_end = raw_start + (int(trace.stats.npts) - 1) * raw_dt
        tolerance = max(1e-8, 0.01 * raw_dt)

        if raw_end < required_raw_end - tolerance:
            raise ValueError(
                "The internal pyFK record does not provide the required late-time "
                "filter guard. The final MTtime sample is at "
                f"{target_times[-1]:.3f} s and requires coverage through "
                f"{required_raw_end:.3f} s, but the trace ends at {raw_end:.3f} s."
            )

        if guarded_start < raw_start - tolerance:
            sac = getattr(trace.stats, "sac", None)
            first_arrival = None
            if sac is not None:
                value = _sac_header_value(sac, "t1", np.nan)
                try:
                    first_arrival = float(value)
                except (TypeError, ValueError):
                    first_arrival = None
            if first_arrival is not None and np.isfinite(first_arrival):
                if raw_start > first_arrival + tolerance:
                    raise ValueError(
                        "pyFK trace metadata place the record start after its "
                        "first P arrival; causal zero extension is invalid."
                    )
            n_pre = int(np.ceil((raw_start - guarded_start) / raw_dt))
            trace.data = np.concatenate([
                np.zeros(n_pre, dtype=np.asarray(trace.data).dtype),
                np.asarray(trace.data),
            ])
            trace.stats.starttime -= n_pre * raw_dt

        trace, derivative_count = _convert_pyfk_motion_before_filter(
            trace, native_motion, target_motion
        )
        trace.filter(
            "bandpass",
            freqmin=settings["freqmin"],
            freqmax=settings["freqmax"],
            corners=settings["corners"],
            zerophase=True,
        )
        trace.taper(max_percentage=0.05, type="hann", side="both")
        for _ in range(derivative_count):
            trace.differentiate(method="gradient")

        old_times = (
            trace.stats.starttime.timestamp
            + np.arange(len(trace.data), dtype=float) * float(trace.stats.delta)
        )
        if target_times[0] < old_times[0] - tolerance:
            raise RuntimeError(
                "Internal timing error: causal pre-padding did not cover the "
                "requested origin-aligned start."
            )
        if target_times[-1] > old_times[-1] + tolerance:
            raise RuntimeError(
                "Internal timing error: the guarded pyFK trace no longer covers "
                "the requested final sample."
            )
        trace.data = np.asarray(
            np.interp(target_times, old_times, np.asarray(trace.data, dtype=float)),
            dtype=np.float64,
        )
        trace.stats.starttime = UTCDateTime(float(target_start_offset_s))
        trace.stats.delta = float(settings["dt"])
        trace.stats.units = settings["units"]
        if not hasattr(trace.stats, "sac") or trace.stats.sac is None:
            trace.stats.sac = {}
        trace.stats.sac.b = float(target_start_offset_s)
        trace.stats.sac.o = 0.0
        trace.stats.sac.user8 = float(guard_seconds)
        processed += trace
    return processed

def _plot_gf_record_sections(gf_manifest, station_df, depth, output_path, read) -> None:
    import matplotlib.pyplot as plt

    distances = station_df.set_index("station_id").apply(
        lambda row: float(row.get("distance", row.get("distance_km"))), axis=1
    ).to_dict()
    fig, axes = plt.subplots(2, 5, figsize=(18, 8), dpi=170, sharex=True, constrained_layout=True)
    for axis, basis in zip(axes.flat, _HERRMANN_BASES):
        subset = gf_manifest.loc[gf_manifest["basis"] == basis].sort_values("distance_km")
        for row in subset.itertuples(index=False):
            trace = read(row.path, format="SAC")[0]
            amplitude = np.nanmax(np.abs(trace.data))
            values = trace.data / amplitude if amplitude > 0 else trace.data
            distance = distances.get(row.station_id, row.distance_km)
            axis.plot(trace.times(), values + distance, linewidth=0.6)
        axis.set_title(basis)
        axis.set_xlabel("Time (s)")
        axis.set_ylabel("Distance (km)")
    fig.suptitle(f"pyFK Herrmann basis Green's functions: depth {depth:.4f} km")
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)



def _plot_tensor_gf_record_sections(
    gf_manifest, station_df, depth, output_path, read
) -> None:
    """Plot normalized record sections for the 18 Cartesian tensor GF files."""
    import matplotlib.pyplot as plt

    distances = station_df.set_index("station_id").apply(
        lambda row: float(row.get("distance", row.get("distance_km"))), axis=1
    ).to_dict()
    fig, axes = plt.subplots(
        3, 6, figsize=(20, 10), dpi=170, sharex=True, constrained_layout=True
    )
    for axis, basis in zip(axes.flat, _TENSOR_BASES):
        subset = gf_manifest.loc[
            gf_manifest["basis"] == basis
        ].sort_values("distance_km")
        for row in subset.itertuples(index=False):
            trace = read(row.path, format="SAC")[0]
            amplitude = np.nanmax(np.abs(trace.data))
            values = trace.data / amplitude if amplitude > 0 else trace.data
            distance = distances.get(row.station_id, row.distance_km)
            axis.plot(trace.times(), values + distance, linewidth=0.6)
        axis.set_title(basis)
        axis.set_xlabel("Time (s)")
        axis.set_ylabel("Distance (km)")
    fig.suptitle(
        f"Syngine MTtime tensor Green's functions: depth {depth:.4f} km"
    )
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)

def _resolve_mtinv_components(components: str) -> tuple[str, str | None]:
    """Resolve helper-level component selection to MTtime header semantics.

    MTtime accepts ``Z`` or the complete ``ZRT`` set for Herrmann radial/transverse
    inversions, while component subsets are selected through each station's
    three-character ``used`` mask. ``ZR`` is therefore represented as a ``ZRT``
    header plus the mask ``110``.
    """
    selection = str(components).strip().upper()
    if selection == "Z":
        return "Z", None
    if selection == "ZRT":
        return "ZRT", None
    if selection == "ZR":
        return "ZRT", "110"
    raise ValueError("components must be 'Z', 'ZR' or 'ZRT'.")


def _intersect_used_mask(value, active_mask: str) -> str:
    """Intersect one MTtime ``used`` flag with a three-component ZRT mask."""
    normalized = _normalize_used_flag(value)
    mask = str(active_mask).strip()
    if len(mask) != 3 or not set(mask).issubset({"0", "1"}):
        raise ValueError("active_mask must be a three-character ZRT binary mask.")

    expanded = {"0": "000", "1": "111"}.get(normalized, normalized)
    return "".join(
        "1" if current == "1" and active == "1" else "0"
        for current, active in zip(expanded, mask)
    )


def _normalize_used_flag(value) -> str:
    """Normalize one MTtime station-use flag.

    MTtime accepts ``0`` or ``1`` for prediction/all available components and a
    three-character binary mask ordered as ZRT (for example ``110``). Numeric
    values read back from CSV such as ``1.0`` are normalized safely.
    """
    if isinstance(value, (int, np.integer)):
        text = str(int(value))
    elif isinstance(value, (float, np.floating)):
        if not np.isfinite(value) or not float(value).is_integer():
            raise ValueError(f"Invalid MTtime used flag {value!r}.")
        text = str(int(value))
    else:
        text = str(value).strip()
        if text.endswith(".0"):
            try:
                numeric = float(text)
            except ValueError:
                numeric = np.nan
            if np.isfinite(numeric) and numeric.is_integer():
                text = str(int(numeric))

    if text in {"0", "1"}:
        return text
    if len(text) == 3 and set(text).issubset({"0", "1"}):
        return text
    raise ValueError(
        f"Invalid MTtime used flag {value!r}; expected 0, 1 or a ZRT mask such as 110."
    )


def _normalize_station_selector(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, tuple) and len(value) == 3:
        network, station, location = value
        return f"{network}.{station}.{location or '--'}"
    raise TypeError("drop_stations entries must be station_id strings or (network, station, location) tuples.")


def _resolve_from_config(config_root: Path, path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else config_root / path


def _column_from_aliases(table: pd.DataFrame, aliases: Sequence[str]) -> pd.Series:
    for alias in aliases:
        if alias in table:
            return table[alias].to_numpy(copy=True)
    raise KeyError(f"Station table is missing one of the required columns: {aliases}.")


def _validate_mtinv_files(
    table,
    gf_manifest,
    depths,
    components,
    data_root,
    green_root,
    *,
    catalog_origin,
    reference_time,
    correlate: bool,
    green: str,
    read,
) -> None:
    """Read and validate observation/GF timing for one selected reference."""
    if not data_root.is_dir():
        raise FileNotFoundError(
            f"Observed-data directory does not exist: {data_root}"
        )
    if not green_root.is_dir():
        raise FileNotFoundError(
            f"Green's-function directory does not exist: {green_root}"
        )

    green = str(green).strip().lower()
    if green == "herrmann":
        basis_order = _HERRMANN_BASES
    elif green == "tensor":
        basis_order = _TENSOR_BASES
    else:
        raise ValueError(
            f"Unsupported Green's-function format {green!r}."
        )
    basis_set = set(basis_order)
    manifest_depth_col = (
        "requested_depth_km"
        if "requested_depth_km" in gf_manifest
        else "source_depth_km"
    )

    for row in table.itertuples(index=False):
        station_id = str(row.station_id)
        origin_ts = int(row.origin_ts)
        reference_ts = int(row.ts)
        station_npts = int(row.npts)
        station_dt = float(row.dt)
        expected_observed_start = catalog_origin - origin_ts * station_dt
        expected_reference = catalog_origin + (
            reference_ts - origin_ts
        ) * station_dt
        tolerance = max(1e-3, 0.01 * station_dt)

        if abs(expected_reference - reference_time) > tolerance:
            raise ValueError(
                f"Station {station_id} resolves to reference time "
                f"{expected_reference}, expected {reference_time}."
            )

        expected_azimuth = float(
            getattr(row, "azimuth_deg", getattr(row, "azimuth", np.nan))
        )
        expected_margin_samples = int(
            getattr(row, "correlation_max_shift_samples", 0)
        )
        observed_npts = None
        observed_start = None
        observed_margin_samples = []

        for component in components:
            path = data_root / f"{station_id}.{component}.dat"
            if not path.exists():
                raise FileNotFoundError(f"Missing observed data file: {path}")
            stream = read(str(path), format="SAC")
            if len(stream) != 1:
                raise ValueError(
                    f"Observed file {path} contains {len(stream)} traces."
                )
            trace = stream[0]
            if not _sample_interval_matches(trace.stats.delta, station_dt):
                raise ValueError(
                    f"Observed file {path} has dt={trace.stats.delta}, "
                    f"expected {station_dt}."
                )
            if int(trace.stats.npts) < reference_ts + station_npts:
                raise ValueError(
                    f"Observed file {path} has {trace.stats.npts} samples but "
                    f"MTtime requires at least reference_ts+npts="
                    f"{reference_ts + station_npts}."
                )
            if not np.isfinite(trace.data).all():
                raise ValueError(
                    f"Observed file {path} contains non-finite samples."
                )
            if abs(trace.stats.starttime - expected_observed_start) > tolerance:
                raise ValueError(
                    f"Observed file {path} is not catalog-origin aligned: "
                    "start + origin_ts*dt does not equal catalog origin."
                )
            if abs(
                trace.stats.starttime + reference_ts * station_dt - reference_time
            ) > tolerance:
                raise ValueError(
                    f"Observed file {path} does not align reference_ts with the "
                    "selected global reference time."
                )

            sac = getattr(trace.stats, "sac", None)
            if sac is None:
                raise ValueError(f"Observed file {path} has no SAC headers.")
            b = float(_sac_header_value(sac, "b", np.nan))
            if np.isfinite(b) and not np.isclose(
                b + origin_ts * station_dt,
                0.0,
                atol=tolerance,
                rtol=0.0,
            ):
                raise ValueError(
                    f"Observed SAC header b in {path} is inconsistent with "
                    "catalog-origin origin_ts."
                )

            expected_cmpaz = {
                "Z": 0.0,
                "R": expected_azimuth % 360.0,
                "T": (expected_azimuth + 90.0) % 360.0,
            }[component]
            expected_cmpinc = 0.0 if component == "Z" else 90.0
            cmpaz = float(_sac_header_value(sac, "cmpaz", np.nan))
            cmpinc = float(_sac_header_value(sac, "cmpinc", np.nan))
            angular_error = abs(
                ((cmpaz - expected_cmpaz + 180.0) % 360.0) - 180.0
            )
            if not np.isfinite(cmpaz) or angular_error > 1e-3:
                raise ValueError(
                    f"Observed SAC cmpaz in {path} is {cmpaz}, expected "
                    f"{expected_cmpaz:.6f} degrees for component {component}."
                )
            if not np.isfinite(cmpinc) or not np.isclose(
                cmpinc, expected_cmpinc, atol=1e-3, rtol=0.0
            ):
                raise ValueError(
                    f"Observed SAC cmpinc in {path} is {cmpinc}, expected "
                    f"{expected_cmpinc:.6f} degrees for component {component}."
                )

            margin_seconds = float(
                _sac_header_value(sac, "user9", np.nan)
            )
            margin_float = margin_seconds / station_dt
            margin_samples = (
                int(round(margin_float)) if np.isfinite(margin_float) else -1
            )
            if (
                not np.isfinite(margin_seconds)
                or margin_seconds < 0
                or not np.isclose(
                    margin_float, margin_samples, atol=1e-8, rtol=0.0
                )
            ):
                raise ValueError(
                    f"Observed SAC user9 in {path} does not contain a valid "
                    "correlation margin."
                )
            observed_margin_samples.append(margin_samples)

            if observed_npts is None:
                observed_npts = int(trace.stats.npts)
                observed_start = trace.stats.starttime
            elif int(trace.stats.npts) != observed_npts or abs(
                trace.stats.starttime - observed_start
            ) > tolerance:
                raise ValueError(
                    f"Observed Z/R/T files for {station_id} do not share one "
                    "sample grid and record length."
                )

        if not observed_margin_samples or len(set(observed_margin_samples)) != 1:
            raise ValueError(
                f"Observed Z/R/T files for {station_id} have inconsistent "
                f"correlation margins: {observed_margin_samples}."
            )
        if observed_margin_samples[0] != expected_margin_samples:
            raise ValueError(
                f"Observed SAC correlation margin for {station_id} is "
                f"{observed_margin_samples[0]} samples, expected "
                f"{expected_margin_samples}."
            )

        if correlate:
            margin = expected_margin_samples
            before = reference_ts
            after = int(observed_npts) - (reference_ts + station_npts)
            if margin <= 0 or before < margin or after < margin:
                raise ValueError(
                    f"Station {station_id} lacks the requested symmetric "
                    "correlation margin around the selected reference: "
                    f"before={before}, after={after}, required={margin}."
                )

        for depth in depths:
            subset = gf_manifest.loc[
                (gf_manifest["station_id"].astype(str) == station_id)
                & np.isclose(
                    gf_manifest[manifest_depth_col].astype(float), depth
                )
            ]
            present = (
                set(subset["basis"].astype(str))
                if "basis" in subset else set()
            )
            missing = basis_set.difference(present)
            if missing:
                raise FileNotFoundError(
                    f"Station {station_id}, depth {depth:.4f}: "
                    f"missing manifest bases {sorted(missing)}."
                )
            if "npts" in subset:
                manifest_npts = pd.to_numeric(
                    subset["npts"], errors="raise"
                ).unique()
                if (
                    len(manifest_npts) != 1
                    or int(manifest_npts[0]) != station_npts
                ):
                    raise ValueError(
                        f"Station {station_id}, depth {depth:.4f}: GF manifest "
                        f"npts {manifest_npts.tolist()} does not match "
                        f"npts={station_npts}."
                    )
            if "dt_s" in subset:
                manifest_dt = pd.to_numeric(
                    subset["dt_s"], errors="raise"
                ).unique()
                if (
                    len(manifest_dt) != 1
                    or not _sample_interval_matches(
                        float(manifest_dt[0]), station_dt
                    )
                ):
                    raise ValueError(
                        f"Station {station_id}, depth {depth:.4f}: GF manifest "
                        f"dt {manifest_dt.tolist()} does not match dt={station_dt}."
                    )

            for basis in basis_order:
                path = green_root / f"{station_id}.{depth:.4f}.{basis}"
                if not path.exists():
                    raise FileNotFoundError(
                        f"Missing Green's-function file: {path}"
                    )
                stream = read(str(path), format="SAC")
                if len(stream) != 1:
                    raise ValueError(
                        f"Green's-function file {path} contains "
                        f"{len(stream)} traces."
                    )
                trace = stream[0]
                if int(trace.stats.npts) != station_npts:
                    raise ValueError(
                        f"Green's-function file {path} has "
                        f"npts={trace.stats.npts}; expected {station_npts}."
                    )
                if not _sample_interval_matches(
                    trace.stats.delta, station_dt
                ):
                    raise ValueError(
                        f"Green's-function file {path} has "
                        f"dt={trace.stats.delta}; expected {station_dt}."
                    )
                if not np.isfinite(trace.data).all():
                    raise ValueError(
                        f"Green's-function file {path} contains non-finite "
                        "samples."
                    )
                sac = getattr(trace.stats, "sac", None)
                if sac is not None:
                    b = float(_sac_header_value(sac, "b", np.nan))
                    if np.isfinite(b) and not np.isclose(
                        b,
                        0.0,
                        atol=max(1e-3, 0.01 * station_dt),
                        rtol=0.0,
                    ):
                        raise ValueError(
                            f"Green's-function file {path} does not start at "
                            "source-reference time zero (SAC b != 0)."
                        )


# ---------------------------------------------------------------------------
# CMT summary figure
# ---------------------------------------------------------------------------

def _mttime_cmt_inputs(inversion) -> tuple[dict[str, float], dict[str, float], str]:
    """Translate the preferred MTtime tensor into ``plot_cmt_summary`` inputs."""
    tensor = inversion.get_preferred_tensor()
    if tensor is None:
        raise RuntimeError("MTtime has no preferred tensor for the CMT plot.")

    elements = tensor.get_tensor_elements(basis="RTP")
    required = ("MRR", "MTT", "MPP", "MRT", "MRP", "MTP")
    missing = [name for name in required if name not in elements]
    if missing:
        raise RuntimeError(f"Preferred MTtime tensor is missing RTP components: {missing}.")

    fps = list(getattr(tensor, "fps", []) or [])
    if len(fps) < 2:
        raise RuntimeError("Preferred MTtime tensor does not contain two nodal planes.")
    fp1, fp2 = fps[:2]

    # MTtime stores tensor components and scalar moment in dyne-cm; the CMT
    # figure reports SI N*m.  1 dyne-cm = 1e-7 N*m.
    dyne_cm_to_nm = 1.0e-7
    summary = {
        "Mrr": float(elements["MRR"]) * dyne_cm_to_nm,
        "Mtt": float(elements["MTT"]) * dyne_cm_to_nm,
        "Mpp": float(elements["MPP"]) * dyne_cm_to_nm,
        "Mrt": float(elements["MRT"]) * dyne_cm_to_nm,
        "Mrp": float(elements["MRP"]) * dyne_cm_to_nm,
        "Mtp": float(elements["MTP"]) * dyne_cm_to_nm,
        "M0_Nm": float(getattr(tensor, "mo", np.nan)) * dyne_cm_to_nm,
        "Mw": float(getattr(tensor, "mw", np.nan)),
        "DC_percent": float(getattr(tensor, "pdc", np.nan)),
        "CLVD_percent": float(getattr(tensor, "pclvd", np.nan)),
        "ISO_percent": float(getattr(tensor, "piso", np.nan)),
        # plot_cmt_summary consumes VR as a fraction, while MTtime stores %.
        "variance_reduction": float(getattr(tensor, "total_VR", np.nan)) / 100.0,
        "NP1_strike_deg": float(fp1[0]),
        "NP1_dip_deg": float(fp1[1]),
        "NP1_rake_deg": float(fp1[2]),
        "NP2_strike_deg": float(fp2[0]),
        "NP2_dip_deg": float(fp2[1]),
        "NP2_rake_deg": float(fp2[2]),
    }
    centroid = {"centroid_depth_km": float(tensor.depth)}
    tensor_mode = "full" if int(inversion.config.degree) == 6 else "deviatoric"
    return summary, centroid, tensor_mode


def plot_cmt_summary(
    summary,
    centroid,
    uncertainty=None,
    *,
    tensor_mode="full",
    facecolor="white",
    bgcolor="red",
    show_dc_overlay=True,
    figsize=(11.5, 6.2),
    dpi=300,
    output_file=None,
    show=False,
):
    """
    Plot a publication-style centroid moment-tensor solution summary.

    The figure combines a preferred solution with a zero-trace beachball, P/T
    labels, a DC nodal-plane overlay, source and quality metrics, moment-tensor
    components, nodal planes and principal axes. It is used by the MTtime helper
    ``plot_views=(..., "cmt")`` route but remains callable directly. For a full
    six-component solution the component table retains the full tensor and ISO
    percentage while the beachball/principal axes use the zero-trace tensor; for
    a deviatoric five-component solution ISO is reported as constrained to zero.

    The beachball fill colours are controlled independently through ``facecolor``
    and ``bgcolor``. Their defaults are white and red, respectively, providing
    the preferred visual polarity convention for this summary figure without
    altering or negating the moment tensor.

    Parameters
    ----------
    summary : mapping, pandas.Series, or one-row pandas.DataFrame
        Solution summary containing ``Mrr``, ``Mtt``, ``Mpp``, ``Mrt``, ``Mrp``,
        ``Mtp``, ``M0_Nm``, ``Mw``, ``DC_percent``, ``CLVD_percent``,
        ``ISO_percent``, ``variance_reduction`` and both NP1/NP2 strike/dip/rake
        triplets. ``condition_number`` is optional. Tensor components use the RTP
        convention and moments are in N·m.

    centroid : mapping, pandas.Series, or one-row pandas.DataFrame
        Preferred centroid information. ``centroid_depth_km`` is required.

    uncertainty : optional
        Retained for backward call compatibility and intentionally ignored.

    tensor_mode : {"full", "deviatoric"}
        Inversion type that produced ``summary``. ``"full"`` denotes the native
        six-component inversion, whereas ``"deviatoric"`` denotes the
        five-component zero-trace inversion. This controls source reporting and
        decomposition interpretation. The beachball itself is plotted zero-trace
        in both modes using ObsPy's zero-trace tensor-display convention; its
        colour assignment is controlled separately by
        ``facecolor`` and ``bgcolor``.

    facecolor : matplotlib color, default="white"
        Foreground beachball colour passed directly to ObsPy ``beach`` as
        ``facecolor``. Together with the default red ``bgcolor``, this defines
        the preferred fill convention used by the summary figure. The moment
        tensor itself is not negated or otherwise modified.

    bgcolor : matplotlib color, default="red"
        Background beachball colour passed directly to ObsPy ``beach`` as
        ``bgcolor``. The default red background combined with white
        ``facecolor`` intentionally sets the preferred visual colour assignment
        while leaving the moment-tensor geometry and P/T axes
        unchanged.

    show_dc_overlay : bool, default=True
        Overlay the double-couple nodal-plane geometry derived from NP1. For a
        non-pure-DC solution these curves need not coincide exactly with the
        zero-trace moment-tensor beachball boundaries; the overlay is retained as
        a useful visual comparison with the decomposed DC mechanism.

    figsize : tuple, default=(11.5, 6.2)
        Matplotlib figure size in inches.

    dpi : int, default=300
        Figure resolution.

    output_file : str or pathlib.Path, optional
        Save the figure to this path. Parent directories are created as needed.

    show : bool, default=False
        Display the figure. In IPython/Jupyter, ``display(fig)`` is used so an
        Agg backend does not emit a non-interactive ``plt.show`` warning.

    Returns
    -------
    matplotlib.figure.Figure
        Generated CMT summary figure.
    """
    import matplotlib.pyplot as plt
    from obspy.imaging.beachball import beach, MomentTensor, mt2axes

    def as_record(obj, name):
        if isinstance(obj, pd.DataFrame):
            if len(obj) != 1:
                raise ValueError(f"{name} must contain exactly one row.")
            return obj.iloc[0].to_dict()
        if isinstance(obj, pd.Series):
            return obj.to_dict()
        return dict(obj)

    def format_value(value, fmt, unit=""):
        return f"{format(float(value), fmt)}{unit}"

    def format_scientific(value, unit=""):
        return f"{float(value):.3e}{unit}"

    def project_axis(axis):
        azimuth = np.deg2rad(axis.strike)
        radius = np.sqrt(2.0) * np.sin(np.deg2rad((90.0 - axis.dip) / 2.0))
        return radius * np.sin(azimuth), radius * np.cos(azimuth)

    def rim_xy(azimuth, radius=1.0):
        azimuth = np.deg2rad(azimuth)
        return radius * np.sin(azimuth), radius * np.cos(azimuth)

    def choose_plane_label_azimuths(strike1, strike2):
        candidates1 = (strike1 % 360.0, (strike1 + 180.0) % 360.0)
        candidates2 = (strike2 % 360.0, (strike2 + 180.0) % 360.0)
        best_pair, best_distance = None, -np.inf
        for az1 in candidates1:
            for az2 in candidates2:
                distance = np.linalg.norm(np.asarray(rim_xy(az1)) - np.asarray(rim_xy(az2)))
                if distance > best_distance:
                    best_pair, best_distance = (az1, az2), distance
        return best_pair

    def style_table(table, *, first_col_bold=False, header=True, fontsize=9):
        table.auto_set_font_size(False)
        table.set_fontsize(fontsize)
        for (row, col), cell in table.get_celld().items():
            cell.set_edgecolor("0.72")
            cell.set_linewidth(0.55)
            cell.visible_edges = "B"
            if header and row == 0:
                cell.get_text().set_fontweight("bold")
            if first_col_bold and col == 0 and (not header or row > 0):
                cell.get_text().set_fontweight("bold")

    summary = as_record(summary, "summary")
    centroid = as_record(centroid, "centroid")
    tensor_mode = str(tensor_mode).lower().strip()
    if tensor_mode not in {"full", "deviatoric"}:
        raise ValueError("tensor_mode must be 'full' or 'deviatoric'.")

    mt = np.array([
        summary["Mrr"], summary["Mtt"], summary["Mpp"],
        summary["Mrt"], summary["Mrp"], summary["Mtp"],
    ], dtype=float)

    # Use the zero-trace tensor for the focal mechanism and principal axes while
    # retaining the full six components in the numerical table when requested.
    mt_plot = mt.copy()
    mt_plot[:3] -= np.mean(mt_plot[:3])

    if tensor_mode == "deviatoric":
        tensor_label = "Deviatoric (5-component)"
        mt_table_values = mt_plot
    else:
        tensor_label = "Full MT (6-component)"
        mt_table_values = mt

    mt_obj = MomentTensor(*mt_plot, 0)
    T, N, P = mt2axes(mt_obj)

    fig = plt.figure(figsize=figsize, dpi=dpi, constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=(1.05, 1.25))
    ax_ball = fig.add_subplot(gs[0])
    ax_info = fig.add_subplot(gs[1])
    ax_info.axis("off")

    ball = beach(
        mt_plot,
        xy=(0, 0),
        width=2.0,
        size=300,
        linewidth=1.15,
        facecolor=facecolor,
        bgcolor=bgcolor,
        edgecolor="black",
        zorder=1,
    )
    ax_ball.add_collection(ball)

    if show_dc_overlay:
        planes = beach(
            (summary["NP1_strike_deg"], summary["NP1_dip_deg"], summary["NP1_rake_deg"]),
            xy=(0, 0), width=2.0, size=300, linewidth=0.65,
            nofill=True, edgecolor="0.35", zorder=2,
        )
        ax_ball.add_collection(planes)

    for label, axis in (("P", P), ("T", T)):
        x, y = project_axis(axis)
        ax_ball.text(x, y, label, ha="center", va="center", fontsize=15, zorder=5)

    if show_dc_overlay:
        np1_az, np2_az = choose_plane_label_azimuths(summary["NP1_strike_deg"], summary["NP2_strike_deg"])
        for label, azimuth in (("NP1", np1_az), ("NP2", np2_az)):
            x0, y0 = rim_xy(azimuth, 1.00)
            x1, y1 = rim_xy(azimuth, 1.11)
            ax_ball.annotate(
                label, xy=(x0, y0), xytext=(x1, y1),
                ha="left" if x1 >= 0 else "right", va="center", fontsize=9,
                annotation_clip=False,
                arrowprops={"arrowstyle": "-", "linewidth": 0.7, "shrinkA": 2, "shrinkB": 0},
                zorder=6,
            )

    ax_ball.set_xlim(-1.18, 1.18)
    ax_ball.set_ylim(-1.18, 1.18)
    ax_ball.set_aspect("equal")
    ax_ball.axis("off")
    ax_ball.set_title("Centroid Moment Tensor", fontsize=13, pad=10)

    depth_text = format_value(centroid["centroid_depth_km"], ".1f", " km")
    moment_text = format_scientific(summary["M0_Nm"], " N·m")
    magnitude_text = format_value(summary["Mw"], ".2f", " Mw")
    dc_text = format_value(summary["DC_percent"], ".1f", "%")
    clvd_text = format_value(summary["CLVD_percent"], ".1f", "%")
    iso_text = (
        format_value(summary["ISO_percent"], ".1f", "%")
        if tensor_mode == "full" else "0.0% (constrained)"
    )
    vr = float(summary["variance_reduction"])

    source_rows = [
        ["Tensor", tensor_label],
        ["Moment", moment_text],
        ["Magnitude", magnitude_text],
        ["Centroid depth", depth_text],
        ["DC", dc_text],
        ["CLVD", clvd_text],
        ["ISO", iso_text],
        ["Variance reduction", f"{100.0 * vr:.1f}%"],
    ]
    condition_number = summary.get("condition_number")
    if condition_number is not None and np.isfinite(float(condition_number)):
        source_rows.append(["Condition number", f"{float(condition_number):.2f}"])

    ax_info.text(0.0, 0.98, "Source", fontsize=12, fontweight="bold", transform=ax_info.transAxes)
    source_table = ax_info.table(
        cellText=source_rows, cellLoc="left", colWidths=[0.42, 0.56],
        bbox=[0.0, 0.62, 1.0, 0.32],
    )
    style_table(source_table, first_col_bold=True, header=False, fontsize=9.2)

    ax_info.text(
        0.0, 0.575, "Moment Tensor Components (N·m)",
        fontsize=11, fontweight="bold", transform=ax_info.transAxes,
    )
    mt_rows = [
        ["Mrr", f"{mt_table_values[0]:.2e}", "Mtt", f"{mt_table_values[1]:.2e}", "Mpp", f"{mt_table_values[2]:.2e}"],
        ["Mrt", f"{mt_table_values[3]:.2e}", "Mrp", f"{mt_table_values[4]:.2e}", "Mtp", f"{mt_table_values[5]:.2e}"],
    ]
    mt_table = ax_info.table(
        cellText=mt_rows, cellLoc="center",
        colWidths=[0.09, 0.23, 0.09, 0.23, 0.09, 0.23],
        bbox=[0.0, 0.448, 1.0, 0.10],
    )
    mt_table.auto_set_font_size(False)
    mt_table.set_fontsize(8.6)
    for (row, col), cell in mt_table.get_celld().items():
        cell.set_edgecolor("0.75")
        cell.set_linewidth(0.5)
        cell.visible_edges = "B"
        if col in (0, 2, 4):
            cell.get_text().set_fontweight("bold")

    ax_info.text(0.0, 0.375, "Nodal Planes", fontsize=11, fontweight="bold", transform=ax_info.transAxes)
    nodal_rows = [
        ["NP1", f"{summary['NP1_strike_deg']:.1f}°", f"{summary['NP1_dip_deg']:.1f}°", f"{summary['NP1_rake_deg']:.1f}°"],
        ["NP2", f"{summary['NP2_strike_deg']:.1f}°", f"{summary['NP2_dip_deg']:.1f}°", f"{summary['NP2_rake_deg']:.1f}°"],
    ]
    nodal_table = ax_info.table(
        cellText=nodal_rows, colLabels=["Plane", "Strike", "Dip", "Rake"],
        cellLoc="center", colLoc="center", bbox=[0.0, 0.075, 0.47, 0.265],
    )
    style_table(nodal_table, header=True, fontsize=8.4)

    ax_info.text(0.52, 0.375, "Principal Axes", fontsize=11, fontweight="bold", transform=ax_info.transAxes)
    axis_rows = [
        ["T", f"{T.val:.2e}", f"{T.dip:.1f}°", f"{T.strike:.1f}°"],
        ["N", f"{N.val:.2e}", f"{N.dip:.1f}°", f"{N.strike:.1f}°"],
        ["P", f"{P.val:.2e}", f"{P.dip:.1f}°", f"{P.strike:.1f}°"],
    ]
    axes_table = ax_info.table(
        cellText=axis_rows, colLabels=["Axis", "Value (N·m)", "Plunge", "Azimuth"],
        cellLoc="center", colLoc="center", bbox=[0.52, 0.075, 0.48, 0.265],
    )
    style_table(axes_table, header=True, fontsize=8.0)

    if output_file is not None:
        output_file = Path(output_file).expanduser()
        output_file.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_file, bbox_inches="tight")

    if show:
        try:
            from IPython import get_ipython
            from IPython.display import display
            if get_ipython() is not None:
                display(fig)
            else:
                plt.show()
        except ImportError:
            plt.show()

    return fig