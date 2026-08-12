from setuptools import setup

from tools.smf_build import BdistWheel, BuildExt, BuildPy, native_extension


setup(
    cmdclass={"build_ext": BuildExt, "build_py": BuildPy, "bdist_wheel": BdistWheel},
    ext_modules=[native_extension()],
)
