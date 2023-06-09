import ast
import importlib.util
import json
import subprocess
import sys
from collections import defaultdict, namedtuple
from pathlib import Path
from typing import Any, Dict, List, Union

from numpydoc.docscrape import NumpyDocString


def _recursive_dd():
    return defaultdict(_recursive_dd)


def _recursive_dd_get(d, keys):
    return _recursive_dd_get(d[keys[0]], keys[1:]) if len(keys) else d


def _recursive_creative_setattr(o, keys, default, value):
    if len(keys) == 1:
        setattr(o, keys[0], value)
        return
    if not hasattr(o, keys[0]):
        setattr(o, keys[0], default())
    _recursive_creative_setattr(getattr(o, keys[0]), keys[1:], default, value)


def _recursive_getattr(o, keys):
    if len(keys) == 1:
        return getattr(o, keys[0])
    return _recursive_getattr(getattr(o, keys[0]), keys[1:])


def get_typing_imports(ann: Any) -> List[str]:
    if hasattr(ann, "__origin__"):
        origin = ann.__origin__
        if origin is Union:
            args = ann.__args__
            return (["Optional"] if type(None) in args and len(args) == 2 else ["Union"]) + sum(
                [get_typing_imports(arg) for arg in args], []
            )
        elif origin is Dict:
            args = ann.__args__
            return ["Dict"] + get_typing_imports(args[0]) + get_typing_imports(args[1])
        else:
            elements = ann.__args__
            ann_import = [origin.__name__] if origin.__module__ != "builtins" else []
            return ann_import + sum([get_typing_imports(e) for e in elements], [])
    elif ann is Any:
        return ["Any"]
    return []


def type_to_code_str(typing_instance: Any) -> str:
    if hasattr(typing_instance, "__origin__"):
        origin = typing_instance.__origin__
        if origin is Union:
            args = typing_instance.__args__
            which = "Optional" if type(None) in args and len(args) == 2 else "Union"
            str_ann = (
                f"{which}["
                + ", ".join([type_to_code_str(arg) for arg in args if which == "Union" or arg is not type(None)])
                + "]"
            )
        elif origin is Dict:
            key, value = typing_instance.__args__
            str_ann = f"Dict[{type_to_code_str(key)}, {type_to_code_str(value)}]"
        elif origin is Any:
            str_ann = "Any"
        else:
            elements = typing_instance.__args__
            str_ann = origin.__name__ + "[" + ", ".join([type_to_code_str(e) for e in elements]) + "]"
    elif typing_instance is type(None):
        str_ann = "None"
    elif hasattr(typing_instance, "_name"):
        str_ann = typing_instance._name
    else:
        str_ann = typing_instance.__name__

    return str_ann


ConfigAttr = namedtuple("ConfigAttr", ["type", "docstring"])

DISCLAIMER = """# This file was generated automatically
# Do not edit by hand, your changes will be lost
# Regenerate by running `python -m foliconf {}`
"""
STUB_BASE = """def config_class(name): ...
def config_from_dict(config_dict: dict[str, Any]) -> Config: ...
def make_config() -> Config: ...
def update_config(config: Config, config_dict: dict[str, Any]) -> Config: ...
def config_to_dict(config: Config) -> dict[str, Any]: ...
"""
CONFIG_PY_BASE = """from foliconf import config_class, config_from_dict, config_to_dict, make_config, update_config, set_Config

__all__ = [
    "Config",
    "config_class",
    "config_from_dict",
    "config_to_dict",
    "make_config",
    "update_config",
]


class Config:
    pass


set_Config(Config)
"""


