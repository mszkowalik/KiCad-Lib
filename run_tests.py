#!/usr/bin/env python3
"""
Test Runner for KiCad Library Component Validation

Provides different test execution modes and formats for CI/CD integration.
"""

import sys
import argparse
import subprocess
import json
from component_validator import ComponentValidator


def run_pytest_tests(verbose=False, html_report=False):
    """Run pytest-based tests."""
    cmd = [sys.executable, "-m", "pytest", "tests/test_components.py"]

    if verbose:
        cmd.extend(["-v", "-s"])

    if html_report:
        cmd.extend(["--html=test_results.html", "--self-contained-html"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0, result.stdout, result.stderr
    except FileNotFoundError:
        return False, "", "pytest not installed"


def run_standalone_validation():
    """Run standalone validation."""
    try:
        validator = ComponentValidator()
        success = validator.run_all_validations()
        return success, validator.stats, validator.errors, validator.warnings
    except Exception as e:
        return False, {}, [f"Validation failed: {e}"], []


def export_results_json(stats, errors, warnings, filename="validation_results.json"):
    """Export validation results to JSON."""
    results = {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "statistics": stats,
        "validation": {"passed": len(errors) == 0, "error_count": len(errors), "warning_count": len(warnings)},
        "errors": [{"message": error.message, "component": error.component_name, "library": error.library_name, "file": error.source_file} for error in errors],
        "warnings": [{"message": warning.message, "component": warning.component_name, "library": warning.library_name, "file": warning.source_file} for warning in warnings],
    }

    with open(filename, "w") as f:
        json.dump(results, f, indent=2)

    return filename


def main():
    parser = argparse.ArgumentParser(description="Run KiCad Library Component Tests")
    parser.add_argument("--mode", choices=["pytest", "standalone", "both"], default="standalone", help="Test execution mode")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--html", action="store_true", help="Generate HTML report (pytest only)")
    parser.add_argument("--json", action="store_true", help="Export results to JSON")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")
    parser.add_argument("--ci", action="store_true", help="CI mode (JSON output, exit codes)")

    args = parser.parse_args()

    if args.ci:
        args.json = True
        args.quiet = True

    success_overall = True

    if not args.quiet:
        print("KiCad Library Component Test Runner")
        print("=" * 50)

    # Run standalone validation
    if args.mode in ["standalone", "both"]:
        if not args.quiet:
            print("\\nRunning standalone validation...")

        success, stats, errors, warnings = run_standalone_validation()
        success_overall = success_overall and success

        if args.json:
            json_file = export_results_json(stats, errors, warnings)
            if not args.quiet:
                print(f"Results exported to {json_file}")

        if not args.quiet:
            if success:
                print("✅ Standalone validation passed")
            else:
                print(f"❌ Standalone validation failed ({len(errors)} errors)")

    # Run pytest tests
    if args.mode in ["pytest", "both"]:
        if not args.quiet:
            print("\\nRunning pytest tests...")

        try:
            success, stdout, stderr = run_pytest_tests(args.verbose, args.html)
            success_overall = success_overall and success

            if not args.quiet:
                if success:
                    print("✅ Pytest tests passed")
                else:
                    print("❌ Pytest tests failed")

                if args.verbose and stdout:
                    print("\\nTest Output:")
                    print(stdout)

                if stderr:
                    print("\\nErrors:")
                    print(stderr)

        except Exception as e:
            success_overall = False
            if not args.quiet:
                print(f"❌ Failed to run pytest: {e}")

    if args.ci:
        # CI mode - just return exit code
        return 0 if success_overall else 1

    if not args.quiet:
        print("\\n" + "=" * 50)
        if success_overall:
            print("🎉 All tests passed!")
        else:
            print("💥 Some tests failed!")
        print("=" * 50)

    return 0 if success_overall else 1


if __name__ == "__main__":
    sys.exit(main())
