#!/usr/bin/env bash
# Apply the Chaos Kernel series against a selected Linux source tree.
#
# The series is intentionally fail-closed. Kernel internal APIs are not
# stable, so a patch that does not match the selected tree must never be
# forced with fuzz or rejected hunks.

set -u

usage()
{
	cat <<'EOF'
Usage: apply-chaos-patches.sh [--apply|--check] [--best-effort|--strict] KERNEL_TREE

Modes:
  --check         Report applicability without changing KERNEL_TREE (default).
  --apply         Apply compatible patches to KERNEL_TREE.
  --strict        Stop and fail when any required patch does not apply (default).
  --best-effort   Skip incompatible patches and their dependents.
  --series NAME   Select patch series: auto (default), clk6.12, or legacy.

The tree must be a clean, disposable kernel source tree when --apply is used.
EOF
}

mode=check
policy=strict
series=auto
kernel_tree=
patch_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

while [ "$#" -gt 0 ]; do
	case "$1" in
		--apply)
			mode=apply
			;;
		--check)
			mode=check
			;;
		--best-effort)
			policy=best-effort
			;;
		--strict)
			policy=strict
			;;
		--series)
			shift
			[ "$#" -gt 0 ] || { usage >&2; exit 2; }
			case "$1" in
				auto|clk6.12|legacy)
					series=$1
					;;
				*)
					printf 'error: unknown patch series: %s\n' "$1" >&2
					usage >&2
					exit 2
					;;
			esac
			;;
		--patch-dir)
			shift
			[ "$#" -gt 0 ] || { usage >&2; exit 2; }
			patch_dir=$1
			;;
		-h|--help)
			usage
			exit 0
			;;
		-*)
			printf 'error: unknown option: %s\n' "$1" >&2
			usage >&2
			exit 2
			;;
		*)
			if [ -n "$kernel_tree" ]; then
				printf 'error: more than one kernel tree was supplied\n' >&2
				usage >&2
				exit 2
			fi
			kernel_tree=$1
			;;
	esac
	shift
done

if [ -z "$kernel_tree" ] || [ ! -d "$kernel_tree" ]; then
	printf 'error: KERNEL_TREE must be an existing directory\n' >&2
	usage >&2
	exit 2
fi

if [ ! -f "$kernel_tree/Makefile" ] || [ ! -d "$kernel_tree/include/linux" ]; then
	printf 'error: not a Linux source tree: %s\n' "$kernel_tree" >&2
	exit 2
fi

if [ ! -d "$patch_dir" ]; then
	printf 'error: patch directory does not exist: %s\n' "$patch_dir" >&2
	exit 2
fi
patch_dir=$(CDPATH= cd -- "$patch_dir" && pwd)

if ! command -v git >/dev/null 2>&1; then
	printf 'error: git is required to check and apply the patch format\n' >&2
	exit 2
fi

if [ "$series" = auto ]; then
	kernel_version=$(sed -n -e 's/^VERSION[[:space:]]*=[[:space:]]*//p' \
		-e 's/^PATCHLEVEL[[:space:]]*=[[:space:]]*//p' "$kernel_tree/Makefile" |
		tr '\n' '.' | sed 's/\.$//')
	if [ "$kernel_version" = 6.12 ]; then
		series=clk6.12
	else
		series=legacy
	fi
fi

declare -a patches
declare -A dependencies
if [ "$series" = clk6.12 ]; then
	# The CLK 6.12 source layout needs a reviewed port for the hooks whose
	# upstream anchors moved. The port follows the common math/OOM/TCP base.
	patches=(
		0001-lib-add-bounded-fixed-point-chaos-math.patch
		0003-mm-detect-nonlinear-free-page-divergence-at-OOM.patch
		0006-tcp-add-bounded-Roessler-congestion-control.patch
		0011-clk6.12-default-roessler.patch
		0007-lib-add-Lorenz-Mandelbrot-and-Lyapunov-dynamics.patch
		0010-clk6.12-enable-full-chaos-feature-set.patch
	)
	dependencies=(
		[0001-lib-add-bounded-fixed-point-chaos-math.patch]=''
		[0003-mm-detect-nonlinear-free-page-divergence-at-OOM.patch]='0001-lib-add-bounded-fixed-point-chaos-math.patch'
		[0006-tcp-add-bounded-Roessler-congestion-control.patch]='0001-lib-add-bounded-fixed-point-chaos-math.patch'
		[0011-clk6.12-default-roessler.patch]='0006-tcp-add-bounded-Roessler-congestion-control.patch'
		[0007-lib-add-Lorenz-Mandelbrot-and-Lyapunov-dynamics.patch]='0001-lib-add-bounded-fixed-point-chaos-math.patch'
		[0010-clk6.12-enable-full-chaos-feature-set.patch]='0001-lib-add-bounded-fixed-point-chaos-math.patch 0003-mm-detect-nonlinear-free-page-divergence-at-OOM.patch 0006-tcp-add-bounded-Roessler-congestion-control.patch 0011-clk6.12-default-roessler.patch 0007-lib-add-Lorenz-Mandelbrot-and-Lyapunov-dynamics.patch'
	)
