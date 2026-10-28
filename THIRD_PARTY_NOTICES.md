# Third-party notices

The signed release package's notices are preserved unchanged in `data/signed_release/THIRD_PARTY_NOTICES.md`.

**Python packages.** The index pipeline in `code/src/` declares openai (Apache-2.0), pandas (BSD-3-Clause), numpy
(BSD-3-Clause), scipy (BSD-3-Clause), pydantic and pydantic-settings (MIT), requests (Apache-2.0), tenacity
(Apache-2.0), jsonschema (MIT), openpyxl (MIT), python-docx (MIT), tqdm (MPL-2.0 / MIT) and python-dotenv
(BSD-3-Clause). The offline reproduction uses only the packages pinned in `requirements-lock.txt`: pandas, numpy,
scipy, jsonschema (with attrs, referencing, rpds-py and jsonschema-specifications, MIT), pydantic, pydantic-settings
and python-dotenv, python-dateutil (Apache-2.0 / BSD-3-Clause), pytz (MIT), tzdata (Apache-2.0), six (MIT),
typing-extensions (PSF-2.0), annotated-types (MIT), typing-inspection (MIT), and pytest (MIT) with iniconfig (MIT),
packaging (Apache-2.0 / BSD-2-Clause), pluggy (MIT) and pygments (BSD-2-Clause). Licenses are as declared by each
project; no third-party code is vendored in this snapshot. Verify current terms before redistribution.

**Data sources.** ClinicalTrials.gov and PubMed/MEDLINE (U.S. National Library of Medicine); use is subject to the
applicable NLM terms. Registry and publication free text is not redistributed; the data contain identifiers, timing
facts and derived codes.

**Model outputs.** The categorical evaluator outputs come from model identifiers accessed through GitHub Copilot on
18 August 2026 (`claude-opus-4.6`, `gemini-3.1-pro-preview`, `gpt-5.4`). This is access through GitHub Copilot, not
native-provider performance. No model weights, provider responses or provider request identifiers are redistributed.
