"""Parse shared role YAML and reject duplicate keys and misplaced module arguments."""
from pathlib import Path
import yaml


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"Duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def check():
    root = Path(__file__).resolve().parents[1]
    paths = sorted((root / "roles").glob("*/tasks/*.yml")) + sorted((root / "roles").glob("*/defaults/*.yml"))
    for path in paths:
        data = yaml.load(path.read_text(), Loader=UniqueLoader)
        if "tasks" not in path.parts:
            continue
        def walk(tasks):
            for task in tasks:
                for key, value in task.items():
                    if key in {"block", "rescue", "always"}:
                        walk(value)
                    elif "." in key and isinstance(value, dict):
                        misplaced = {"tags", "no_log", "when", "register", "become"} & value.keys()
                        if misplaced:
                            raise ValueError(f"{path}: task keywords inside module {key}: {sorted(misplaced)}")
        walk(data)
    print(f"Validated {len(paths)} role YAML files")


if __name__ == "__main__":
    check()
