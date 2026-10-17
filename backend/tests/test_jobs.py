import os
import time
import uuid

import pytest

from app.services.jobs import JobStore


def make_job(store: JobStore, name="Archivo.xlsx"):
    job = store.create()
    job.output_path.write_bytes(b"datos-financieros")
    store.commit(job, name)
    return job


def test_create_commit_get_delete(store):
    job = make_job(store)
    found = store.get(job.job_id)
    assert found is not None and found[1] == "Archivo.xlsx"
    assert store.delete(job.job_id) is True
    assert not job.directory.exists()
    assert store.get(job.job_id) is None


def test_job_is_uuid4_directory_under_root(store):
    job = store.create()
    assert uuid.UUID(job.job_id).version == 4
    assert job.directory.parent == store.root.resolve()


@pytest.mark.parametrize("bad", ["../etc/passwd", "..", ".", "", "x" * 40, "%2e%2e%2f", "/tmp",
                                 "00000000-0000-0000-0000-000000000000", "../" + str(uuid.uuid4())])
def test_path_traversal_and_malformed_ids_are_rejected(store, bad):
    assert store.get(bad) is None
    assert store.delete(bad) is False


def test_job_without_commit_is_not_downloadable(store):
    job = store.create()
    job.output_path.write_bytes(b"x")
    assert store.get(job.job_id) is None


def test_ttl_expiry_on_get(store, monkeypatch):
    job = make_job(store)
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + store.ttl_seconds + 5)
    assert store.get(job.job_id) is None
    assert not job.directory.exists()


def test_cleanup_expired_removes_only_old_jobs(store, monkeypatch):
    old, fresh = make_job(store), make_job(store)
    meta_old = old.meta_path
    meta_old.write_text('{"filename": "a.xlsx", "created": %f}' % (time.time() - store.ttl_seconds - 10))
    assert store.cleanup_expired() == 1
    assert not old.directory.exists() and fresh.directory.exists()


def test_cleanup_handles_jobs_without_meta_by_directory_age(store):
    job = store.create()
    old = time.time() - store.ttl_seconds - 60
    os.utime(job.directory, (old, old))
    assert store.cleanup_expired() == 1


def test_cleanup_ignores_foreign_entries(store):
    foreign = store.root / "not-a-job"
    foreign.mkdir()
    (store.root / "readme.txt").write_text("x")
    assert store.cleanup_expired() == 0
    assert foreign.exists()


def test_creating_a_new_job_cleans_expired_ones(store):
    old = make_job(store)
    old.meta_path.write_text('{"filename": "a.xlsx", "created": %f}' % (time.time() - store.ttl_seconds - 10))
    store.create()
    assert not old.directory.exists()
