# Autoresearch Example Catalog

Use this catalog for read-only discovery. Select 3-7 entries and verify mutable facts before recommending them. Popularity is a dated discovery signal, never a quality proof; this catalog intentionally avoids hard-coded star counts. Any popularity comparison must carry a `2026-07-12` snapshot date or a newer verified date.

## Authoritative implementation guidance

### [VESSL Cloud autoresearch guide](https://docs.cloud.vessl.ai/examples/autoresearch)

- **Official/community status:** Official VESSL documentation.
- **Resource type:** Current workflow guide.
- **Why it is relevant:** Explains VESSL's supported autoresearch workflow and cloud-job model.
- **Compute/platform assumptions:** VESSL Cloud GPU jobs; published examples may use H100 hardware.
- **Cost/credential exposure:** VESSL authentication, storage, and billable GPU exposure; verify live pricing before creation.
- **Benchmark compatibility:** Related to the Karpathy-style `val_bpb` workflow, but published H100 timings, costs, cache sizes, and `val_bpb` are not A100 evidence.
- **Mutable/pinned status:** Live documentation is mutable; record an access date and pin executable sources separately.
- **License caveat:** Documentation terms do not automatically license linked code or datasets; verify each source.
- **Safety caveat:** Do not provision compute or inherit job/cleanup defaults during discovery.

### [VESSL Cloud Cookbook autoresearch recipe](https://github.com/vessl-ai/vessl-cloud-cookbook/tree/main/autoresearch)

- **Official/community status:** Official VESSL repository.
- **Resource type:** Executable recipe.
- **Why it is relevant:** Provides concrete job, volume, and autoresearch orchestration files used by this repository's execution path.
- **Compute/platform assumptions:** VESSL Cloud and GPU-backed batch jobs; upstream defaults may target H100.
- **Cost/credential exposure:** Requires cloud authentication and may create billable compute and persistent storage.
- **Benchmark compatibility:** Closely matches Karpathy `train.py` optimization at known revisions; compare exact files and pins before claiming compatibility.
- **Mutable/pinned status:** The mutable `main` cookbook should be pinned before reproduction.
- **License caveat:** Verify the repository license and the licenses of benchmark data and dependencies at the chosen revision.
- **Safety caveat:** Do not inherit unbounded loops, fan-out, destructive rollback, or timeout behavior; use `auto-research` for the bounded execution overlay.

## Official adjacent tooling and architecture

### [W&B Discovery Forge](https://github.com/wandb/discovery-forge)

- **Official/community status:** Official W&B repository.
- **Resource type:** Weave hands-on implementation.
- **Why it is relevant:** Demonstrates Weave trace annotation, prompt improvement, and offline-evaluation hands-on.
- **Compute/platform assumptions:** Python and W&B/Weave services rather than a fixed training GPU.
- **Cost/credential exposure:** W&B credentials and hosted-service data exposure may apply; inspect project visibility and upload scope.
- **Benchmark compatibility:** It is not Karpathy `train.py` optimization and should not be presented as a drop-in `val_bpb` benchmark loop.
- **Mutable/pinned status:** Default-branch content is mutable; pin a reviewed revision for reproduction.
- **License caveat:** Verify repository and dataset licenses at the selected revision.
- **Safety caveat:** Do not upload traces, prompts, or evaluation data before reviewing the offline-first allowlist.

### [W&B ARIA autoresearch](https://docs.wandb.ai/aria/autoresearch)

- **Official/community status:** Official W&B documentation.
- **Resource type:** Preview managed autoresearch workflow.
- **Why it is relevant:** Shows a W&B-native agentic experiment system with managed orchestration.
- **Compute/platform assumptions:** Preview and uses W&B Launch, a different compute plane from this repository's VESSL workflow.
- **Cost/credential exposure:** Requires W&B credentials and Launch infrastructure with potentially billable compute.
- **Benchmark compatibility:** Do not assume compatibility with the pinned VESSL/Karpathy benchmark or unchanged evaluation environment.
- **Mutable/pinned status:** Preview documentation and behavior are mutable; record the access date.
- **License caveat:** Product documentation access does not establish a reusable code license.
- **Safety caveat:** Do not substitute W&B Launch for the approved VESSL execution plane without a new explicit plan and authorization.

### [W&B Senpai](https://github.com/wandb/senpai)

