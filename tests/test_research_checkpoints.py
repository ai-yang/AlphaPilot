from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from alphapilot.research import checkpoints
from alphapilot.research.common import ResearchError, encode
from alphapilot.research.store import Store


@pytest.fixture
def checkpoint(tmp_path, monkeypatch, isolated_env):
    from alphapilot.systems import run_workspace as workspace_module
    from alphapilot.utils.workflow import LoopBase
    store = Store(tmp_path / 'jobs')
    source = store.root / 'source-job'
    root = tmp_path / 'source-run'
    (root / 'workspaces' / 'experiment').mkdir(parents=True)
    (root / 'workspaces' / 'experiment' / 'factor.csv').write_text('original')
    path = tmp_path / 'source-logs/session_snapshots/round_01/step_03/workflow.snapshot.pkl'
    manifest = {'normalized_input': {'dataset_id': 'test', 'max_steps': 3, 'resume_run_id': None}, 'dataset_revision': 'data-1'}
    run = SimpleNamespace(record=lambda **kw: manifest.update(kw))
    monkeypatch.setattr(workspace_module, 'current_run', lambda: run)
    session = LoopBase()
    session.step_idx = 3
    session.loop_prev_out = {'file': root / 'workspaces/experiment/factor.csv', 'dataset': str(source / 'inputs/dataset')}
    checkpoints.save(session, path)
    with store.connect(write=True) as db:
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)', ('source-job', 'succeeded', 'now', 'test', 'key', 'hash', '{}', encode({'folder': str(source)}), None))
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?)', ('source-run', 'source-job', None, str(root), encode(manifest)))
    return store, root, path, manifest, workspace_module


def test_checkpoint_is_verified_and_rebased_without_modifying_source(checkpoint, tmp_path, monkeypatch):
    from alphapilot.log import logger
    store, root, source_path, manifest, workspace_module = checkpoint
    destination = store.root / 'new-job/inputs/mining_session'
    original = source_path.read_bytes()
    restored, revision = checkpoints.prepare(store, 'source-run', {'dataset_id': 'test', 'max_steps': 2, 'resume_run_id': 'source-run'}, destination)
    assert Path(restored).is_file() and revision == 'data-1'
    new_root = tmp_path / 'new-run'
    new_workspace = new_root / 'workspaces'
    new_workspace.mkdir(parents=True)
    recorded = {}
    monkeypatch.setattr(workspace_module, 'current_run', lambda: SimpleNamespace(root=new_root, workspaces_dir=new_workspace, record=lambda **kw: recorded.update(kw)))
    old_log = logger.log_trace_path
    session = checkpoints.load(restored)
    assert session.step_idx == 3
    assert session.loop_prev_out['file'] == new_workspace / 'experiment/factor.csv'
    assert session.loop_prev_out['dataset'] == str(store.root / 'new-job/inputs/dataset')
    session.loop_prev_out['file'].write_text('new output')
    assert (root / 'workspaces/experiment/factor.csv').read_text() == 'original'
    assert source_path.read_bytes() == original and logger.log_trace_path == old_log
    assert recorded['resumed_from_run_id'] == 'source-run'


@pytest.mark.parametrize('case,code', [('active','RESUME_SOURCE_ACTIVE'), ('config','RESUME_CONFIG_CONFLICT'), ('corrupt','RESUME_CHECKPOINT_CORRUPT'), ('missing','RESUME_UNAVAILABLE')])
def test_checkpoint_rejects_unsafe_resume(checkpoint, case, code):
    store, _, path, manifest, _ = checkpoint
    request = {'dataset_id': 'test', 'max_steps': 2, 'resume_run_id': 'source-run'}
    if case == 'active':
        with store.connect(write=True) as db:
            db.execute("UPDATE jobs SET status='cancelling'")
    elif case == 'config':
        request['dataset_id'] = 'other'
    elif case == 'corrupt':
        path.write_bytes(b'incomplete')
    else:
        path.unlink()
    with pytest.raises(ResearchError) as error:
        checkpoints.prepare(store, 'source-run', request, store.root / 'new-job/inputs/mining_session')
    assert error.value.code == code


def test_resumed_loop_stop_event_is_process_local_and_instance_scoped():
    import threading
    from alphapilot.modules.alpha_mining.loops.alphapilot_loop import AlphaPilotLoop, stop_event_check
    restored = AlphaPilotLoop.__new__(AlphaPilotLoop)
    active = AlphaPilotLoop.__new__(AlphaPilotLoop)
    active._stop_event = threading.Event()
    active._stop_event.set()
    call = stop_event_check(lambda self: 'executed')
    assert call(restored) == 'executed'
    with pytest.raises(Exception, match='stopped due to stop_event'):
        call(active)
    state = active.__getstate__()
    assert state['_stop_event'] is None