class StubMaker(ast.NodeVisitor):
    def __init__(self, base_path: str, verbose: bool):
        self.config = _recursive_dd()
        self._base_path = base_path
        self._verbose = verbose

    def start_module(self, path, local_path):
        self._mod_path = path
        self._local_mod_path = Path(local_path)
        self._should_import = False

    def finalize_module(self):
        if self._should_import:
            assert self._local_mod_path.suffix == ".py" and self._local_mod_path.parts[0] == "src"
            module_name = ".".join(self._local_mod_path.parts[1:-1]) + "." + self._local_mod_path.name[: -len(".py")]
            if module_name in sys.modules:
                # We've already imported this module because some other module imported it, no need to do it again
                return
            spec = importlib.util.spec_from_file_location(module_name, self._mod_path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

    def output_stub(self):
        imports = []
        typing_imports = []
        for cname, cobj in _name_to_config.items():
            # We first extract possible docstrings for the attributes
            docstrings = defaultdict(lambda: "")
            if cobj.__doc__ is not None:
                doc = NumpyDocString(cobj.__doc__)
                for doc_attr in doc["Attributes"]:
                    docstrings[doc_attr.name] = "\n".join(doc_attr.desc)
            # We then extract the attributes themselves and infer their types from the class objects
            if cname == "@base":
                attr_dict = self.config
            else:
                attr_dict = _recursive_dd_get(self.config, cname.split("."))
            for attr_name in dir(cobj):
                if attr_name.startswith("__"):
                    continue  # ignore dunderscores
                t = type(getattr(cobj, attr_name))
                attr_dict[attr_name] = ConfigAttr(t.__name__, docstrings[attr_name])
                if t.__module__ != "builtins":
                    imports.append(f"from {t.__module__} import {t.__name__}")
            # But we allow for explicit type annotations to override the inferred types
            for attr_name, t in cobj.__annotations__.items() if hasattr(cobj, "__annotations__") else []:
                # If the type is a class, we use its name, otherwise we have to do some guessing
                if isinstance(t, type):
                    tname = iname = t.__name__
                else:
                    tstr = str(t)
                    if tstr.startswith("typing."):
                        typing_imports += get_typing_imports(t)
                        tname = type_to_code_str(t)
                        iname = None
                    else:
                        tname = iname = tstr
                attr_dict[attr_name] = ConfigAttr(tname, docstrings[attr_name])
                if t.__module__ != "builtins" and iname is not None:
                    imports.append(f"from {t.__module__} import {iname}")

        def f(name, d, indentlevel):
            s = ""
            s += "    " * indentlevel + f"class {name}:\n"
            for k, v in sorted(d.items(), key=lambda x: "_" + x[0] if not isinstance(x[1], dict) else x[0]):
                if isinstance(v, dict):
                    s += f(k, v, indentlevel + 1)
                else:
                    s += "    " * (indentlevel + 1) + f"{k}: {v.type}\n"
                    if v.docstring:
                        s += "    " * (indentlevel + 1) + f'"""{v.docstring}"""\n'
            if not len(d.items()):
                print(f"Empty config class {name}?")
                s += "    " * (indentlevel + 1) + "...\n"
            return s

        s = DISCLAIMER.format(self._base_path)
        s += f"from typing import {', '.join(sorted(set(typing_imports)))}\n"
        s += "\n".join(sorted(set(imports))) + "\n\n"
        s += f("Config", self.config, 0)
        s += STUB_BASE
        self.stub_path = Path(self._base_path).parent / "config.pyi"
        with open(self.stub_path, "w") as f:
            f.write(s)
        with open(self._base_path, "w") as f:
            f.write(DISCLAIMER.format(self._base_path) + CONFIG_PY_BASE)

    def visit_ClassDef(self, node):
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Name)
                and dec.func.id == "config_class"
                and len(dec.args) == 1
                and isinstance(dec.args[0], ast.Constant)
            ):
                if self._verbose:
                    print("Found config class", dec.args[0].value)
                self._should_import = True
        self.generic_visit(node)


_Config_cls: type = None


def set_Config(cls):
    global _Config_cls
    _Config_cls = cls


def make_config():
    config = _name_to_config.get("@base", _Config_cls)()
    for cname, cobj in sorted(_name_to_config.items()):
        if cname == "@base":
            continue
        _recursive_creative_setattr(config, cname.split("."), _Config_cls, cobj())
    return config


def update_config(config, config_dict):
    for cname, val in config_dict.items():
        _recursive_creative_setattr(config, cname.split("."), _Config_cls, val)


def config_from_dict(config_dict) -> _Config_cls:
    config = make_config()
    update_config(config, config_dict)
    check_config(config)
    return config


def check_config(config):
    for cname, cobj in _name_to_config.items():
        if cname == "@base":
            continue
        subcfg = _recursive_getattr(config, cname.split("."))
        for name, t in cobj.__annotations__.items() if hasattr(cobj, "__annotations__") else []:
            if not hasattr(subcfg, name):
                print(f"Warning, setting {cname}.{name} was declared but not defined in created config")


def config_to_dict(config):
    d = {}
    config_classes = tuple(_name_to_config.values()) + (_Config_cls,)
    for cname, _ in _name_to_config.items():
        if cname == "@base":
            csplit = []
            subcfg = config
        else:
            csplit = cname.split(".")
            subcfg = _recursive_getattr(config, csplit)
        for i in dir(subcfg):
            if i.startswith("__"):
                continue
            o = getattr(subcfg, i)
            if isinstance(o, config_classes):
                continue
            d[".".join(csplit + [i])] = o
    return d


def config_class(name):
    assert isinstance(name, str), "config_class decorator must be called with a section name"

    def decorator(c):
        if name in _name_to_config:
            raise ValueError("Redefining", name, "is not allowed; found", c, "and", _name_to_config[name])
        _name_to_config[name] = c
        return c

    return decorator


_name_to_config: dict[str, Any] = {}
if 0:
    if __name__ != "__main__" and hasattr(sys.modules["__main__"], "__main__sentinel"):
        # If we reach this point, config is being imported as a module by another part of the package, while we are running
        # the __main__ script below. In this case, we don't want to overwrite the global _name_to_config, so we just use
        # the existing one.
        _name_to_config = sys.modules["__main__"]._name_to_config
    else:
        _name_to_config = {}
