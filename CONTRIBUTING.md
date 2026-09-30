# Contributing

Nuvio Hub for Kodi starts its public development from version 6.0.7. Contributions are welcome in code, design, testing, documentation and accessibility.

## Useful places to help

- Kodi Python integration and reliable playback/navigation behavior.
- Skin XML, focus order and remote-control usability.
- CoreELEC and other real-device testing, including lower-powered hardware.
- Metadata mapping, missing episode descriptions and artwork edge cases.
- Performance measurements, installation instructions and clear bug reports.

## Workflow

Open an issue before a substantial change so we can agree on scope. Fork the repository, create a focused branch and submit a pull request describing the problem, resulting behavior and validation. Include before/after screenshots for visible UI changes, with fictional content or identifying artwork blurred.

Anyone can submit a pull request. Trusted ongoing contributors may receive a collaborator invitation from the repository owner. This gives write access after acceptance; use feature branches and reviewed pull requests for shared work.

Keep component licenses and upstream notices. Do not include personal profiles, account credentials, personalized provider URLs or debug databases. Generated installer archives belong in Releases.

## Source layout

| Folder | Role |
| --- | --- |
| `plugin.video.nuviohub/` | Backend, provider/account integration, playback services and bundle installer |
| `script.nuvio/` | Nuvio interface/controller and WindowXML assets |
| `skin.nuvio/` | Kodi skin, launcher and playback presentation |
| `screensaver.nuvio/` | Nuvio screensaver |
| `review/build_bundle.py` | Build the installable bundle from all four source components |
| `review/check_packaged_build.py` | Check nested packages, metadata, assets and module imports |

## Build and targeted checks

Run from the repository root with Python 3.10 or newer. These scripts use the standard library; the import smoke check uses the included Kodi stubs.

```sh
python3 review/build_bundle.py --output Nuvio-Hub-Complete-6.0.7.zip
python3 review/check_packaged_build.py Nuvio-Hub-Complete-6.0.7.zip
```

For the Continue Watching regression group, use a temporary test profile:

```sh
python3 - <<'PY'
import os, sys, tempfile, unittest
from pathlib import Path
with tempfile.TemporaryDirectory(prefix='nuvio-tests-') as profile:
    os.environ['NUVIO_TEST_PROFILE'] = profile
    sys.path.insert(0, str(Path('plugin.video.nuviohub/tests').resolve()))
    suite = unittest.defaultTestLoader.loadTestsFromName('test_nuvio_605.PlaybackExitAndOrder')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
PY
```

The builder generates nested packages under `plugin.video.nuviohub/resources/packages/`; those files are intentionally not tracked. A source checkout must be built before installation. Public README edits can change a rebuilt ZIP's hash even when executable code and assets match the baseline. Use the checksum attached to the downloaded release when verifying that exact release asset.

Tests with stubs do not replace Kodi runtime or device testing. Report what you tested and what remains untested.
