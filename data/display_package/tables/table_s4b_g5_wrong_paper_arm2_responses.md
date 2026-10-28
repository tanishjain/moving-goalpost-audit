**Supplementary Table S4B. Arm-2 (no publication-identity step) responses among the 47 cases whose human-reference publication label is an incorrectly matched publication, by model identifier.**

| Model identifier | Valid: material change | Valid: no material change | Valid: unassessable | Invalid | Total |
| --- | --- | --- | --- | --- | --- |
| claude-opus-4.6 | 6 | 1 | 40 | 0 | 47 |
| gemini-3.1-pro-preview | 6 | 1 | 39 | 1 | 47 |
| gpt-5.4 | 4 | 0 | 36 | 7 | 47 |

Categories are mutually exclusive. Valid responses (terminal status OK) are classified by the Gate-D label: material change; no material change; or unassessable (Gate D UNASSESSABLE, derived disposition AMBIGUOUS). Invalid responses (any non-OK terminal status) are assigned first, regardless of any partially parsed Gate-D value, and are never promoted to a label.
Invalid responses by terminal status: claude-opus-4.6 none; gemini-3.1-pro-preview 1 schema failure; gpt-5.4 4 schema failures, 3 semantic failures; no transport failures.
Under the reference convention, the no-material-change count equals Arm-2 correct in this stratum; a correct classification does not establish that the model recognized the publication-identity error. Both arms received identical inputs under the same rubric, and no replacement publication was supplied.
Derived from the immutable G5 run and reconciled exactly against the public-safe categorical cell file (benchmark/g5_cells_source_text_free.csv); the aggregate is released as benchmark/g5_wrong_paper_arm2_responses.csv. Model identifiers were accessed through GitHub Copilot on 2026-08-18; they are not native-provider models.
