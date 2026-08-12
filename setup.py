from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from setuptools import setup


def _load_build_module():
    module_path = Path(__file__).resolve().parent / "tools" / "smf_build.py"
    spec = spec_from_file_location("_pysmf_build", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load build helper module from {module_path}")
    module = module_from_spec(spec)
    # Dataclasses in Python 3.14 expect the module to be present in sys.modules
    # while class decorators execute.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build = _load_build_module()

setup(
    cmdclass={
        "build_ext": build.BuildExt,
        "build_py": build.BuildPy,
        "bdist_wheel": build.BdistWheel,
    },
    ext_modules=[build.native_extension()],
)
