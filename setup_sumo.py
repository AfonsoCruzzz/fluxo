import os
import sys

def configurar_sumo():
    """Configurar SUMO para instalação via Flatpak"""
    flatpak_paths = [
        "/var/lib/flatpak/app/org.eclipse.sumo/current/active/files",
        os.path.expanduser("~/.local/share/flatpak/app/org.eclipse.sumo/current/active/files"),
        "/app"  # Dentro do próprio Flatpak
    ]
    
    for path in flatpak_paths:
        if os.path.exists(path):
            print(f"✅ Flatpak SUMO encontrado em: {path}")
            os.environ["SUMO_HOME"] = path

            # Adicionar ao Python path
            if path not in sys.path:
                sys.path.append(path)
            
            # Procurar por tools/python
            python_tools_path = os.path.join(path, "tools", "python")
            if os.path.exists(python_tools_path) and python_tools_path not in sys.path:
                sys.path.append(python_tools_path)
                print(f"✅ Tools/python path adicionado: {python_tools_path}")
            
            return True
    
    print("❌ Flatpak SUMO não encontrado nos caminhos padrão")
    return False

# Testar
if configurar_sumo():
    try:
        import traci
        print("✅ TRACI importado com sucesso!")
    except ImportError as e:
        print(f"❌ TRACI não disponível: {e}")