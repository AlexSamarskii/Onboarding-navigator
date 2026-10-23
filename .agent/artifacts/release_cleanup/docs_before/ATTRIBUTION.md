# Attribution

## Upstream and extension

- Upstream: **telegram-rag-bot0.14.6**, [PyPI release](https://pypi.org/project/telegram-rag-bot/0.14.6/).
- Author: **Mikhail Malorod** (MikhailMalorod).
- License: **MIT**, read directly from `workspace/telegram-rag-bot-src/LICENSE`; source pyproject also declares MIT. Full exact notice is retained below.
- Related orchestration upstream: [MikhailMalorod/Multi-LLM-Orchestrator](https://github.com/MikhailMalorod/Multi-LLM-Orchestrator).
- Fork/extension: **Onboarding Navigator**, HR modes and support/onboarding workflows. Upstream authorship remains unchanged.

## Reuse boundary

Hash-verified unchanged core: upstream `orchestrator/router.py`, `orchestrator/retrieval/async_faiss.py`, and source `telegram_rag_bot/langchain_adapter/rag_chains.py`, `telegram_rag_bot/vectorstore/local_faiss.py`, `telegram_rag_bot/__main__.py`, embeddings implementation. The accepted installed upstream audit copy contains the orchestrator package. Final infra guard verified44/44 frozen files plus8/8 accepted i18n files unchanged. The frozen set protects earlier accepted additions/adaptations too; it does not imply all44 files are upstream-as-is.

See [release_notes.md](release_notes.md) for what is retained as-is, adapted or added. No upstream license headers or documentation were removed by this docs-only change. Future forks/distributions must retain the copyright and permission notice in copies or substantial portions as required by MIT, keeping upstream authorship distinct from downstream additions.

## Full upstream license notice

```text
MIT License

Copyright (c) 2025 Mikhail Malorod

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
