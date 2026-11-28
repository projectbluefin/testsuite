---
name: polkit-password-prompt
description: "How the chairlift suite answers a real polkit password prompt in the GNOME session, and waits for the app Homebrew installs at first login."
metadata:
  type: reference
  audience: agents
  maturity: draft
---
# Answering a polkit password prompt (chairlift suite)

Only the `chairlift` suite answers a real polkit prompt, and only because
`e2e.yml` gives its guest a throwaway password (`SUITE_DIR == chairlift`; see
#1326). Never add a polkit rule to get past a prompt: the scenario would no
longer test the shipped `auth_admin_keep` default.

- `tests/chairlift/polkit_tty_agent.py` runs in the guest with the guest's
  `python3` (standard library only), started over SSH through
  `detached_launch_command()`. It forks `pkttyagent --process <GUI pid>` on a
  private PTY, writes the password from the guest-side file when it sees
  `password:`, and writes `registered` / `answered N` / `stopped` / `error`
  lines to a status file the steps poll. The password never reaches the
  container, a command line or the behave log; the transcript is saved with it
  replaced. This is ChairLift's own technique (its Docker system test).
- Bind the agent to the GUI's pid, not the session: GNOME Shell's own agent
  still owns the session, and a process-bound agent takes precedence for that
  process. If the agent answers no prompt and the action still succeeds,
  something else authorized it; the step fails and says so.
- Prove the action through `CHAIRLIFT_ACTION_JOURNAL` (the one test hook in the
  released binary): `would_run` must be the real `pkexec` argv with
  `suppressed: no`, and `outcome` must be `succeeded`. Then check the system
  state itself over SSH.
- Pick an action that changes nothing a later scenario depends on and undo it
  in the same scenario (the Automatic Updates switch flips `uupd.timer`), with
  a `sudo -n` restore in `after_scenario` in case the scenario stops half way.
  `auth_admin_keep` may let the undo through without a second prompt.

The suite also needs the cask that Homebrew installs at first login. It waits
for the launcher with one bounded deadline and fails, never skips, when
Homebrew setup cannot install it. How `brew-preinstall.service` ends is
recorded (state, exit status, journal tail in
`results/chairlift-brew-preinstall.txt`) but not judged yet: any ending but
`active` with result `success` (failed, still running when the wait ends,
never started, unit missing) is printed as a known gap until a maintainer
decides (#1326). A journal that cannot be read fails the step.

To read a user unit's journal as root, do not use `journalctl --user-unit=`:
it matches the `_UID=` of whoever runs `journalctl`, so under `sudo` it finds
nothing. Match the test user's uid yourself:
`journalctl _SYSTEMD_USER_UNIT=<unit> _UID=<uid> + USER_UNIT=<unit> _UID=<uid>`.
