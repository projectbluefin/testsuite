---
name: gnome-51-app-divergences
description: "Why the Calculator and Text Editor smoke scenarios failed on plain GNOME OS 51 and what fixed them (#1211): stacked windows from repeated launches, the display read through AT-SPI Text, the save chooser outside the app, and Clear leaving an empty field."
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# GNOME 51: Calculator and Text Editor scenarios

These are **not** among the twelve GNOME 50 workarounds in
[gnome-51-audit.md](gnome-51-audit.md). The first plain `gnomeos-51` run
(audit §Run evidence) failed most Calculator and Text Editor scenarios. An
earlier version of this page blamed the `Key combo` path; the screenshots
show that was wrong. #1211 found the causes below and fixed them, and the
scenarios now pass on `quay.io/gnome_infrastructure/gnome-build-meta:gnomeos-51`.
`dakota:testing` and `utah:testing` don't ship either app, so these scenarios
skip there.

## Causes and fixes

| What failed | Cause | Fix |
| --- | --- | --- |
| Most scenarios after the first one in each feature | Each scenario's Background launched the app again. A second launch of a running app opens another window, so windows stacked (3–5 Calculator windows on screen) and the steps read `frames[0]`, the oldest. Typed text, Ctrl+N's new window and the calculator result all went to a window the step never read. | Launch steps call `stop_app_instances` first (exact-name `pkill`, TERM then KILL). Steps read the window with the AT-SPI `active` state, else the newest. |
| Calculator windows still stacked after that fix | The kernel cuts process names to 15 characters: Calculator runs as `gnome-calculato`, so `pkill -x gnome-calculator` matched nothing. | `stop_app_instances` cuts the name to 15 characters itself. |
| Text Editor reopened the last scenario's text | Text Editor keeps unsaved drafts and reopens them on the next launch. | Text Editor's launch also removes its state directory (`~/.local/share/org.gnome.TextEditor`, and the Flatpak equivalent) once the app has exited. |
| `Calculator display shows "3"` passed whatever the display showed | The display lookup gathered every label in the window, keypad labels included. `3`, `5` and `0` matched a key; `42` and `-5` matched nothing. | The lookup skips nodes under any button (`push button`, `toggle button`, menu buttons). |
| Display values read empty | The display is a `text` node whose dogtail `text` reads empty while the window shows the value. | `node_text` falls back to the AT-SPI Text interface (`get_text_iface`, `Atspi.Text.get_text`). |
| `Clear button resets display` | GNOME 51 clears to an empty input field, not `0`. | The scenario first proves the field reads `8+1`, then checks the input field is empty or `0`. History labels and keypad labels don't count, and a window with no input field fails. |
| `Save dialog via Ctrl+S` | The "Save a File" chooser opens as a top-level window outside Text Editor, while `org.gnome.Nautilus` and `xdg-desktop-portal-gtk` are registered; it is not a dialog in Text Editor's tree. | The check also looks at portal and Nautilus windows, counting only one with a button named exactly `Save`, so an ordinary Files window can't pass. |
| `Closing with unsaved changes shows discard dialog` | Same stacked-window cause. Ctrl+Q works: it shows libadwaita's "Save Changes?" prompt with **Discard All**, an `alert`, not a `dialog`. | Dialog checks accept `alert`. |

## For the next image

Display, buffer and dialog failures print the window's AT-SPI tree (role, name,
text and key states, 30 levels deep) in the assertion message. Read that before
changing a lookup: it shows where the value lives on the new image.

## Run evidence

| Run | Image | Branch commit | Result |
| --- | --- | --- | --- |
| [42919511431](https://github.com/projectbluefin/testsuite/actions/runs/42919511431) | `gnomeos-51` | `05e6ae5a` (before #1211) | Calculator 3 failed and 3 passed only on a keypad label; Text Editor 4 failed; screenshots show stacked windows |
| [43592207794](https://github.com/projectbluefin/testsuite/actions/runs/43592207794) | `gnomeos-51` | `f98464e7` | Text Editor all pass but save; Calculator display read empty, windows still stacked |
| [43593921231](https://github.com/projectbluefin/testsuite/actions/runs/43593921231) | `gnomeos-51` | `13ca7205` | Calculator 7/8 (Clear failed: empty field); Text Editor all pass but save |
| [43595503343](https://github.com/projectbluefin/testsuite/actions/runs/43595503343) | `gnomeos-51` | `347877cb` | All 9 Calculator and 6 Text Editor scenarios pass (coredump checks skip) |
