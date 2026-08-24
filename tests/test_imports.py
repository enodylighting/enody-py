import subprocess
import sys
import textwrap


def test_base_import_does_not_load_science_dependencies():
    code = textwrap.dedent(
        """
        import importlib.abc
        import sys

        blocked = {"colour", "matplotlib", "tinygrad"}

        class ScienceBlocker(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.partition(".")[0] in blocked:
                    raise AssertionError(f"imported optional module: {fullname}")
                return None

        sys.meta_path.insert(0, ScienceBlocker())

        import enody

        loaded = sorted(
            name
            for name in blocked
            if any(
                module == name or module.startswith(name + ".")
                for module in sys.modules
            )
        )
        if loaded:
            raise AssertionError(f"optional modules loaded by import enody: {loaded}")
        """
    )

    subprocess.run([sys.executable, "-c", code], check=True)
