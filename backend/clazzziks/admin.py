"""``clazzziks-db`` — a tiny CLI to manage the Postgres store from the shell.

Mainly for bootstrapping/managing the VIP group without going through the admin
dashboard (e.g. on a fresh server, or to promote the first admin):

    clazzziks-db init                         # create the tables (+ owner seed)
    clazzziks-db vip ls                       # list the VIP group
    clazzziks-db vip add you@example.com      # add a VIP (unlimited)
    clazzziks-db vip add boss@x.com --admin --note "owner"
    clazzziks-db vip add pal@x.com --rate-limit 50   # capped VIP
    clazzziks-db vip limit pal@x.com 100      # change a VIP's cap
    clazzziks-db vip limit pal@x.com unlimited
    clazzziks-db vip rm you@example.com       # remove a VIP

Honours ``CLAZZZIKS_DATABASE_URL`` like the rest of the app.
"""

from __future__ import annotations

import argparse

from . import db


def _cmd_init(_args: argparse.Namespace) -> int:
    db.init_db()
    print(f"Initialised {db.database_url()}")
    return 0


def _fmt_limit(value: int | None) -> str:
    return "unlimited" if value is None else f"{value}/window"


def _parse_limit(raw: str) -> int | None:
    if raw.strip().lower() in ("unlimited", "inf", "infinite", "none", "0"):
        return None
    limit = int(raw)
    if limit <= 0:
        raise ValueError("rate limit must be a positive integer or 'unlimited'")
    return limit


def _cmd_vip_ls(_args: argparse.Namespace) -> int:
    vips = db.list_vips()
    if not vips:
        print("(no VIPs)")
        return 0
    for v in vips:
        flag = " [admin]" if v.is_admin else ""
        note = f"  — {v.note}" if v.note else ""
        print(f"{v.email}{flag}  limit={_fmt_limit(v.rate_limit)}  (added {v.added_at}){note}")
    return 0


def _cmd_vip_add(args: argparse.Namespace) -> int:
    limit = _parse_limit(args.rate_limit) if args.rate_limit is not None else None
    db.add_vip(args.email, note=args.note, is_admin=args.admin, rate_limit=limit)
    role = "admin" if args.admin else "VIP"
    print(f"Added {args.email} as {role} (limit {_fmt_limit(limit)}).")
    return 0


def _cmd_vip_limit(args: argparse.Namespace) -> int:
    limit = _parse_limit(args.rate_limit)
    if not db.update_vip(args.email, rate_limit=limit):
        print(f"{args.email} is not a VIP.")
        return 1
    print(f"Set {args.email} rate limit to {_fmt_limit(limit)}.")
    return 0


def _cmd_vip_rm(args: argparse.Namespace) -> int:
    if db.remove_vip(args.email):
        print(f"Removed {args.email}.")
        return 0
    print(f"{args.email} is not a VIP.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clazzziks-db", description="Manage the CLAZZZIKS Postgres store."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create the database tables (and owner seed).").set_defaults(
        func=_cmd_init
    )

    vip = sub.add_parser("vip", help="Manage the VIP group.")
    vip_sub = vip.add_subparsers(dest="vip_command", required=True)

    vip_sub.add_parser("ls", help="List VIPs.").set_defaults(func=_cmd_vip_ls)

    add = vip_sub.add_parser("add", help="Add or update a VIP.")
    add.add_argument("email")
    add.add_argument("--admin", action="store_true", help="Grant admin rights.")
    add.add_argument("--note", default=None, help="Optional note.")
    add.add_argument(
        "--rate-limit", default=None,
        help="Per-VIP cap (integer) or 'unlimited' (default).",
    )
    add.set_defaults(func=_cmd_vip_add)

    limit = vip_sub.add_parser("limit", help="Set a VIP's rate limit.")
    limit.add_argument("email")
    limit.add_argument("rate_limit", help="Integer cap or 'unlimited'.")
    limit.set_defaults(func=_cmd_vip_limit)

    rm = vip_sub.add_parser("rm", help="Remove a VIP.")
    rm.add_argument("email")
    rm.set_defaults(func=_cmd_vip_rm)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
