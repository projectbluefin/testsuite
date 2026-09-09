"""Unit tests for tests/software/features/steps/flatpak_permissions_steps.py.

Covers the pure keyfile parsing helpers and the step wrappers that assert on
`flatpak override --show` / `flatpak info --show-permissions` output.
"""
import sys
import types
from unittest.mock import MagicMock, patch


def _import_module():
    behave_stub = types.ModuleType("behave")
    behave_stub.step = lambda *a, **kw: (lambda f: f)
    sys.modules["behave"] = behave_stub

    qecore_stub = types.ModuleType("qecore")
    qecore_common_stub = types.ModuleType("qecore.common_steps")
    qecore_common_stub.__all__ = []
    qecore_stub.common_steps = qecore_common_stub
    sys.modules["qecore"] = qecore_stub
    sys.modules["qecore.common_steps"] = qecore_common_stub

    # An earlier test module may have registered "tests.shared" as a plain
    # module; steps.py imports tests.shared.ssh_config, which needs the real
    # package, so drop any stand-in before importing.
    if not hasattr(sys.modules.get("tests.shared"), "__path__"):
        sys.modules.pop("tests.shared", None)
    import tests.shared  # noqa: F401,PLC0415 - real package for submodule imports

    ssh_steps_stub = types.ModuleType("tests.shared.ssh_steps")
    ssh_steps_stub.__all__ = []
    # A stub missing run_ssh permanently corrupts this sys.modules entry for
    # every later test in this xdist worker (e.g. test_installer_environment.py
    # monkeypatching ssh_steps.run_ssh), so keep the attribute present.
    ssh_steps_stub.run_ssh = MagicMock(return_value=("", 0))
    sys.modules["tests.shared.ssh_steps"] = ssh_steps_stub

    # steps.py imports smoke app_support (dogtail-dependent); stub it out.
    app_support_stub = types.ModuleType("tests.smoke.features.steps.app_support")
    app_support_stub.atspi_click = lambda *a, **kw: None
    app_support_stub.launch_background = lambda *a, **kw: None
    sys.modules["tests.smoke.features.steps.app_support"] = app_support_stub

    for key in list(sys.modules):
        if "software.features.steps" in key:
            del sys.modules[key]

    import tests.software.features.steps.flatpak_permissions_steps as m  # noqa: PLC0415
    return m


def _completed(stdout="", rc=0, stderr=""):
    result = MagicMock()
    result.stdout = stdout
    result.returncode = rc
    result.stderr = stderr
    return result


OVERRIDE_OUTPUT = """[Context]
sockets=!wayland;
devices=all;
filesystems=xdg-download:ro;home;

[Environment]
BLUEFIN_TESTSUITE=1
"""


class TestParseFlatpakContext:
    def test_parses_sections_and_keys(self):
        m = _import_module()
        parsed = m.parse_flatpak_context(OVERRIDE_OUTPUT)
        assert parsed["Context"]["devices"] == "all;"
        assert parsed["Environment"]["BLUEFIN_TESTSUITE"] == "1"

    def test_empty_output_is_empty_dict(self):
        m = _import_module()
        assert m.parse_flatpak_context("") == {}

    def test_section_with_no_entries_is_present(self):
        m = _import_module()
        assert m.parse_flatpak_context("[Context]\n") == {"Context": {}}

    def test_comments_and_stray_lines_ignored(self):
        m = _import_module()
        parsed = m.parse_flatpak_context("# comment\nstray=1\n[Context]\nshared=network;\n")
        assert parsed == {"Context": {"shared": "network;"}}

    def test_value_containing_equals_is_preserved(self):
        m = _import_module()
        parsed = m.parse_flatpak_context("[Environment]\nFOO=a=b\n")
        assert parsed["Environment"]["FOO"] == "a=b"


class TestContextValues:
    def test_splits_on_semicolon(self):
        m = _import_module()
        assert m.context_values(OVERRIDE_OUTPUT, "filesystems") == ["xdg-download:ro", "home"]

    def test_negated_socket_preserved(self):
        m = _import_module()
        assert m.context_values(OVERRIDE_OUTPUT, "sockets") == ["!wayland"]

    def test_missing_key_returns_empty_list(self):
        m = _import_module()
        assert m.context_values(OVERRIDE_OUTPUT, "features") == []

    def test_alternate_section(self):
        m = _import_module()
        assert m.context_values(OVERRIDE_OUTPUT, "BLUEFIN_TESTSUITE", section="Environment") == ["1"]


