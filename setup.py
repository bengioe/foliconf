from ast import literal_eval
from setuptools import setup


def get_version():
    with open("VERSION", "r") as f:
        lines = f.read().splitlines()
    version_parts = {k: literal_eval(v) for k, v in map(lambda x: x.split("="), lines)}
    major = int(version_parts["MAJOR"])
    minor = int(version_parts["MINOR"])
    return f"{major}.{minor}"


setup(name="foliconf", version=get_version())
