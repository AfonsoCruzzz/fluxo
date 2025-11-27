#!/usr/bin/env python3
"""
Registrar automaticamente os usuários necessários no Prosody para executar main.py.

Este script cria:
  - Um usuário por cabeça de semáforo (signal head/linkIndex) do arquivo .net.xml (tl_<id>_l<linkIndex>@<domínio>)
  - Um usuário por veículo definido no arquivo .rou.xml (veh_<id>@<domínio>)

Ele usa `prosodyctl register <user> <host> <password>` para cada conta.
Execute-o em uma máquina que tenha o Prosody instalado e privilégios suficientes
para executar o prosodyctl (normalmente requer sudo).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, List, Tuple

from setup_sumo import criar_arquivos_sumo

DEFAULT_PASSWORD = "senha"


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
        "--domain",
        default="localhost",
        help="Domínio XMPP para todas as contas (padrão: %(default)s).",
    )
    parser.add_argument(
        "--config",
        default="simple.sumocfg",
        help="Arquivo .sumocfg para ler os ids de tls/veículos (padrão: %(default)s).",
    )
    parser.add_argument(
        "--max-vehicles",
        type=int,
        default=None,
        help="Limite opcional de contas de veículos a criar (na ordem que aparecem).",
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
) -> Iterable[List[str]]:
    for user, host, password in accounts:
        yield [
            prosodyctl,
            "register",
            user,
            host,
            override_password if override_password is not None else password,
        ]


def _parse_sumo_config(config_path: str) -> Tuple[str, List[str]]:
    """Return net file path and list of route file paths from a .sumocfg."""
    tree = ET.parse(config_path)
    root = tree.getroot()
    input_node = root.find("input")
    if input_node is None:
        raise ValueError("Configuração SUMO sem nó <input>")

    net_file = input_node.find("net-file")
    route_files = input_node.find("route-files")
    if net_file is None or "value" not in net_file.attrib:
        raise ValueError("Configuração SUMO sem 'net-file'.")
    if route_files is None or "value" not in route_files.attrib:
        raise ValueError("Configuração SUMO sem 'route-files'.")

    net_path = os.path.abspath(
        os.path.join(os.path.dirname(config_path), net_file.attrib["value"])
    )
    route_paths = [
        os.path.abspath(os.path.join(os.path.dirname(config_path), path.strip()))
        for path in route_files.attrib["value"].split()
        if path.strip()
    ]
    return net_path, route_paths


def _link_counts(net_path: str) -> Dict[str, int]:
    """Retorna quantas cabeças (linkIndex) cada TLS possui."""
    counts: Dict[str, int] = {}
    root = ET.parse(net_path).getroot()
    for conn in root.findall("connection"):
        tl = conn.attrib.get("tl")
        if not tl:
            continue
        link_idx = int(conn.attrib.get("linkIndex", "0"))
        counts[tl] = max(counts.get(tl, 0), link_idx + 1)
    return counts


def _vehicle_ids(route_paths: Iterable[str]) -> List[str]:
    ids: List[str] = []
    for route_path in route_paths:
        root = ET.parse(route_path).getroot()
        for veh in root.findall("vehicle"):
            vid = veh.attrib.get("id")
            if vid:
                ids.append(vid)
    return ids


def main() -> int:
    args = parse_args()
    try:
        config_path = criar_arquivos_sumo(args.config)
        net_path, route_paths = _parse_sumo_config(config_path)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Falha ao ler configuração SUMO: {exc}")
        return 1

    link_counts = _link_counts(net_path)
    tls_accounts = []
    for tl_id, count in link_counts.items():
        for link_index in range(count):
            tls_accounts.append((f"tl_{tl_id}_l{link_index}", args.domain, DEFAULT_PASSWORD))
    vehicle_ids = _vehicle_ids(route_paths)
    if args.max_vehicles is not None:
        vehicle_ids = vehicle_ids[: args.max_vehicles]
    vehicle_accounts = [
        (f"veh_{vid}", args.domain, DEFAULT_PASSWORD) for vid in vehicle_ids
    ]

    accounts = tls_accounts + vehicle_accounts
    if not accounts:
        print("Nada para registrar (nenhum semáforo ou veículo encontrado).")
        return 0

    commands = list(build_commands(args.prosodyctl, accounts, args.password))

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
