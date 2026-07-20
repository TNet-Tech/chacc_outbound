import sys
import os
import subprocess


def run_tests():
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(os.path.dirname(tests_dir), "..", ".venv", "bin", "python")
    python = str(venv_python if os.path.exists(venv_python) else sys.executable)
    result = subprocess.run(
        [python, "-m", "pytest", "tests", "-v", "--tb=short"],
        cwd=tests_dir,
        env={**os.environ, "PYTHONPATH": tests_dir},
    )
    if result.returncode == 0:
        print("All tests passed")
        sys.exit(0)
    else:
        print("Tests failed")
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
