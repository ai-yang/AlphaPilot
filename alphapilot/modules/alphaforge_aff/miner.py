"""AFFMiner -- AlphaForge stage-1 (GAN-style) mining refactored as a class.

This is a faithful port of ``AlphaForge/train_AFF.py:main`` with three changes:

* device is resolved (cuda/mps/cpu) instead of hardcoded ``cuda:0``;
* data comes from alphapilot's qlib config via
  :mod:`alphapilot.modules.alphaforge.data_adapter`;
* ``run()`` returns the mined ``(exprs, scores)`` instead of only writing a
  pickle, so the module can translate + backtest them.

The generator/predictor/masker/collector internals are used unchanged from the
vendored ``gan`` package.
"""

from __future__ import annotations

import gc
from typing import TYPE_CHECKING, Any

import numpy as np

# Ensure the vendored top-level packages are importable (sys.path shim).
import alphapilot.modules.alphaforge  # noqa: F401
from alphapilot.modules.alphaforge.device import empty_cache, resolve_device, use_fork_start_method

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


# --------------------------------------------------------------------------- #
# helpers (lifted from train_AFF.py)                                          #
# --------------------------------------------------------------------------- #

def _pre_process_y(y):
    max_y = y.flatten().max()
    return (y - 0) / (max_y - 0) * 100


def _numpy2onehot(integer_matrix, max_num_categories=None, min_num_categories=None):
    if max_num_categories is None:
        max_num_categories = np.max(integer_matrix) + 1
    if min_num_categories is None:
        min_num_categories = np.min(integer_matrix)
    integer_matrix = integer_matrix - min_num_categories
    num_categories = max_num_categories - min_num_categories
    return np.eye(num_categories)[integer_matrix]


def _blds_list_to_tensor(blds_list, weights_list, size_action):
    import torch

    x_list, y_list, w_list = [], [], []
    for blds, weight_int in zip(blds_list, weights_list):
        x_np = _numpy2onehot(np.array(blds.builders_tokens), size_action, 0).astype("float32")
        y_np = np.array(blds.scores).astype("float32")[:, None]
        w_np = np.ones(x_np.shape[0]).astype("float32")[:, None] * weight_int
        x_list.append(x_np)
        y_list.append(y_np)
        w_list.append(w_np)
    x = torch.from_numpy(np.concatenate(x_list, axis=0))
    y = torch.from_numpy(np.concatenate(y_list, axis=0))
    w = torch.from_numpy(np.concatenate(w_list, axis=0))
    return x, y, w


def _train_predictor(cfg, net, x, y, weights, lr):
    import torch
    from torch.utils.data import DataLoader, TensorDataset
    from sklearn.model_selection import train_test_split
    from gan.network.predictor import train_regression_model_with_weight

    x_tr, x_va, y_tr, y_va, w_tr, w_va = train_test_split(x, y, weights, test_size=0.2, random_state=42)
    train_loader = DataLoader(TensorDataset(x_tr, y_tr, w_tr), batch_size=cfg.batch_size_p, shuffle=True)
    valid_loader = DataLoader(TensorDataset(x_va, y_va, w_va), batch_size=cfg.batch_size_p, shuffle=False)

    def weighted_mse_loss(inp, target, w):
        return ((inp - target) ** 2 * w.expand_as((inp - target) ** 2)).mean()

    optimizer = torch.optim.Adam(net.parameters(), lr=lr)
    train_regression_model_with_weight(
        train_loader, valid_loader, net, weighted_mse_loss, optimizer,
        device=cfg.device, num_epochs=cfg.num_epochs_p, use_tensorboard=False,
        tensorboard_path="logs", early_stopping_patience=cfg.es_p,
    )


