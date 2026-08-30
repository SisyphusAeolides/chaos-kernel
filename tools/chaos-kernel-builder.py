#!/usr/bin/env python3
"""Build a kernel in a disposable tree with the Chaos Kernel patches.

The builder deliberately separates portability checks, patch application, and
kernel compilation. It never modifies the supplied source tree, installs a
kernel, unloads a driver, or reboots the host.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time


FEATURE_CONFIGS = {
    "core": ("SCHED_CORE=y",),
    "tcp-roessler": ("TCP_CONG_ROESSLER=m",),
    "block-duffing": (),
}
CONFIG_ASSIGNMENT = re.compile(r"^(CONFIG_[A-Z0-9_]+)=(.*)$")
CONFIG_DISABLED = re.compile(r"^# (CONFIG_[A-Z0-9_]+) is not set$")


class BuilderError(RuntimeError):
    """An expected, user-actionable builder failure."""


def kernel_status(_args: argparse.Namespace | None = None) -> int:
    """Print a manager-friendly view of installed and selected kernels."""

    current = os.uname().release
    default = "unknown"
    grubby = shutil.which("grubby")
    if grubby:
        commands = [[grubby, "--default-kernel"]]
        sudo = shutil.which("sudo")
        if sudo:
            commands.insert(0, [sudo, "-n", grubby, "--default-kernel"])
        for command in commands:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            candidate = result.stdout.strip()
            if result.returncode == 0 and candidate.startswith("/boot/vmlinuz-"):
                default = candidate
                break
    images = sorted(Path("/boot").glob("vmlinuz-*"))
    print(f"Current kernel: {current}")
    print(f"Default kernel: {default}")
    print("Installed kernels:")
    if not images:
        print("  (no /boot/vmlinuz-* images found)")
    for image in images:
        marks = []
        if image.name == f"vmlinuz-{current}":
            marks.append("current")
        if str(image) == default:
            marks.append("default")
        suffix = f" [{', '.join(marks)}]" if marks else ""
        print(f"  {image}{suffix}")
    return 0


def privileged_command(command: list[str], use_pkexec: bool) -> list[str]:
    tool = "pkexec" if use_pkexec else "sudo"
    if not shutil.which(tool):
        raise BuilderError(f"{tool} is required for this manager action")
    return [tool, *command]


def install_artifacts(args: argparse.Namespace) -> int:
    artifact_dir = Path(args.artifacts).expanduser().resolve()
    if not artifact_dir.is_dir():
        raise BuilderError(f"artifact directory does not exist: {artifact_dir}")
    pattern = "*.rpm" if args.format == "rpm" else "*.deb"
    artifacts = sorted(item for item in artifact_dir.glob(pattern) if item.is_file())
    if not artifacts:
        raise BuilderError(f"no {args.format} artifacts found in {artifact_dir}")
    if args.format == "rpm":
        command = ["dnf", "install", "-y", *[str(item) for item in artifacts]]
    else:
        command = ["dpkg", "--install", *[str(item) for item in artifacts]]
    run_command(privileged_command(command, args.pkexec))
    print("Installed kernel artifacts. Reboot only after reviewing the new entry in the manager.")
    return 0


def set_default_kernel(args: argparse.Namespace) -> int:
    kernel = Path(args.kernel).expanduser().resolve()
    boot = Path("/boot").resolve()
    if not is_within(kernel, boot) or not kernel.name.startswith("vmlinuz-"):
        raise BuilderError("--kernel must name a vmlinuz-* image below /boot")
    run_command(privileged_command(["grubby", "--set-default", str(kernel)], args.pkexec))
    return 0


def say(message: str) -> None:
    print(message, flush=True)


def command_text(command: list[str]) -> str:
    return shlex.join(command)


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> list[str]:
    """Run an argv command and stream its output without a shell."""

    say(f"$ {command_text(command)}")
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        output.append(line)
        print(line, end="", flush=True)
    status = process.wait()
    if check and status != 0:
        raise BuilderError(f"command failed with exit status {status}: {command_text(command)}")
    return output


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def parse_features(value: str) -> list[str]:
    if not value or value.lower() in {"none", "off"}:
        return []
    features = [item.strip().lower() for item in value.split(",") if item.strip()]
    unknown = sorted(set(features) - set(FEATURE_CONFIGS))
    if unknown:
        raise BuilderError(
            "unknown feature(s): " + ", ".join(unknown) +
            "; choose core, tcp-roessler, block-duffing, or none"
        )
    return list(dict.fromkeys(features))


def validate_extra_config(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value.startswith("CONFIG_"):
            value = value[len("CONFIG_"):]
        if not re.fullmatch(r"[A-Z0-9_]+=(?:y|m|n|[0-9]+|\"[^\"\n]*\")", value):
            raise BuilderError(
                f"invalid --extra-config value {value!r}; use SYMBOL=y|m|n|NUMBER|\"STRING\""
            )
        result.append(value)
    return result


class KernelBuilder:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.source = Path(args.source).expanduser().resolve() if args.source else None
        self.output = Path(args.output).expanduser().resolve()
        self.patch_root = (
            Path(args.patch_root).expanduser().resolve()
            if args.patch_root
            else Path(__file__).resolve().parent.parent / "packaging" / "copr"
        )
        self.features = parse_features(args.features)
        self.extra_config = validate_extra_config(args.extra_config)
        self.worktree: Path | None = None
        self.artifacts: Path | None = None
        self.parent_artifacts_before: set[Path] = set()
        self.started = time.monotonic()

    def validate(self) -> None:
        if bool(self.source) == bool(self.args.clone_url):
            raise BuilderError("provide exactly one of --source or --clone-url")
        if self.source:
            if not self.source.is_dir():
                raise BuilderError(f"kernel source directory does not exist: {self.source}")
            if not (self.source / "Makefile").is_file():
                raise BuilderError(f"not a Linux source tree (missing Makefile): {self.source}")
            if is_within(self.output, self.source):
                raise BuilderError("--output must not be inside the supplied source tree")
        if not self.patch_root.is_dir():
            raise BuilderError(f"patch directory does not exist: {self.patch_root}")
        runner = self.patch_root / "apply-chaos-patches.sh"
        if not runner.is_file() or not os.access(runner, os.X_OK):
            raise BuilderError(f"patch runner is missing or not executable: {runner}")
        if not isinstance(self.args.jobs, int) or self.args.jobs < 1:
            raise BuilderError("--jobs must be a positive integer")

    def choose_output(self) -> None:
        """Avoid deleting or overwriting an earlier build run."""

        if not self.output.exists():
            self.output.mkdir(parents=True)
            return
        if not any(self.output.iterdir()):
            return
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = self.output.parent / f"{self.output.name}-{stamp}"
        suffix = 1
        while candidate.exists():
            candidate = self.output.parent / f"{self.output.name}-{stamp}-{suffix}"
            suffix += 1
        self.output = candidate
        self.output.mkdir(parents=True)
        say(f"Existing output preserved; using {self.output}")

    def prepare_tree(self) -> None:
        self.choose_output()
        self.worktree = self.output / "kernel"
        self.artifacts = self.output / "artifacts"
        assert self.worktree is not None
        assert self.artifacts is not None
        self.parent_artifacts_before = {
            item.resolve()
            for pattern in ("*.rpm", "*.deb")
            for item in self.output.parent.glob(pattern)
            if item.is_file()
        }

        if self.args.clone_url:
            command = ["git", "clone", "--filter=blob:none"]
            command.extend([self.args.clone_url, str(self.worktree)])
            run_command(command)
            if self.args.ref:
                run_command(["git", "checkout", "--quiet", "--detach", self.args.ref], cwd=self.worktree)
        elif self.source and (self.source / ".git").exists():
            status = subprocess.run(
                ["git", "-C", str(self.source), "status", "--porcelain"],
                check=False,
                capture_output=True,
                text=True,
            )
            if status.returncode != 0:
                raise BuilderError(f"could not inspect Git source tree: {self.source}")
            if status.stdout.strip():
                raise BuilderError("the supplied Git source tree is dirty; commit or copy it first")
            run_command(["git", "clone", "--local", "--no-hardlinks", str(self.source), str(self.worktree)])
        else:
            assert self.source is not None
            say(f"Copying non-Git kernel source into {self.worktree}")
            shutil.copytree(self.source, self.worktree, symlinks=True)
            run_command(["git", "init", "--quiet"], cwd=self.worktree)
            run_command(["git", "add", "--all"], cwd=self.worktree)
            run_command(
                [
                    "git",
                    "-c",
                    "user.name=Kernel Builder",
                    "-c",
                    "user.email=builder@localhost",
                    "commit",
                    "--quiet",
                    "-m",
                    "base kernel source",
                ],
                cwd=self.worktree,
            )
        self.artifacts.mkdir(parents=True)
        say(f"Build tree: {self.worktree}")

    def apply_patches(self, apply: bool) -> list[str]:
        assert self.worktree is not None
        runner = self.patch_root / "apply-chaos-patches.sh"
        command = [str(runner), "--apply" if apply else "--check", f"--{self.args.policy}", str(self.worktree)]
        output = run_command(command)
        result = [line.strip() for line in output if re.match(r"^(PASS|APPLY|SKIP|FAIL) ", line)]
        return result

    def set_config_line(self, config: Path, assignment: str) -> None:
        symbol, value = assignment.split("=", 1)
        lines = config.read_text(encoding="utf-8").splitlines()
        replaced = False
        new_lines: list[str] = []
        for line in lines:
            match = CONFIG_ASSIGNMENT.match(line) or CONFIG_DISABLED.match(line)
            if match and match.group(1) == f"CONFIG_{symbol}":
                new_lines.append(f"CONFIG_{symbol}={value}")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.append(f"CONFIG_{symbol}={value}")
        config.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def configure(self) -> None:
        assert self.worktree is not None
        config = self.worktree / ".config"
        if self.args.config:
            supplied = Path(self.args.config).expanduser().resolve()
            if not supplied.is_file():
                raise BuilderError(f"config file does not exist: {supplied}")
            shutil.copy2(supplied, config)
        else:
            run_command(["make", "defconfig"], cwd=self.worktree)

        assignments: list[str] = []
        for feature in self.features:
            assignments.extend(FEATURE_CONFIGS[feature])
            if feature == "block-duffing":
                say("block-duffing is runtime opt-in; use blk_mq.chaos_bypass_shift after boot")
        assignments.extend(self.extra_config)
        for assignment in assignments:
            self.set_config_line(config, assignment)
        if assignments:
            say("Applying requested kernel configuration: " + ", ".join(assignments))
        if self.args.config_ui != "none":
            run_command(["make", self.args.config_ui], cwd=self.worktree)
            for assignment in assignments:
                self.set_config_line(config, assignment)
        run_command(["make", "olddefconfig"], cwd=self.worktree)

    def compile(self) -> None:
        assert self.worktree is not None
        run_command(["make", "-j", str(self.args.jobs), "bzImage", "modules"], cwd=self.worktree)
        if self.args.package == "rpm":
            run_command(["make", "-j", str(self.args.jobs), "rpm-pkg"], cwd=self.worktree)
        elif self.args.package == "deb":
            run_command(["make", "-j", str(self.args.jobs), "bindeb-pkg"], cwd=self.worktree)

    def collect(self, patch_result: list[str]) -> None:
        assert self.worktree is not None
        assert self.artifacts is not None
        copied: list[str] = []
        candidates = [self.worktree / ".config"]
        for image in ("bzImage", "Image", "vmlinuz"):
            candidates.append(self.worktree / "arch" / "x86" / "boot" / image)
            candidates.append(self.worktree / "arch" / "arm64" / "boot" / image)
        for candidate in candidates:
            if candidate.is_file():
                destination = self.artifacts / candidate.name
                shutil.copy2(candidate, destination)
                copied.append(str(destination))
        package_candidates = list(self.worktree.rglob("*.rpm")) + list(self.worktree.rglob("*.deb"))
        package_candidates.extend(self.output.parent.glob("*.rpm"))
        package_candidates.extend(self.output.parent.glob("*.deb"))
        for candidate in package_candidates:
            resolved = candidate.resolve()
            if not candidate.is_file() or resolved in self.parent_artifacts_before:
                continue
            destination = self.artifacts / candidate.name
            if not destination.exists():
                shutil.copy2(candidate, destination)
                copied.append(str(destination))
        manifest = {
            "source": str(self.source) if self.source else self.args.clone_url,
            "ref": self.args.ref,
            "policy": self.args.policy,
            "features": self.features,
            "extra_config": self.extra_config,
            "package": self.args.package,
            "jobs": self.args.jobs,
            "patch_result": patch_result,
            "artifacts": copied,
            "worktree": str(self.worktree),
            "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        (self.output / "build.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        say(f"Build manifest: {self.output / 'build.json'}")
        if copied:
            say("Artifacts:")
            for item in copied:
                say(f"  {item}")

    def run(self, command: str) -> int:
        self.validate()
        self.prepare_tree()
        patch_result = self.apply_patches(command == "build")
        if command == "check":
            self.collect(patch_result)
            say("Portability check completed; no kernel source was modified outside the disposable tree.")
            return 0
        self.configure()
        self.compile()
        self.collect(patch_result)
        say(f"Kernel build completed in {time.monotonic() - self.started:.1f}s")
        return 0


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source", help="local Linux kernel source tree")
    source.add_argument("--clone-url", help="Git URL for a Linux kernel source tree")
    parser.add_argument("--ref", help="branch, tag, or commit for --clone-url")
    parser.add_argument(
        "--output",
        default="~/Projects/chaos-kernel-build",
        help="output directory; an existing run is preserved and a new directory is selected",
    )
    parser.add_argument("--patch-root", help="directory containing apply-chaos-patches.sh")
    parser.add_argument("--policy", choices=("strict", "best-effort"), default="strict")
    parser.add_argument("--config", help="optional kernel .config to seed the build")
    parser.add_argument("--features", default="core,tcp-roessler")
    parser.add_argument("--extra-config", action="append", default=[])
    parser.add_argument(
        "--config-ui",
        choices=("none", "menuconfig", "nconfig", "xconfig", "gconfig"),
        default="none",
        help="optional kernel configuration editor before the final olddefconfig",
    )
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)


def run_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="list installed, current, and default kernels")
    status.set_defaults(action=kernel_status)

    install = subparsers.add_parser("install", help="install built kernel artifacts without rebooting")
    install.add_argument("--artifacts", required=True, help="directory containing the built packages")
    install.add_argument("--format", choices=("rpm", "deb"), default="rpm")
    install.add_argument("--pkexec", action="store_true", help="use the graphical polkit prompt")
    install.set_defaults(action=install_artifacts)

    set_default = subparsers.add_parser("set-default", help="select an installed /boot/vmlinuz image")
    set_default.add_argument("--kernel", required=True, help="absolute path to a /boot/vmlinuz-* image")
    set_default.add_argument("--pkexec", action="store_true", help="use the graphical polkit prompt")
    set_default.set_defaults(action=set_default_kernel)

    check = subparsers.add_parser("check", help="check patch portability in a disposable tree")
    add_common_arguments(check)
    check.set_defaults(package="none")

    build = subparsers.add_parser("build", help="apply patches and compile a disposable kernel tree")
    add_common_arguments(build)
    build.add_argument("--package", choices=("none", "rpm", "deb"), default="none")

    args = parser.parse_args(argv)
    try:
        if hasattr(args, "action"):
            return args.action(args)
        return KernelBuilder(args).run(args.command)
    except (BuilderError, OSError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def launch_gui() -> int:
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk
    except (ImportError, ValueError) as error:
        print(f"error: GTK3/PyGObject is required for the GUI: {error}", file=sys.stderr)
        return 1

    class BuilderWindow(Gtk.Window):
        def __init__(self) -> None:
            super().__init__(title="Chaos Kernel Manager — Chaos Kernel")
            self.set_default_size(900, 650)
            self.running = False
            grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
            self.add(grid)

            heading = Gtk.Label(
                label="Chaos Kernel Manager\nCheck, configure, build, and install a compatible kernel",
                xalign=0,
            )
            heading.set_halign(Gtk.Align.FILL)
            grid.attach(heading, 0, 0, 4, 1)

            self.source = Gtk.Entry()
            self.source.set_placeholder_text("/path/to/linux or leave empty when using clone URL")
            self.clone_url = Gtk.Entry()
            self.clone_url.set_placeholder_text("https://git.kernel.org/... (optional)")
            self.ref = Gtk.Entry()
            self.ref.set_placeholder_text("tag/branch/commit (optional)")
            self.output = Gtk.Entry(text="~/Projects/chaos-kernel-build")
            self.config = Gtk.Entry()
            self.config.set_placeholder_text("optional .config")
            self.preset = Gtk.ComboBoxText()
            for item in ("performance", "balanced", "safe", "custom"):
                self.preset.append_text(item)
            self.preset.set_active(0)
            self.preset.connect("changed", self.preset_changed)
            self.features = Gtk.Entry(text="core,tcp-roessler")
            self.jobs = Gtk.Entry(text=str(os.cpu_count() or 1))
            self.policy = Gtk.ComboBoxText()
            self.policy.append_text("strict")
            self.policy.append_text("best-effort")
            self.policy.set_active(0)
            self.package = Gtk.ComboBoxText()
            for item in ("none", "rpm", "deb"):
                self.package.append_text(item)
            self.package.set_active(0)
            self.config_ui = Gtk.ComboBoxText()
            for item in ("none", "menuconfig", "nconfig", "xconfig", "gconfig"):
                self.config_ui.append_text(item)
            self.config_ui.set_active(0)
            self.kernel_choice = Gtk.ComboBoxText()
            self.refresh_kernel_choices()

            fields = (
                ("Local source", self.source),
                ("Clone URL", self.clone_url),
                ("Ref", self.ref),
                ("Output", self.output),
                ("Seed config", self.config),
                ("Preset", self.preset),
                ("Features", self.features),
                ("Jobs", self.jobs),
                ("Patch policy", self.policy),
                ("Package", self.package),
                ("Config editor", self.config_ui),
                ("Boot entry", self.kernel_choice),
            )
            for offset, (label, widget) in enumerate(fields, start=1):
                grid.attach(Gtk.Label(label=label, xalign=0), 0, offset, 1, 1)
                grid.attach(widget, 1, offset, 3, 1)

            self.status_button = Gtk.Button(label="Installed kernels")
            self.default_button = Gtk.Button(label="Set selected default")
            self.check_button = Gtk.Button(label="Check portability")
            self.build_button = Gtk.Button(label="Build kernel")
            self.install_button = Gtk.Button(label="Install built kernel")
            self.status_button.connect("clicked", self.start, "status")
            self.default_button.connect("clicked", self.start, "set-default")
            self.check_button.connect("clicked", self.start, "check")
            self.build_button.connect("clicked", self.start, "build")
            self.install_button.connect("clicked", self.start, "install")
            button_row = len(fields) + 1
            grid.attach(self.status_button, 0, button_row, 1, 1)
            grid.attach(self.default_button, 1, button_row, 1, 1)
            grid.attach(self.check_button, 2, button_row, 1, 1)
            grid.attach(self.build_button, 3, button_row, 1, 1)
            grid.attach(self.install_button, 4, button_row, 1, 1)

            self.buffer = Gtk.TextBuffer()
            view = Gtk.TextView(buffer=self.buffer, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.NONE)
            scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
            scroll.add(view)
            grid.attach(scroll, 0, button_row + 1, 5, 1)

        def refresh_kernel_choices(self) -> None:
            self.kernel_choice.remove_all()
            for image in sorted(Path("/boot").glob("vmlinuz-*")):
                self.kernel_choice.append(str(image), str(image))
            if self.kernel_choice.get_active() < 0:
                self.kernel_choice.set_active(0)

        def start(self, _button: Gtk.Button, action: str) -> None:
            if self.running:
                return
            command = [sys.executable, str(Path(__file__).resolve()), action]
            if action == "status":
                self.refresh_kernel_choices()
            elif action == "set-default":
                selected = self.kernel_choice.get_active_id()
                if not selected:
                    self.append("No /boot/vmlinuz-* entry is available.\n")
                    return
                command.extend(["--kernel", selected, "--pkexec"])
            elif action == "install":
                package = self.package.get_active_text() or "rpm"
                if package == "none":
                    package = "rpm"
                command.extend([
                    "--artifacts",
                    str(Path(self.output.get_text().strip()).expanduser() / "artifacts"),
                    "--format",
                    package,
                    "--pkexec",
                ])
            else:
                source = self.source.get_text().strip()
                clone_url = self.clone_url.get_text().strip()
                if bool(source) == bool(clone_url):
                    self.append("Provide exactly one local source or clone URL.\n")
                    return
                command.extend(["--source", source] if source else ["--clone-url", clone_url])
                for flag, value in (("--ref", self.ref.get_text().strip()), ("--output", self.output.get_text().strip()),
                                    ("--config", self.config.get_text().strip()), ("--features", self.features.get_text().strip()),
                                    ("--config-ui", self.config_ui.get_active_text() or "none"),
                                    ("--jobs", self.jobs.get_text().strip())):
                    if value:
                        command.extend([flag, value])
                command.extend(["--policy", self.policy.get_active_text() or "strict"])
                if action == "build":
                    command.extend(["--package", self.package.get_active_text() or "none"])
            self.running = True
            self.check_button.set_sensitive(False)
            self.build_button.set_sensitive(False)
            self.status_button.set_sensitive(False)
            self.default_button.set_sensitive(False)
            self.install_button.set_sensitive(False)
            self.append(f"$ {command_text(command)}\n")

            def worker() -> None:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                assert process.stdout is not None
                for line in process.stdout:
                    GLib.idle_add(self.append, line)
                status = process.wait()
                GLib.idle_add(self.finished, status)

            import threading

            threading.Thread(target=worker, daemon=True).start()

        def preset_changed(self, combo: Gtk.ComboBoxText) -> None:
            presets = {
                "performance": "core,tcp-roessler",
                "balanced": "core",
                "safe": "none",
            }
            value = combo.get_active_text() or "custom"
            if value in presets:
                self.features.set_text(presets[value])

        def append(self, text: str) -> bool:
            end = self.buffer.get_end_iter()
            self.buffer.insert(end, text)
            return False

        def finished(self, status: int) -> bool:
            self.append(f"\nFinished with status {status}.\n")
            self.running = False
            self.check_button.set_sensitive(True)
            self.build_button.set_sensitive(True)
            self.status_button.set_sensitive(True)
            self.default_button.set_sensitive(True)
            self.install_button.set_sensitive(True)
            return False

    window = BuilderWindow()
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    if "--gui" in sys.argv[1:]:
        sys.argv.remove("--gui")
        raise SystemExit(launch_gui())
    raise SystemExit(run_cli(sys.argv[1:]))
