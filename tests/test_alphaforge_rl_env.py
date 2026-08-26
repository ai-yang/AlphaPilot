"""Contracts for the vendored Gymnasium expression environment."""

from __future__ import annotations

import numpy as np

import alphapilot.modules.alphaforge  # noqa: F401 - installs vendor path


def test_rl_env_package_is_vendored_and_uses_gymnasium_contract() -> None:
    from alphagen.rl.env.wrapper import SIZE_ACTION, AlphaEnvWrapper, action2token

    assert SIZE_ACTION > 1
    assert AlphaEnvWrapper.__module__ == "alphagen.rl.env.wrapper"
    assert action2token(0) is not None


def test_rl_wrapper_reset_step_and_action_masks() -> None:
    import gymnasium as gym

    from alphagen.rl.env.wrapper import MAX_EXPR_LENGTH, SIZE_ACTION, AlphaEnvWrapper

    class Core(gym.Env):
        metadata = {"render_modes": []}
        render_mode = None

        def reset(self, *, seed=None, options=None):
            return [], {"seed": seed}

        def step(self, token):
            return [], 0.25, False, False, {"token": str(token)}

        def valid_action_types(self):
            from alphagen.config import OPERATORS

            return {
                "select": [True, True, True, True, False],
                "op": {operator.category_type(): True for operator in OPERATORS},
            }

    wrapped = AlphaEnvWrapper(Core())
    obs, info = wrapped.reset(seed=7)
    assert obs.shape == (MAX_EXPR_LENGTH,)
    assert info == {"seed": 7}
    mask = wrapped.action_masks()
    assert mask.dtype == np.bool_
    assert mask.shape == (SIZE_ACTION,)
    assert mask.any()
    action = int(np.flatnonzero(mask)[0])
    next_obs, reward, terminated, truncated, step_info = wrapped.step(action)
    assert next_obs.shape == obs.shape
    assert reward == 0.25
    assert not terminated and not truncated
    assert step_info["token"]


def test_aff_length_agnostic_networks_support_small_qa_shape() -> None:
    import torch

    from gan.network.generater import NetG_CNN
    from gan.network.predictor import NetP_CNN

    generator = NetG_CNN(n_chars=48, latent_size=8, seq_len=4, hidden=16)
    predictor = NetP_CNN(n_chars=48, seq_len=4, hidden=16)
    logits = generator(torch.randn(2, 8))
    assert logits.shape == (2, 4, 48)
    prediction, latent = predictor(logits.softmax(dim=-1), latent=True)
    assert prediction.shape == (2, 1)
    assert latent.shape == (2, 64)


def test_default_target_keeps_legacy_default_and_supports_five_day_close() -> None:
    from alphapilot.modules.alphaforge.data_adapter import default_target

    assert str(default_target()) == "((Ref(vwap,-21)/Ref(vwap,-1))-1)"
    assert str(default_target(target_horizon=5, target_price="close")) == (
        "((Ref(close,-6)/Ref(close,-1))-1)"
    )


def test_default_target_rejects_unsupported_horizon_or_price() -> None:
    import pytest

    from alphapilot.modules.alphaforge.data_adapter import default_target

    with pytest.raises(ValueError, match="positive integer"):
        default_target(target_horizon=0)
    with pytest.raises(ValueError, match="close, vwap"):
        default_target(target_price="open")
