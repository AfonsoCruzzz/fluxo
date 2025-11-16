#!/usr/bin/env python3
"""
Registrar automaticamente os usuários necessários no Prosody para executar main.py.

Este script usa `prosodyctl register <user> <host> <password>` para cada conta.
Execute-o em uma máquina que tenha o Prosody instalado e privilégios suficientes
para executar o prosodyctl (normalmente requer sudo).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Iterable, Tuple

DEFAULT_PASSWORD = "senha"
REQUIRED_ACCOUNTS = (
    ("traffic_controller", "localhost", DEFAULT_PASSWORD),
    ("monitor", "localhost", DEFAULT_PASSWORD),
    ("vehicle", "localhost", DEFAULT_PASSWORD),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Registrar usuários obrigatórios no Prosody para o projeto."
    )
    parser.add_argument(
        "--prosodyctl",
        default=os.environ.get("PROSODYCTL", "prosodyctl"),
        help="Caminho para o binário prosodyctl (padrão: %(default)s).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas exibe os comandos que seriam executados, sem chamá-los.",
    )
    parser.add_argument(
        "--password",
        help="Senha única a ser usada para todas as contas (padrão: 'senha').",
    )
    return parser.parse_args()


def build_commands(
    prosodyctl: str, accounts: Iterable[Tuple[str, str, str]], override_password: str | None
):
    for user, host, password in accounts:
        yield [
            prosodyctl,
            "register",
            user,
            host,
            override_password if override_password is not None else password,
        ]


def main() -> int:
    args = parse_args()
    commands = list(build_commands(args.prosodyctl, REQUIRED_ACCOUNTS, args.password))

    if args.dry_run:
        for cmd in commands:
            print("DRY-RUN:", " ".join(cmd))
        return 0

    for cmd in commands:
        print("Executando:", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)
        except FileNotFoundError:
            print(f"❌ prosodyctl não encontrado: {cmd[0]}")
            return 1
        except subprocess.CalledProcessError as exc:
            print(f"❌ Falha ao registrar {cmd[2]}@{cmd[3]} (código {exc.returncode})")
            return exc.returncode

    print("✅ Usuários registrados com sucesso!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
