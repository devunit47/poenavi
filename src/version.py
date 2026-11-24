APP_VERSION = "4.5.6"
IS_FORK = True
FORK_LABEL = "Fork"


def with_fork_label(title: str) -> str:
    return f"{title} ({FORK_LABEL})" if IS_FORK else title
