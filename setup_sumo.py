import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SUMO_FILES_DIR = os.path.join(CURRENT_DIR, "sumo_files")
DEFAULT_SUMO_CONFIG = "cross.sumocfg"


def _registrar_sumo_home(sumo_home: str) -> bool:
    """Validar diretório e configurar variáveis/paths necessários."""
    if not sumo_home or not os.path.isdir(sumo_home):
        return False

    tools_dir = os.path.join(sumo_home, "tools")
    if not os.path.isdir(tools_dir):
        return False

    os.environ["SUMO_HOME"] = sumo_home

    # Garantir que o Python encontre as bibliotecas do SUMO
    for path_option in (sumo_home, tools_dir, os.path.join(tools_dir, "python")):
        if os.path.isdir(path_option) and path_option not in sys.path:
            sys.path.append(path_option)
            print(f"✅ Path adicionado ao Python: {path_option}")

    print(f"✅ SUMO encontrado em: {sumo_home}")
    return True


def configurar_sumo():
    """Configurar SUMO considerando instalações Flatpak, macOS pkg e padrões comuns."""
    candidatos = []

    # 1. Respeitar SUMO_HOME já definido
    sumo_home_env = os.environ.get("SUMO_HOME")
    if sumo_home_env:
        candidatos.append(sumo_home_env)

    # 2. Caminhos padrão do Flatpak
    flatpak_paths = [
        "/var/lib/flatpak/app/org.eclipse.sumo/current/active/files",
        os.path.expanduser("~/.local/share/flatpak/app/org.eclipse.sumo/current/active/files"),
        "/app",  # Dentro do próprio Flatpak
    ]
    candidatos.extend(flatpak_paths)

    # 3. Instalação oficial via pacote macOS (framework)
    mac_versions_base = "/Library/Frameworks/EclipseSUMO.framework/Versions"
    candidatos.append(os.path.join(mac_versions_base, "Current", "EclipseSUMO", "share", "sumo"))
    if os.path.isdir(mac_versions_base):
        for version_dir in os.listdir(mac_versions_base):
            candidatos.append(
                os.path.join(mac_versions_base, version_dir, "EclipseSUMO", "share", "sumo")
            )

    # 4. Outras instalações comuns (Homebrew, system wide)
    candidatos.extend(
        [
            "/opt/homebrew/opt/sumo/share/sumo",
            "/usr/local/opt/sumo/share/sumo",
            "/usr/share/sumo",
            "/opt/sumo",
        ]
    )

    vistos = set()
    for candidato in candidatos:
        if candidato in vistos:
            continue
        vistos.add(candidato)

        if _registrar_sumo_home(candidato):
            return True

    print("❌ SUMO não encontrado nos caminhos conhecidos. Defina SUMO_HOME manualmente.")
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
