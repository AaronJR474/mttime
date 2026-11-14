"""End-to-end SAC and jackknife regressions for the public workflow."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from obspy import Stream, Trace, UTCDateTime, read
from obspy.core.inventory import Channel, Inventory, Network, Station
from obspy.core.inventory.response import Response

from mttime.workflows import mttime_helpers as mh


@pytest.fixture
def tensor_case(tmp_path):
    """Synthesize six independent basis responses and a known XYZ tensor."""
    origin = UTCDateTime("2020-01-01")
    event = dict(event_id="0001", origin_time=str(origin), event_lon=172.0,
                 event_lat=-44.0, event_depth_km=8.0, magnitude=5.0)
    green_root = tmp_path / "external greens"
    data_root = tmp_path / "observed data"
    green_root.mkdir()
    data_root.mkdir()
    rng = np.random.default_rng(284)
    moment = np.array([0.6, -0.35, 0.2, 0.1, 0.42, -0.3])
    rows, records = [], []
    basis_order = ("xx", "yy", "zz", "xy", "xz", "yz")
    for index, azimuth in enumerate([0., 25., 45., 90., 135., 180., 225., 270., 315.]):
        station_id = f"NZ.S{index:02d}.01"
        npts = 64 + index
        dt = 0.5
        origin_ts = 8
        stored_npts = npts + 16
        basis_values = rng.normal(size=(3, 6, npts))
        rows.append(dict(
            station_id=station_id, distance_km=10.0 + 2 * index, azimuth_deg=azimuth,
            station_lon=172.0, station_lat=-44.0, channel_prefix="LH" if index == 0 else "HH",
            used={7: "000", 8: "110"}.get(index, "111"),
            ts=origin_ts, origin_ts=origin_ts, npts=npts, stored_npts=stored_npts,
            dt=dt, max_reference_time_shift=1.0, correlation_max_shift_samples=2,
            motion="VEL", units="cm/s", freqmin=0.02, freqmax=0.05, corners=3,
        ))
        for component_index, component in enumerate("ZRT"):
            signal = basis_values[component_index].T @ moment
            observed = rng.normal(scale=0.01, size=stored_npts)
            observed[origin_ts + 2:origin_ts + 2 + npts] += signal
            Trace(observed.astype("f4"), header=dict(
                channel=component, delta=dt, starttime=origin - origin_ts * dt,
                sac=dict(cmpaz={"Z": 0., "R": azimuth, "T": (azimuth + 90.) % 360.}[component],
                         cmpinc=0. if component == "Z" else 90., b=-origin_ts * dt, user9=1.0),
            )).write(str(data_root / f"{station_id}.{component}.dat"), format="SAC")
            for depth in (8.0, 10.0):
                values = basis_values[component_index] if depth == 8.0 else rng.normal(size=(6, npts))
                for basis, trace in zip(basis_order, values):
                    name = f"{component}{basis}"
                    path = green_root / f"{station_id}.{depth:.4f}.{name}"
                    Trace(trace.astype("f4"), header=dict(delta=dt, sac=dict(b=0.))).write(str(path), format="SAC")
                    records.append(dict(
                        station_id=station_id, requested_depth_km=depth, basis=name, path=str(path),
                        green="tensor", npts=npts, dt_s=dt, motion="VEL", units="cm/s",
                        freqmin=0.02, freqmax=0.05, corners=3, reference_moment_nm=1e13,
                    ))
    return event, pd.DataFrame(rows), pd.DataFrame(records), data_root, green_root


def test_station_selection_respects_channels_sectors_and_masks(tensor_case, tmp_path):
    event, stations, manifest, data, green = tensor_case
    controls = dict(azimuth_selection=True, azimuth_min_sectors=3,
                    azimuth_max_stations_per_sector=1, minimum_stations=4)
    configured, inv, _, _, products = mh.run_mttime_inversion(
        event, stations, manifest, output_file=tmp_path / "mtinv.in", path_to_data=data,
        path_to_green=green, components="ZR", degree=6, reference_time_shift=1.0,
        drop_stations=["S03", ("NZ", "S06", "01")], azimuth_control=controls,
        channel_priority=("HH", "LH"), plot_views=(), write_option=None,
    )
    audit = inv.station_selection.set_index("station_id")
    assert audit.loc["NZ.S00.01", "selection_status"] == "azimuth_excluded"
    assert audit.loc["NZ.S03.01", "selection_status"] == "manual_drop"
    assert audit.loc["NZ.S06.01", "selection_status"] == "manual_drop"
    assert audit.loc["NZ.S07.01", "selection_status"] == "prediction_only"
    assert audit.loc["NZ.S08.01", "used_components"] == "ZR"
    assert len(configured) == 6
    assert (tmp_path / "results" / "station_selection.csv").is_file()
    assert "station_selection" in set(products["view"])
    duplicate_code = stations.iloc[[3]].assign(station_id="XY.S03.01")
    with pytest.raises(ValueError, match="ambiguous"):
        mh._resolve_station_drops(pd.concat([stations, duplicate_code])["station_id"], "S03")
    with pytest.raises(ValueError, match="occupied sectors"):
        mh._select_inversion_stations(
            stations, "ZR", None,
            mh._normalize_azimuth_control({"azimuth_min_sectors": 8}), ("HH", "LH"),
        )


@pytest.mark.parametrize("degree,weight,correlate", [
    (5, "variance", True), (6, "distance", False), (6, "none", False),
])
def test_single_station_jackknife_matches_direct_refit(tensor_case, tmp_path, degree, weight, correlate):
    event, stations, manifest, data, green = tensor_case
    args = dict(path_to_data=data, path_to_green=green, degree=degree, weight=weight,
                correlate=correlate, components="ZR", reference_time_shift=1.0,
                plot_views=(), write_option=None)
    _, inv, _, _, _ = mh.run_mttime_inversion(
        event, stations, manifest, output_file=tmp_path / "parent" / "mtinv.in",
        station_jackknife={"jackknife_min_stations": 4}, **args,
    )
    checks = inv.station_jackknife
    assert len(checks) == len(stations) - 1
    assert "NZ.S07.01" not in set(checks["station_id"])
    assert set(checks["status"]) == {"ok"}
    assert (tmp_path / "parent" / "results" / "station_jackknife.csv").is_file()
    for row in (checks.iloc[0], checks.iloc[-1]):
        _, _, direct, _, _ = mh.run_mttime_inversion(
            event, stations, manifest, output_file=tmp_path / "direct" / "mtinv.in",
            drop_stations=[row["station_id"]], save_tables=False, **args,
        )
        expected = direct.loc[direct["preferred"]].iloc[0]
        np.testing.assert_allclose(
            [row["loo_depth_km"], row["loo_mw"], row["loo_total_vr_percent"]],
            [expected["depth_km"], expected["mw"], expected["total_vr_percent"]],
            rtol=1e-10, atol=1e-8,
        )
        for column in mh._RESAMPLING_TENSOR_COLUMNS:
            assert row[f"loo_{column}"] == pytest.approx(expected[column], rel=1e-9)


def test_shift_scan_freezes_stations_and_searches_each_omission(tensor_case, tmp_path, monkeypatch):
    event, stations, manifest, data, green = tensor_case
    influential = "NZ.S01.01"
    moment = np.array([0.6, -0.35, 0.2, 0.1, 0.42, -0.3])
    for component in "ZRT":
        target = []
        for depth in (8.0, 10.0):
            for basis in ("xx", "yy", "zz", "xy", "xz", "yz"):
                path = green / f"{influential}.{depth:.4f}.{component}{basis}"
                trace = read(str(path))[0]
                trace.data *= 20
                trace.write(str(path), format="SAC")
                if depth == 10.0:
                    target.append(trace.data)
        path = data / f"{influential}.{component}.dat"
        trace = read(str(path))[0]
        trace.data[:] = 0
        series = np.asarray(target).T @ moment
        trace.data[8:8 + len(series)] = series
        trace.write(str(path), format="SAC")
    capture_count = 0
    capture = mh._capture_station_statistics

    def count_capture(inversion, depth):
        nonlocal capture_count
        capture_count += 1
        return capture(inversion, depth)

    monkeypatch.setattr(mh, "_capture_station_statistics", count_capture)
    args = dict(reference_time_shifts=[-1, 0, 1], path_to_data=data, path_to_green=green,
                degree=6, components="ZRT", write_option=None, progress=False)
    summary, solutions, fits, products = mh.mttime_inversion_oshift(
        event, stations, manifest, output_dir=tmp_path / "scan",
        azimuth_control={"azimuth_max_stations_per_sector": 1},
        station_jackknife=True, **args,
    )
    assert capture_count == 6
    best = summary.loc[summary["best_vr_across_shifts"]].iloc[0]
    assert (best["reference_time_shift"], best["depth_km"]) == (0., 10.)
    omitted = next(row for row in summary.attrs["station_jackknife"] if row["station_id"] == influential)
    assert (omitted["loo_reference_time_shift_s"], omitted["loo_depth_km"]) == (1., 8.)
    selected = set(pd.DataFrame(summary.attrs["station_selection"]).query(
        "selection_status in ['selected', 'prediction_only']"
    )["station_id"])
    assert fits.groupby("run_index")["station"].agg(set).tolist() == [selected] * 3
    retained = stations.loc[stations["station_id"].isin(selected - {omitted["station_id"]})]
    direct, *_ = mh.mttime_inversion_oshift(
        event, retained, manifest, output_dir=tmp_path / "direct_scan", save_tables=False, **args,
    )
    assert capture_count == 6
    expected = direct.loc[direct["best_vr_across_shifts"]].iloc[0]
    assert omitted["loo_reference_time_shift_s"] == expected["reference_time_shift"]
    assert omitted["loo_total_vr_percent"] == pytest.approx(expected["total_vr_percent"])
    assert len(solutions) == 6
    assert len(pd.concat([summary, direct])) == 6
    assert (tmp_path / "scan" / "station_jackknife.csv").is_file()
    assert "station_jackknife" in set(products["view"])


def test_opposing_pairs_and_minimum_station_count(tensor_case, tmp_path):
    event, stations, manifest, data, green = tensor_case
    _, inv, _, _, _ = mh.run_mttime_inversion(
        event, stations, manifest, output_file=tmp_path / "mtinv.in", path_to_data=data,
        path_to_green=green, degree=6, reference_time_shift=1.0, plot_views=(),
        write_option=None, save_tables=False,
        station_jackknife=dict(jackknife_opposing_station=True, jackknife_min_stations=7),
    )
    checks = inv.station_jackknife
    assert set(checks["n_omitted_stations"]) == {2}
    assert set(checks["reason"]) == {"insufficient_remaining_stations"}
    assert ((checks["station_id"] == "NZ.S00.01") & (checks["opposing_station_id"] == "NZ.S05.01")).any()
    assert "NZ.S07.01" not in set(checks["opposing_station_id"])


def test_auto_uses_csv_custom_gfs_and_local_station_manifest(tensor_case, tmp_path, monkeypatch):
    event, stations, manifest, data, green = tensor_case
    root = tmp_path / "auto"
    source_stations = tmp_path / "raw_stations.csv"
    stations.assign(event_id=event["event_id"], location="01").to_csv(source_stations, index=False)
    source_gfs = tmp_path / "external_gfs.csv"
    manifest.assign(path=manifest["path"].map(lambda p: str(Path(p).relative_to(tmp_path)))).to_csv(source_gfs, index=False)

    def process(event_df, station_df, *, output_dir, max_reference_time_shift, **settings):
        assert max_reference_time_shift == 1.0
        assert set(station_df["location"]) == {"01"}
        destination = output_dir / "processed" / "data"
        destination.parent.mkdir(parents=True)
        destination.symlink_to(data, target_is_directory=True)
        (output_dir / "metadata").mkdir()
        return None, station_df, pd.DataFrame()

    def unexpected(*args, **kwargs):
        pytest.fail("The local custom-GF route called a download or GF generator.")

    monkeypatch.setattr(mh, "process_mseed_sac", process)
    for name in ("get_mseed_stationxml", "generate_pyfk_gfs", "generate_syngine_gfs"):
        monkeypatch.setattr(mh, name, unexpected)
    result = mh.run_auto_cmt(
        "0001", event["origin_time"], event["event_lon"], event["event_lat"], 8., 5.,
        output_dir=root, waveform_source="local", station_df=source_stations,
        gf_source="custom", gf_options={"manifest": source_gfs}, degree=6, motion="VEL",
        dt=0.5, reference_time_shifts=[0., 1.], station_jackknife=True,
        inversion_options=dict(progress=False, write_option=None),
    )
    assert result["path_to_green"] == green
    assert result["depths_km"] == [8., 10.]
    assert len(result["results"]["station_fit"]) == len(stations)
    assert result["results"]["summary"].iloc[0]["reference_time_shift"] == 1.
    assert set(result["station_jackknife"]["status"]) == {"ok"}
    assert (root / "metadata" / "station_selection.csv").is_file()
    with pytest.raises(ValueError, match="reference"):
        mh._validate_custom_gf_metadata(
            manifest.assign(reference_moment_nm=1e20), event, stations, [8.], green,
        )
    with pytest.raises(ValueError, match="observation geometry"):
        mh._validate_custom_gf_metadata(
            manifest.assign(azimuth_deg=31.), event, stations, [8.], green,
        )


def test_rank_deficient_station_subset_is_skipped():
    normal = np.array([np.eye(6), np.diag([1., 1., 1., 1., 1., 0.])])
    trial = mh._StationStatistics(
        8., 0., normal, np.ones((2, 6)), np.full(2, 8.),
        np.full(2, 12), np.eye(6) * 1e20, "Full",
    )
    assert mh._jackknife_candidate(trial, [1], [0]) is None
    assert mh._jackknife_candidate(trial, [0], [1])["loo_condition_number"] == 1.


class LocalFDSN:
    """Serve a real StationXML inventory and continuous miniSEED from memory."""

    def __init__(self, origin):
        self.origin = origin
        self.requests = []
        channels = []
        for code, dip, azimuth in [("HHZ", -90., 0.), ("HHN", 0., 0.), ("HHE", 0., 90.)]:
            response = Response.from_paz(
                zeros=[0j], poles=[-1 + 1j, -1 - 1j], stage_gain=1.0,
                stage_gain_frequency=1.0, input_units="M/S", output_units="COUNTS",
            )
            channels.append(Channel(
                code=code, location_code="01", latitude=-44.0, longitude=172.6,
                elevation=0., depth=0., azimuth=azimuth, dip=dip, sample_rate=10., response=response,
            ))
        station = Station(code="NEAR", latitude=-44., longitude=172.6, elevation=0., channels=channels)
        self.inventory = Inventory([Network(code="NZ", stations=[station])], source="fixture")

    def get_stations(self, **kwargs):
        return self.inventory

    def get_waveforms(self, *, network, station, location, channel, starttime, endtime, **kwargs):
        self.requests.append((starttime, endtime))
        start = self.origin + np.floor((starttime - self.origin) * 10) / 10
        npts = int(np.ceil((endtime - start) * 10)) + 1
        stream = Stream()
        for index, code in enumerate(channel.split(",")):
            time = (start - self.origin) + np.arange(npts) / 10
            signal = np.sin(2 * np.pi * 0.05 * time + index) * np.exp(-((time - 35) / 20) ** 2)
            stream += Trace(signal.astype("f4"), header=dict(
                network=network, station=station, location=location, channel=code,
                starttime=start, sampling_rate=10.,
            ))
        return stream


def test_default_radius_and_processing_window_use_same_acquisition(tmp_path):
    origin = UTCDateTime("2020-01-01")
    client = LocalFDSN(origin)
    geometry = dict(dt=1., window_start_phase="P", time_before_window_start=60.,
                    window_end_phase="S", time_after_window_end=60., inversion_duration=160.,
                    max_correlation_shift=0., max_reference_time_shift=5., reduction_velocity_km_s=0.)
    args = dict(magnitude=5.9, output_dir=tmp_path, client=client, before_p=10., after_s=20.,
                processing_window=geometry)
    event, stations, _ = mh.get_mseed_stationxml("0002", origin, 172., -44., 8., **args)
    assert event.iloc[0]["min_radius_km"] == 0.
    assert event.iloc[0]["max_radius_km"] == pytest.approx(600.6175, abs=1e-3)
    assert stations.iloc[0]["station_id"] == "NZ.NEAR.01"
    assert stations.iloc[0]["distance_km"] < 100.
    assert client.requests[0][1] >= origin + 164.
    _, reused, _ = mh.get_mseed_stationxml("0002", origin, 172., -44., 8., **args)
    assert len(client.requests) == 1
    assert reused.iloc[0]["download_status"] == "existing"
    processing = {key: value for key, value in geometry.items() if key != "dt"}
    _, processed, log = mh.process_mseed_sac(
        event, stations, output_dir=tmp_path, dt=1., motion="VEL", **processing,
    )
    assert len(processed) == 1, log.to_dict("records")


def test_custom_library_can_use_an_explicit_directory_and_vertical_only(tensor_case, tmp_path):
    event, stations, manifest, data, green = tensor_case
    vertical = manifest.loc[manifest["basis"].str.startswith("Z")].drop(columns="path")
    index = tmp_path / "vertical.csv"
    vertical.to_csv(index, index=False)
    loaded, directory = mh._load_custom_gfs({"manifest": index, "path_to_green": green.name})
    assert directory == green
    _, inv, _, _, _ = mh.run_mttime_inversion(
        event, stations, loaded, output_file=tmp_path / "mtinv.in", path_to_data=data,
        path_to_green=directory, components="Z", degree=6, depths_km=[8.],
        reference_time_shift=1., plot_views=(), write_option=None,
    )
    assert inv.get_preferred_tensor().total_VR > 99.