def _make_get_metric(zoo_blds, device, corr_thresh, metric_target="ic"):
    """Closure scoring a candidate factor's IC with correlation de-dup vs zoo."""
    import torch
    from alphagen.utils.correlation import batch_ret, batch_pearsonr

    n_blds = len(zoo_blds)
    existed = None
    n_days = None
    if n_blds > 0:
        n_days = len(zoo_blds.ret_list[0])
        existed = torch.from_numpy(np.vstack(zoo_blds.ret_list)).to(device)

    def get_score(fct, tgt):
        ret = batch_ret(fct, tgt)
        ic = batch_pearsonr(fct, tgt)
        ic_mean = ic.mean().abs().item()
        icir = (ic_mean / ic.std()).item()
        ret_mean = ret.mean().abs().item()
        ret_ir = (ret_mean / ret.std()).item()
        sharpe = ((ret_mean - 0.03 / 252) / ret.std() * np.sqrt(252)).item()

        def clean(v):
            return 0.0 if not np.isfinite(v) else max(v, 0.0)

        multi = {k: clean(v) for k, v in
                 {"ic": ic_mean, "icir": icir, "ret": ret_mean, "sharpe": sharpe, "retir": ret_ir}.items()}
        score = multi[metric_target]

        if torch.isfinite(fct[0]).sum() / torch.isfinite(tgt[0]).sum() < 0.8:
            score = 0.0
        elif len(torch.unique(fct[0])) / len(torch.unique(tgt[0])) < 0.01:
            score = 0.0

        if n_blds > 0 and score > 0.0:
            all_matrix = torch.concatenate([existed, ret[None]], dim=0)
            corr_score = torch.corrcoef(all_matrix)[-1, :-1].abs().max().item()
            if corr_score > corr_thresh:
                score = 0.0

        return {"score": score, "ret": ret.detach().cpu().numpy(), "multi_score": multi}

    return get_score


