from foliconf import *
import argparse

parser = argparse.ArgumentParser(description="Your script description")
parser.add_argument("config_path", type=str, help="Path to the configuration file (e.g. src/<package>/config.py)")
parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
parser.add_argument("--show_default", "-s", action="store_true", help="Show the default config")

args = parser.parse_args()


class BuildConfig:
    pass


set_Config(BuildConfig)
repo = subprocess.check_output("git rev-parse --show-toplevel", shell=True).decode().strip()  # nosec
print("Working in repo", repo)
files = (
    subprocess.check_output('git ls-files | grep -e ".py$"', shell=True, cwd=repo)  # nosec
    .decode()
    .strip()
    .splitlines()
)

stub_maker = StubMaker(args.config_path, args.verbose)
for f in files:
    if not f.startswith("src/"):  # Only package files in src/
        continue
    path = Path(repo) / f
    if args.verbose:
        print("Processing", f)
    root = ast.parse(open(path, "r").read())
    stub_maker.start_module(path, f)
    stub_maker.visit(root)
    stub_maker.finalize_module()
stub_maker.output_stub()
subprocess.check_output(f"black {stub_maker.stub_path}", shell=True)  # nosec
if args.show_default:
    print("Default config:")
    d = config_to_dict(make_config())
    print(json.dumps(d, indent=2, sort_keys=True))
