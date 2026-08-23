from __future__ import annotations

import queue
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from ypendulum.ui.desktop_app import (
    YPendulumDesktopApp,
    _compact_guard_label,
    _physical_playback_fraction,
    _sphere_faces,
)


class _FakeTree:
    def __init__(self, selected: tuple[str, ...] = ()) -> None:
        self.rows: dict[str, tuple[Any, ...]] = {identifier: () for identifier in selected}
        self.selected = selected
        self.selection_set_calls = 0

    def selection(self) -> tuple[str, ...]:
        return self.selected

    def get_children(self) -> tuple[str, ...]:
        return tuple(self.rows)

    def exists(self, identifier: str) -> bool:
        return identifier in self.rows

    def item(self, identifier: str, *, values: tuple[Any, ...]) -> None:
        self.rows[identifier] = values

    def insert(
        self,
        _parent: str,
        _where: str,
        *,
        iid: str,
        values: tuple[Any, ...],
    ) -> None:
        self.rows[iid] = values

    def delete(self, identifier: str) -> None:
        del self.rows[identifier]

    def selection_set(self, identifier: str) -> None:
        self.selection_set_calls += 1
        self.selected = (identifier,)


class _FakeConfigurable:
    def __init__(self) -> None:
        self.options: dict[str, Any] = {}

    def configure(self, **kwargs: Any) -> None:
        self.options.update(kwargs)


def _record(
    identifier: str,
    output_directory: Path,
    *,
    state: str = "COMPLETED",
) -> SimpleNamespace:
    return SimpleNamespace(
        identifier=identifier,
        label="desktop_case",
        backend="forward",
        state=state,
        submitted_at_utc="2026-08-22T00:00:00+00:00",
        output_directory=str(output_directory),
    )


def test_sphere_faces_keep_physical_radius_during_in_place_motion() -> None:
    centre = np.asarray([0.15, -0.04, 0.63])
    radius = 0.021
    faces = _sphere_faces(centre, radius, longitude_count=8, latitude_count=5)

    assert len(faces) == 8 * 4
    vertices = np.concatenate(faces, axis=0)
    np.testing.assert_allclose(
        np.linalg.norm(vertices - centre, axis=1),
        radius,
        rtol=0.0,
        atol=1.0e-14,
    )


def test_one_times_animation_speed_tracks_physical_time() -> None:
    assert _physical_playback_fraction(0.0, 4.0, 1.0, 8.0) == 0.5
    assert _physical_playback_fraction(0.25, 2.0, 2.0, 8.0) == 0.75

    with np.testing.assert_raises(ValueError):
        _physical_playback_fraction(0.0, 1.0, 1.0, 0.0)


def test_compact_guard_labels_keep_branch_quantity_and_element_identity() -> None:
    assert (
        _compact_guard_label(
            "forward",
            "MATERIAL_DOMAIN:lower:lambda_lower:element:2",
        )
        == "FWD lower λ− e2"
    )
    assert (
        _compact_guard_label("high_fidelity", "JUNCTION_SOCKET_PROJECTIVE_OPENING")
        == "HF junction opening"
    )


def test_job_poll_does_not_reselect_an_unchanged_row(tmp_path: Path) -> None:
    app = object.__new__(YPendulumDesktopApp)
    app.jobs_tree = _FakeTree(("job-1",))
    app.current_job_id = "job-1"

    app._refresh_jobs([_record("job-1", tmp_path)])

    assert app.jobs_tree.selection_set_calls == 0


def test_completed_result_is_not_automatically_loaded_twice(tmp_path: Path) -> None:
    output_directory = tmp_path.resolve()
    app = object.__new__(YPendulumDesktopApp)
    app.jobs_tree = _FakeTree(("job-1",))
    app.current_job_id = "job-1"
    app.manager = SimpleNamespace(get=lambda _identifier, refresh: _record("job-1", tmp_path))
    app._loaded_result_directory = output_directory
    app._loading_result_directory = None
    app._load_generation = 4

    app._load_selected_result(force=False)

    assert app._load_generation == 4
    assert app._loading_result_directory is None