class _Cfg:
    """Lightweight namespace mirroring the inner ``cfg`` of train_AFF.main."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


# --------------------------------------------------------------------------- #
# miner                                                                       #
# --------------------------------------------------------------------------- #

class AFFMiner:
    def __init__(
        self,
        *,
        context: "Context",
        instruments: str = "csi300",
        train_end_year: int = 2020,
        freq: str = "day",
        seed: int = 0,
        zoo_size: int = 100,
        corr_thresh: float = 0.7,
        ic_thresh: float = 0.03,
        icir_thresh: float = 0.1,
        max_len: int = 20,
        device: str | None = None,
        qlib_dir: str | None = None,
        raw: bool = False,
        # training knobs (shrink these for smoke tests)
        batch_size: int = 256,
        num_epochs_g: int = 200,
        num_epochs_p: int = 100,
        init_collect: int = 10000,
        iter_collect: int = 1000,
        max_iter_init: int = 200,
        max_iter: int = 100,
        max_loops: int | None = None,
    ):
        self.context = context
        self.instruments = instruments
        self.train_end_year = train_end_year
        self.freq = freq
        self.seed = seed
        self.zoo_size = zoo_size
        self.corr_thresh = corr_thresh
        self.ic_thresh = ic_thresh
        self.icir_thresh = icir_thresh
        self.max_len = max_len
        self.device_pref = device
        self.qlib_dir = qlib_dir
        self.raw = raw
        self.batch_size = batch_size
        self.num_epochs_g = num_epochs_g
        self.num_epochs_p = num_epochs_p
        self.init_collect = init_collect
        self.iter_collect = iter_collect
        self.max_iter_init = max_iter_init
        self.max_iter = max_iter
        self.max_loops = max_loops

    def _build_cfg(self, device) -> _Cfg:
        return _Cfg(
            max_len=self.max_len, batch_size=self.batch_size, potential_size=100,
            n_layers=2, d_model=128, dropout=0.2, num_factors=self.zoo_size,
            num_epochs_g=self.num_epochs_g, g_es_score="max", g_es=10, g_hidden=128, g_lr=1e-3,
            p_hidden=128, p_lr=1e-3, es_p=10, batch_size_p=64,
            num_epochs_p=self.num_epochs_p, data_keep_p=20000,
            f_corr_thresh=self.corr_thresh, f_add_thresh=self.corr_thresh,
            f_score_thresh=self.ic_thresh, f_multi_score_thresh={"icir": self.icir_thresh},
            l_pred=1.0, l_simi=10.0, l_simi_thresh=0.4,
            l_potential=10.0, l_potential_thresh=0.4, l_potential_epsilon=1e-7,
            l_entropy=0, device=str(device),
        )

    def run(self) -> tuple[list[Any], list[float]]:
        """Run the AFF mining loop; return (exprs, scores) for the final zoo."""
        import torch
        from alphagen.rl.env.wrapper import SIZE_ACTION
        from alphagen.utils.random import reseed_everything
        from gan.dataset import Collector
        from gan.network.generater import NetG_DCGAN, train_network_generator
        from gan.network.masker import NetM
        from gan.network.predictor import NetP
        from gan.utils import Builders, filter_valid_blds
        from alphapilot.modules.alphaforge.data_adapter import default_target, get_data_splits

        use_fork_start_method()
        dev = resolve_device(self.device_pref)
        reseed_everything(self.seed)
        cfg = self._build_cfg(dev)

        splits = get_data_splits(
            self.context, instruments=self.instruments, train_end_year=self.train_end_year,
            freq=self.freq, device=dev, raw=self.raw, qlib_dir=self.qlib_dir,
        )
        data = splits.train
        target = default_target()

        netG = NetG_DCGAN(n_chars=SIZE_ACTION, latent_size=cfg.potential_size,
                          seq_len=cfg.max_len, hidden=cfg.g_hidden).to(cfg.device)
        netM = NetM(max_len=cfg.max_len, size_action=SIZE_ACTION).to(cfg.device)
        netP = NetP(n_chars=SIZE_ACTION, seq_len=cfg.max_len, hidden=cfg.p_hidden).to(cfg.device)

        z = torch.zeros([cfg.batch_size, cfg.potential_size], device=cfg.device).normal_()

        def random_call(zz):
            return zz.normal_()

        zoo_blds = Builders(0, max_len=cfg.max_len, n_actions=SIZE_ACTION)
        metric = _make_get_metric(zoo_blds, dev, cfg.f_corr_thresh)
        empty_metric = _make_get_metric(
            Builders(0, max_len=cfg.max_len, n_actions=SIZE_ACTION), dev, cfg.f_corr_thresh
        )

        coll = Collector(seq_len=cfg.max_len, n_actions=SIZE_ACTION)
        coll.reset(data, target, metric)
        coll.collect_target_num(netG, netM, z, data, target, metric,
                                target_num=self.init_collect, reset_net=True, drop_invalid=False,
                                randomly=False, random_method=random_call, max_iter=self.max_iter_init)

        t = 0
        while len(zoo_blds) < cfg.num_factors:
            if self.max_loops is not None and t >= self.max_loops:
                break
            if not zoo_blds.examined:
                zoo_blds.evaluate(data, target, empty_metric, verbose=True)
            metric = _make_get_metric(zoo_blds, dev, cfg.f_corr_thresh)

            coll.blds.evaluate(data, target, metric, verbose=True)
            if coll.blds_bak.batch_size > cfg.data_keep_p:
                idx = np.random.choice(np.arange(coll.blds_bak.batch_size), cfg.data_keep_p, replace=False)
                coll.blds_bak = coll.blds_bak.filter_by_index(idx)
            coll.blds_bak.evaluate(data, target, metric, verbose=True)

            if coll.blds_bak.batch_size > 0:
                blds_list, weight_list = [coll.blds_bak, coll.blds], [1.0, 2.0]
            else:
                blds_list, weight_list = [coll.blds], [1.0]

            x, y, weights = _blds_list_to_tensor(blds_list, weight_list, SIZE_ACTION)
            y = _pre_process_y(y)

            netP.initialize_parameters()
            _train_predictor(cfg, netP, x, y, weights, lr=cfg.p_lr)

            netG.initialize_parameters()
            blds_in_train = train_network_generator(
                netG, netM, netP, cfg, data, target, t, random_method=random_call,
                metric=metric, lr=cfg.g_lr, n_actions=SIZE_ACTION,
            )

            coll.reset(data, target, metric)
            coll.collect_target_num(netG, netM, z, data, target, metric,
                                    target_num=self.iter_collect, reset_net=False, drop_invalid=False,
                                    randomly=False, random_method=random_call, max_iter=self.max_iter)

            coll.blds = coll.blds + blds_in_train
            coll.blds.drop_duplicated()

            new_zoo = filter_valid_blds(
                coll.blds, corr_thresh=cfg.f_add_thresh, score_thresh=cfg.f_score_thresh,
                multi_score_thresh=cfg.f_multi_score_thresh, device=dev, verbose=True,
            )
            zoo_blds = zoo_blds + new_zoo
            zoo_blds.evaluate(data, target, empty_metric, verbose=True)
            if t % 5 == 2:
                zoo_blds = filter_valid_blds(
                    zoo_blds, corr_thresh=cfg.f_add_thresh, score_thresh=cfg.f_score_thresh,
                    multi_score_thresh=cfg.f_multi_score_thresh, device=dev, verbose=False,
                )

            coll.collect_target_num(netG, netM, z, data, target, metric,
                                    target_num=self.iter_collect, reset_net=False, drop_invalid=False,
                                    randomly=True, random_method=random_call, max_iter=self.max_iter)

            del x, y, weights
            gc.collect()
            empty_cache(dev)
            t += 1

        final_metric = _make_get_metric(
            Builders(0, max_len=cfg.max_len, n_actions=SIZE_ACTION), dev, cfg.f_corr_thresh
        )
        zoo_blds.evaluate(data, target, final_metric, verbose=True)

        exprs = list(zoo_blds.exprs)
        scores = list(zoo_blds.scores)
        return exprs, scores
