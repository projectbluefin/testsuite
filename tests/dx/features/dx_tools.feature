@dx_only @developer_suite
Feature: Bluefin DX variant smoke tests
  Validates developer-experience-specific tools present in the DX image.
  These scenarios are SKIPPED on standard Bluefin — DX only.
  Runner: qecore-headless + behave (GNOME GUI interaction for VS Code/Codium).

  # Requires: Bluefin DX golden disk (ghcr.io/ublue-os/bluefin-dx:latest).
  # See QA-REVIEW.md Epic E05 for full design.

  @dx @vscode @launch
  Scenario: VS Code or Codium launches and window is accessible
    # AT-SPI app name is likely "code" or "codium".
    * Start application "code" via "command"
    * Wait until "Visual Studio Code" "frame" appears in "code"
    * Application "code" is running

  @dx @vscode @close
  Scenario: VS Code closes cleanly
    * Start application "code" via "command"
    * Wait until "Visual Studio Code" "frame" appears in "code"
    * Close application "code" via "shortcut"
    * Application "code" is no longer running

  @dx @devcontainer @plain_ssh
  Scenario: devcontainer CLI is available on PATH
    * Run DX SSH command: "which devcontainer || echo missing"
    * Last command output does not contain "missing"

  @dx @distrobox @plain_ssh
  Scenario: distrobox CLI is available
    * Run DX SSH command: "which distrobox || echo missing"
    * Last command output does not contain "missing"

  @pending @dx @distrobox @plain_ssh
  Scenario: distrobox enter works with default container
    # Pending: requires pulling fedora:latest from the registry; times out in CI
    # because the DX runner has no warm container cache.
    * DX distrobox "test-dx" can be created from "fedora:latest"

  # The following scenarios cover the full distrobox value proposition —
  # create a container, install an app inside it, export it to the host.
  # All carry @requires_cached_image: they need a pre-pulled
  # registry.fedoraproject.org/fedora-toolbox:latest on the VM, which no
  # caching infrastructure provides yet (see projectbluefin/testsuite#501,
  # blocked on projectbluefin/lab#621).
  #
  # @requires_cached_image is a runtime capability gate, not a pending marker:
  # environment.py probes `podman image exists` for the image each scenario
  # names and skips with an explicit reason while it is absent, exactly as
  # @requires_brew does for Homebrew. Once lab#621 pre-pulls the image these
  # scenarios activate on their own — no edit to this file.
  @dx @distrobox @plain_ssh @requires_cached_image
  Scenario: distrobox container can be created from fedora-toolbox
    * DX distrobox "test-box" can be created from "registry.fedoraproject.org/fedora-toolbox:latest"

  @dx @distrobox @plain_ssh @requires_cached_image
  Scenario: package can be installed inside a distrobox container
    * DX distrobox "test-box" can be created from "registry.fedoraproject.org/fedora-toolbox:latest"
    * DX distrobox "test-box" installs package "htop"

  @dx @distrobox @plain_ssh @requires_cached_image
  Scenario: app inside a distrobox container can be exported to the host
    * DX distrobox "test-box" can be created from "registry.fedoraproject.org/fedora-toolbox:latest"
    * DX distrobox "test-box" installs package "htop"
    * DX distrobox "test-box" exports "/usr/bin/htop" to the host

  @dx @toolbox @plain_ssh
  Scenario: toolbox is available as alternative to distrobox
    * Run DX SSH command: "which toolbox || echo missing"
    * Last command output does not contain "missing"

  @dx @podman_compose @plain_ssh
  Scenario: podman-compose is available for container orchestration
    * Run DX SSH command: "podman-compose --version"
    * SSH command return code is "0"
    * Last command output contains "podman-compose"

  @pending @dx @jupyter @plain_ssh
  Scenario: JupyterLab can be launched (DX includes scientific stack)
    # Pending: JupyterLab is not preinstalled in the DX base image, so this covers
    # planned scientific-stack content rather than shipped behaviour.
    * Run DX SSH command: "which jupyter-lab 2>/dev/null || (pip3 show jupyterlab 2>/dev/null | grep -q Name && echo found) || echo missing"
    * SSH command return code is "0"
    * Last command output does not contain "missing"

  @pending @dx @brew @plain_ssh
  Scenario: Homebrew is available on the DX variant
    # Pending: e2e.yml masks brew-setup.service in CI, so brew is not initialized (see #487).
    * Run DX SSH command: "brew --version 2>&1 | head -1"
    * SSH command return code is "0"
    * Last command output contains "Homebrew"

  @pending @dx @mise @plain_ssh
  Scenario: mise is available for version management
    # Pending: mise comes from Homebrew, and e2e.yml masks brew-setup.service in CI (see #487).
    * Run DX SSH command: "mise --version"
    * SSH command return code is "0"

  @pending @dx @mise @plain_ssh
  Scenario: mise lists available runtimes
    # Pending: mise comes from Homebrew, and e2e.yml masks brew-setup.service in CI (see #487).
    * Run DX SSH command: "mise ls 2>/dev/null | wc -l || echo 0"
    * SSH command return code is "0"

  @dx @nodejs @plain_ssh
  Scenario: Node.js is available on DX
    * Run DX SSH command: "node --version 2>/dev/null || mise exec node -- node --version 2>/dev/null || echo missing"
    * Last command output does not contain "missing"

  @dx @python @plain_ssh
  Scenario: Python venv module is available
    * Run DX SSH command: "python3 -c 'import venv'"
    * SSH command return code is "0"

  @dx @podman @plain_ssh
  Scenario: podman CLI is functional
    * Run DX SSH command: "podman info --format '{{.Host.OSType}}' 2>/dev/null || echo missing"
    * Last command output does not contain "missing"

  @dx @vscode @plain_ssh
  Scenario: VS Code CLI (code) is available on PATH
    * Run DX SSH command: "which code || which codium || echo missing"
    * Last command output does not contain "missing"
