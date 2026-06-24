import logging
import os
import sys
import threading
import time
from contextlib import contextmanager

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.theme import Theme

BONFIRE_THEME = Theme(
    {
        "info": "cyan",
        "warning": "bold yellow",
        "error": "bold red",
        "success": "bold green",
        "header": "bold blue",
        "muted": "dim",
    }
)

_interactive = None
_console = None


def _is_interactive():
    global _interactive
    if _interactive is None:
        if os.environ.get("NO_COLOR"):
            _interactive = False
        elif os.environ.get("BONFIRE_PLAIN_OUTPUT", "").lower() in ("1", "true"):
            _interactive = False
        else:
            _interactive = sys.stdout.isatty() and sys.stderr.isatty()
    return _interactive


def get_console():
    global _console
    if _console is None:
        _console = Console(stderr=True, theme=BONFIRE_THEME, highlight=False)
    return _console


def configure_logging(debug=False):
    level = logging.DEBUG if debug else logging.INFO
    logging.getLogger("sh").setLevel(logging.CRITICAL)

    if _is_interactive():
        handler = RichHandler(
            console=get_console(),
            show_time=True,
            show_path=False,
            rich_tracebacks=True,
            tracebacks_show_locals=debug,
            markup=False,
            log_time_format="%H:%M:%S",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.basicConfig(level=level, handlers=[handler])
    else:
        logging.basicConfig(
            format="%(asctime)s [%(levelname)8s] [%(threadName)20s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            level=level,
        )


def echo_error(msg):
    console = get_console()
    if _is_interactive():
        console.print(f"\n[error]ERROR:[/error] {msg}")
    else:
        console.print(f"\nERROR: {msg}")


def echo_success(msg):
    console = get_console()
    if _is_interactive():
        console.print(f"[success]{msg}[/success]")
    else:
        console.print(msg)


def echo_warning(msg):
    console = get_console()
    if _is_interactive():
        console.print(f"\n[warning]WARNING:[/warning] {msg}")
    else:
        console.print(f"\nWARNING: {msg}")


def _fmt_countdown(remaining):
    m, s = divmod(int(remaining), 60)
    if m > 0:
        return f"{m}m{s:02d}s"
    return f"{s}s"


@contextmanager
def status_spinner(message, timeout=None):
    console = get_console()
    if _is_interactive():
        with console.status(f"[info]{message}[/info]", spinner="dots") as status:
            if timeout is not None and timeout > 0:
                stop_event = threading.Event()
                start = time.monotonic()

                def _tick():
                    while not stop_event.wait(1):
                        elapsed = time.monotonic() - start
                        remaining = max(0, timeout - elapsed)
                        status.update(
                            f"[info]{message}[/info]  [muted]({_fmt_countdown(remaining)} remaining)[/muted]"
                        )

                ticker = threading.Thread(target=_tick, daemon=True)
                ticker.start()
                try:
                    yield status
                finally:
                    stop_event.set()
                    ticker.join(timeout=2)
            else:
                yield status
    else:
        console.print(message)
        yield None


def _style_status(value):
    v = str(value).lower()
    if v == "ready":
        return f"[success]{v}[/success]"
    if v in ("failed", "error"):
        return f"[error]{v}[/error]"
    return f"[warning]{v}[/warning]"


def _style_reserved(value):
    v = str(value).lower()
    if v == "true":
        return f"[warning]{v}[/warning]"
    return f"[muted]{v}[/muted]"


def _style_expires(value):
    v = str(value)
    if v.lower() == "expired":
        return f"[error]{v}[/error]"
    if not v or v == "N/A":
        return f"[muted]{v}[/muted]"
    return f"[info]{v}[/info]"


def render_ns_table(namespaces):
    from tabulate import tabulate as tabulate_plain

    console = get_console()

    if _is_interactive():
        table = Table(
            title="[header]Ephemeral Namespaces[/header]",
            show_header=True,
            header_style="header",
            border_style="dim",
            title_style="",
            pad_edge=True,
        )
        table.add_column("Name", style="bold cyan", no_wrap=True)
        table.add_column("Reserved")
        table.add_column("Env Status")
        table.add_column("ClowdApps\n(ready/total)")
        table.add_column("Clusters\n(ready/total)")
        table.add_column("Requester", style="info")
        table.add_column("Pool Type")
        table.add_column("Expires In")

        for ns in namespaces:
            table.add_row(
                ns.name,
                _style_reserved(ns.reserved),
                _style_status(ns.status),
                str(ns.clowdapps),
                str(ns.clusters),
                ns.requester,
                ns.pool_type,
                _style_expires(ns.expires_in),
            )
        console.print(table)
    else:
        data = {
            "NAME": [ns.name for ns in namespaces],
            "RESERVED": [str(ns.reserved).lower() for ns in namespaces],
            "ENV STATUS": [str(ns.status).lower() for ns in namespaces],
            "CLOWDAPPS\n(ready/total)": [ns.clowdapps for ns in namespaces],
            "CLUSTERS\n(ready/total)": [ns.clusters for ns in namespaces],
            "REQUESTER": [ns.requester for ns in namespaces],
            "POOL TYPE": [ns.pool_type for ns in namespaces],
            "EXPIRES IN": [ns.expires_in for ns in namespaces],
        }
        click_echo(tabulate_plain(data, headers="keys"))


def render_describe(info, project_name):

    if not _is_interactive():
        return _render_describe_plain(info, project_name)
    return _render_describe_rich(info, project_name)


def _render_describe_plain(info, project_name):
    from tabulate import tabulate as tabulate_plain

    rows = [("Namespace", project_name)]
    if info.get("console_namespace_route"):
        rows.append(("Project URL", info["console_namespace_route"]))
    if info.get("gateway_route"):
        rows.append(("Gateway route", info["gateway_route"]))
    if info.get("clowdapps_deployed"):
        rows.append(("ClowdApps deployed", info["clowdapps_deployed"]))
    if info.get("frontends_deployed"):
        rows.append(("Frontends deployed", info["frontends_deployed"]))

    cred_rows = _get_cred_rows(info)
    lines = [tabulate_plain(rows, tablefmt="simple")]

    if cred_rows:
        lines.append("\nCredentials:")
        for name, route, user, pw in cred_rows:
            cred_info = [
                (f"{name} username", user),
                (f"{name} password", pw),
            ]
            if route:
                cred_info.append((f"{name} route", route))
            lines.append(tabulate_plain(cred_info, tablefmt="simple"))
            lines.append("")

    if info.get("has_cluster"):
        lines.append(_rosa_instructions_plain(project_name))

    return "\n" + "\n".join(lines) + "\n"


def _render_describe_rich(info, project_name):
    from rich.panel import Panel

    console = get_console()
    console.print()

    info_table = Table(show_header=False, box=None, padding=(0, 2))
    info_table.add_column("Key", style="header")
    info_table.add_column("Value")

    info_table.add_row("Namespace", f"[bold cyan]{project_name}[/bold cyan]")
    if info.get("console_namespace_route"):
        info_table.add_row("Project URL", f"[info]{info['console_namespace_route']}[/info]")
    if info.get("gateway_route"):
        info_table.add_row("Gateway route", f"[info]{info['gateway_route']}[/info]")
    if info.get("clowdapps_deployed"):
        info_table.add_row("ClowdApps deployed", str(info["clowdapps_deployed"]))
    if info.get("frontends_deployed"):
        info_table.add_row("Frontends deployed", str(info["frontends_deployed"]))

    console.print(Panel(info_table, title="[header]Namespace Info[/header]", border_style="dim"))

    cred_rows = _get_cred_rows(info)
    if cred_rows:
        cred_table = Table(show_header=True, header_style="header", border_style="dim")
        cred_table.add_column("Service")
        cred_table.add_column("Username")
        cred_table.add_column("Password")
        cred_table.add_column("Route")
        for name, route, user, pw in cred_rows:
            cred_table.add_row(
                name, f"[info]{user}[/info]", f"[warning]{pw}[/warning]", route or ""
            )
        console.print(Panel(cred_table, title="[header]Credentials[/header]", border_style="dim"))

    if info.get("has_cluster"):
        from rich.syntax import Syntax

        ns = project_name
        code = (
            f"oc get secret {ns}-cluster-kubeconfig \\\n"
            f"  -n {ns} \\\n"
            f"  -o jsonpath='{{.data.value}}' | base64 -d > /tmp/{ns}-kubeconfig\n"
            f"KUBECONFIG=/tmp/{ns}-kubeconfig oc whoami"
        )
        console.print(
            Panel(
                Syntax(code, "bash", theme="monokai"),
                title="[header]ROSA Cluster Access[/header]",
                border_style="dim",
            )
        )
    console.print()
    return None


def _get_cred_rows(info):
    def _has_cred(user, pw):
        return user not in ("", "N/A") or pw not in ("", "N/A")

    cred_rows = []
    if _has_cred(info["keycloak_admin_username"], info["keycloak_admin_password"]):
        cred_rows.append(
            (
                "Keycloak admin",
                info["keycloak_admin_route"],
                info["keycloak_admin_username"],
                info["keycloak_admin_password"],
            )
        )
    if _has_cred(info["default_username"], info["default_password"]):
        cred_rows.append(("Default user", "", info["default_username"], info["default_password"]))
    return cred_rows


def _rosa_instructions_plain(ns):
    return (
        "ROSA Cluster configuration detected! To access it, run:\n"
        "\n"
        f"  oc get secret {ns}-cluster-kubeconfig \\\n"
        f"    -n {ns} \\\n"
        f"    -o jsonpath='{{.data.value}}' | base64 -d > /tmp/{ns}-kubeconfig\n"
        f"  KUBECONFIG=/tmp/{ns}-kubeconfig oc whoami"
    )


def render_apps_list(apps, list_components):
    console = get_console()
    sorted_keys = sorted(apps.keys())

    if _is_interactive():
        from rich.tree import Tree

        tree = Tree("[header]Applications[/header]")
        for app_name in sorted_keys:
            app_config = apps[app_name]
            branch = tree.add(f"[bold cyan]{app_name}[/bold cyan]")
            if list_components:
                component_names = sorted([c["name"] for c in app_config["components"]])
                for component_name in component_names:
                    branch.add(f"[muted]{component_name}[/muted]")
        console.print(tree)
    else:
        click_echo("")
        for app_name in sorted_keys:
            app_config = apps[app_name]
            click_echo(app_name)
            if list_components:
                component_names = sorted([c["name"] for c in app_config["components"]])
                for component_name in component_names:
                    click_echo(f" `-- {component_name}")


def render_pool_list(pools):
    console = get_console()
    if _is_interactive():
        for p in pools:
            console.print(f"  [bold cyan]{p}[/bold cyan]")
    else:
        click_echo("\n".join(pools))


def render_aliases(aliases):
    console = get_console()

    if _is_interactive():
        table = Table(
            title="[header]CLI Aliases[/header]",
            show_header=True,
            header_style="header",
            border_style="dim",
            title_style="",
        )
        table.add_column("Alias", style="bold cyan")
        table.add_column("Expands To")
        table.add_column("Args", style="muted")

        for name, alias_cfg in sorted(aliases.items()):
            app_names = " ".join(alias_cfg.get("app_names", [name]))
            args = alias_cfg.get("args", {})
            args_str = " ".join(f"--{k.replace('_', '-')}={v}" for k, v in args.items())
            table.add_row(name, app_names, args_str)
        console.print(table)
    else:
        for name, alias_cfg in sorted(aliases.items()):
            app_names = " ".join(alias_cfg.get("app_names", [name]))
            args = alias_cfg.get("args", {})
            args_str = " ".join(f"--{k.replace('_', '-')}={v}" for k, v in args.items())
            click_echo(f"  {name} => {app_names} {args_str}".rstrip())


def render_version(version):
    console = get_console()
    if _is_interactive():
        console.print(f"[bold cyan]bonfire[/bold cyan] version [success]{version}[/success]")
    else:
        click_echo(f"{version}")


def click_echo(msg="", **kwargs):
    import click

    click.echo(msg, **kwargs)


_SKIPPED_TREE_RESTYPES = frozenset(("pod", "replicaset", "replicationcontroller"))


def _resource_status_summary(resource):
    conditions = resource.data.get("status", {}).get("conditions", [])
    for c in conditions:
        if c.get("status") != "True":
            reason = c.get("reason") or c.get("message") or c.get("type")
            if reason:
                return reason
    if conditions:
        types_true = [c.get("type") for c in conditions if c.get("status") == "True"]
        if types_true:
            return ", ".join(types_true)
    return ""


def _resource_label_text(resource):
    name_part = f"[dim]{resource.restype}/[/dim]"
    if resource.ready:
        return f"[bold green]✓[/bold green] {name_part}[bold cyan]{resource.name}[/bold cyan]"
    status = _resource_status_summary(resource)
    status_part = f"  [dim italic]{status}[/dim italic]" if status else ""
    return f"[bold yellow]⠶[/bold yellow] {name_part}[bold yellow]{resource.name}[/bold yellow]{status_part}"


def _build_hierarchy(resources_snapshot):
    filtered = {
        k: r for k, r in resources_snapshot.items() if r.restype not in _SKIPPED_TREE_RESTYPES
    }

    # only show ClowdEnvironments referenced by a ClowdApp in this namespace
    relevant_envs = {
        r.data.get("spec", {}).get("envName")
        for r in filtered.values()
        if r.restype == "clowdapp"
    }
    relevant_envs.discard(None)
    if relevant_envs:
        filtered = {
            k: r
            for k, r in filtered.items()
            if r.restype != "clowdenvironment" or r.name in relevant_envs
        }

    uid_to_resource = {}
    for r in filtered.values():
        try:
            uid_to_resource[r.uid] = r
        except (KeyError, AttributeError):
            pass

    children = {}
    roots = []
    for r in filtered.values():
        owner_refs = r.data.get("metadata", {}).get("ownerReferences", [])
        parent_found = False
        for ref in owner_refs:
            parent_uid = ref.get("uid")
            if parent_uid in uid_to_resource:
                children.setdefault(parent_uid, []).append(r)
                parent_found = True
                break
        if not parent_found:
            roots.append(r)

    roots.sort(key=lambda r: (r.restype, r.name))
    for kids in children.values():
        kids.sort(key=lambda r: (r.restype, r.name))

    total = len(filtered)
    ready = sum(1 for r in filtered.values() if r.ready)
    return roots, children, total, ready


def _make_tree_app_class():
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container
    from textual.widgets import Label, ProgressBar, Tree

    class ResourceWaitApp(App):

        CSS = """
        Tree {
            height: 1fr;
        }
        #footer-bar {
            dock: bottom;
            height: 3;
            padding: 0 1;
        }
        #progress {
            width: 100%;
        }
        #status-label {
            width: 100%;
            color: $accent;
        }
        """

        ENABLE_COMMAND_PALETTE = False

        BINDINGS = [
            Binding("q,ctrl+q", "leave_tree", "Leave tree view", show=True),
            Binding("ctrl+c", "leave_tree", "Leave tree view", show=False, priority=True),
        ]

        def __init__(self, watcher, timeout, start_time, done_event):
            super().__init__()
            self._watcher = watcher
            self._timeout = timeout
            self._start_time = start_time
            self._done_event = done_event
            self._prev_keys = set()
            self._prev_ready = {}
            self._node_map = {}
            self._spinner_frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            self._spinner_idx = 0

        def compose(self) -> ComposeResult:
            yield Tree("Namespace Resources")
            with Container(id="footer-bar"):
                yield ProgressBar(id="progress", total=100, show_eta=False)
                yield Label("", id="status-label")

        def on_mount(self) -> None:
            tree = self.query_one(Tree)
            tree.show_root = True
            tree.root.expand()
            self._refresh_tree()
            self.set_interval(5, self._refresh_tree)
            self.set_interval(1, self._refresh_status)

        def _refresh_status(self) -> None:
            if self._done_event.is_set():
                self.exit()
                return
            resources_snapshot = self._watcher.resources.copy()
            filtered = {
                k: r for k, r in resources_snapshot.items() if r.restype not in _SKIPPED_TREE_RESTYPES
            }
            total = len(filtered)
            ready = sum(1 for r in filtered.values() if r.ready)
            self._update_status_label(total, ready)

        def _refresh_tree(self) -> None:
            resources_snapshot = self._watcher.resources.copy()
            if not resources_snapshot:
                return

            roots, children_map, total, ready = _build_hierarchy(resources_snapshot)
            tree = self.query_one(Tree)

            current_keys = set()
            current_ready = {}
            for r in resources_snapshot.values():
                if r.restype not in _SKIPPED_TREE_RESTYPES:
                    current_keys.add(r.key)
                    current_ready[r.key] = r.ready

            added = current_keys - self._prev_keys
            removed = self._prev_keys - current_keys
            changed_ready = {
                k for k in current_keys & self._prev_keys if current_ready[k] != self._prev_ready.get(k)
            }

            if added or removed:
                tree.clear()
                self._node_map.clear()
                tree.root.expand()

                def _add_nodes(parent_node, resource):
                    label = _resource_label_text(resource)
                    node = parent_node.add(label, data=resource.key, expand=True)
                    self._node_map[resource.key] = node
                    for child in children_map.get(resource.uid, []):
                        _add_nodes(node, child)

                for root in roots:
                    _add_nodes(tree.root, root)
            elif changed_ready:
                filtered = {
                    k: r
                    for k, r in resources_snapshot.items()
                    if r.restype not in _SKIPPED_TREE_RESTYPES
                }
                for key in changed_ready:
                    node = self._node_map.get(key)
                    r = filtered.get(key)
                    if node and r:
                        node.set_label(_resource_label_text(r))

            self._prev_keys = current_keys
            self._prev_ready = current_ready

            bar = self.query_one("#progress", ProgressBar)
            bar.update(total=max(total, 1), progress=ready)

            self._update_status_label(total, ready)

        def _update_status_label(self, total, ready) -> None:
            pct = (ready / total * 100) if total > 0 else 0
            elapsed = time.monotonic() - self._start_time
            remaining = max(0, self._timeout - elapsed) if self._timeout else None
            countdown = (
                f" — {_fmt_countdown(remaining)} until timeout, press ctrl+q to leave tree view"
                if remaining is not None
                else ""
            )
            spinner = self._spinner_frames[self._spinner_idx % len(self._spinner_frames)]
            self._spinner_idx += 1
            label = self.query_one("#status-label", Label)
            label.update(f" {spinner} {ready}/{total} ready ({pct:.0f}%){countdown}")

        def action_leave_tree(self) -> None:
            self.exit()

    return ResourceWaitApp


def resource_wait_display(watcher, timeout, wait_fn):
    console = get_console()

    if not _is_interactive():
        console.print("Waiting for resources to be ready...")
        wait_fn()
        return

    done_event = threading.Event()
    wait_error = [None]
    start_time = time.monotonic()

    def _run_wait():
        try:
            wait_fn()
        except Exception as exc:
            wait_error[0] = exc
        finally:
            done_event.set()

    wait_thread = threading.Thread(target=_run_wait, daemon=True)
    wait_thread.start()

    in_tree_view = True
    ResourceWaitApp = _make_tree_app_class()

    while not done_event.is_set():
        if in_tree_view:
            app = ResourceWaitApp(watcher, timeout, start_time, done_event)
            app.run()
            in_tree_view = False
            if done_event.is_set():
                break
        else:
            import select

            remaining = max(0, timeout - (time.monotonic() - start_time)) if timeout else None
            countdown = f"  [muted]({_fmt_countdown(remaining)} until timeout)[/muted]" if remaining is not None else ""
            msg = f"[info]Waiting for resources...[/info]{countdown}  [muted](press ctrl+t to open tree view, ctrl+c to cancel)[/muted]"
            with console.status(msg, spinner="dots") as status:
                while not done_event.is_set():
                    # check for ctrl+t keypress via stdin
                    if sys.stdin.isatty():
                        import termios
                        import tty

                        fd = sys.stdin.fileno()
                        old_settings = termios.tcgetattr(fd)
                        try:
                            tty.setcbreak(fd)
                            rlist, _, _ = select.select([sys.stdin], [], [], 1.0)
                            if rlist:
                                ch = sys.stdin.read(1)
                                if ch == "\x14":  # ctrl+t
                                    in_tree_view = True
                                    break
                                elif ch == "\x03":  # ctrl+c
                                    done_event.set()
                                    wait_error[0] = KeyboardInterrupt()
                                    break
                        finally:
                            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    else:
                        done_event.wait(1)

                    remaining = max(0, timeout - (time.monotonic() - start_time)) if timeout else None
                    countdown = f"  [muted]({_fmt_countdown(remaining)} until timeout)[/muted]" if remaining is not None else ""
                    msg = f"[info]Waiting for resources...[/info]{countdown}  [muted](press ctrl+t to open tree view, ctrl+c to cancel)[/muted]"
                    status.update(msg)

    wait_thread.join(timeout=5)

    if wait_error[0] is not None:
        raise wait_error[0]
