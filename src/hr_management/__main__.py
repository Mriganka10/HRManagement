"""Command line:

    python -m hr_management [serve] [--host 127.0.0.1] [--port 8000] [--reload]
    python -m hr_management create-hr --email hr@kairoz.com --name "HR Admin" [--role hr_admin|hr]
    python -m hr_management seed-demo          # demo employees, attendance, payslips (not in production)
    python -m hr_management init-db            # create/upgrade tables and reference data, then exit
"""
from __future__ import annotations

import argparse
import logging
import os


def main() -> None:
    parser = argparse.ArgumentParser(prog="hr_management", description="Kairoz HR Management")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="Run the web server (default).")
    for target in (parser, serve):
        target.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
        target.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
        target.add_argument("--reload", action="store_true", help="Auto-restart on code changes (development).")
    hr = sub.add_parser("create-hr", help="Create an HR user and print the temporary password.")
    hr.add_argument("--email", required=True)
    hr.add_argument("--name", required=True)
    hr.add_argument("--role", choices=["hr_admin", "hr"], default="hr_admin")
    sub.add_parser("seed-demo", help="Load demo data for local trials.")
    sub.add_parser("init-db", help="Create/upgrade tables and reference data.")
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("HRM_LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command in {"create-hr", "seed-demo", "init-db"}:
        from . import db
        from .services.demo import seed_reference_data

        db.init_db()
        seed_reference_data()
        if args.command == "create-hr":
            from .services.accounts import create_account

            account, password = create_account(email=args.email, full_name=args.name, role=args.role)
            print(f"\nCreated {args.role} {account['user_id']} ({account['email']})\nTemporary password: {password}\n"
                  "The password must be changed at first sign-in.\n")
        elif args.command == "seed-demo":
            from .services.demo import seed_demo

            result = seed_demo()
            print(f"\nDemo data ready.\n  HR admin : {result['hr']['user_id']} / {result['hr']['password']}")
            for emp in result["employees"]:
                print(f"  Employee : {emp['user_id']} / {emp['password']}  ({emp['name']})")
            print("  (existing demo users keep their passwords; demo employees use Welcome2026)\n")
        else:
            print("Database ready.")
        return

    import uvicorn

    print(f"\n  Kairoz HR Management running →  http://{args.host}:{args.port}\n")
    uvicorn.run("hr_management.web:create_app", factory=True, host=args.host, port=args.port, reload=args.reload,
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
