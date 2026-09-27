# WinWin.travel — AI hotel-search filter assistant (test task)

An OpenAI assistant that turns natural-language hotel requests into a validated search request
(destination, dates, guests, and boolean + range filters), then helps the user refine it.

**Main document:** [Google Doc](https://docs.google.com/document/d/1jwnq4Mqip39ZfDd5gdgx3MyYeP1l9w-TdKRjOgzpFmk/edit)
(source: [`docs/SOLUTION.md`](docs/SOLUTION.md)), with the full filter list in a
[Google Sheet](https://docs.google.com/spreadsheets/d/128ZokZ-7i1DlkE2ely5_0iaH2J77SGZib79K8D8IYzM/edit). The same content is in
[`docs/WinWin_AI_Assistant.docx`](docs/WinWin_AI_Assistant.docx), which includes the full prompt and
all 1,021 filters as appendices. To get a Google Doc: upload the .docx to Google Drive, then choose
*Open with → Google Docs*.

| Deliverable | Where |
|---|---|
| Assistant configuration (OpenAI settings, tools, response format) | `assistant/config.json` |
| Instructions (system prompt) | `assistant/system_prompt.md` |
| Filters list — 1,021 filters (914 boolean, 104 range, 3 enum) | `filters/catalog.csv`, `filters/catalog.json`, `filters/SUMMARY.md` |
| How it works: extraction, conflicts, no results, follow-ups, rejection | `docs/SOLUTION.md`, "How the assistant works" |
| Example JSON output (all 3 task messages + 7 more turns) | `docs/SOLUTION.md`, "Example JSON output", `examples/conversation.json` |
| A/B testing proposal | `docs/SOLUTION.md`, "How to A/B test" |

## Design in one line
The model **proposes** a patch through a strict function call. A deterministic backend
(`src/winwin_assistant/`) **decides**: it validates ids, values, dates and conflicts, checks what is
possible at the destination, and returns the real offer count plus relaxation options. The model only
phrases the result.

## Run
```bash
pip install -e ".[dev]"            # or just: pip install pytest
python filters/build_catalog.py    # regenerate the filter catalog
PYTHONPATH=src python examples/build_examples.py   # regenerate the example conversation
python -m pytest -q                # 35 tests, no API key needed

# Live turn against OpenAI (optional)
pip install -e ".[openai]"
export OPENAI_API_KEY=...          # set in your shell, never commit it (see .env.example)
PYTHONPATH=src python -m winwin_assistant.assistant "Going to Haarlem 15-18 Aug, solo, quiet boutique hotel"

pip install python-docx && python docs/build_docx.py   # rebuild the .docx
pip install markdown && python docs/build_gdoc_html.py <sheet-url>   # HTML for Google Docs import
```

The inventory service is a deterministic mock, so offer counts are illustrative. The example model
outputs are golden (expected) outputs, not recordings of a live run.
