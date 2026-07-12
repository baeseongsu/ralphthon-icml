# ICML 2026 review dataset: descriptive statistics

The local Hugging Face dataset contains accepted ICML 2026 papers and their
official reviews. Author rebuttals and discussion messages are not represented
as separate records; `final_justification` may contain post-rebuttal reviewer
updates.

## Dataset scale

| Statistic | Value |
|---|---:|
| Papers | 6,341 |
| Official reviews | 24,378 |
| Unique authors | 25,065 |
| Primary areas | 84 |
| Regular accepts | 5,805 (91.55%) |
| Spotlight accepts | 536 (8.45%) |
| Reviews per paper | 3.84 ± 0.40; median 4 |
| Abstract length | 166.29 ± 29.58 words |
| Review text length | 484.51 ± 246.42 words |

Most papers have four reviews (5,190; 81.85%), followed by three reviews
(1,057; 16.67%).

## Review scores

| Field | Mean ± SD | Median | Scale |
|---|---:|---:|---:|
| Soundness | 2.856 ± 0.603 | 3 | 1–4 |
| Presentation | 2.891 ± 0.638 | 3 | 1–4 |
| Significance | 2.749 ± 0.618 | 3 | 1–4 |
| Originality | 2.781 ± 0.609 | 3 | 1–4 |
| Overall recommendation | 4.146 ± 0.726 | 4 | 1–6 |
| Confidence | 3.462 ± 0.797 | 4 | 1–5 |

Mean within-paper reviewer disagreement, measured as the standard deviation of
scores, is 0.61 for overall recommendation and 0.50–0.54 for the four quality
dimensions. Confidence has the largest mean disagreement (0.68).

## Area distribution

The largest primary area is `deep_learning->large_language_models` with 1,155
papers (18.21%), followed by computer vision with 515 (8.12%), and generative
models and autoencoders with 349 (5.50%). The remaining papers are distributed
across 81 other primary areas.

## Missing values

The structured fields are nearly complete. The only fields with missing values
are paper TLDRs (2,406; 37.94%) and review `final_justification` fields (5,098;
20.91%). All six numeric review-score fields are complete across 24,378 reviews.

## Interpretation boundary

This is an accepted-paper dataset, not the full ICML submission population.
Accordingly, decision and score distributions should not be interpreted as
conference-wide acceptance statistics or used to model rejection outcomes.
