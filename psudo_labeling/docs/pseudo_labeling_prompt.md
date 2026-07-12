# Pseudo-Labeling 프롬프트 (v2)

ICML 2026 논문 1편당 인간 리뷰 여러 개(3~4개) + 메타리뷰를 **단일 리뷰 1개**로 증류하는
서브에이전트용 프롬프트. 실행 시 `${id}` 자리에 논문의 OpenReview forum id가 치환되어
논문당 에이전트 1개에게 전달된다.

- **모델**: Claude Opus 4.8 (`opus`), 논문당 에이전트 1개, 워크플로우 10개 병렬
- **입력**: `data/label_inputs/<id>.json` — 최초 리뷰들(rebuttal 이전) + 메타리뷰. `rebuttal`,
  `final_justification`(rebuttal 후 입장)은 입력에서 제외됨
- **출력 1**: `data/pseudo_labels/<id>.json` — ICML 2026 공식 폼 10필드만 (리뷰 그 자체)
- **출력 2**: `data/label_meta/<id>.json` — 리뷰어 가중치 판정 기록 (라벨러 메타데이터, 데이터셋에 미포함)
- **워크플로우 스크립트**: `pseudo_label_v2.js` (agent 호출·병렬화만 담당, 리뷰 내용은 전부 에이전트가 생성)

## v1 → v2 변경 이력

| 항목 | v1 (폐기, `data/pseudo_labels_v1_backup/`) | v2 (현행) |
|---|---|---|
| rebuttal 반영 | `final_justification`으로 "rebuttal에서 해소된 지적" 필터링 | **rebuttal 정보 일절 미사용** — 최초 리뷰만 |
| 리뷰 본문 문체 | "Reviewer BLmy가 지적했듯..." 식 메타 서술 허용 | **단일 리뷰어 1인칭 시점 강제**, 리뷰어/메타리뷰/rebuttal 언급 금지 |
| 라벨 파일 구성 | 리뷰 + reviewer_stances + score_rationale 혼재 | **공식 폼 10필드만**, 판정 기록은 별도 파일로 분리 |

---

## 프롬프트 원문 (에이전트에게 전달되는 그대로)

```
You are an expert ICML reviewer producing a single "pseudo-label" review of an ICML 2026 paper. Multiple human reviewers reviewed this paper; your job is to distill their INITIAL reviews into ONE review, written as if a single careful expert reviewer had reviewed the paper themselves.

Read this JSON file: /home/hkh/github/ralphton/data/label_inputs/${id}.json
It contains: title, abstract, primary_area, decision, decision_comment (the program chairs' meta-review), and reviews[] — each reviewer's initial official ICML 2026 review: summary, strengths_and_weaknesses, scores (soundness/presentation/significance/originality 1-4, overall_recommendation 1-6, confidence 1-5), key_questions_for_authors, limitations.

INTERNAL STEP — weigh the reviewers (this guides you, but must NEVER appear in the review text):
Use the meta-review (decision_comment) as the anchor for reviewer quality. Assign each reviewer a weight:
- high: their points are adopted/echoed by the meta-review or independently corroborated by other reviewers, and their review is specific and substantiated
- medium: partly on-target
- low: vague, generic, low-effort, or clearly off-base (contradicted by the meta-review)
Record this ONLY in the reviewer_stances field of your structured output (labeler metadata).

WRITE THE REVIEW — official ICML 2026 form, in the voice of ONE reviewer:
ABSOLUTE RULES:
- Write as one reviewer giving their own direct, first-hand assessment of the paper.
- NEVER mention or allude to: other reviewers ("Reviewer X", "reviewers agree", "one reviewer noted"), the meta-review, the area chair, the rebuttal, the discussion period, score changes, or the acceptance decision. The review must read exactly like a normal initial review written before any rebuttal existed.
- Build the content from the high-weight reviewers' points, rephrased in your own words as your own observations. Drop low-weight or off-base points. Do not invent criticisms no reviewer raised.

Fields:
- summary: one paragraph restating the paper and its contributions in your own words (not the abstract verbatim); a summary the authors would agree with.
- strengths_and_weaknesses: a thorough first-hand assessment covering all four dimensions — soundness, presentation, significance, originality — as flowing review prose (e.g. "The theoretical analysis is rigorous..." not "Reviewer X found...").
- soundness, presentation, significance, originality: integers 1-4 (4 excellent / 3 good / 2 fair / 1 poor). Stay within the [min, max] of the human reviewers' scores for that dimension, positioned by your reviewer weights and the meta-review's direction.
- key_questions_for_authors: 3-5 numbered questions merged/deduplicated from the most evaluation-relevant reviewer questions, asked as your own.
- limitations: "Yes" if the limitations discussion is adequate; otherwise 1-3 constructive sentences.
- overall_recommendation: integer 1-6 (6 strong accept / 5 accept / 4 weak accept / 3 weak reject / 2 reject / 1 strong reject). Weigh high-weight reviewers most; stay within [min, max] of the reviewers' overall recommendations unless the meta-review clearly indicates otherwise.
- confidence: integer 1-5 reflecting how coherent and mutually corroborating the underlying evidence is (not an average).
- score_rationale (metadata only, not part of the review): 2-4 sentences on how the weights and meta-review shaped your scores.

Professional, specific review prose. All text in English.

OUTPUT — write TWO files using the Write tool, then return the full structured output:
1. /home/hkh/github/ralphton/data/pseudo_labels/${id}.json — the review ONLY, with EXACTLY these keys:
   {"forum_id": "${id}", "summary", "strengths_and_weaknesses", "soundness", "presentation", "significance", "originality", "key_questions_for_authors", "limitations", "overall_recommendation", "confidence"}
   No reviewer_stances, no score_rationale, no other keys.
2. /home/hkh/github/ralphton/data/label_meta/${id}.json — the metadata: {"forum_id": "${id}", "reviewer_stances": [...], "score_rationale": "..."}
```

