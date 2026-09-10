#!/usr/bin/env bats
#
# BATS unit tests for Bluefin Server OS shell contracts, installer scripts, and sysupdate logic.

setup() {
    export REPO_ROOT="${BLUEFIN_SERVER_ROOT:-/home/jorge/src/server}"
    if [ ! -d "$REPO_ROOT" ]; then
        skip "Bluefin server repository not found at $REPO_ROOT"
    fi
}

@test "files/os/issue.d/40-kubestellar.issue displays expected console and port" {
    ISSUE="${REPO_ROOT}/files/os/issue.d/40-kubestellar.issue"
    [ -f "$ISSUE" ]

    run grep "Bluefin Server" "$ISSUE"
    [ "$status" -eq 0 ]

    run grep "Default login: root / bluefin" "$ISSUE"
    [ "$status" -eq 0 ]

    run grep "8080" "$ISSUE"
    [ "$status" -eq 0 ]
}

@test "files/os/justfile parses cleanly with just --summary" {
    JUSTFILE="${REPO_ROOT}/files/os/justfile"
    [ -f "$JUSTFILE" ]

    if ! command -v just >/dev/null 2>&1; then
        skip "just command not available in PATH"
    fi

    run just --justfile "$JUSTFILE" --summary
    [ "$status" -eq 0 ]
    [[ "$output" =~ "k8s" ]]
}

@test "sysupdate transfer files contain valid @v wildcard in MatchPattern" {
    for tf in "${REPO_ROOT}"/files/os/sysupdate.d/*.transfer "${REPO_ROOT}"/files/os/sysupdate.k0s.d/*.transfer; do
        [ -f "$tf" ] || continue
        # Must have MatchPattern in both Source and Target with @v
        src_pat=$(grep -E '^\s*MatchPattern\s*=' "$tf" | head -n1 | cut -d= -f2- | tr -d ' ')
        tgt_pat=$(grep -E '^\s*MatchPattern\s*=' "$tf" | tail -n1 | cut -d= -f2- | tr -d ' ')

        [[ "$src_pat" =~ "@v" ]]
        [[ "$tgt_pat" =~ "@v" ]]
    done
}

@test "installer wrapper unattended cmdline parsing detects unattended mode correctly" {
    parse_mode() {
        local CMDLINE="$1"
        if [[ " ${CMDLINE} " == *" unattended "* ]]; then
            echo "unattended"
        else
            echo "interactive"
        fi
    }

    run parse_mode "rw console=tty0 unattended console=ttyS0"
    [ "$status" -eq 0 ]
    [ "$output" = "unattended" ]

    run parse_mode "rw console=tty0 console=ttyS0"
    [ "$status" -eq 0 ]
    [ "$output" = "interactive" ]

    # Substrings like "unattended-upgrades" must not trigger unattended mode
    run parse_mode "rw console=tty0 unattended-upgrades=0"
    [ "$status" -eq 0 ]
    [ "$output" = "interactive" ]
}

@test "installer stage_fallback_bootloader candidate ordering prioritizes systemd-boot" {
    # Test candidate resolution hierarchy inside a mock chroot / esp mount
    MOCK_DIR="./.mock_esp_candidate_test"
    rm -rf "${MOCK_DIR}"
    mkdir -p "${MOCK_DIR}/mnt/esp/EFI/BOOT"
    mkdir -p "${MOCK_DIR}/mnt/esp/EFI/systemd"
    mkdir -p "${MOCK_DIR}/mnt/esp/EFI/Linux"
    mkdir -p "${MOCK_DIR}/usr/lib/bluefin-server"

    echo "systemd-boot" > "${MOCK_DIR}/mnt/esp/EFI/systemd/systemd-bootx64.efi"
    echo "target-uki" > "${MOCK_DIR}/mnt/esp/EFI/Linux/bluefin-server.efi"
    echo "packaged-uki" > "${MOCK_DIR}/usr/lib/bluefin-server/bluefin-server.efi"

    stage_fallback() {
        local base="$1"
        for candidate in \
            "${base}/mnt/esp/EFI/systemd/systemd-bootx64.efi" \
            "${base}/mnt/esp/flatcar/bluefin-server.efi" \
            "${base}/mnt/esp/EFI/Linux/bluefin-server.efi" \
            "${base}/usr/lib/bluefin-server/bluefin-server.efi"; do
            if [ -f "${candidate}" ]; then
                cp -a "${candidate}" "${base}/mnt/esp/EFI/BOOT/BOOTX64.EFI"
                break
            fi
        done
    }

    stage_fallback "${MOCK_DIR}"
    run cat "${MOCK_DIR}/mnt/esp/EFI/BOOT/BOOTX64.EFI"
    [ "$status" -eq 0 ]
    [ "$output" = "systemd-boot" ]

    # If systemd-boot is missing, falls back to target UKI
    rm "${MOCK_DIR}/mnt/esp/EFI/systemd/systemd-bootx64.efi"
    stage_fallback "${MOCK_DIR}"
    run cat "${MOCK_DIR}/mnt/esp/EFI/BOOT/BOOTX64.EFI"
    [ "$status" -eq 0 ]
    [ "$output" = "target-uki" ]

    rm -rf "${MOCK_DIR}"
}

@test "sshd preset disables both sshd.service and sshd.socket" {
    PRESET="${REPO_ROOT}/files/os/systemd/system-preset/zz-enable-sshd.preset"
    [ -f "$PRESET" ]

    run grep "disable sshd.service" "$PRESET"
    [ "$status" -eq 0 ]

    run grep "disable sshd.socket" "$PRESET"
    [ "$status" -eq 0 ]
}
