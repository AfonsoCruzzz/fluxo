#!/usr/bin/env python3
import subprocess
import time

def executar_comando(comando):
    """Executar comando e retornar resultado"""
    try:
        resultado = subprocess.run(comando, shell=True, capture_output=True, text=True)
        return resultado.returncode, resultado.stdout, resultado.stderr
    except Exception as e:
        return -1, "", str(e)

def configurar_prosody():
    print("🔧 Configurando Prosody para desenvolvimento...")
    
    # Parar Prosody se estiver rodando
    print("🛑 Parando Prosody...")
    executar_comando("sudo systemctl stop prosody")
    
    # Backup da configuração original
    print("💾 Fazendo backup da configuração...")
    executar_comando("sudo cp /etc/prosody/prosody.cfg.lua /etc/prosody/prosody.cfg.lua.backup")
    
    # Configuração para desenvolvimento
    config = '''-- Configuração para desenvolvimento SPADE
daemonize = false

VirtualHost "localhost"
    authentication = "internal_plain"
    allow_registration = true

Component "conference.localhost" "muc"
Component "pubsub.localhost" "pubsub"

interfaces = { "127.0.0.1", "::1" }
c2s_require_encryption = false
s2s_require_encryption = false

log = {
    { levels = { "error", "warn", "info", "debug" }, to = "console" };
}

c2s_ports = { 5222 }
s2s_ports = { 5269 }
unlimited_jids = { "localhost" }
'''
    
    # Escrever nova configuração
    with open("/tmp/prosody_dev.cfg.lua", "w") as f:
        f.write(config)
    
    executar_comando("sudo cp /tmp/prosody_dev.cfg.lua /etc/prosody/prosody.cfg.lua")
    
    # Iniciar Prosody
    print("🚀 Iniciando Prosody...")
    executar_comando("sudo systemctl start prosody")
    
    time.sleep(2)
    
    # Verificar status
    codigo, saida, erro = executar_comando("sudo systemctl is-active prosody")
    
    if codigo == 0 and saida.strip() == "active":
        print("✅ Prosody configurado e rodando!")
        return True
    else:
        print("❌ Erro ao iniciar Prosody")
        print(f"Erro: {erro}")
        return False

if __name__ == "__main__":
    configurar_prosody()