def test_background_result_completion_is_applied_by_main_thread_queue(tmp_path: Path) -> None:
    app = object.__new__(YPendulumDesktopApp)
    app._load_generation = 3
    app._loading_result_directory = tmp_path / "loading"
    app._loaded_result_directory = None
    app._failed_result_directories = set()
    app._result_load_queue = queue.Queue()
    app.inline_error = _FakeConfigurable()
    app.top_status = _FakeConfigurable()
    rendered: list[Any] = []
    app._render_bundle = rendered.append
    stale = SimpleNamespace(status="STALE")
    current = SimpleNamespace(status="COMPLETE")
    app._result_load_queue.put((2, tmp_path / "stale", stale, None))
    app._result_load_queue.put((3, tmp_path / "current", current, None))

    app._drain_result_load_queue()

    assert rendered == [current]
    assert app.current_bundle is current
    assert app._loaded_result_directory == tmp_path / "current"
    assert app._loading_result_directory is None
    assert app.top_status.options["text"] == "已加载结果 · COMPLETE"
    assert app.inline_error.options == {}


def test_play_during_running_job_waits_without_false_no_result_error(
    tmp_path: Path,
) -> None:
    record = _record("job-1", tmp_path, state="RUNNING")
    app = object.__new__(YPendulumDesktopApp)
    app.current_bundle = None
    app.current_job_id = "job-1"
    app.jobs_tree = _FakeTree(("job-1",))
    app.manager = SimpleNamespace(get=lambda _identifier, refresh: record)
    app.inline_error = _FakeConfigurable()
    app.geometry_play_button = _FakeConfigurable()
    app.geometry_animation_status = _FakeConfigurable()
    app._geometry_autoplay_pending = False
    app._geometry_autoplay_output_directory = None
    app._loaded_result_directory = None
    app._loading_result_directory = None

    app._play_geometry()

    assert app._geometry_autoplay_pending is True
    assert app._geometry_autoplay_output_directory == tmp_path.resolve()
    assert app.inline_error.options["text"] == ""
    assert app.geometry_play_button.options["text"] == "✕ 取消等待"
    assert "完成并载入结果后自动播放" in app.geometry_animation_status.options["text"]


def test_play_on_completed_unloaded_job_queues_load_and_autoplay(tmp_path: Path) -> None:
    record = _record("job-1", tmp_path)
    app = object.__new__(YPendulumDesktopApp)
    app.current_bundle = None
    app.current_job_id = "job-1"
    app.jobs_tree = _FakeTree(("job-1",))
    app.manager = SimpleNamespace(get=lambda _identifier, refresh: record)
    app.inline_error = _FakeConfigurable()
    app.geometry_play_button = _FakeConfigurable()
    app.geometry_animation_status = _FakeConfigurable()
    app._geometry_autoplay_pending = False
    app._geometry_autoplay_output_directory = None
    app._loaded_result_directory = None
    app._loading_result_directory = None
    queued: list[tuple[Any, bool]] = []
    app._queue_result_load = lambda selected, *, force: queued.append((selected, force))

    app._play_geometry()

    assert queued == [(record, False)]
    assert app._geometry_autoplay_pending is True
    assert app.inline_error.options["text"] == ""


def test_matching_result_load_consumes_pending_autoplay(tmp_path: Path) -> None:
    app = object.__new__(YPendulumDesktopApp)
    app._load_generation = 7
    app._loading_result_directory = tmp_path
    app._loaded_result_directory = None
    app._failed_result_directories = set()
    app._result_load_queue = queue.Queue()
    app._geometry_autoplay_pending = True
    app._geometry_autoplay_output_directory = tmp_path.resolve()
    app.inline_error = _FakeConfigurable()
    app.top_status = _FakeConfigurable()
    rendered: list[Any] = []
    played: list[bool] = []
    app._render_bundle = rendered.append
    app._play_geometry = lambda: played.append(True)
    bundle = SimpleNamespace(status="COMPLETE")
    app._result_load_queue.put((7, tmp_path.resolve(), bundle, None))

    app._drain_result_load_queue()

    assert rendered == [bundle]
    assert played == [True]
    assert app._geometry_autoplay_pending is False
    assert app._geometry_autoplay_output_directory is None


def test_completed_current_job_is_automatically_loaded_once(tmp_path: Path) -> None:
    record = _record("job-1", tmp_path)
    app = object.__new__(YPendulumDesktopApp)
    app.current_job_id = "job-1"
    app._geometry_autoplay_pending = False
    app._geometry_autoplay_output_directory = None
    queued: list[tuple[Any, bool]] = []
    app._queue_result_load = lambda selected, *, force: queued.append((selected, force))

    app._sync_current_job_result([record])

    assert queued == [(record, False)]