class TestOverrideKeys:
    def test_collects_qualified_keys(self):
        m = _import_module()
        assert m.override_keys(OVERRIDE_OUTPUT) == {
            "Context.sockets",
            "Context.devices",
            "Context.filesystems",
            "Environment.BLUEFIN_TESTSUITE",
        }

    def test_empty_after_reset(self):
        m = _import_module()
        assert m.override_keys("") == set()

    def test_bare_section_header_yields_no_keys(self):
        m = _import_module()
        assert m.override_keys("[Context]\n") == set()


class TestOverrideSteps:
    def test_grants_passes_on_match(self):
        m = _import_module()
        with patch.object(m, "_flatpak", return_value=_completed(OVERRIDE_OUTPUT)):
            m.flatpak_user_override_grants(MagicMock(), "app", "devices", "all")

    def test_grants_fails_on_missing_value(self):
        m = _import_module()
        with patch.object(m, "_flatpak", return_value=_completed(OVERRIDE_OUTPUT)):
            try:
                m.flatpak_user_override_grants(MagicMock(), "app", "devices", "dri")
            except AssertionError:
                return
        raise AssertionError("expected AssertionError for absent value")

    def test_grants_fails_on_nonzero_return_code(self):
        m = _import_module()
        with patch.object(m, "_flatpak", return_value=_completed("", rc=1, stderr="boom")):
            try:
                m.flatpak_user_override_grants(MagicMock(), "app", "devices", "all")
            except AssertionError:
                return
        raise AssertionError("expected AssertionError for rc=1")

    def test_section_sets_exact_value(self):
        m = _import_module()
        with patch.object(m, "_flatpak", return_value=_completed(OVERRIDE_OUTPUT)):
            m.flatpak_user_override_section_sets(
                MagicMock(), "app", "Environment", "BLUEFIN_TESTSUITE", "1"
            )

    def test_section_sets_rejects_wrong_value(self):
        m = _import_module()
        with patch.object(m, "_flatpak", return_value=_completed(OVERRIDE_OUTPUT)):
            try:
                m.flatpak_user_override_section_sets(
                    MagicMock(), "app", "Environment", "BLUEFIN_TESTSUITE", "0"
                )
            except AssertionError:
                return
        raise AssertionError("expected AssertionError for wrong value")

    def test_records_at_least_counts_keys(self):
        m = _import_module()
        with patch.object(m, "_flatpak", return_value=_completed(OVERRIDE_OUTPUT)):
            m.flatpak_user_override_records_at_least(MagicMock(), "app", "4")

    def test_records_at_least_fails_when_short(self):
        m = _import_module()
        with patch.object(m, "_flatpak", return_value=_completed("[Context]\nshared=network;\n")):
            try:
                m.flatpak_user_override_records_at_least(MagicMock(), "app", "2")
            except AssertionError:
                return
        raise AssertionError("expected AssertionError when fewer keys than required")

    def test_records_none_passes_on_empty_output(self):
        m = _import_module()
        with patch.object(m, "_flatpak", return_value=_completed("")):
            m.flatpak_user_override_records_none(MagicMock(), "app")

    def test_records_none_fails_when_override_remains(self):
        m = _import_module()
        with patch.object(m, "_flatpak", return_value=_completed(OVERRIDE_OUTPUT)):
            try:
                m.flatpak_user_override_records_none(MagicMock(), "app")
            except AssertionError:
                return
        raise AssertionError("expected AssertionError when overrides remain")


