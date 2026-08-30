# SimForge — demo video brief (HyperFrames)

Everything needed to produce the hackathon demo video. **Read the Hard rules
section before writing a single frame** — the video's whole credibility rests on
not overclaiming, and the judges are the people who built Daytona.

---

## 1. What SimForge is

> Describe your operation. Fork the future before you build it.

SimForge turns a natural-language description of a physical operation into an
executable simulation, runs it across hundreds of stochastic futures inside
isolated Daytona sandboxes, tests alternative interventions against the same
futures, and returns an operational **and financial** comparison.

The one-sentence claim the whole product rests on:

> **The LLM explains the result. The simulator produces the numbers.**

The demo models a real industrial failure chain:

```
continuous CO₂ production  →  storage tanks  →  tanker collections
        a collection is missed
                ↓
        storage keeps filling
                ↓
        tanks reach capacity
                ↓
        production must be curtailed
                ↓
        output is lost, permanently
```

---

## 2. The story the video must tell

This is the spine. Do not reorder it — the punchline only lands in this order.

1. **The setup.** A plant makes 1 t/h of CO₂ (24 t/day). Two 45 t tanks. One
   tanker a day, 24 t. Collection capacity exactly matches production.
2. **The trap.** That leaves *zero recovery capacity*. Miss one collection and
   the 24 t never comes back — the buffer just fills, permanently.
3. **The measurement.** 200 stochastic futures. The plant curtails production in
   **46.5%** of them, losing **12.2 t** on average and **57.9 t** in the bad tail.
4. **The interventions.** Three obvious fixes, each executed in its own isolated
   Daytona sandbox, against *the same 200 futures*.
5. **The punchline.** The two interventions that eliminate **100%** of the loss
   are the two that lose money. The one that wins doesn't even fix the problem
   fully — it recovers 88% of the loss and pays back in 4.4 years.

> **A spreadsheet would have picked the wrong answer. The simulator didn't.**

---

## 3. The numbers — verified, do not invent or round differently

Generate them fresh before recording:

```bash
python demo.py --execution daytona --runs 200 --json video-data.json
```

Take every figure from that file. Do not hand-type numbers from this document
into the composition — read them from the JSON, so the video and the live demo
can never disagree. These are the current values, for storyboarding:

### Baseline
| | |
|---|---|
| Expected lost production | **12.2 t** |
| P95 lost production | **57.9 t** |
| Failure probability | **46.5 %** |
| Expected output | 707.7 t |
| Peak storage utilisation | 84.0 % |

### Interventions

| Intervention | Expected loss | vs baseline | P95 | Failure | Cost | **Annual value** | Payback |
|---|---|---|---|---|---|---|---|
| **Add a 3rd 45 t tank** | 1.5 t | **−88%** | 12.9 t | 8.0% | £80,000 CAPEX | **+£10,109/y** | **4.4 y** |
| 2nd daily collection | 0.0 t | −100% | 0.0 t | 0.0% | £53,898/y OPEX | **−£31,614/y** | never |
| 36 t tanker | 0.1 t | −100% | 0.0 t | 1.0% | £40,267/y OPEX | **−£18,091/y** | never |

**Recommendation: add the third tank.**

The ranking rule, shown on screen so it is not a black box:

> `annual_value = annualised benefit − annual opex delta − capex / 10 years`

### Execution (the Daytona proof)
| | |
|---|---|
| Mode | Daytona |
| Isolation | one isolated sandbox per scenario, run in parallel |
| Snapshot | `simforge-572e50b46b55` — model pre-baked, nothing uploaded |
| Sandbox runtime | Python 3.12.10 |
| Sandbox ids | 4 real UUIDs — baseline + 3 scenarios |
| Total | ~6 s for 800 simulated months |

---

## 4. Hard rules — non-negotiable

These are the things that lose the room if you get them wrong.

1. **Never say "native Daytona forks", "forking", or "branching sandboxes".**
   `Sandbox.fork()` is implemented in our code but this account cannot use it:
   forking requires a VM-class sandbox and no region serves them on this key
   (proven four ways — see `HANDOVER.md`). Say instead:
   *"each counterfactual executes in its own isolated Daytona sandbox, in parallel."*
   That is true, verifiable on screen, and still strong.

2. **Every number on screen must come from `video-data.json`.** No illustrative
   figures, no rounded-for-drama values, no invented percentages. If a number
   isn't in the backend output, it doesn't go in the video.

3. **Don't claim real-plant validation.** These are explicit demo assumptions.
   If the script needs a qualifier, use *"a modelled CO₂ operation"*, never
   *"a real plant"*.

4. **Don't imply the LLM computed anything.** The LLM writes the ModelSpec and
   can phrase the recommendation. It never produces a KPI.

5. **No fake UI.** Every screen shown must be a real capture of the running app.
   Don't mock up prettier panels in HTML and pass them off as the product.

---

## 5. Assets to capture

Start the app and warm it up first:

