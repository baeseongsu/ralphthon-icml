# Pseudo-labeling subagent pipeline

```mermaid
%%{init: {
  "theme": "base",
  "flowchart": {"curve": "basis", "nodeSpacing": 42, "rankSpacing": 60},
  "themeVariables": {
    "fontFamily": "Inter, Arial, sans-serif",
    "fontSize": "18px",
    "primaryTextColor": "#183B56",
    "lineColor": "#668396"
  }
}}%%
flowchart TB
    subgraph PREP["1 · Prepare review evidence"]
        direction LR
        DATA[("<b>ICML 2026 reviews</b><br/>6,341 papers")]
        SAMPLE["<b>Stratified sample</b><br/>area × review score"]
        INPUT["<b>Per-paper input</b><br/>abstract · initial reviews · meta-review<br/><i>no rebuttal or final justification</i>"]
        DATA --> SAMPLE --> INPUT
    end
    subgraph DISTILL["2 · Distill with a pseudo-labeling subagent"]
        direction LR
        AGENT["<b>Pseudo-labeling subagent</b><br/>process one paper"]
        WEIGHT["<b>Weight reviewer evidence</b><br/>high · medium · low"]
        SYNTH["<b>Consolidate one review</b><br/>deduplicate critiques<br/>single-reviewer voice"]
        SCORE["<b>Assign ICML scores</b><br/>within human [min, max]"]
        AGENT --> WEIGHT --> SYNTH --> SCORE
    end
    subgraph DELIVER["3 · Deliver structured labels"]
        direction LR
        REVIEW[("<b>Pseudo-review JSON</b><br/>10 ICML review fields")]
        META[("<b>Reviewer-weight metadata</b><br/>analysis only")]
        USE["<b>Review Agent</b><br/>training and evaluation"]
        REVIEW --> USE
    end
    INPUT --> AGENT
    SCORE --> REVIEW
    SCORE -. analysis only .-> META
    classDef data fill:#EAF3F8,stroke:#3D86A6,stroke-width:2px,color:#183B56;
    classDef process fill:#E9F1FB,stroke:#2878B5,stroke-width:2px,color:#183B56;
    classDef output fill:#EDF6EC,stroke:#5B9A68,stroke-width:2px,color:#214C2B;
    class DATA,SAMPLE,INPUT data;
    class AGENT,WEIGHT,SYNTH,SCORE process;
    class REVIEW,META,USE output;
```

**Suggested caption.** Pseudo-labeling workflow. A stratified ICML review sample
is processed by a pseudo-labeling subagent. Reviewer evidence is weighted and
deduplicated before producing a single structured review whose scores are
constrained by the human-review range. The pseudo-review is used downstream,
while reviewer-weight metadata is retained only for analysis.
