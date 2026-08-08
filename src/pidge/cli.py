"""Command-line entrypoint."""

from __future__ import annotations

import argparse

from pidge.web import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="pidge")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="Run the Pidge web server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--no-debug", action="store_true")
    subparsers.add_parser("check", help="Validate routes, templates, and configuration")
    subparsers.add_parser("migrate", help="Apply database migrations")
    args = parser.parse_args()

    if args.command == "migrate":
        app = create_app(debug=False)
        print("migrations applied")
        return
    if args.command == "serve":
        app = create_app(debug=not args.no_debug)
        app.run(host=args.host, port=args.port)
        return
    result = create_app(debug=False).check(warnings_as_errors=True)
    if result is not None:
        print(result)


if __name__ == "__main__":
    main()