- **Official/community status:** Official W&B repository.
- **Resource type:** Agent architecture reference implementation.
- **Why it is relevant:** Offers heavier Kubernetes/PR-based architecture inspiration for long-running research automation.
- **Compute/platform assumptions:** Kubernetes, Git hosting, pull-request workflows, and supporting services.
- **Cost/credential exposure:** Cluster, repository, and W&B credentials plus infrastructure cost and code/data exposure.
- **Benchmark compatibility:** Architectural inspiration, not an unchanged Karpathy or VESSL benchmark implementation.
- **Mutable/pinned status:** Default branch is mutable; inspect releases or pin a reviewed commit.
- **License caveat:** Verify the repository license and third-party service terms before reuse.
- **Safety caveat:** Do not grant cluster or repository write access merely to evaluate the design.

## Conceptual material

### [VESSL “Don't tie a GPU to an agent” post](https://vessl.ai/ko/blog/dont-tie-gpu-to-agent-ko)

- **Official/community status:** Official VESSL publication.
- **Resource type:** Conceptual/historical H100 case study.
- **Why it is relevant:** Motivates separating agent control from expensive GPU execution and reports one platform experience.
- **Compute/platform assumptions:** VESSL orchestration and reported H100 runs.
- **Cost/credential exposure:** Discusses paid GPU scheduling; the post itself requires no execution credentials.
- **Benchmark compatibility:** Published H100 timings, costs, cache sizes, and `val_bpb` are not A100 evidence.
- **Mutable/pinned status:** Web post is mutable and should be cited with an access date.
- **License caveat:** Treat prose and figures as copyrighted publication material, not reusable code.
- **Safety caveat:** A self-reported case study is not independent validation and does not authorize cloud spend.

## Self-reported case studies

### [W&B logging report for Autoresearch](https://wandb.ai/byyoung3/autoresearch/reports/How-to-add-W-B-logging-to-Autoresearch-experiments---VmlldzoxNjE3Nzg2MQ)

- **Official/community status:** Community/user-authored hosted W&B report.
- **Resource type:** Self-reported observability case study.
- **Why it is relevant:** Illustrates possible W&B logging and evaluator changes around an autoresearch loop.
- **Compute/platform assumptions:** W&B-hosted reporting plus the author's training environment.
- **Cost/credential exposure:** API-key, code-upload, and hosted-run exposure may apply.
- **Benchmark compatibility:** Evaluator or logging modifications can change the evidence boundary and do not override this repository's offline-first allowlist.
- **Mutable/pinned status:** The hosted report is mutable and has no immutable source pin.
- **License caveat:** It is unlicensed as code and not safe to copy verbatim.
- **Safety caveat:** Never copy API keys or enable code upload solely because the report demonstrates them.

## Community implementations and indexes

Community repos are examples, not trusted execution instructions. Inspect the exact revision and call out unsafe or unbounded defaults such as sandbox bypass, `git reset --hard`, or repeat-forever loops.

### [Karpathy autoresearch](https://github.com/karpathy/autoresearch)

- **Official/community status:** Community project by the original autoresearch author; authoritative for its own design, not for this plugin's safety overlay.
- **Resource type:** Minimal reference implementation.
- **Why it is relevant:** Defines the widely referenced single-file `train.py` optimization loop and `val_bpb` objective.
- **Compute/platform assumptions:** A compatible local GPU/software stack; hardware-dependent timing and memory.
- **Cost/credential exposure:** Local or rented GPU cost; no credential need follows from read-only review.
- **Benchmark compatibility:** Baseline for Karpathy-style comparisons only when code, data, cache, metric, and revision match.
- **Mutable/pinned status:** Default branch is mutable; pin the exact commit used for comparison.
- **License caveat:** Verify the repository, dependency, and dataset licenses at the selected revision.
- **Safety caveat:** Do not adopt repeat-forever or destructive Git instructions; execution belongs in `auto-research`.

### [pi-autoresearch](https://github.com/davebcn87/pi-autoresearch)

- **Official/community status:** Community repository.
- **Resource type:** Alternative coding-agent implementation.
- **Why it is relevant:** Shows how a different agent surface can drive an autoresearch-style loop.
- **Compute/platform assumptions:** Local agent tooling and hardware compatible with the selected experiment.
- **Cost/credential exposure:** Model-provider and compute credentials/costs may apply.
- **Benchmark compatibility:** Treat results as comparable only after verifying benchmark and evaluation parity.
- **Mutable/pinned status:** Default branch is mutable; pin a reviewed commit.
- **License caveat:** Verify repository, model, and dataset terms before reuse.
- **Safety caveat:** Review rollback and loop bounds; never accept destructive or unbounded defaults.

