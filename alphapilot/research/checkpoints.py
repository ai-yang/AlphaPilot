"""Trusted server-side workflow checkpoints. Never accepts client pickle or paths."""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import shutil
import uuid
from pathlib import Path

from .common import ACTIVE, ResearchError, atomic_json


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(session, path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        with temporary.open('wb') as stream:
            pickle.dump(session, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    from alphapilot.systems.run_workspace import current_run
    run = current_run()
    if run is not None:
        run.record(checkpoint={"version": 1, "path": str(path), "sha256": checksum(path),
                               "loop_index": session.loop_idx, "next_step_index": session.step_idx},
                   session_path=str(path.parents[3]))


def prepare(store, run_id, normalized, destination):
    with store.connect() as db:
        row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        source_job = db.execute('SELECT * FROM jobs WHERE id=?', (row['job_id'],)).fetchone() if row else None
    if not row or not source_job:
        raise ResearchError('RESUME_UNAVAILABLE', 'A recorded job and complete checkpoint are required', 409)
    if source_job['status'] in ACTIVE:
        raise ResearchError('RESUME_SOURCE_ACTIVE', 'Wait for the source job to terminate before resuming', 409)
    payload = json.loads(row['payload'])
    checkpoint = payload.get('checkpoint', {})
    source_input = payload.get('normalized_input')
    ignored = {'max_steps', 'resume_run_id'}
    if not source_input or {k: v for k, v in source_input.items() if k not in ignored} != {k: v for k, v in normalized.items() if k not in ignored}:
        raise ResearchError('RESUME_CONFIG_CONFLICT', 'Resume must use the original resolved configuration and asset revisions', 409)
    path = Path(checkpoint.get('path', ''))
    source_root = Path(row['path']).resolve()
    if checkpoint.get('version') != 1 or not path.is_file() or not payload.get('dataset_revision'):
        raise ResearchError('RESUME_UNAVAILABLE', 'No complete checkpoint with data provenance is registered', 409)
    destination = Path(destination)
    destination.mkdir(parents=True)
    copied = destination / 'workflow.snapshot.pkl'
    shutil.copyfile(path, copied)
    if checksum(copied) != checkpoint.get('sha256'):
        raise ResearchError('RESUME_CHECKPOINT_CORRUPT', 'Checkpoint checksum mismatch', 409)
    if (source_root / 'workspaces').exists():
        shutil.copytree(source_root / 'workspaces', destination / 'workspaces', symlinks=True)
    # Obtain the actual persisted execution folder (job roots may have nested layout).
    execution = json.loads(source_job['execution'])
    source_folder = Path(execution['folder'])
    metadata = {'source_run_id': run_id, 'source_root': str(source_root),
                'source_folder': str(source_folder), 'source_log': str(path.parents[3]),
                'destination_folder': str(destination.parent.parent),
                'dataset_revision': payload['dataset_revision'], 'sha256': checkpoint['sha256']}
    atomic_json(destination / 'resume.json', metadata)
    return str(copied), metadata['dataset_revision']


def load(path):
    """Load only a checkpoint staged by prepare, rebasing its private workspace graph."""
    path = Path(path)
    metadata = json.loads((path.parent / 'resume.json').read_text())
    if checksum(path) != metadata['sha256']:
        raise ResearchError('RESUME_CHECKPOINT_CORRUPT', 'Staged checkpoint checksum mismatch', 409)
    from alphapilot.systems.run_workspace import current_run
    from alphapilot.log import logger
    run = current_run()
    if run is None:
        raise ResearchError('RESUME_UNAVAILABLE', 'Resume requires an active run workspace', 409)
    source = path.parent / 'workspaces'
    if source.exists():
        shutil.copytree(source, run.workspaces_dir, dirs_exist_ok=True, symlinks=True)
    with path.open('rb') as stream:
        session = pickle.load(stream)  # trusted, checksum-verified server-produced state
    mapping = {metadata['source_root']: str(run.root), metadata['source_folder']: metadata['destination_folder'],
               metadata['source_log']: str(logger.log_trace_path.resolve())}
    prefixes = sorted(mapping, key=len, reverse=True)
    seen = {}

    def rebind(value):
        if isinstance(value, (str, Path)):
            text = str(value)
            for old in prefixes:
                if text == old or text.startswith(old + os.sep):
                    text = mapping[old] + text[len(old):]
                    break
            return Path(text) if isinstance(value, Path) else text
        if id(value) in seen:
            return seen[id(value)]
        seen[id(value)] = value
        if isinstance(value, dict):
            for key, item in list(value.items()):
                value[key] = rebind(item)
        elif isinstance(value, list):
            value[:] = [rebind(item) for item in value]
        elif isinstance(value, tuple):
            result = tuple(rebind(item) for item in value)
            seen[id(value)] = result
            return result
        elif type(value).__module__.startswith('alphapilot.') and hasattr(value, '__dict__'):
            for key, item in list(vars(value).items()):
                object.__setattr__(value, key, rebind(item))
        return value

    session = rebind(session)
    session.session_folder = logger.log_trace_path / 'session_snapshots'
    run.record(resumed_from_run_id=metadata['source_run_id'])
    return session