else
	patches=(
		0001-lib-add-bounded-fixed-point-chaos-math.patch
		0002-random-add-stateless-nonlinear-entropy-conditioning.patch
		0003-mm-detect-nonlinear-free-page-divergence-at-OOM.patch
		0004-sched-fair-add-bounded-CORE-wakeup-placement.patch
		0005-block-add-optional-Duffing-plug-bypass.patch
		0006-tcp-add-bounded-Roessler-congestion-control.patch
		0007-lib-add-Lorenz-Mandelbrot-and-Lyapunov-dynamics.patch
		0008-sched-mm-wire-Lorenz-Mandelbrot-and-Lyapunov-dynamics.patch
		0009-cgroup-dmem-preserve-legacy-registration-api.patch
	)
	dependencies=(
		[0001-lib-add-bounded-fixed-point-chaos-math.patch]=''
		[0002-random-add-stateless-nonlinear-entropy-conditioning.patch]='0001-lib-add-bounded-fixed-point-chaos-math.patch'
		[0003-mm-detect-nonlinear-free-page-divergence-at-OOM.patch]='0001-lib-add-bounded-fixed-point-chaos-math.patch'
		[0004-sched-fair-add-bounded-CORE-wakeup-placement.patch]='0001-lib-add-bounded-fixed-point-chaos-math.patch'
		[0005-block-add-optional-Duffing-plug-bypass.patch]='0001-lib-add-bounded-fixed-point-chaos-math.patch'
		[0006-tcp-add-bounded-Roessler-congestion-control.patch]='0001-lib-add-bounded-fixed-point-chaos-math.patch'
		[0007-lib-add-Lorenz-Mandelbrot-and-Lyapunov-dynamics.patch]='0001-lib-add-bounded-fixed-point-chaos-math.patch'
		[0008-sched-mm-wire-Lorenz-Mandelbrot-and-Lyapunov-dynamics.patch]='0003-mm-detect-nonlinear-free-page-divergence-at-OOM.patch 0004-sched-fair-add-bounded-CORE-wakeup-placement.patch 0007-lib-add-Lorenz-Mandelbrot-and-Lyapunov-dynamics.patch'
		[0009-cgroup-dmem-preserve-legacy-registration-api.patch]=''
	)
fi

declare -A state
failed=0

for patch_name in "${patches[@]}"; do
	patch_path=$patch_dir/$patch_name
	if [ ! -f "$patch_path" ]; then
		printf 'FAIL %s: patch file is missing\n' "$patch_name" >&2
		failed=1
		state[$patch_name]=failed
		if [ "$policy" = strict ]; then
			exit 1
		fi
		continue
	fi

	blocked=
	for dependency in ${dependencies[$patch_name]}; do
		if [ "${state[$dependency]:-}" != applied ] &&
		   [ "${state[$dependency]:-}" != check-pass ]; then
			blocked=$dependency
			break
		fi
	done
	if [ -n "$blocked" ]; then
		printf 'SKIP %s: prerequisite %s was not applied\n' "$patch_name" "$blocked"
		state[$patch_name]=skipped
		failed=1
		if [ "$policy" = strict ]; then
			exit 1
		fi
		continue
	fi

	check_output=$(git -C "$kernel_tree" apply --check --whitespace=nowarn "$patch_path" 2>&1)
	check_status=$?
	if [ "$check_status" -ne 0 ]; then
		printf 'SKIP %s: does not match this kernel tree\n' "$patch_name"
		printf '%s\n' "$check_output" | sed -n '1,8p' >&2
		state[$patch_name]=failed
		failed=1
		if [ "$policy" = strict ]; then
			exit 1
		fi
		continue
	fi

	if [ "$mode" = apply ]; then
		if ! git -C "$kernel_tree" apply --whitespace=nowarn "$patch_path"; then
			printf 'FAIL %s: check passed but application failed\n' "$patch_name" >&2
			state[$patch_name]=failed
			failed=1
			if [ "$policy" = strict ]; then
				exit 1
			fi
			continue
		fi
		printf 'APPLY %s\n' "$patch_name"
		state[$patch_name]=applied
	else
		printf 'PASS %s\n' "$patch_name"
		state[$patch_name]=check-pass
	fi
done

if [ "$failed" -ne 0 ]; then
	if [ "$policy" = best-effort ]; then
		printf 'completed in best-effort mode; unsupported patches were skipped\n' >&2
		exit 0
	fi
	exit 1
fi

printf 'all Chaos Kernel patches are compatible with this tree\n'