class TestInstalledAppSweep:
    def test_empty_install_set_passes(self):
        m = _import_module()
        context = MagicMock()
        with patch.object(m, "_flatpak", return_value=_completed("")):
            m.every_installed_app_exposes_permissions(context)
        assert context.flatpak_apps_checked == 0

    def test_each_app_is_queried(self):
        m = _import_module()
        context = MagicMock()
        responses = [
            _completed("org.gnome.Calculator\norg.gnome.Loupe\n"),
            _completed("[Context]\nshared=network;\n"),
            _completed("[Context]\ndevices=dri;\n"),
        ]
        with patch.object(m, "_flatpak", side_effect=responses):
            m.every_installed_app_exposes_permissions(context)
        assert context.flatpak_apps_checked == 2

    def test_missing_context_section_fails(self):
        m = _import_module()
        responses = [_completed("org.gnome.Calculator\n"), _completed("garbage output\n")]
        with patch.object(m, "_flatpak", side_effect=responses):
            try:
                m.every_installed_app_exposes_permissions(MagicMock())
            except AssertionError:
                return
        raise AssertionError("expected AssertionError for unparsable permission output")

    def test_list_failure_fails(self):
        m = _import_module()
        with patch.object(m, "_flatpak", return_value=_completed("", rc=1)):
            try:
                m.every_installed_app_exposes_permissions(MagicMock())
            except AssertionError:
                return
        raise AssertionError("expected AssertionError when flatpak list fails")


class TestPermissionStore:
    def test_queryable_on_success(self):
        m = _import_module()
        with patch.object(m, "_flatpak", return_value=_completed("background\tbackground\tapp\n")):
            m.flatpak_portal_permission_store_is_queryable(MagicMock())

    def test_empty_store_still_passes(self):
        m = _import_module()
        with patch.object(m, "_flatpak", return_value=_completed("")):
            m.flatpak_portal_permission_store_is_queryable(MagicMock())

    def test_failure_raises(self):
        m = _import_module()
        with patch.object(m, "_flatpak", return_value=_completed("", rc=1, stderr="no store")):
            try:
                m.flatpak_portal_permission_store_is_queryable(MagicMock())
            except AssertionError:
                return
        raise AssertionError("expected AssertionError when permission store is unavailable")


class TestFlatpakCallSignature:
    """`_flatpak` is `_flatpak(context, args, timeout=...)`.

    Calling it with only the argument list raised TypeError at runtime for
    every step in this module; the mocks accepted any signature and hid it.
    """

    def test_override_show_passes_context_first(self):
        m = _import_module()
        ctx = MagicMock()
        with patch.object(m, "_flatpak", return_value=_completed(OVERRIDE_OUTPUT)) as flatpak:
            m.flatpak_user_override_grants(ctx, "app", "devices", "all")

        assert flatpak.call_args.args[0] is ctx
        assert flatpak.call_args.args[1] == ["override", "--user", "--show", "app"]

    def test_installed_sweep_passes_context_first(self):
        m = _import_module()
        ctx = MagicMock()
        with patch.object(m, "_flatpak", return_value=_completed("")) as flatpak:
            m.every_installed_app_exposes_permissions(ctx)

        assert flatpak.call_args.args[0] is ctx

    def test_permission_store_passes_context_first(self):
        m = _import_module()
        ctx = MagicMock()
        with patch.object(m, "_flatpak", return_value=_completed("")) as flatpak:
            m.flatpak_portal_permission_store_is_queryable(ctx)

        assert flatpak.call_args.args[0] is ctx

    def test_steps_are_callable_against_the_real_flatpak_signature(self):
        """Bind the real `_flatpak` signature so an arity error cannot hide."""
        import inspect  # noqa: PLC0415

        m = _import_module()
        signature = inspect.signature(m._flatpak)
        recorded = []

        def fake(*args, **kwargs):
            signature.bind(*args, **kwargs)
            recorded.append(args)
            return _completed(OVERRIDE_OUTPUT)

        with patch.object(m, "_flatpak", side_effect=fake):
            m.flatpak_user_override_grants(MagicMock(), "app", "devices", "all")
            m.flatpak_portal_permission_store_is_queryable(MagicMock())

        assert len(recorded) == 2


class TestResetProbeOverrides:
    def test_resets_the_synthetic_probe_id(self):
        m = _import_module()
        ctx = MagicMock()
        with patch.object(m, "_flatpak", return_value=_completed("")) as flatpak:
            m.reset_probe_overrides(ctx)

        assert flatpak.call_args.args[0] is ctx
        assert flatpak.call_args.args[1] == [
            "override", "--user", "--reset", m.PROBE_APP_ID,
        ]

    def test_probe_id_matches_the_feature_file(self):
        import pathlib  # noqa: PLC0415

        m = _import_module()
        feature = pathlib.Path("tests/software/features/flatpak_permissions_mgmt.feature").read_text()
        assert m.PROBE_APP_ID in feature
