import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SUMO_FILES_DIR = os.path.join(CURRENT_DIR, "sumo_files")
DEFAULT_SUMO_CONFIG = "cross.sumocfg"


def configurar_sumo():
    """Configurar SUMO para instalação via Flatpak."""
    flatpak_paths = [
        "/var/lib/flatpak/app/org.eclipse.sumo/current/active/files",
        os.path.expanduser("~/.local/share/flatpak/app/org.eclipse.sumo/current/active/files"),
        "/app",  # Dentro do próprio Flatpak
    ]

    for path in flatpak_paths:
        if os.path.exists(path):
            print(f"✅ Flatpak SUMO encontrado em: {path}")
            os.environ["SUMO_HOME"] = path

            # Adicionar ao Python path
            if path not in sys.path:
                sys.path.append(path)

            python_tools_path = os.path.join(path, "tools", "python")
            if os.path.exists(python_tools_path) and python_tools_path not in sys.path:
                sys.path.append(python_tools_path)
                print(f"✅ Tools/python path adicionado: {python_tools_path}")

            return True

    print("❌ Flatpak SUMO não encontrado nos caminhos padrão")
    return False


def criar_arquivos_sumo(config_name: str = DEFAULT_SUMO_CONFIG) -> str:
    """
    Retornar o caminho do arquivo de configuração SUMO solicitado.

    Como os arquivos já estão versionados no repositório, apenas valida-se
    a existência e devolve-se o caminho absoluto.
    """
    config_path = os.path.join(SUMO_FILES_DIR, config_name)
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Arquivo SUMO '{config_name}' não encontrado em {SUMO_FILES_DIR}")
    return config_path


if __name__ == "__main__":
    if configurar_sumo():
        try:
            import traci  # noqa: F401
            print("✅ TRACI importado com sucesso!")
        except ImportError as e:
            print(f"❌ TRACI não disponível: {e}")
