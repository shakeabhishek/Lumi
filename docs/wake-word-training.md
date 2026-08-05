# Training a "Hey Lumi" wake word

## The problem

Lumi does not answer to "Hey Lumi." She answers to **"Hey Jarvis."**

openwakeword ships only pre-trained models. Enumerated directly off the
installed package on the Pi (2026-08-05):

```
alexa            hey_jarvis       hey_marvin       hey_mycroft      weather
1_minute_timer   5_minute_timer   10_minute_timer  20_minute_timer
30_minute_timer  1_hour_timer
```

There is no `hey_lumi`. `config.py`'s `wake_word_model` therefore defaults to
`hey_jarvis` as a stand-in, and that is what is running on the device today.

This is a product-identity gap, not a config detail. The tagline promises
"Hey Lumi", onboarding step 3 invites the user to *name* their Lumi from a
curated palette (Lumi, Aria, Nova, Sage, Atlas, Iris, Juno, Hugo, Echo, Pip)
— and then the device wakes to none of those names. Every one of those ten
names needs a model that doesn't exist yet.

## What's already wired

The loading path is done, so a trained model is a drop-in with no code change:

- `OpenWakeWordWake(model=..., model_path=...)` loads a custom ONNX by path
  when the file exists, and falls back to the bundled pretrained set when it
  doesn't.
- `main.py` points `model_path` at `models/wake/<wake_word_model>.onnx`.
- So: train `hey_lumi.onnx`, drop it at `models/wake/hey_lumi.onnx`, set
  `LUMI_WAKE_WORD_MODEL=hey_lumi`, restart `lumi-voice`. Done.

Two traps that are now guarded but worth knowing:

1. **Score-dict keys differ by load method.** Bundled models key on friendly
   names (`hey_jarvis`); path-loaded models key on the **file stem**
   (`hey_jarvis_v0.1` for `hey_jarvis_v0.1.onnx`). `_listen()` looks up
   `self._model_name` in that dict, so **the filename stem must exactly equal
   the configured model name.** Name the file `hey_lumi.onnx`, not
   `hey_lumi_v0.1.onnx`.
2. **A name mismatch used to fail silently.** A missing key returns `0.0`
   forever, so the wake word simply never fires and nothing says why.
   `_load_model()` now validates the configured name against what actually
   loaded and logs `wake.model_missing` at error level. Check for that line
   in `journalctl -u lumi-voice` if wake stops working.

## Training procedure

openwakeword's own synthetic-data pipeline. No recorded speech needed — it
generates training audio with TTS, which is why this is a one-hour job rather
than a data-collection project.

**Requires a GPU.** Use the upstream Colab notebook
(`automatic_model_training.ipynb` in the openwakeword repo) on a T4; the Pi
cannot do this, and neither can a laptop CPU in reasonable time.

1. Open the notebook, set the target phrase to `hey lumi`.
2. Let it generate positive clips via `piper-sample-generator` — aim for the
   notebook's default sample count or higher. Vary speaker, speed, and pitch;
   the defaults already do this.
3. Negative/background data comes from the notebook's standard sets
   (AudioSet, FMA, plus generated hard negatives). **Add "hey Lumi"-adjacent
   phrases as explicit hard negatives** — "hey loomy", "hey lucy", "hey ludi",
   "hey movie", "okay Lumi". Short two-syllable names false-positive easily,
   and this is the cheapest place to fix that.
4. Train. Export ONNX.
5. Rename the export to exactly `hey_lumi.onnx` (see trap 1 above).

## Deploying

```bash
# From the Mac, per AGENTS.md's edit -> deploy loop:
mkdir -p models/wake && cp ~/Downloads/hey_lumi.onnx models/wake/
rsync -az models/wake/hey_lumi.onnx \
  -e ssh lumi@192.168.0.45:/home/lumi/lumi/models/wake/
ssh lumi@192.168.0.45 \
  "grep -q LUMI_WAKE_WORD_MODEL /home/lumi/lumi/.env \
   || echo LUMI_WAKE_WORD_MODEL=hey_lumi >> /home/lumi/lumi/.env"
ssh lumi@192.168.0.45 'sudo systemctl restart lumi-voice'
```

Note `models/` is gitignored (models are downloaded/generated, not checked
in), so the ONNX lives on the Pi and in the eventual pi-gen image, not in the
repo. Bake it into `os-image/` when Phase 6 comes around.

## Validating

Numbers off a validation split are not the acceptance criterion — this has to
work across a desk, in a case, over the speaker's own output. Test on the real
device:

1. **True positives.** Say "Hey Lumi" 20 times from ~1m at normal volume.
   Count fires. `journalctl -u lumi-voice -f | grep wake.fired` shows the
   score for each. Target ≥18/20.
2. **Distance and angle.** Repeat at 2m, and off-axis — the ReSpeaker mics
   face a rear vent in the SmartiPi enclosure, away from the user (see
   CLAUDE.md's open question on enclosure audio), so off-axis pickup is the
   real risk here, not on-axis accuracy.
3. **False positives.** Leave it running through an hour of normal desk
   conversation and a podcast. Zero fires is the bar; more than one per hour
   is unusable on an always-on device.
4. **Self-trigger.** Have Lumi say "Hey Lumi" in her own voice via
   `/settings/voice`. She must not wake herself — there's no hardware AEC (2-Mics
   HAT, AEC is software-side), so this is a genuine risk, not a hypothetical.
5. **Threshold tuning.** `LUMI_WAKE_WORD_THRESHOLD` defaults to 0.6. Raise it
   if step 3 fails, lower it if step 1 does. Retest both directions after any
   change — they trade off against each other.

## If it doesn't work

Custom openwakeword models on short two-syllable names are hit-or-miss.
Fallback is **Porcupine** (Picovoice), which generates custom wake words from
a web console and is generally more accurate on short phrases. CLAUDE.md
already lists it as an alternative. Cost: an access key, a dependency, and a
licensing review before any commercial release — free for personal use, which
covers V1 and the Lang Center demos.

Do not conclude "the wake word works" from a single successful "Hey Lumi" in
a quiet room. Steps 3 and 4 are the ones that decide whether this ships.
