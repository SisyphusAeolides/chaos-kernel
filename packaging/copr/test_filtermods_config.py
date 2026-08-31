#!/usr/bin/env python3
"""Regression tests for the module-package rule loader."""

import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MAPS = (
    ROOT / "def_variants.yaml.fedora",
    ROOT / "def_variants.yaml.rhel",
    ROOT / "clk612" / "def_variants.yaml.rocky",
)


def load_filtermods(path):
    spec = importlib.util.spec_from_file_location("filtermods_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rule_metadata_is_not_a_package_name(module):
    fedora = module.load_config(str(MAPS[0]), None)
    assert any(rule[3] for rule in fedora.rules)
    assert all(len(rule) == 4 for rule in fedora.rules)
    assert all(isinstance(rule[3], bool) for rule in fedora.rules)


def test_ignore_deps_severs_only_the_exact_module(module):
    config = """\
packages:
  - name: modules
  - name: modules-internal
    depends-on: [modules]
  - name: modules-partner
    depends-on: [modules]
rules:
  - .*kunit.*: modules-internal
    exact_pkg: true
    ignore_deps: true
  - real: modules-partner
  - default: modules
"""
    depmod = """\
kernel/test_kunit.ko: kernel/real.ko
kernel/real.ko: kernel/base.ko
kernel/base.ko:
"""
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        config_path = directory / "rules.yaml"
        depmod_path = directory / "modules.dep"
        config_path.write_text(config)
        depmod_path.write_text(depmod)
        packages, kmods = module.sort_kmods(str(depmod_path), str(config_path))

    test_kmod = kmods.get("test_kunit.ko")
    assert test_kmod.allowed_list == {packages.get("modules-internal")}
    assert not test_kmod.depends_on
    assert not test_kmod.is_dependency_for


def main():
    for implementation in (ROOT / "filtermods.py", ROOT / "clk612" / "filtermods.py"):
        module = load_filtermods(implementation)
        for rule_map in MAPS:
            loaded = module.load_config(str(rule_map), None)
            assert loaded.rules, rule_map
            assert all(len(rule) == 4 for rule in loaded.rules), rule_map
        test_rule_metadata_is_not_a_package_name(module)
        test_ignore_deps_severs_only_the_exact_module(module)
        print(f"{implementation.relative_to(ROOT)}: PASS")


if __name__ == "__main__":
    main()