---

## 구조화 출력 스키마 (JSON Schema로 강제 — 위반 시 에이전트 자동 재시도)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["reviewer_stances", "summary", "strengths_and_weaknesses",
               "soundness", "presentation", "significance", "originality",
               "key_questions_for_authors", "limitations",
               "overall_recommendation", "confidence", "score_rationale"],
  "properties": {
    "reviewer_stances": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["reviewer", "weight", "reason"],
        "properties": {
          "reviewer": {"type": "string"},
          "weight":   {"enum": ["high", "medium", "low"]},
          "reason":   {"type": "string"}
        }
      }
    },
    "summary": {"type": "string"},
    "strengths_and_weaknesses": {"type": "string"},
    "soundness":    {"type": "integer", "minimum": 1, "maximum": 4},
    "presentation": {"type": "integer", "minimum": 1, "maximum": 4},
    "significance": {"type": "integer", "minimum": 1, "maximum": 4},
    "originality":  {"type": "integer", "minimum": 1, "maximum": 4},
    "key_questions_for_authors": {"type": "string"},
    "limitations": {"type": "string"},
    "overall_recommendation": {"type": "integer", "minimum": 1, "maximum": 6},
    "confidence":             {"type": "integer", "minimum": 1, "maximum": 5},
    "score_rationale": {"type": "string"}
  }
}
```

## 설계 포인트 요약

1. **메타리뷰 = 리뷰어 품질의 앵커.** 메타리뷰가 채택/반향한 지적을 한 리뷰어(+타 리뷰어 교차 검증,
   구체성)에 high 가중치. 모호하거나 메타리뷰와 모순되는 리뷰는 low로 강등되어 최종 리뷰에서 배제.
2. **점수 가드레일.** 각 점수는 해당 축의 인간 리뷰어 점수 [min, max] 범위 내로 제한 —
   라벨러의 점수 환각 방지, 인간 분포에 정박.
3. **없는 비판 금지.** 어떤 리뷰어도 제기하지 않은 약점을 새로 만들어내지 못하게 명시 —
   증류(distillation)이지 재리뷰가 아님.
4. **단일 리뷰어 목소리.** 최종 산출물은 rebuttal 이전에 쓰인 평범한 리뷰 1개처럼 읽혀야 하며,
   리뷰 과정(리뷰어들/메타/토론)의 흔적이 텍스트에 남지 않음.
