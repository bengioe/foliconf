# foliconf
Minimal Python configuration library that produces pyi stubs for git repositories.

## Installation

`git clone` and `pip install -e .`.


## Usage

You may first want to seed your project with a `config.py` module, within anywhere in the repository:
```bash
python -m foliconf src/my_package/config.py
```

In a module you'd like to configure add:

```python
from my_package.config import config_class

@config_class("pizza.toppings")
class ToppingsConfig:
    mushrooms: bool = True
    pepper_slices: int = 7
```

You can now update the `pyi` stubs by rerunning `python -m foliconf src/my_package/config.py`.

To create the configuration object:
```python
from my_package.config import make_config, Config, config_from_dict

# Create the default config:
def make_my_config() -> Config:
    cfg = make_config()
    return cfg

# Create a custom config:
def make_my_config_custom(overrides: dict[str, Any]) -> Config:
    cfg = config_from_dict(overrides)
    return cfg
```

The `cfg` object can now be used as e.g. `cfg.pizza.toppings.pepper_slices`. `mypy` and other tools will correctly 
evaluate this expression to be an integer.