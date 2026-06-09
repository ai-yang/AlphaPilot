# AlphaPilot Adapter Layer

The `alphapilot.adapters` package provides a thin plugin layer around
two external boundaries that previously bled into the business code:

| Boundary       | Interface                | Default implementation                  |
|----------------|--------------------------|-----------------------------------------|
| LLM provider   | `BaseLLMAdapter`         | `openai` — wraps `APIBackend`           |
| Data source    | `BaseDataSourceAdapter`  | `baostock_cn` — wraps `systems.data.prepare_cn` |

The defaults reuse the existing implementations verbatim, so no caller
is forced to migrate. New code that wants to stay loosely coupled
should import from this package instead of the concrete modules.

Backtest execution is **not** part of this layer — it lives in
[`systems/backtest/`](../systems/backtest/) (Qlib workspace, factor runner, pipelines).

## Built-in layout

Built-in adapters are grouped by capability under `alphapilot/adapters/builtin/`:

- `llm/` (for example `llm/openai.py`)
- `data_source/` (for example `data_source/baostock_cn.py`)

The legacy flat module paths are kept as compatibility shims.

## Quick start

```python
from alphapilot.adapters import DataDownloadRequest, get_data_source, get_llm

llm = get_llm()                           # default registered adapter
text = llm.chat_text("Summarize TSMC Q1.")

ds = get_data_source("baostock_cn")
ds.download(DataDownloadRequest(start_date="2024-01-01"))
```

## Adding a new adapter

1. Subclass the relevant base class in `alphapilot/adapters/base/`.
2. Register it with the corresponding registry. Either as a decorator:

   ```python
   from alphapilot.adapters.base import BaseLLMAdapter, ChatRequest, ChatResponse
   from alphapilot.adapters.registry import LLM_REGISTRY

   @LLM_REGISTRY.register("anthropic")
   class AnthropicLLMAdapter(BaseLLMAdapter):
       def chat(self, request: ChatRequest) -> ChatResponse:
           ...
   ```

   …or via class path lookup without any registration:

   ```python
   from alphapilot.adapters import get_llm
   llm = get_llm("my_pkg.adapters.AnthropicLLMAdapter")
   ```

3. (Optional) Set it as the global default:

   ```python
   LLM_REGISTRY.set_default("anthropic")
   ```

## Design notes

* Each registry caches instances per `(name, kwargs)` to avoid rebuilding
  heavy backends.
* Built-in adapters import their concrete dependencies lazily, so simply
  importing `alphapilot.adapters` never forces baostock / openai to load.
* DTOs (`ChatRequest`, `DataDownloadRequest`) are plain `dataclass`
  objects — keep them stable as the public boundary.
* Adapters intentionally do **not** replace the legacy modules; they are
  a façade. Existing call sites continue to work unchanged and can be
  migrated incrementally.
* Backtest is handled by [`systems/backtest/`](../systems/backtest/), not
  by adapters.
