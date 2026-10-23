# Атрибуция

## Исходный проект и расширение

- Исходный проект: **telegram-rag-bot 0.14.6**, [выпуск PyPI](https://pypi.org/project/telegram-rag-bot/0.14.6/).
- Автор: **Mikhail Malorod** (MikhailMalorod).
- Лицензия: **MIT**, прочитана непосредственно из `workspace/telegram-rag-bot-src/LICENSE`; исходный pyproject также декларирует MIT. Полный точный текст уведомления сохранён ниже без перевода.
- Связанный исходный проект оркестрации: [MikhailMalorod/Multi-LLM-Orchestrator](https://github.com/MikhailMalorod/Multi-LLM-Orchestrator).
- Локальный референс: [sazonovanton/SirChatalot](https://github.com/sazonovanton/SirChatalot.git). Это справочная копия, а не зависимость продукта времени выполнения.
- Форк/расширение: **Onboarding Navigator**, HR-режимы и сценарии поддержки/онбординга. Авторство исходного проекта сохранено.

## Граница переиспользования

Неизменность ядра подтверждена хешами: upstream `orchestrator/router.py`, `orchestrator/retrieval/async_faiss.py` и исходные `telegram_rag_bot/langchain_adapter/rag_chains.py`, `telegram_rag_bot/vectorstore/local_faiss.py`, `telegram_rag_bot/__main__.py`, реализация embeddings. Принятая установленная аудит-копия upstream содержит пакет orchestrator. Финальная инфраструктурная проверка подтвердила неизменность 44/44 замороженных файлов и 8/8 принятых файлов i18n. Замороженный набор защищает также ранее принятые добавления и адаптации; это не означает, что все 44 файла взяты из upstream без изменений.

Что сохранено без изменений, адаптировано или добавлено, описано в [release_notes.md](release_notes.md). При этой правке документации лицензионные заголовки и документация upstream не удалялись. Будущие форки и поставки должны сохранять уведомление об авторских правах и разрешении в копиях или существенных частях ПО согласно MIT, отделяя авторство upstream от последующих дополнений.

## Полный текст лицензии исходного проекта

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