```bash
uvicorn app.main:app                       # http://localhost:8000
python demo.py --execution daytona --runs 200   # WARM-UP — see §7
```

Capture at **1920×1080**, browser zoom 100%, dark theme, no browser chrome
(use a clean window / hide bookmarks).

| # | Shot | What must be legible |
|---|---|---|
| 1 | Description form, filled in | The natural-language sentence |
| 2 | Gemini's clarification question | That the AI asks rather than assumes |
| 3 | Assumptions review | The `user` vs `assumption` provenance labels |
| 4 | Baseline dashboard | Storage curve **hitting the 90 t ceiling**, then the loss curve rising |
| 5 | Scenario comparison table | All three interventions side by side |
| 6 | **"Where this ran" panel** | The 4 Daytona sandbox ids, snapshot name, Python version |
| 7 | Recommendation | The trade-off sentence |

**Shot 6 is the single most important frame in the video.** It is the only
on-screen proof that Daytona executed anything. If one frame has to be perfect,
it is that one.

Also capture the terminal running `demo.py` — the `[daytona] created ... sandbox`
lines and the EXECUTION block make a strong B-roll cut.

---

## 6. HyperFrames implementation

```bash
npx hyperframes init simforge-video
cd simforge-video
npx hyperframes preview     # live reload while building
npx hyperframes render      # → MP4
```

Requires **Node 22+ and FFmpeg**.

Composition skeleton — 1920×1080, tracks layered by `data-track-index`
(0 = background):

```html
<div id="stage" data-composition-id="simforge" data-start="0"
     data-width="1920" data-height="1080">

  <img class="clip" data-start="0"  data-duration="5" data-track-index="0"
       src="assets/01-description.png">
  <h1 class="clip"  data-start="0.5" data-duration="4" data-track-index="1"
      id="hook">Describe your operation.</h1>

  <audio data-start="0" data-duration="75" data-track-index="9"
         data-volume="0.35" src="assets/music.wav"></audio>

  <script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>
  <script>
    const tl = gsap.timeline({ paused: true });
    tl.from("#hook", { opacity: 0, y: 40, duration: 0.8 }, 0.5);
    window.__timelines = window.__timelines || {};
    window.__timelines.simforge = tl;   // keyed by data-composition-id
  </script>
</div>
```

Rules that matter: media elements need `class="clip"`; timelines go in
`window.__timelines` keyed by the composition id and must be **`paused: true`**
(HyperFrames seeks them deterministically); every element needs `data-start` and
`data-duration`.

### Suggested cut — 75 seconds

| Time | Beat | Visual |
|---|---|---|
| 0–6 s | "Should we buy another tank?" — the question operators guess at | Title card |
| 6–14 s | Describe the operation in plain English | Shot 1 → 2 |
| 14–22 s | The AI asks what it doesn't know; assumptions are labelled | Shot 3, highlight the provenance chips |
| 22–32 s | **The failure.** Storage climbs to the 90 t ceiling, production curtails | Shot 4 — animate the curve, hold on the ceiling hit |
| 32–42 s | 200 futures. Fails 46.5% of the time. 57.9 t in the bad tail | Animate the three KPI numbers counting up |
| 42–52 s | **Daytona.** Four isolated sandboxes, in parallel, same 200 futures | Shot 6 + terminal B-roll. Let the sandbox ids be readable |
| 52–66 s | The comparison. Two fixes eliminate 100% of the loss — and both lose money | Shot 5, reveal the annual-value column last |
| 66–75 s | The third tank wins: −88% loss, £10,109/y, payback 4.4 years | Shot 7 + closing line |

Closing line:

> **The LLM explains it. The simulator proves it.**

### Craft notes
- Let numbers **animate to their value** (GSAP counters) rather than cutting in;
  it makes the measurement feel computed, not asserted.
- The strongest single moment is the storage curve touching the 90 t ceiling.
  Give it a beat of silence.
- Reveal the annual-value column **after** the loss reductions. The surprise is
  the whole point, and it dies if both are on screen at once.
- Keep the sandbox ids on screen ≥ 2.5 s. They are the evidence.
- Prefer real captures over motion graphics. Judges trust screens, not slides.

---

## 7. Before you record

**Warm Daytona up.** A cold run takes **~25 s** because the runners pull the
snapshot image for the first time; warm runs take **3–6 s**. Run
`python demo.py --execution daytona --runs 200` a few minutes before recording,
or the app will sit on a spinner. This is the single most likely way the capture
session goes wrong.

Sanity check first:

```bash
curl 'localhost:8000/api/health?deep=1'      # must report "ok"
```

If Daytona is unreachable at capture time, `?execution=local` produces
**bit-identical numbers** — but then shot 6 shows local execution, and you lose
the Daytona proof. Fix Daytona rather than shipping that.

---

## 8. Reference

- `HANDOVER.md` — demo runbook, what is and isn't true about our Daytona usage
- `HANDOFF.md` — every displayed number mapped to its exact JSON path
- `video-data.json` — the source of truth for every figure in the video