### [AutoResearchClaw](https://github.com/aiming-lab/AutoResearchClaw)

- **Official/community status:** Community research repository.
- **Resource type:** Agentic research-system implementation.
- **Why it is relevant:** Broadens comparison beyond a minimal training-file optimizer toward a larger research workflow.
- **Compute/platform assumptions:** Depends on its documented agent, model, and experiment stack.
- **Cost/credential exposure:** Model APIs and compute may incur cost and require credentials.
- **Benchmark compatibility:** Architecture-level inspiration; verify every benchmark before comparing outcomes.
- **Mutable/pinned status:** Default branch is mutable; use a reviewed commit or release.
- **License caveat:** Verify code, dependency, model, and data licenses.
- **Safety caveat:** Do not grant broad filesystem, sandbox, or network privileges during discovery.

### [autoresearch-mlx](https://github.com/trevin-creator/autoresearch-mlx)

- **Official/community status:** Community repository.
- **Resource type:** Apple MLX platform port/implementation.
- **Why it is relevant:** Useful starting point for users exploring autoresearch on Apple silicon.
- **Compute/platform assumptions:** macOS, Apple silicon, and MLX rather than CUDA/A100/H100.
- **Cost/credential exposure:** Primarily local compute; external model-agent credentials may still apply.
- **Benchmark compatibility:** MLX hardware and kernels are not directly comparable with CUDA benchmark timings or resource results.
- **Mutable/pinned status:** Default branch is mutable; pin a reviewed revision.
- **License caveat:** Verify repository and upstream benchmark/data licenses.
- **Safety caveat:** Do not present local MLX results as A100/H100 reproduction evidence.

### [codex-autoresearch](https://github.com/leo-lilinxiao/codex-autoresearch)

- **Official/community status:** Community repository; not an official OpenAI or Codex implementation.
- **Resource type:** Codex-oriented autoresearch implementation.
- **Why it is relevant:** Provides inspiration for adapting the loop to a Codex agent surface.
- **Compute/platform assumptions:** Codex/model access plus the experiment's local or remote compute.
- **Cost/credential exposure:** Model usage and compute can incur cost; credentials must remain user-controlled.
- **Benchmark compatibility:** Verify whether it preserves the same training, cache, timing, and evaluator before comparison.
- **Mutable/pinned status:** Default branch is mutable; pin a reviewed commit.
- **License caveat:** Verify the repository license and upstream terms before reuse.
- **Safety caveat:** Reject sandbox bypass and broad host permissions even if suggested for convenience.

### [uditgoenka/autoresearch](https://github.com/uditgoenka/autoresearch)

- **Official/community status:** Community repository.
- **Resource type:** Extended autoresearch implementation.
- **Why it is relevant:** Offers another implementation perspective for feature and workflow comparison.
- **Compute/platform assumptions:** Follow its documented agent/model and compute requirements only as descriptive metadata.
- **Cost/credential exposure:** Provider APIs and GPU execution may expose credentials and incur cost.
- **Benchmark compatibility:** Self-reported results require exact benchmark and environment verification.
- **Mutable/pinned status:** Default branch is mutable; pin before reproduction.
- **License caveat:** Verify code, model, dependency, and dataset licenses.
- **Safety caveat:** Bound iterations and reject destructive cleanup or uncontrolled spend.

### [Awesome Autoresearch](https://github.com/WecoAI/awesome-autoresearch)

- **Official/community status:** Community-maintained index.
- **Resource type:** Curated discovery list.
- **Why it is relevant:** Expands discovery across implementations, commentary, and tools when this catalog is too narrow.
- **Compute/platform assumptions:** Vary by linked resource; the index itself establishes none.
- **Cost/credential exposure:** Vary by destination; inspect each link independently.
- **Benchmark compatibility:** Inclusion does not establish benchmark equivalence or result quality.
- **Mutable/pinned status:** The list and its outbound links are mutable; record an access date.
- **License caveat:** The index license does not grant licenses to linked projects.
- **Safety caveat:** Treat inclusion and popularity as discovery signals only, never trust or quality proof.
