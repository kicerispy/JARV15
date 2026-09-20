# JARVIS Wake-Word Production Baseline

## Status

The personalized Heed wake-word model is the current production baseline for JARVIS.

The production runtime loads:

- `Jarvis/export/wake.onnx`
- `Jarvis/export/wake.json`

The personalized training dataset and model weights remain local-only and are intentionally ignored by Git.

## Production model integrity

Personalized production ONNX SHA256:

`8D8D2B9D5EFE819D341676778A7476521B3B8BA4BB15EB5666D5FCBCE3C3BF84`

Production and personalized `wake.onnx` were verified byte-for-byte with matching SHA256 hashes.

Production and personalized `wake.json` were also verified with matching SHA256:

`F6DF7BF66EDA4DF36D25A2319D0182D30BF35699D3450935551B95DB82C209F7`

The model binaries are not committed to Git. Rebuilding or restoring the local model should be followed by a hash check.

## Wake model baseline

The personalized model was trained from the local voice dataset with:

- 20 positive `Jarvis` recordings
- 60 negative recordings, including targeted `Jared`, `Jar`, and `Java` hard negatives
- 16 kHz mono audio
- Heed medium model
- Exported FP32 ONNX runtime model

Exported Heed threshold:

`0.700`

Production preprocessing remains aligned with the training/export pipeline:

1. 100 Hz high-pass filter
2. 50/60 Hz mains-notch filtering
3. Peak normalization to -3 dBFS for model input
4. Log-mel features
5. CMN

The production energy/voice-band gate operates before model activation.

## Temporal activation baseline

Normal activation:

- Heed candidate threshold: `0.500`
- Strong single-frame trigger: `0.900`
- Moderate multi-frame threshold: `0.620`
- Multi-frame support threshold: `0.680`
- Soft threshold: `0.560`
- Score window: `6` frames
- Maximum speech episode: `1.80` seconds
- Silence reset: `0.30` seconds
- Minimum speech support: `0.45`

Active-task activation:

- Strong single-frame trigger: `0.920`

Temporal confirmation must use the original frame timeline. Weak frames must not be removed before adjacency checks; doing so can incorrectly turn separated peaks into a false consecutive sequence.

## Validation baseline

The current personalized holdout result used for the production promotion was:

- Positive fusion activations: 10/10
- Negative fusion activations: 0/10

The live production check also confirmed:

- Strong natural wake scores from the personalized model
- Activation from farther away in the room
- No observed false activation during the test
- No observed activation from targeted similar words

## Regression tests

Run these after changing wake-word code or activation thresholds:

```powershell
.\jarvis_cuda\Scripts\python.exe -m py_compile .\wakeword.py .\activation_controller.py .\activation_controller_test.py
.\jarvis_cuda\Scripts\python.exe .\activation_controller_test.py
.\jarvis_cuda\Scripts\python.exe .\wakeword_ab_test.py
.\jarvis_cuda\Scripts\python.exe .\wakeword_activation_fusion_test.py
```

The A/B and fusion harnesses require the local ignored `wakeword_dataset` and personalized export artifacts.

## Model A/B testing

`wakeword.py` supports isolated local A/B testing through:

- `JARVIS_WAKE_MODEL_PATH`
- `JARVIS_WAKE_METADATA_PATH`

These variables must be cleared before a normal production run:

```powershell
Remove-Item Env:JARVIS_WAKE_MODEL_PATH -ErrorAction SilentlyContinue
Remove-Item Env:JARVIS_WAKE_METADATA_PATH -ErrorAction SilentlyContinue
Remove-Item Env:JARVIS_ACTIVATION_DEBUG -ErrorAction SilentlyContinue
```

Do not overwrite the production model merely to test an experimental export.

## Rollback

A generic production model backup is kept locally under `Jarvis/export` and is ignored by Git.

Use the timestamp printed when the backup was created:

```powershell
$stamp = "YYYYMMDD-HHMMSS"

Copy-Item ".\Jarvis\export\wake.generic.backup.$stamp.onnx" ".\Jarvis\export\wake.onnx" -Force
Copy-Item ".\Jarvis\export\wake.generic.backup.$stamp.json" ".\Jarvis\export\wake.json" -Force
```

After rollback, verify both hashes and run JARVIS normally.

## Privacy / repository hygiene

The following remain local and must not be committed:

- `wakeword_dataset/`
- Recorded WAV files
- Heed `.pt` weights
- ONNX model binaries
- Timestamped generic model backups

The repository keeps the recorder, A/B harness, and deterministic fusion regression test because they are useful for future wake-word improvements and retraining.
