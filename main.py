import argparse
import os
import shutil
import subprocess
import sys
from typing import Optional

from setup_sumo import configurar_sumo, criar_arquivos_sumo


def _resolver_config(config_arg: str) -> str:
    """Return an absolute path to a SUMO config file."""
    if os.path.isabs(config_arg) or os.path.exists(config_arg):
        return os.path.abspath(config_arg)
    return criar_arquivos_sumo(config_arg)


def _encontrar_binario_sumo() -> Optional[str]:
    """Prefer sumo-gui and fall back to sumo if needed."""
    candidatos: list[str] = []

    # 1) PATH
    for nome in ("sumo-gui", "sumo"):
        caminho = shutil.which(nome)
        if caminho:
            return caminho
    candidatos.extend(filter(None, (shutil.which("sumo-gui"), shutil.which("sumo"))))

    # 2) Inferir do SUMO_HOME (pkg macOS coloca bin dois níveis acima de share/sumo)
    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        bin_dir = os.path.normpath(os.path.join(sumo_home, "..", "..", "bin"))
        for nome in ("sumo-gui", "sumo"):
            caminho = os.path.join(bin_dir, nome)
            if os.path.isfile(caminho) and os.access(caminho, os.X_OK):
                return caminho

    return candidatos[0] if candidatos else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Abrir SUMO com o mapa atual.")
    parser.add_argument(
        "--config",
        default="simple.sumocfg",
        help="Arquivo .sumocfg a usar (nome dentro de sumo_files ou caminho absoluto).",
    )
    args = parser.parse_args()

    if not configurar_sumo():
        print("Defina SUMO_HOME para apontar para a instalação do SUMO e tente novamente.")
        return 1

    try:
        config_path = _resolver_config(args.config)
    except FileNotFoundError as exc:
        print(exc)
        return 1

    sumo_bin = _encontrar_binario_sumo()
    if not sumo_bin:
        print("sumo-gui ou sumo não encontrados no PATH.")
        return 1

    print(f"Iniciando '{sumo_bin}' com '{config_path}'. Feche a janela do SUMO para encerrar.")
    resultado = subprocess.run([sumo_bin, "-c", config_path])
    return resultado.returncode


if __name__ == "__main__":
    sys.exit(main())
